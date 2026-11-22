"""Opt-in audio evidence for visually matched clips. Never changes review decisions.

Only extracted PCM audio leaves the machine, after an explicit UI action. The
transcription cache is content addressed; uncertain submissions are not retried.
Runtime dependencies remain Python's standard library plus FFmpeg/FFprobe.
"""

from __future__ import annotations

import array
import hashlib
import http.client
import io
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
import urllib.request
import wave
from contextlib import contextmanager
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

import run_store
from openai_credit_meter import CreditBudgetError, OpenAICreditMeter

MODEL = "gpt-transcribe"
ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
# Official published duration tariff, verified 2026-11-21; USD 0.0045/minute.
MICROS_PER_SECOND = 75
SAMPLE_RATE = 16_000
MAX_CLIP_SECONDS = 60
MAX_REVIEW_CLIPS = 12  # pairs; at most 24 one-minute audio uploads per click
SCHEMA = "aligned-audio-v1"


class AudioReviewError(ValueError):
    """An audio review cannot be completed safely."""


@dataclass(frozen=True)
class AudioClip:
    pcm: bytes

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (SAMPLE_RATE * 2)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.pcm).hexdigest()

    @property
    def silent(self) -> bool:
        samples = array.array("h", self.pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        return not samples or max(abs(sample) for sample in samples) <= 8

    def wav(self) -> bytes:
        stream = io.BytesIO()
        with wave.open(stream, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(self.pcm)
        return stream.getvalue()


def group_key(files: dict[int, dict], matches: list[dict], interval: float) -> str:
    value = {"schema": SCHEMA, "model": MODEL, "interval": interval,
             "files": [files[key] for key in sorted(files)], "matches": matches}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_source(item: dict) -> Path:
    try:
        path = Path(item["path"]).resolve(strict=True)
        stat = path.stat()
    except OSError as exc:
        raise AudioReviewError("A source video changed since scanning. Rescan before audio review.") from exc
    if not path.is_file() or stat.st_size != item.get("size_bytes") or stat.st_mtime_ns != item.get("mtime_ns"):
        raise AudioReviewError("A source video changed since scanning. Rescan before audio review.")
    return path


def extract_clip(item: dict, start: float, duration: float) -> AudioClip | None:
    if not math.isfinite(start) or start < 0 or not 0 < duration <= MAX_CLIP_SECONDS:
        raise AudioReviewError("Audio clip bounds are invalid.")
    path = validate_source(item)
    ffprobe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        raise AudioReviewError("FFmpeg and FFprobe are required for local audio extraction.")
    try:
        probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0",
                                "-show_entries", "stream=index", "-of", "json", str(path)],
                               capture_output=True, check=True, timeout=30)
        if not json.loads(probe.stdout).get("streams"):
            validate_source(item)
            return None
        result = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(path),
                                 "-ss", str(start), "-t", str(duration), "-map", "0:a:0",
                                 "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                                 "-f", "s16le", "pipe:1"],
                                capture_output=True, check=True, timeout=120)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise AudioReviewError("Local audio extraction failed; no audio was uploaded.") from exc
    validate_source(item)
    max_bytes = math.floor(duration * SAMPLE_RATE) * 2
    if len(result.stdout) > max_bytes + 2 or len(result.stdout) % 2:
        raise AudioReviewError("Decoded audio exceeded its bounded clip size.")
    # Allow for decoder rounding by one sample, but never upload beyond the
    # requested interval or the hard clip limit.
    return AudioClip(result.stdout[:max_bytes])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AudioReviewError("Official transcription redirected unexpectedly; request was not retried.")


def official_transcribe(api_key: str, clip: AudioClip) -> dict:
    boundary = "video-dedup-" + uuid4().hex
    body = bytearray()
    for name, value in (("model", MODEL), ("response_format", "json")):
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="matched-clip.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
    body.extend(clip.wav())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(ENDPOINT, data=bytes(body), method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=90) as response:
            data = response.read(1024 * 1024 + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise AudioReviewError("Official transcription failed or timed out; its budget hold was retained.") from exc
    if len(data) > 1024 * 1024:
        raise AudioReviewError("Official transcription response exceeded the size limit.")
    try:
        result = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AudioReviewError("Official transcription returned an invalid response.") from exc
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise AudioReviewError("Official transcription returned an invalid response.")
    return result


def compare_text(left: dict, right: dict) -> dict:
    def normalized(text):
        return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())
    a, b = normalized(left["text"]), normalized(right["text"])
    if max(len(a), len(b)) > 4000:
        return {"status": "unknown", "reason": "Transcript is unusually long for a bounded clip; inspect the audio."}
    if min(len(a), len(b)) < 12:
        return {"status": "unknown", "reason": "Too little reliable speech to compare."}
    a_lang, b_lang = set(left.get("languages", [])), set(right.get("languages", []))
    if a_lang and b_lang and a_lang.isdisjoint(b_lang):
        return {"status": "different_language", "reason": "Detected speech languages differ; inspect both tracks."}
    similarity = SequenceMatcher(None, a, b, autojunk=False).ratio()
    return {"status": "similar_speech" if similarity >= 0.85 else "different_speech",
            "similarity": round(similarity, 3),
            "reason": ("Similar words, but decoded audio differs. Music, timing, voices or effects may differ."
                       if similarity >= 0.85 else "Transcript wording differs; verify by listening.")}


class AudioReviewer:
    def __init__(self, root: Path, meter: OpenAICreditMeter, api_key: str,
                 *, transcribe=official_transcribe, extract=extract_clip):
        self.root, self.meter, self.api_key = root, meter, api_key
        self.transcribe, self.extract = transcribe, extract
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.root / "transcripts.sqlite3"
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS transcripts (id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT, reservation TEXT)")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.cache_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @classmethod
    def from_env(cls, root: Path):
        enabled = os.environ.get("VIDEO_DEDUP_AUDIO_REVIEW_ENABLED", "false").strip().lower()
        if enabled in {"false", "0", "no", "off", ""}:
            return None
        if enabled not in {"true", "1", "yes", "on"}:
            raise AudioReviewError("VIDEO_DEDUP_AUDIO_REVIEW_ENABLED must be true or false.")
        meter = OpenAICreditMeter.from_env("video")
        if meter is None:
            raise AudioReviewError("Audio review requires OPENAI_OFFICIAL_BUDGET_ENABLED=true and a credit period.")
        key = os.environ.get("OPENAI_OFFICIAL_API_KEY", "").strip()
        if not key:
            raise AudioReviewError("Set OPENAI_OFFICIAL_API_KEY to enable official audio review.")
        return cls(root, meter, key)

    def _transcript(self, clip: AudioClip) -> dict:
        key = hashlib.sha256(f"{SCHEMA}:{MODEL}:{clip.digest}".encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM transcripts WHERE id = ?", (key,)).fetchone()
            if existing:
                if existing["state"] == "ready":
                    return {**json.loads(existing["payload"]), "cached": True, "chargedMicros": 0}
                raise AudioReviewError("This audio has an unfinished or uncertain transcription. Reconcile the existing request before retrying.")
            db.execute("INSERT INTO transcripts VALUES (?, 'pending', NULL, NULL)", (key,))
        reservation = None
        submitted = False
        try:
            reservation = self.meter.reserve("matched-audio-transcription",
                (math.ceil(clip.seconds) + 1) * MICROS_PER_SECOND,
                "audio:" + key, nonessential=True)
            with self._db() as db:
                db.execute("UPDATE transcripts SET reservation = ? WHERE id = ?", (reservation.id, key))
            self.meter.submitted(reservation.id)
            submitted = True
            response = self.transcribe(self.api_key, clip)
            if not isinstance(response, dict) or not isinstance(response.get("text"), str) or len(response["text"]) > 20_000:
                raise AudioReviewError("Transcription text is missing or too large.")
            usage = response.get("usage") or {}
            if not isinstance(usage, dict):
                usage = {}
            seconds = usage.get("seconds")
            if usage.get("type") == "duration" and type(seconds) in {int, float} and math.isfinite(seconds) and seconds >= 0:
                charged = math.ceil(seconds * MICROS_PER_SECOND)
                self.meter.settle(reservation.id, charged)
                accounting = "settled"
            else:
                # Text remains useful, but absent/unknown billing data cannot release credit.
                self.meter.unknown(reservation.id)
                charged, accounting = 0, "held"
            raw_languages = response.get("languages") or []
            if not isinstance(raw_languages, list):
                raw_languages = []
            languages = [lang["code"] for lang in raw_languages
                         if isinstance(lang, dict) and isinstance(lang.get("code"), str)]
            result = {"text": response["text"], "languages": languages, "accounting": accounting,
                      "reservationId": reservation.id, "chargedMicros": charged, "cached": False}
            with self._db() as db:
                db.execute("UPDATE transcripts SET state = 'ready', payload = ? WHERE id = ?", (json.dumps(result), key))
            return result
        except Exception:
            if reservation is not None:
                if submitted:
                    self.meter.unknown(reservation.id)
                else:
                    self.meter.release(reservation.id)
            with self._db() as db:
                if submitted:
                    db.execute("UPDATE transcripts SET state = 'unknown' WHERE id = ?", (key,))
                else:
                    db.execute("DELETE FROM transcripts WHERE id = ?", (key,))
            raise

    def reconcile_transcription(self, cache_key: str, actual_micros: int, *, confirm_stopped: bool = False) -> None:
        """Record a verified charge and resolve a held or uncertain transcription.

        Pending entries are recoverable only after the operator stops every
        process using this cache and explicitly confirms that no request is in flight.
        """
        if type(actual_micros) is not int or actual_micros < 0:
            raise AudioReviewError("The verified charge must be nonnegative integer microdollars.")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM transcripts WHERE id = ?", (cache_key,)).fetchone()
            if row is None:
                raise AudioReviewError("The transcription cache entry was not found.")
            if row["state"] == "ready":
                payload = json.loads(row["payload"])
                if payload.get("accounting") != "held" or not row["reservation"]:
                    raise AudioReviewError("Only a held transcript can be reconciled.")
                self.meter.settle(row["reservation"], actual_micros)
                payload.update(accounting="settled", chargedMicros=actual_micros)
                db.execute("UPDATE transcripts SET payload = ? WHERE id = ?", (json.dumps(payload), cache_key))
                return
            if row["state"] not in {"unknown", "pending"}:
                raise AudioReviewError("Only a held or uncertain transcription can be reconciled.")
            if row["state"] == "pending" and confirm_stopped is not True:
                raise AudioReviewError("Stop every process using the cache before reconciling a pending request.")
            reservation_id = row["reservation"]
            if reservation_id is None:
                reservation = self.meter.inspect_request("audio:" + cache_key)
                if reservation is None:
                    if row["state"] != "pending" or actual_micros != 0:
                        raise AudioReviewError("No matching reservation was found; reconcile the ledger manually.")
                    db.execute("DELETE FROM transcripts WHERE id = ?", (cache_key,))
                    return
                reservation_id = reservation["id"]
                # Persist the link before changing the ledger, so recovery is
                # repeatable even if this process stops between the two stores.
                db.execute("UPDATE transcripts SET reservation = ? WHERE id = ?", (reservation_id, cache_key))

        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state, reservation FROM transcripts WHERE id = ?", (cache_key,)).fetchone()
            if row is None or row["reservation"] != reservation_id or row["state"] not in {"unknown", "pending"}:
                raise AudioReviewError("The transcription changed during reconciliation. Inspect it before retrying.")
            if row["state"] == "pending" and confirm_stopped is not True:
                raise AudioReviewError("Stop every process using the cache before reconciling a pending request.")
            if self.meter.inspect(reservation_id)["state"] == "released":
                if actual_micros != 0:
                    raise AudioReviewError("A released reservation cannot have a charge; reconcile the ledger manually.")
            else:
                self.meter.settle(reservation_id, actual_micros)
                self.meter.allow_retry_after_settlement(reservation_id)
            db.execute("DELETE FROM transcripts WHERE id = ?", (cache_key,))

    def review(self, files: dict[int, dict], matches: list[dict], interval: float) -> dict:
        if not math.isfinite(interval) or interval <= 0:
            raise AudioReviewError("The scan has an invalid sampling interval.")
        for item in files.values():
            validate_source(item)
        key = group_key(files, matches, interval)
        evidence = []
        clip_count = 0
        truncated = False
        for match in matches:
            a, b = files[match["a_id"]], files[match["b_id"]]
            base = {"aId": a["id"], "bId": b["id"], "aName": Path(a["path"]).name,
                    "bName": Path(b["path"]).name}
            if match.get("kind") == "exact":
                evidence.append({**base, "status": "exact_file", "reason": "The scan found identical file bytes; no API request."})
                continue
            ranges = match.get("aligned_ranges") or []
            if not ranges:
                evidence.append({**base, "status": "alignment_unavailable", "reason": "Rescan to record paired time ranges before uploading audio."})
                continue
            for alignment in ranges:
                try:
                    a_start, b_start = float(alignment["a_start_seconds"]), float(alignment["b_start_seconds"])
                    duration = min(float(alignment["duration_seconds"]),
                                   float(a["duration_seconds"]) - a_start,
                                   float(b["duration_seconds"]) - b_start)
                except (KeyError, TypeError, ValueError) as exc:
                    raise AudioReviewError("The scan contains invalid paired audio ranges.") from exc
                if not all(math.isfinite(v) for v in (a_start, b_start, duration)) or min(a_start, b_start) < 0 or duration <= 0:
                    raise AudioReviewError("The scan contains invalid paired audio ranges.")
                offset = 0.0
                while offset < duration:
                    if clip_count >= MAX_REVIEW_CLIPS:
                        truncated = True
                        break
                    seconds = min(MAX_CLIP_SECONDS, duration - offset)
                    clip_count += 1
                    entry = {**base, "aStartSeconds": round(a_start + offset, 3),
                             "bStartSeconds": round(b_start + offset, 3), "durationSeconds": round(seconds, 3)}
                    try:
                        left = self.extract(a, a_start + offset, seconds)
                        right = self.extract(b, b_start + offset, seconds)
                        if left is None or right is None:
                            entry.update(status="missing_audio", reason="At least one video has no audio stream; no API request.")
                        elif min(left.seconds, right.seconds) < seconds - 0.25:
                            entry.update(status="unknown", reason="An audio track ends before the visual interval; no API request.")
                        elif left.digest == right.digest:
                            entry.update(status="identical_audio", reason="Decoded mono audio samples match in this interval; no API request.")
                        elif left.silent or right.silent:
                            entry.update(status="silent_audio", reason="At least one interval is silent; inspect both tracks. No API request.")
                        else:
                            entry["aTranscript"] = self._transcript(left)
                            entry["bTranscript"] = self._transcript(right)
                            entry.update(compare_text(entry["aTranscript"], entry["bTranscript"]))
                    except (AudioReviewError, CreditBudgetError) as exc:
                        entry.update(status="unavailable", reason=str(exc))
                        evidence.append(entry)
                        return self._save(key, evidence, True)
                    evidence.append(entry)
                    offset += seconds
        return self._save(key, evidence, truncated)

    def _save(self, key: str, evidence: list[dict], partial: bool) -> dict:
        result = {"ok": True, "groupKey": key, "model": MODEL, "evidence": evidence,
                  "partial": partial, "budget": self.meter.snapshot(),
                  "notice": "Audio evidence is advisory. Speech similarity does not prove whole-video or soundtrack equivalence."}
        run_store.write_json(self.root / f"{key}.json", result)
        return result

    def saved(self, key: str) -> dict | None:
        # Caller computes the fingerprint from server-side report data.
        path = self.root / f"{key}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
