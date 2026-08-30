#!/usr/bin/env python3
"""Scalable, review-first video duplicate finder.

The scanner uses FFmpeg/FFprobe and only Python's standard library.  It first
extracts inexpensive key-frame fingerprints to build an index, then decodes
fixed-interval frames only for likely pairs.  Decisions are saved separately
from the scan and no file is changed until ``apply`` is invoked.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import heapq
import http.server
import json
import math
import mimetypes
import os
import re
import shlex
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
import zlib
from array import array
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

VERSION = "1.4.0"
FRAME_WIDTH = 9
FRAME_HEIGHT = 8
FRAME_BYTES = FRAME_WIDTH * FRAME_HEIGHT
DEFAULT_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogv",
    ".ts",
    ".webm",
    ".wmv",
}
SAMPLE_STRUCT = struct.Struct("<QQBf")  # dHash, aHash, mean luma, time
# The optimized extractor produces the same fingerprint representation as 1.0,
# so existing expensive caches remain valid across the upgrade.
FAST_CACHE_KIND = "fast"
DETAILED_CACHE_KIND = "detailed"
CACHE_COMMIT_BATCH = 100
PTS_TIME_PATTERN = re.compile(rb"pts_time:([+-]?(?:\d+(?:\.\d*)?|\.\d+))")
REVIEW_STRATEGIES = (
    "manual",
    "delete-shallower",
    "delete-shorter-name",
    "delete-numbered-name",
    "delete-fully-covered",
)


class DedupError(RuntimeError):
    pass


@dataclass
class ReviewDecision:
    keepers: set[int]
    removal_order: list[int]
    method: str


@dataclass(frozen=True)
class Sample:
    dhash: int
    ahash: int
    mean: int
    timestamp: float


@dataclass
class VideoRecord:
    id: int
    path: str
    size: int
    mtime_ns: int
    duration: float
    width: int
    height: int
    codec: str
    fast_samples: list[Sample]
    sha256: str | None = None
    detailed_samples: list[Sample] | None = None
    fast_token_index: dict[int, list[int]] | None = field(
        default=None, init=False, repr=False
    )

    def public(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "size_bytes": self.size,
            "mtime_ns": self.mtime_ns,
            "duration_seconds": round(self.duration, 3),
            "width": self.width,
            "height": self.height,
            "codec": self.codec,
            "sha256": self.sha256,
            "fast_sample_count": len(self.fast_samples),
            "detailed_sample_count": (
                len(self.detailed_samples)
                if self.detailed_samples is not None
                else None
            ),
        }


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run_process(
    command: Sequence[str],
    *,
    timeout: float | None = None,
    media_path: Path | str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        raise DedupError(f"Required command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        target = media_path if media_path is not None else command[-1]
        raise DedupError(f"Timed out while reading media: {target}") from exc
    if proc.returncode:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        tail = detail[-1] if detail else f"exit code {proc.returncode}"
        target = media_path if media_path is not None else command[-1]
        raise DedupError(f"{command[0]} failed for {target}: {tail}")
    return proc


def run_checked(
    command: Sequence[str],
    *,
    timeout: float | None = None,
    media_path: Path | str | None = None,
) -> bytes:
    return run_process(command, timeout=timeout, media_path=media_path).stdout


def executable_version(name: str) -> str | None:
    path = shutil.which(name)
    if not path:
        return None
    try:
        output = run_checked([path, "-version"], timeout=15).decode("utf-8", "replace")
        return output.splitlines()[0] if output else path
    except DedupError:
        return path


def discover_videos(
    roots: Sequence[str], depth: int, extensions: set[str], follow_symlinks: bool
) -> list[Path]:
    found: dict[str, Path] = {}
    for raw_root in roots:
        root = Path(raw_root).expanduser().resolve()
        if not root.exists():
            raise DedupError(f"Folder does not exist: {root}")
        if root.is_file():
            candidates = [root]
        else:
            candidates = []
            for current, dirs, files in os.walk(root, followlinks=follow_symlinks):
                current_path = Path(current)
                relative_depth = len(current_path.relative_to(root).parts)
                if depth >= 0 and relative_depth >= depth:
                    dirs[:] = []
                if not follow_symlinks:
                    dirs[:] = [d for d in dirs if not (current_path / d).is_symlink()]
                candidates.extend(current_path / name for name in files)
        for path in candidates:
            if path.suffix.lower() not in extensions or (
                path.is_symlink() and not follow_symlinks
            ):
                continue
            try:
                resolved = path.resolve(strict=True)
            except OSError:
                continue
            key = os.path.normcase(str(resolved))
            found[key] = resolved
    return sorted(found.values(), key=lambda p: os.path.normcase(str(p)))


def _parse_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def probe_video(path: Path, include_keyframes: bool) -> tuple[dict, list[float]]:
    try:
        return _probe_video(path, include_keyframes, thorough=False)
    except (
        DedupError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as first_error:
        # Some MPEG transport streams and files with large headers need a wider
        # analyze window. Keep the normal path cheap and pay for this only after
        # the ordinary probe fails.
        try:
            return _probe_video(path, include_keyframes, thorough=True)
        except (
            DedupError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as retry_error:
            if isinstance(retry_error, DedupError):
                raise retry_error from first_error
            raise DedupError(
                f"ffprobe returned invalid metadata for {path}: {retry_error}"
            ) from first_error


def _probe_video(
    path: Path, include_keyframes: bool, thorough: bool
) -> tuple[dict, list[float]]:
    entries = "format=duration:stream=codec_name,width,height,duration"
    command = ["ffprobe", "-v", "error"]
    if thorough:
        command += ["-analyzeduration", "100M", "-probesize", "100M"]
    if include_keyframes:
        command += ["-skip_frame", "nokey", "-show_frames"]
        entries += ":frame=best_effort_timestamp_time"
    command += [
        "-select_streams",
        "v:0",
        "-show_entries",
        entries,
        "-of",
        "json",
        str(path),
    ]
    payload = json.loads(
        run_checked(command, timeout=300 if thorough else 180, media_path=path).decode(
            "utf-8", "replace"
        )
    )
    streams = payload.get("streams") or []
    if not streams:
        raise DedupError(f"No video stream found: {path}")
    stream = streams[0]
    duration = _parse_float(stream.get("duration")) or _parse_float(
        (payload.get("format") or {}).get("duration")
    )
    if duration <= 0:
        raise DedupError(f"Could not determine a positive duration: {path}")
    metadata = {
        "duration": duration,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec": str(stream.get("codec_name") or "unknown"),
    }
    timestamps = []
    for frame in payload.get("frames") or []:
        value = _parse_float(frame.get("best_effort_timestamp_time"), -1.0)
        if value >= 0:
            timestamps.append(value)
    return metadata, timestamps


def frame_sample(frame: bytes, timestamp: float) -> Sample:
    if len(frame) != FRAME_BYTES:
        raise ValueError("Unexpected raw frame size")
    dhash = 0
    for row in range(FRAME_HEIGHT):
        start = row * FRAME_WIDTH
        for col in range(FRAME_WIDTH - 1):
            dhash = (dhash << 1) | (frame[start + col] > frame[start + col + 1])
    pixels = [
        frame[row * FRAME_WIDTH + col]
        for row in range(FRAME_HEIGHT)
        for col in range(8)
    ]
    mean = sum(pixels) // len(pixels)
    ahash = 0
    for value in pixels:
        ahash = (ahash << 1) | (value >= mean)
    return Sample(dhash=dhash, ahash=ahash, mean=mean, timestamp=timestamp)


def _raw_frames(
    command: Sequence[str], timestamps: Sequence[float] | None, interval: float
) -> list[Sample]:
    raw = run_checked(command, timeout=3600)
    return _samples_from_raw(raw, command[-1], timestamps, interval)


def _samples_from_raw(
    raw: bytes, source: Path | str, timestamps: Sequence[float] | None, interval: float
) -> list[Sample]:
    count = len(raw) // FRAME_BYTES
    if count == 0:
        raise DedupError(f"FFmpeg produced no frames: {source}")
    if len(raw) % FRAME_BYTES:
        log(
            f"warning: ignoring {len(raw) % FRAME_BYTES} trailing raw bytes for {source}"
        )
    if timestamps is not None and len(timestamps) != count:
        usable = min(len(timestamps), count)
        if usable == 0:
            timestamps = None
        else:
            count = usable
    result = []
    for index in range(count):
        stamp = timestamps[index] if timestamps is not None else index * interval
        frame = raw[index * FRAME_BYTES : (index + 1) * FRAME_BYTES]
        result.append(frame_sample(frame, float(stamp)))
    return result


def extract_fast(path: Path, max_frames: int) -> tuple[dict, list[Sample]]:
    metadata, _ = probe_video(path, include_keyframes=False)
    spacing = max(0.001, metadata["duration"] / max_frames)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-skip_frame",
        "nokey",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-vf",
        (
            f"select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,{spacing:.9g}),"
            f"scale={FRAME_WIDTH}:{FRAME_HEIGHT}:flags=area,format=gray,showinfo"
        ),
        "-fps_mode",
        "passthrough",
        "-frames:v",
        str(max_frames),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    process = run_process(command, timeout=3600, media_path=path)
    timestamps = [
        float(match.group(1)) for match in PTS_TIME_PATTERN.finditer(process.stderr)
    ]
    fallback_interval = metadata["duration"] / max(
        1, len(process.stdout) // FRAME_BYTES - 1
    )
    samples = _samples_from_raw(
        process.stdout, path, timestamps or None, fallback_interval
    )
    return metadata, samples


def extract_detailed(path: Path, interval: float) -> list[Sample]:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-vf",
        f"fps=1/{interval:g},scale={FRAME_WIDTH}:{FRAME_HEIGHT}:flags=area,format=gray",
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    raw = run_checked(command, timeout=3600, media_path=path)
    return _samples_from_raw(raw, path, None, interval)


def encode_samples(samples: Sequence[Sample]) -> bytes:
    raw = bytearray()
    for sample in samples:
        raw += SAMPLE_STRUCT.pack(
            sample.dhash, sample.ahash, sample.mean, sample.timestamp
        )
    return zlib.compress(bytes(raw), level=6)


def decode_samples(blob: bytes) -> list[Sample]:
    raw = zlib.decompress(blob)
    if len(raw) % SAMPLE_STRUCT.size:
        raise DedupError("Fingerprint cache is corrupt")
    return [
        Sample(*SAMPLE_STRUCT.unpack_from(raw, offset))
        for offset in range(0, len(raw), SAMPLE_STRUCT.size)
    ]


class FingerprintCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self._pending_writes = 0
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS fingerprints (
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                kind TEXT NOT NULL,
                interval REAL NOT NULL,
                metadata TEXT NOT NULL,
                samples BLOB NOT NULL,
                PRIMARY KEY(path, size, mtime_ns, kind, interval)
            )
            """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS failures (
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                kind TEXT NOT NULL,
                error TEXT NOT NULL,
                PRIMARY KEY(path, size, mtime_ns, kind)
            )
            """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS file_hashes (
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                algorithm TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY(path, size, mtime_ns, algorithm)
            )
            """)

    def _changed(self) -> None:
        self._pending_writes += 1
        if self._pending_writes >= CACHE_COMMIT_BATCH:
            self.flush()

    def flush(self) -> None:
        if self._pending_writes:
            self.connection.commit()
            self._pending_writes = 0

    def get(
        self, path: str, size: int, mtime_ns: int, kind: str, interval: float
    ) -> tuple[dict, list[Sample]] | None:
        row = self.connection.execute(
            "SELECT metadata, samples FROM fingerprints WHERE path=? AND size=? AND mtime_ns=? AND kind=? AND interval=?",
            (path, size, mtime_ns, kind, interval),
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0]), decode_samples(row[1])
        except (json.JSONDecodeError, TypeError, ValueError, zlib.error, struct.error):
            # A partial/corrupt row should cost one recomputation, not abort the
            # entire library scan.
            self.connection.execute(
                "DELETE FROM fingerprints WHERE path=? AND size=? AND mtime_ns=? AND kind=? AND interval=?",
                (path, size, mtime_ns, kind, interval),
            )
            self._changed()
            return None

    def put(
        self,
        path: str,
        size: int,
        mtime_ns: int,
        kind: str,
        interval: float,
        metadata: dict,
        samples: Sequence[Sample],
    ) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO fingerprints(path,size,mtime_ns,kind,interval,metadata,samples) VALUES(?,?,?,?,?,?,?)",
            (
                path,
                size,
                mtime_ns,
                kind,
                interval,
                json.dumps(metadata, separators=(",", ":")),
                encode_samples(samples),
            ),
        )
        self.connection.execute(
            "DELETE FROM failures WHERE path=? AND size=? AND mtime_ns=? AND kind=?",
            (path, size, mtime_ns, kind),
        )
        self._changed()

    def get_failure(self, path: str, size: int, mtime_ns: int, kind: str) -> str | None:
        row = self.connection.execute(
            "SELECT error FROM failures WHERE path=? AND size=? AND mtime_ns=? AND kind=?",
            (path, size, mtime_ns, kind),
        ).fetchone()
        return str(row[0]) if row else None

    def put_failure(
        self, path: str, size: int, mtime_ns: int, kind: str, error: str
    ) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO failures(path,size,mtime_ns,kind,error) VALUES(?,?,?,?,?)",
            (path, size, mtime_ns, kind, error),
        )
        self._changed()

    def get_file_hash(
        self, path: str, size: int, mtime_ns: int, algorithm: str
    ) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM file_hashes WHERE path=? AND size=? AND mtime_ns=? AND algorithm=?",
            (path, size, mtime_ns, algorithm),
        ).fetchone()
        return str(row[0]) if row else None

    def put_file_hash(
        self, path: str, size: int, mtime_ns: int, algorithm: str, value: str
    ) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO file_hashes(path,size,mtime_ns,algorithm,value) VALUES(?,?,?,?,?)",
            (path, size, mtime_ns, algorithm, value),
        )
        self._changed()

    def close(self) -> None:
        self.flush()
        self.connection.close()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024 * 4):
            digest.update(chunk)
    return digest.hexdigest()


def splitmix64(value: int) -> int:
    value = (value + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return value ^ (value >> 31)


def sample_tokens(sample: Sample) -> Iterator[int]:
    # Eight independent 16-bit bands. The band number is part of the key.
    for band in range(4):
        yield (band << 16) | ((sample.dhash >> (band * 16)) & 0xFFFF)
    for band in range(4):
        yield ((band + 4) << 16) | ((sample.ahash >> (band * 16)) & 0xFFFF)


def informative_sample(sample: Sample) -> bool:
    return not (sample.dhash == 0 and sample.ahash in (0, 0xFFFFFFFFFFFFFFFF))


def selected_tokens(samples: Sequence[Sample], limit: int) -> list[int]:
    tokens: set[int] = set()
    for sample in samples:
        # Flat frames generate extremely common, low-information keys.
        if not informative_sample(sample):
            continue
        tokens.update(sample_tokens(sample))
    if len(tokens) <= limit:
        return list(tokens)
    return heapq.nsmallest(limit, tokens, key=splitmix64)


def build_candidates(
    videos: Sequence[VideoRecord],
    token_limit: int,
    minimum_shared: int,
    max_frequency: int,
    per_video_limit: int,
) -> set[tuple[int, int]]:
    index: dict[int, array] = {}
    selected: list[list[int]] = []
    for video in videos:
        keys = selected_tokens(video.fast_samples, token_limit)
        selected.append(keys)
        for key in keys:
            index.setdefault(key, array("I")).append(video.id)
    candidates: set[tuple[int, int]] = set()
    for video in videos:
        scores: dict[int, int] = defaultdict(int)
        for key in selected[video.id]:
            owners = index[key]
            if len(owners) > max_frequency:
                continue
            for other in owners:
                if other != video.id:
                    scores[other] += 1
        ranked = sorted(
            (
                (score, other)
                for other, score in scores.items()
                if score >= minimum_shared
            ),
            reverse=True,
        )[:per_video_limit]
        candidates.update(
            (min(video.id, other), max(video.id, other)) for _, other in ranked
        )
    return candidates


def sample_distance(left: Sample, right: Sample) -> int:
    # Mean luma is a small penalty, while the two perceptual hashes dominate.
    return (
        (left.dhash ^ right.dhash).bit_count()
        + (left.ahash ^ right.ahash).bit_count()
        + min(8, abs(left.mean - right.mean) // 16)
    )


def matching_points(
    left: Sequence[Sample], right: Sequence[Sample], threshold: int
) -> list[tuple[int, int, int]]:
    band_index: dict[int, list[int]] = defaultdict(list)
    for index, sample in enumerate(right):
        if not informative_sample(sample):
            continue
        for token in sample_tokens(sample):
            band_index[token].append(index)
    points: list[tuple[int, int, int]] = []
    for left_index, sample in enumerate(left):
        if not informative_sample(sample):
            continue
        possible: set[int] = set()
        for token in sample_tokens(sample):
            possible.update(band_index.get(token, ()))
        for right_index in possible:
            distance = sample_distance(sample, right[right_index])
            if distance <= threshold:
                points.append((left_index, right_index, distance))
    return points


def fast_candidate_likely(
    left: VideoRecord, right: VideoRecord, threshold: int, min_segment: float
) -> bool:
    tolerance = 2.0
    required = 1 if min(left.duration, right.duration) < min_segment else 2
    if right.fast_token_index is None:
        right.fast_token_index = defaultdict(list)
        for right_index, sample in enumerate(right.fast_samples):
            if not informative_sample(sample):
                continue
            for token in sample_tokens(sample):
                right.fast_token_index[token].append(right_index)
    bucket_left: dict[int, set[int]] = defaultdict(set)
    bucket_right: dict[int, set[int]] = defaultdict(set)
    for left_index, sample in enumerate(left.fast_samples):
        if not informative_sample(sample):
            continue
        possible: set[int] = set()
        for token in sample_tokens(sample):
            possible.update(right.fast_token_index.get(token, ()))
        for right_index in possible:
            other = right.fast_samples[right_index]
            if sample_distance(sample, other) > threshold:
                continue
            bucket = round((other.timestamp - sample.timestamp) / tolerance)
            bucket_left[bucket].add(left_index)
            bucket_right[bucket].add(right_index)
            if min(len(bucket_left[bucket]), len(bucket_right[bucket])) >= required:
                return True
    return False


def _runs(values: Sequence[int]) -> list[list[int]]:
    if not values:
        return []
    runs = [[values[0]]]
    for value in values[1:]:
        if value <= runs[-1][-1] + 2:  # tolerate one missed sample
            runs[-1].append(value)
        else:
            runs.append([value])
    return runs


def normalize_coverage_bins(values: set[int], sample_count: int) -> set[int]:
    """Treat one-sample holes and boundary misses as sampling uncertainty."""
    if not values:
        return set()
    normalized = set(values)
    ordered = sorted(values)
    for left, right in zip(ordered, ordered[1:]):
        if right - left == 2:
            normalized.add(left + 1)
    if min(normalized) <= 1:
        normalized.update(range(0, min(normalized)))
    if max(normalized) >= sample_count - 2:
        normalized.update(range(max(normalized) + 1, sample_count))
    return normalized


def detailed_match(
    left: VideoRecord,
    right: VideoRecord,
    interval: float,
    threshold: int,
    min_segment: float,
) -> dict | None:
    assert left.detailed_samples is not None and right.detailed_samples is not None
    a = left.detailed_samples
    b = right.detailed_samples
    points = matching_points(a, b, threshold)
    if not points:
        return None
    offset_counts: dict[int, int] = defaultdict(int)
    point_lookup: dict[tuple[int, int], int] = {}
    for i, j, distance in points:
        offset_counts[j - i] += 1
        point_lookup[(i, j)] = distance
    offsets = [
        item[1]
        for item in heapq.nlargest(
            20, ((count, offset) for offset, count in offset_counts.items())
        )
    ]
    min_samples = max(1, math.ceil(min_segment / interval))
    used_a: set[int] = set()
    used_b: set[int] = set()
    chosen: list[tuple[int, int, int]] = []
    for base_offset in offsets:
        available: list[tuple[int, int, int]] = []
        for i in range(len(a)):
            options = []
            for offset in (base_offset - 1, base_offset, base_offset + 1):
                j = i + offset
                candidate_distance = point_lookup.get((i, j))
                if (
                    candidate_distance is not None
                    and i not in used_a
                    and j not in used_b
                ):
                    options.append((candidate_distance, j))
            if options:
                distance, j = min(options)
                available.append((i, j, distance))
        by_i = {i: (j, distance) for i, j, distance in available}
        for run in _runs(sorted(by_i)):
            span = run[-1] - run[0] + 1
            if len(run) < min_samples or span < min_samples:
                continue
            run_points = [(i, by_i[i][0], by_i[i][1]) for i in run]
            # Enforce forward order and one-to-one matches.
            run_points.sort()
            monotonic: list[tuple[int, int, int]] = []
            last_j = -1
            for point in run_points:
                if point[1] > last_j:
                    monotonic.append(point)
                    last_j = point[1]
            if len(monotonic) < min_samples:
                continue
            for i, j, distance in monotonic:
                used_a.add(i)
                used_b.add(j)
                chosen.append((i, j, distance))
    if len(chosen) < min_samples:
        return None
    covered_a = normalize_coverage_bins(used_a, len(a))
    covered_b = normalize_coverage_bins(used_b, len(b))
    overlap = min(len(covered_a), len(covered_b)) * interval
    a_percent = min(100.0, 100.0 * len(covered_a) / max(1, len(a)))
    b_percent = min(100.0, 100.0 * len(covered_b) / max(1, len(b)))
    confidence = max(
        0.0, 1.0 - (sum(p[2] for p in chosen) / len(chosen)) / max(1, threshold + 8)
    )
    return {
        "a_id": left.id,
        "b_id": right.id,
        "kind": "perceptual",
        "overlap_seconds": round(min(overlap, left.duration, right.duration), 3),
        "a_duplicated_percent": round(a_percent, 2),
        "b_duplicated_percent": round(b_percent, 2),
        "confidence": round(confidence, 4),
        "a_sample_ranges": compress_ranges(covered_a),
        "b_sample_ranges": compress_ranges(covered_b),
    }


def compress_ranges(values: Iterable[int]) -> list[list[int]]:
    ordered = sorted(set(values))
    if not ordered:
        return []
    ranges = [[ordered[0], ordered[0]]]
    for value in ordered[1:]:
        if value == ranges[-1][1] + 1:
            ranges[-1][1] = value
        else:
            ranges.append([value, value])
    return ranges


def expand_ranges(ranges: Sequence[Sequence[int]]) -> set[int]:
    result: set[int] = set()
    for start, end in ranges:
        result.update(range(int(start), int(end) + 1))
    return result


def load_fast_records(
    paths: Sequence[Path],
    cache: FingerprintCache,
    workers: int,
    max_fast_frames: int,
    retry_failures: bool = False,
) -> tuple[list[VideoRecord], list[dict]]:
    records: list[VideoRecord | None] = [None] * len(paths)
    failures: list[dict] = []
    pending: dict[concurrent.futures.Future, tuple[int, Path, os.stat_result]] = {}
    completed = 0
    cache_hits = 0
    cached_failures = 0
    lock = threading.Lock()

    def worker(path: Path) -> tuple[dict, list[Sample]]:
        return extract_fast(path, max_fast_frames)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for index, path in enumerate(paths):
            try:
                stat = path.stat()
            except OSError as exc:
                failures.append({"path": str(path), "error": f"stat failed: {exc}"})
                completed += 1
                continue
            cached_failure = (
                None
                if retry_failures
                else cache.get_failure(
                    str(path), stat.st_size, stat.st_mtime_ns, FAST_CACHE_KIND
                )
            )
            if cached_failure:
                failures.append(
                    {"path": str(path), "error": cached_failure, "cached": True}
                )
                completed += 1
                cached_failures += 1
                continue
            cached = cache.get(
                str(path), stat.st_size, stat.st_mtime_ns, FAST_CACHE_KIND, 0.0
            )
            if cached:
                metadata, samples = cached
                records[index] = VideoRecord(
                    index,
                    str(path),
                    stat.st_size,
                    stat.st_mtime_ns,
                    **metadata,
                    fast_samples=samples,
                )
                completed += 1
                cache_hits += 1
            else:
                pending[pool.submit(worker, path)] = (index, path, stat)
        if cache_hits:
            log(f"Loaded {cache_hits:,} fingerprints from cache")
        if cached_failures:
            log(f"Skipped {cached_failures:,} unchanged files with cached failures")
        for future in concurrent.futures.as_completed(pending):
            index, path, stat = pending[future]
            try:
                metadata, samples = future.result()
                records[index] = VideoRecord(
                    index,
                    str(path),
                    stat.st_size,
                    stat.st_mtime_ns,
                    **metadata,
                    fast_samples=samples,
                )
                cache.put(
                    str(path),
                    stat.st_size,
                    stat.st_mtime_ns,
                    FAST_CACHE_KIND,
                    0.0,
                    metadata,
                    samples,
                )
            except Exception as exc:  # one corrupt file must not abort a 10k-file run
                error = str(exc)
                failures.append({"path": str(path), "error": error})
                cache.put_failure(
                    str(path), stat.st_size, stat.st_mtime_ns, FAST_CACHE_KIND, error
                )
            with lock:
                completed += 1
                if completed % 25 == 0 or completed == len(paths):
                    log(f"Fast fingerprints: {completed:,}/{len(paths):,}")
    valid = [record for record in records if record is not None]
    # Failed records create holes; compact IDs are required by the indexes.
    for new_id, record in enumerate(valid):
        record.id = new_id
    return valid, failures


def compute_exact_groups(
    videos: Sequence[VideoRecord],
    workers: int,
    cache: FingerprintCache | None = None,
    failures: list[dict] | None = None,
) -> list[list[int]]:
    by_size: dict[int, list[VideoRecord]] = defaultdict(list)
    for video in videos:
        by_size[video.size].append(video)
    suspects = [
        video for group in by_size.values() if len(group) > 1 for video in group
    ]
    if not suspects:
        return []
    log(f"Hashing {len(suspects):,} same-size files for byte-exact duplicates")
    pending = []
    cached_count = 0
    for video in suspects:
        cached = (
            cache.get_file_hash(video.path, video.size, video.mtime_ns, "sha256")
            if cache
            else None
        )
        if cached:
            video.sha256 = cached
            cached_count += 1
        else:
            pending.append(video)
    if cached_count:
        log(f"Loaded {cached_count:,} exact hashes from cache")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(file_sha256, Path(video.path)): video for video in pending
        }
        for future in concurrent.futures.as_completed(futures):
            video = futures[future]
            try:
                video.sha256 = future.result()
                if cache:
                    cache.put_file_hash(
                        video.path, video.size, video.mtime_ns, "sha256", video.sha256
                    )
            except Exception as exc:
                if failures is not None:
                    failures.append(
                        {"path": video.path, "error": f"exact hashing: {exc}"}
                    )
    by_hash: dict[str, list[int]] = defaultdict(list)
    for video in suspects:
        if video.sha256 is not None:
            by_hash[video.sha256].append(video.id)
    return [ids for ids in by_hash.values() if len(ids) > 1]


def exact_matches(
    groups: Sequence[Sequence[int]], videos: Sequence[VideoRecord]
) -> list[dict]:
    matches = []
    for group in groups:
        anchor = group[0]
        for other in group[1:]:
            overlap = min(videos[anchor].duration, videos[other].duration)
            matches.append(
                {
                    "a_id": anchor,
                    "b_id": other,
                    "kind": "exact",
                    "overlap_seconds": round(overlap, 3),
                    "a_duplicated_percent": 100.0,
                    "b_duplicated_percent": 100.0,
                    "confidence": 1.0,
                    "a_sample_ranges": [],
                    "b_sample_ranges": [],
                }
            )
    return matches


def load_detailed_records(
    videos: Sequence[VideoRecord],
    video_ids: Sequence[int],
    cache: FingerprintCache,
    interval: float,
    workers: int,
    failures: list[dict],
) -> None:
    """Load/decode confirmation samples while keeping SQLite on its owner thread."""
    pending_ids = []
    for video_id in video_ids:
        video = videos[video_id]
        cached = cache.get(
            video.path, video.size, video.mtime_ns, DETAILED_CACHE_KIND, interval
        )
        if cached:
            video.detailed_samples = cached[1]
        else:
            pending_ids.append(video_id)
    cached_count = len(video_ids) - len(pending_ids)
    if cached_count:
        log(f"Loaded {cached_count:,} detailed fingerprints from cache")
    completed = cached_count
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                extract_detailed, Path(videos[video_id].path), interval
            ): video_id
            for video_id in pending_ids
        }
        for future in concurrent.futures.as_completed(futures):
            video_id = futures[future]
            video = videos[video_id]
            try:
                samples = future.result()
                video.detailed_samples = samples
                metadata = {
                    "duration": video.duration,
                    "width": video.width,
                    "height": video.height,
                    "codec": video.codec,
                }
                cache.put(
                    video.path,
                    video.size,
                    video.mtime_ns,
                    DETAILED_CACHE_KIND,
                    interval,
                    metadata,
                    samples,
                )
            except Exception as exc:
                failures.append(
                    {"path": video.path, "error": f"detailed verification: {exc}"}
                )
            completed += 1
            if completed % 10 == 0 or completed == len(video_ids):
                log(f"Detailed fingerprints: {completed:,}/{len(video_ids):,}")


def scan(args: argparse.Namespace) -> int:
    extensions = {
        item.lower() if item.startswith(".") else f".{item.lower()}"
        for item in args.extensions.split(",")
    }
    paths = discover_videos(args.folders, args.depth, extensions, args.follow_symlinks)
    if not paths:
        raise DedupError("No supported video files found")
    log(f"Discovered {len(paths):,} videos")
    cache = FingerprintCache(Path(args.cache).expanduser().resolve())
    started = time.monotonic()
    try:
        videos, failures = load_fast_records(
            paths, cache, args.workers, args.max_fast_frames, args.retry_failures
        )
        if not videos:
            raise DedupError("Every discovered video failed to decode")
        exact_groups = compute_exact_groups(videos, args.workers, cache, failures)
        exact_pair_keys = {
            (group[left], group[right])
            for group in exact_groups
            for left in range(len(group))
            for right in range(left + 1, len(group))
        }
        matches = exact_matches(exact_groups, videos)
        log("Building the perceptual candidate index")
        candidates = build_candidates(
            videos,
            args.candidate_tokens,
            args.candidate_shared,
            args.max_token_frequency,
            args.max_candidates_per_video,
        )
        candidates -= exact_pair_keys
        log(f"Candidate index narrowed the search to {len(candidates):,} pairs")
        likely = []
        for number, (a_id, b_id) in enumerate(sorted(candidates), 1):
            if fast_candidate_likely(
                videos[a_id], videos[b_id], args.hash_distance, args.min_segment
            ):
                likely.append((a_id, b_id))
            if number % 5000 == 0:
                log(f"Key-frame verification: {number:,}/{len(candidates):,}")
        log(f"{len(likely):,} pairs need fixed-interval verification")
        detailed_ids = sorted({video_id for pair in likely for video_id in pair})
        load_detailed_records(
            videos, detailed_ids, cache, args.sample_interval, args.workers, failures
        )
        for number, (a_id, b_id) in enumerate(likely, 1):
            if (
                videos[a_id].detailed_samples is None
                or videos[b_id].detailed_samples is None
            ):
                continue
            result = detailed_match(
                videos[a_id],
                videos[b_id],
                args.sample_interval,
                args.hash_distance,
                args.min_segment,
            )
            if result:
                matches.append(result)
            if number % 1000 == 0:
                log(f"Pair verification: {number:,}/{len(likely):,}")
        summary: dict[str, object] = {
            "discovered_files": len(paths),
            "scanned_files": len(videos),
            "failed_files": len(failures),
            "candidate_pairs": len(candidates),
            "verified_pairs": len(likely),
            "duplicate_pairs": len(matches),
            "cached_failure_files": sum(
                1 for failure in failures if failure.get("cached")
            ),
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
        report = {
            "schema_version": 1,
            "tool_version": VERSION,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "settings": {
                "roots": [
                    str(Path(folder).expanduser().resolve()) for folder in args.folders
                ],
                "depth": args.depth,
                "sample_interval_seconds": args.sample_interval,
                "minimum_segment_seconds": args.min_segment,
                "hash_distance": args.hash_distance,
            },
            "summary": summary,
            "files": [video.public() for video in videos],
            "matches": sorted(
                matches,
                key=lambda item: (
                    -max(item["a_duplicated_percent"], item["b_duplicated_percent"]),
                    item["a_id"],
                    item["b_id"],
                ),
            ),
            "failures": failures,
        }
        output = Path(args.report).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        log(f"Report written to {output}")
        print(json.dumps({"ok": True, "report": str(output), **summary}, indent=2))
        return 0
    finally:
        cache.close()


def load_json(path: str) -> tuple[Path, dict]:
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved, json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DedupError(f"Could not read JSON file {resolved}: {exc}") from exc


def connected_components(
    file_ids: Iterable[int], matches: Sequence[dict]
) -> list[list[int]]:
    parent = {file_id: file_id for file_id in file_ids}

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    for match in matches:
        union(int(match["a_id"]), int(match["b_id"]))
    groups: dict[int, list[int]] = defaultdict(list)
    involved = {int(match[key]) for match in matches for key in ("a_id", "b_id")}
    for file_id in involved:
        groups[find(file_id)].append(file_id)
    return sorted(
        (sorted(group) for group in groups.values()), key=lambda group: group[0]
    )


def relation_bins(match: dict, file_id: int, sample_count: int) -> set[int]:
    if match["kind"] == "exact":
        return set(range(sample_count))
    if int(match["a_id"]) == file_id:
        return expand_ranges(match.get("a_sample_ranges") or [])
    return expand_ranges(match.get("b_sample_ranges") or [])


def covered_by(
    file_id: int,
    keeper_ids: set[int],
    matches: Sequence[dict],
    files: dict[int, dict],
    interval: float,
) -> tuple[float, list[int]]:
    sample_count = int(files[file_id].get("detailed_sample_count") or 0)
    if sample_count <= 0:
        sample_count = max(
            1, math.ceil(float(files[file_id]["duration_seconds"]) / interval)
        )
    bins: set[int] = set()
    sources = []
    exact_adjacency: dict[int, set[int]] = defaultdict(set)
    for match in matches:
        if match["kind"] != "exact":
            continue
        left, right = int(match["a_id"]), int(match["b_id"])
        exact_adjacency[left].add(right)
        exact_adjacency[right].add(left)
    reachable = {file_id}
    stack = [file_id]
    while stack:
        current = stack.pop()
        unseen = exact_adjacency.get(current, set()) - reachable
        reachable.update(unseen)
        stack.extend(unseen)
    exact_keepers = (reachable - {file_id}) & keeper_ids
    if exact_keepers:
        return 100.0, sorted(exact_keepers)
    for match in matches:
        pair = {int(match["a_id"]), int(match["b_id"])}
        if file_id not in pair:
            continue
        other = next(iter(pair - {file_id}), file_id)
        if other in keeper_ids:
            bins.update(relation_bins(match, file_id, sample_count))
            sources.append(other)
    return min(100.0, 100.0 * len(bins) / sample_count), sorted(set(sources))


def relative_folder_depth(path_value: str, roots: Sequence[str]) -> int:
    path = Path(path_value)
    depths = []
    for raw_root in roots:
        root = Path(raw_root)
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        depths.append(max(0, len(relative.parts) - 1))
    if depths:
        return min(depths)
    return max(0, len(path.parent.parts) - 1)


def mixed_alphanumeric_filename(path_value: str) -> bool:
    stem = Path(path_value).stem
    return any(character.isalpha() for character in stem) and any(
        character.isdigit() for character in stem
    )


def _lower_quality_key(item: dict) -> tuple[int, int, float, str]:
    pixels = int(item.get("width") or 0) * int(item.get("height") or 0)
    return (
        pixels,
        int(item.get("size_bytes") or 0),
        float(item.get("duration_seconds") or 0.0),
        os.path.normcase(str(item.get("path") or "")),
    )


def automatic_removal_order(
    group: Sequence[int],
    strategy: str,
    matches: Sequence[dict],
    files: dict[int, dict],
    interval: float,
    minimum_coverage: float,
    roots: Sequence[str],
) -> list[int]:
    """Choose a coverage-safe removal order for one duplicate group."""
    if strategy not in REVIEW_STRATEGIES or strategy == "manual":
        raise ValueError(f"Not an automatic review strategy: {strategy}")

    initial_keepers = set(group)
    coverage_by_file = {
        file_id: covered_by(
            file_id, initial_keepers - {file_id}, matches, files, interval
        )[0]
        for file_id in group
    }

    def priority(file_id: int) -> tuple:
        item = files[file_id]
        quality = _lower_quality_key(item)
        if strategy == "delete-shallower":
            return (relative_folder_depth(str(item["path"]), roots), *quality)
        if strategy == "delete-shorter-name":
            name = Path(str(item["path"])).name
            return (len(name), *quality)
        if strategy == "delete-numbered-name":
            return (
                0 if mixed_alphanumeric_filename(str(item["path"])) else 1,
                *quality,
            )
        return (-coverage_by_file[file_id], *quality)

    keepers = set(group)
    removals = []
    for file_id in sorted(group, key=priority):
        if len(keepers) <= 1:
            break
        remaining = keepers - {file_id}
        coverage, _ = covered_by(file_id, remaining, matches, files, interval)
        if coverage + 1e-9 >= minimum_coverage:
            keepers.remove(file_id)
            removals.append(file_id)
    return removals


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def parse_number_spec(value: str, maximum: int, label: str) -> list[int]:
    """Parse one-based values such as ``1,3-5`` while preserving order."""
    if maximum < 1:
        return []
    normalized = value.strip().lower()
    if normalized == "all":
        return list(range(1, maximum + 1))
    result: list[int] = []
    seen: set[int] = set()
    try:
        for raw_part in normalized.split(","):
            part = raw_part.strip()
            if not part:
                raise ValueError
            if "-" in part:
                start_raw, end_raw = part.split("-", 1)
                start, end = int(start_raw), int(end_raw)
                if start > end:
                    raise ValueError
                values = range(start, end + 1)
            else:
                values = (int(part),)
            for number in values:
                if not 1 <= number <= maximum:
                    raise ValueError
                if number not in seen:
                    seen.add(number)
                    result.append(number)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {label} '{value}'. Use values from 1 to {maximum}, "
            "for example 1,3-5 or all."
        ) from exc
    return result


def group_matches_for(group: Sequence[int], matches: Sequence[dict]) -> list[dict]:
    members = set(group)
    return [
        match
        for match in matches
        if int(match["a_id"]) in members and int(match["b_id"]) in members
    ]


def print_review_group(
    group_number: int,
    groups: Sequence[Sequence[int]],
    files: dict[int, dict],
    matches: Sequence[dict],
    interval: float,
) -> None:
    group = groups[group_number - 1]
    group_matches = group_matches_for(group, matches)
    print(f"Set {group_number}/{len(groups)} ({len(group)} files)")
    for display, file_id in enumerate(group, 1):
        item = files[file_id]
        coverage, _ = covered_by(
            file_id, set(group) - {file_id}, group_matches, files, interval
        )
        print(
            f"  {display}. {item['path']}\n"
            f"     {float(item['duration_seconds']):.1f}s | {item['width']}x{item['height']} | "
            f"{human_size(int(item['size_bytes']))} | covered by set: {coverage:.1f}%"
        )


def strategy_decision(
    group: Sequence[int],
    strategy: str,
    matches: Sequence[dict],
    files: dict[int, dict],
    interval: float,
    minimum_coverage: float,
    roots: Sequence[str],
) -> ReviewDecision:
    removal_order = automatic_removal_order(
        group,
        strategy,
        group_matches_for(group, matches),
        files,
        interval,
        minimum_coverage,
        roots,
    )
    return ReviewDecision(set(group) - set(removal_order), removal_order, strategy)


def _decision_payload(
    groups: Sequence[Sequence[int]],
    decisions: dict[int, ReviewDecision],
    files: dict[int, dict],
) -> list[dict]:
    payload = []
    for group_index, group in enumerate(groups, 1):
        decision = decisions[group_index]
        payload.append(
            {
                "set": group_index,
                "group_paths": [files[file_id]["path"] for file_id in group],
                "keeper_paths": [
                    files[file_id]["path"]
                    for file_id in group
                    if file_id in decision.keepers
                ],
                "removal_order_paths": [
                    files[file_id]["path"] for file_id in decision.removal_order
                ],
                "method": decision.method,
            }
        )
    return payload


def load_review_decisions(
    plan_value: str,
    report_path: Path,
    groups: Sequence[Sequence[int]],
    files: dict[int, dict],
) -> dict[int, ReviewDecision]:
    plan_path, plan = load_json(plan_value)
    by_path = {str(item["path"]): file_id for file_id, item in files.items()}
    group_by_paths = {
        frozenset(str(files[file_id]["path"]) for file_id in group): (index, group)
        for index, group in enumerate(groups, 1)
    }
    loaded: dict[int, ReviewDecision] = {}
    stored_decisions = plan.get("decisions") or []
    for item in stored_decisions:
        group_paths = frozenset(str(path) for path in item.get("group_paths") or [])
        target = group_by_paths.get(group_paths)
        if target is None:
            continue
        group_index, group = target
        try:
            keepers = {by_path[str(path)] for path in item.get("keeper_paths") or []}
            removal_order = [
                by_path[str(path)] for path in item.get("removal_order_paths") or []
            ]
        except KeyError:
            continue
        if not keepers or not keepers.issubset(set(group)):
            continue
        if set(removal_order) != set(group) - keepers:
            removal_order = [file_id for file_id in group if file_id not in keepers]
        loaded[group_index] = ReviewDecision(
            keepers,
            removal_order,
            f"edited:{item.get('method') or 'manual'}",
        )

    if not stored_decisions:
        action_paths = [str(action.get("path")) for action in plan.get("actions") or []]
        action_order = {path: index for index, path in enumerate(action_paths)}
        for group_index, group in enumerate(groups, 1):
            removals = [
                file_id
                for file_id in group
                if str(files[file_id]["path"]) in action_order
            ]
            if not removals:
                continue
            removals.sort(key=lambda file_id: action_order[str(files[file_id]["path"])])
            keepers = set(group) - set(removals)
            if keepers:
                loaded[group_index] = ReviewDecision(
                    keepers, removals, "edited:legacy-plan"
                )

    source_report = plan.get("source_report")
    if source_report and Path(str(source_report)).expanduser().resolve() != report_path:
        print(
            f"Warning: {plan_path} names a different source report; matched decisions by file path."
        )
    print(f"Loaded {len(loaded)} editable set decision(s) from {plan_path}.")
    return loaded


def _batch_help() -> None:
    print(
        "Batch commands:\n"
        "  list [SETS]                  Compact list (default: next 20 unresolved)\n"
        "  show SET                     Show every file and its number in one set\n"
        "  keep SETS FILES              Keep file number(s), e.g. keep 1-100 1\n"
        "  strategy SETS NAME           Apply an automatic strategy to many sets\n"
        "  skip SETS                    Keep every file in the selected sets\n"
        "  unset SETS                   Mark selected sets unresolved\n"
        "  undo                          Undo the last keep/strategy/skip/unset command\n"
        "  status                        Show decision progress\n"
        "  done / save                   Save; unresolved sets are safely kept\n"
        "  quit                          Exit without writing a plan\n"
        "SETS accepts all or ranges such as 1,4-25. Strategy names: "
        + ", ".join(REVIEW_STRATEGIES[1:])
    )


def batch_review(
    groups: Sequence[Sequence[int]],
    files: dict[int, dict],
    matches: Sequence[dict],
    interval: float,
    roots: Sequence[str],
    minimum_coverage: float,
    initial: dict[int, ReviewDecision] | None = None,
) -> dict[int, ReviewDecision] | None:
    decisions = dict(initial or {})
    history: list[list[tuple[int, ReviewDecision | None]]] = []

    def status() -> None:
        unresolved = len(groups) - len(decisions)
        selected_removals = sum(
            len(decision.removal_order) for decision in decisions.values()
        )
        print(
            f"Decided {len(decisions)}/{len(groups)} sets; {unresolved} unresolved; "
            f"{selected_removals} selected removal(s) before coverage checks."
        )

    print("Batch review is active. No files are changed here; this only builds a plan.")
    _batch_help()
    status()
    while True:
        try:
            raw = input("batch> ")
        except EOFError:
            print("Input ended; no plan was written. Use 'done' to save safely.")
            return None
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            print(f"Could not parse command: {exc}")
            continue
        if not parts:
            continue
        command = parts[0].lower()
        try:
            if command in {"help", "?"}:
                _batch_help()
            elif command == "status":
                status()
            elif command == "list":
                if len(parts) > 2:
                    raise ValueError("Usage: list [SETS]")
                if len(parts) == 2:
                    selected = parse_number_spec(parts[1], len(groups), "set range")
                else:
                    selected = [
                        index
                        for index in range(1, len(groups) + 1)
                        if index not in decisions
                    ][:20]
                    if not selected:
                        selected = list(range(1, min(len(groups), 20) + 1))
                for group_index in selected:
                    group = groups[group_index - 1]
                    decision = decisions.get(group_index)
                    state = decision.method if decision else "unresolved"
                    sample_names = ", ".join(
                        Path(str(files[file_id]["path"])).name for file_id in group[:2]
                    )
                    if len(group) > 2:
                        sample_names += f", +{len(group) - 2} more"
                    print(
                        f"  {group_index:>4}: {len(group):>4} files | {state} | {sample_names}"
                    )
            elif command == "show":
                if len(parts) != 2:
                    raise ValueError("Usage: show SET")
                selected = parse_number_spec(parts[1], len(groups), "set number")
                if len(selected) != 1:
                    raise ValueError(
                        "show accepts exactly one set number; use list for ranges."
                    )
                print_review_group(selected[0], groups, files, matches, interval)
                decision = decisions.get(selected[0])
                print(f"Decision: {decision.method if decision else 'unresolved'}")
            elif command in {"keep", "strategy", "skip", "unset"}:
                required = 3 if command in {"keep", "strategy"} else 2
                if len(parts) != required:
                    usage = {
                        "keep": "keep SETS FILES",
                        "strategy": "strategy SETS NAME",
                        "skip": "skip SETS",
                        "unset": "unset SETS",
                    }[command]
                    raise ValueError(f"Usage: {usage}")
                selected = parse_number_spec(parts[1], len(groups), "set range")
                changes = [
                    (group_index, decisions.get(group_index))
                    for group_index in selected
                ]
                if command == "keep":
                    file_positions: dict[int, list[int]] = {}
                    for group_index in selected:
                        file_positions[group_index] = parse_number_spec(
                            parts[2],
                            len(groups[group_index - 1]),
                            f"file selection for set {group_index}",
                        )
                    for group_index in selected:
                        group = groups[group_index - 1]
                        keepers = {
                            group[position - 1]
                            for position in file_positions[group_index]
                        }
                        decisions[group_index] = ReviewDecision(
                            keepers,
                            [file_id for file_id in group if file_id not in keepers],
                            "manual-batch",
                        )
                elif command == "strategy":
                    strategy = parts[2].lower()
                    if strategy not in REVIEW_STRATEGIES[1:]:
                        raise ValueError(
                            "Unknown strategy. Choose: "
                            + ", ".join(REVIEW_STRATEGIES[1:])
                        )
                    for group_index in selected:
                        decisions[group_index] = strategy_decision(
                            groups[group_index - 1],
                            strategy,
                            matches,
                            files,
                            interval,
                            minimum_coverage,
                            roots,
                        )
                elif command == "skip":
                    for group_index in selected:
                        group = groups[group_index - 1]
                        decisions[group_index] = ReviewDecision(
                            set(group), [], "keep-all"
                        )
                else:
                    for group_index in selected:
                        decisions.pop(group_index, None)
                history.append(changes)
                print(f"Updated {len(selected)} set(s).")
                status()
            elif command == "undo":
                if not history:
                    print("Nothing to undo.")
                    continue
                for group_index, old_decision in history.pop():
                    if old_decision is None:
                        decisions.pop(group_index, None)
                    else:
                        decisions[group_index] = old_decision
                print("Undid the last batch edit.")
                status()
            elif command in {"done", "save"}:
                unresolved = [
                    index
                    for index in range(1, len(groups) + 1)
                    if index not in decisions
                ]
                if unresolved:
                    answer = (
                        input(
                            f"Keep all files in {len(unresolved)} unresolved set(s) and save? [y/N]: "
                        )
                        .strip()
                        .lower()
                    )
                    if answer not in {"y", "yes"}:
                        print("Continue editing; use list to see unresolved sets.")
                        continue
                    for group_index in unresolved:
                        group = groups[group_index - 1]
                        decisions[group_index] = ReviewDecision(
                            set(group), [], "unresolved-kept"
                        )
                return decisions
            elif command in {"quit", "exit"}:
                print("No plan was written.")
                return None
            else:
                print(f"Unknown command '{command}'. Type help for available commands.")
        except ValueError as exc:
            print(exc)


def build_review_actions(
    groups: Sequence[Sequence[int]],
    decisions: dict[int, ReviewDecision],
    files: dict[int, dict],
    matches: Sequence[dict],
    interval: float,
    minimum_coverage: float,
    *,
    verbose: bool,
) -> list[dict]:
    actions = []
    for group_index, group in enumerate(groups, 1):
        decision = decisions[group_index]
        group_matches = group_matches_for(group, matches)
        for file_id in decision.removal_order:
            if file_id in decision.keepers:
                continue
            coverage, sources = covered_by(
                file_id, decision.keepers, group_matches, files, interval
            )
            if coverage + 1e-9 < minimum_coverage:
                if verbose:
                    print(
                        f"  Retaining {files[file_id]['path']} (only {coverage:.1f}% covered by selected keepers)."
                    )
                continue
            actions.append(
                {
                    "path": files[file_id]["path"],
                    "size_bytes": files[file_id]["size_bytes"],
                    "mtime_ns": files[file_id]["mtime_ns"],
                    "covered_percent": round(coverage, 2),
                    "kept_source_paths": [files[source]["path"] for source in sources],
                }
            )
            if verbose:
                print(
                    f"  Planned removal: {files[file_id]['path']} ({coverage:.1f}% covered)"
                )
    return actions


@dataclass
class WebReviewState:
    report_path: Path
    plan_path: Path
    files: dict[int, dict]
    matches: list[dict]
    groups: list[list[int]]
    interval: float
    roots: list[str]
    minimum_coverage: float
    decisions: dict[int, ReviewDecision] = field(default_factory=dict)
    group_matches: dict[int, list[dict]] = field(init=False, repr=False)
    group_payloads: list[dict] = field(init=False, repr=False)
    save_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.group_matches = {
            group_number: group_matches_for(group, self.matches)
            for group_number, group in enumerate(self.groups, 1)
        }
        self.group_payloads = []
        for group_number, group in enumerate(self.groups, 1):
            group_matches = self.group_matches[group_number]
            file_payloads = []
            for file_id in group:
                item = self.files[file_id]
                coverage, _ = covered_by(
                    file_id,
                    set(group) - {file_id},
                    group_matches,
                    self.files,
                    self.interval,
                )
                path = Path(str(item["path"]))
                file_payloads.append(
                    {
                        "id": file_id,
                        "name": path.name,
                        "path": str(item["path"]),
                        "folder": str(path.parent),
                        "sizeBytes": int(item["size_bytes"]),
                        "durationSeconds": float(item["duration_seconds"]),
                        "width": int(item.get("width") or 0),
                        "height": int(item.get("height") or 0),
                        "codec": str(item.get("codec") or "unknown"),
                        "coveredPercent": round(coverage, 2),
                        "videoUrl": f"/api/video/{file_id}",
                    }
                )
            self.group_payloads.append(
                {
                    "id": group_number,
                    "fileCount": len(group),
                    "matchCount": len(group_matches),
                    "files": file_payloads,
                }
            )

    def session_payload(self) -> dict:
        initial_decisions = []
        for group_number, decision in sorted(self.decisions.items()):
            group = self.groups[group_number - 1]
            initial_decisions.append(
                {
                    "groupId": group_number,
                    "keeperIds": [
                        file_id for file_id in group if file_id in decision.keepers
                    ],
                    "method": decision.method,
                }
            )
        files_in_groups = sum(len(group) for group in self.groups)
        return {
            "reportPath": str(self.report_path),
            "planPath": str(self.plan_path),
            "minimumCoverage": self.minimum_coverage,
            "summary": {
                "groupCount": len(self.groups),
                "fileCount": files_in_groups,
                "matchCount": len(self.matches),
                "decidedCount": len(self.decisions),
                "totalBytes": sum(
                    int(self.files[file_id]["size_bytes"])
                    for group in self.groups
                    for file_id in group
                ),
            },
            "groups": self.group_payloads,
            "initialDecisions": initial_decisions,
        }

    def recommend(self, group_ids: Sequence[int], strategy: str) -> list[dict]:
        if strategy not in REVIEW_STRATEGIES[1:]:
            raise ValueError("Unknown review strategy.")
        unique_group_ids = list(dict.fromkeys(int(value) for value in group_ids))
        if not unique_group_ids:
            raise ValueError("Select at least one duplicate set.")
        recommendations = []
        for group_number in unique_group_ids:
            if not 1 <= group_number <= len(self.groups):
                raise ValueError(f"Unknown duplicate set {group_number}.")
            group = self.groups[group_number - 1]
            decision = strategy_decision(
                group,
                strategy,
                self.matches,
                self.files,
                self.interval,
                self.minimum_coverage,
                self.roots,
            )
            recommendations.append(
                {
                    "groupId": group_number,
                    "keeperIds": [
                        file_id for file_id in group if file_id in decision.keepers
                    ],
                    "method": strategy,
                }
            )
        return recommendations

    def save_plan(self, raw_decisions: object) -> dict:
        if not isinstance(raw_decisions, list):
            raise ValueError("decisions must be a list.")
        submitted: dict[int, ReviewDecision] = {}
        for raw_decision in raw_decisions:
            if not isinstance(raw_decision, dict):
                raise ValueError("Each decision must be an object.")
            try:
                group_number = int(raw_decision["groupId"])
                keeper_values = raw_decision["keeperIds"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "Each decision needs a valid groupId and keeperIds."
                ) from exc
            if group_number in submitted:
                raise ValueError(f"Duplicate decision for set {group_number}.")
            if not 1 <= group_number <= len(self.groups):
                raise ValueError(f"Unknown duplicate set {group_number}.")
            if not isinstance(keeper_values, list):
                raise ValueError(f"keeperIds for set {group_number} must be a list.")
            try:
                keepers = {int(value) for value in keeper_values}
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"keeperIds for set {group_number} must contain integers."
                ) from exc
            group = self.groups[group_number - 1]
            if not keepers or not keepers.issubset(set(group)):
                raise ValueError(
                    f"Set {group_number} must keep at least one file from that set."
                )
            method = str(raw_decision.get("method") or "web-manual")[:80]
            submitted[group_number] = ReviewDecision(
                keepers,
                [file_id for file_id in group if file_id not in keepers],
                method,
            )

        unresolved_count = len(self.groups) - len(submitted)
        complete_decisions = dict(submitted)
        for group_number, group in enumerate(self.groups, 1):
            if group_number not in complete_decisions:
                complete_decisions[group_number] = ReviewDecision(
                    set(group),
                    [],
                    "web-unresolved-kept",
                )
        actions = build_review_actions(
            self.groups,
            complete_decisions,
            self.files,
            self.matches,
            self.interval,
            self.minimum_coverage,
            verbose=False,
        )
        plan = {
            "schema_version": 1,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source_report": str(self.report_path),
            "minimum_delete_coverage": self.minimum_coverage,
            "strategy": "web",
            "decisions": _decision_payload(self.groups, complete_decisions, self.files),
            "actions": actions,
        }
        self.plan_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.plan_path.parent,
            prefix=f".{self.plan_path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary_path = Path(temporary_file.name)
        try:
            with temporary_file:
                json.dump(plan, temporary_file, indent=2)
            with self.save_lock:
                os.replace(temporary_path, self.plan_path)
                self.decisions = complete_decisions
        finally:
            temporary_path.unlink(missing_ok=True)
        return {
            "ok": True,
            "planPath": str(self.plan_path),
            "actionCount": len(actions),
            "unresolvedKeptCount": unresolved_count,
            "reclaimBytes": sum(int(action["size_bytes"]) for action in actions),
        }


def make_web_review_handler(
    state: WebReviewState,
    html: bytes,
) -> type[http.server.BaseHTTPRequestHandler]:
    class ReviewHandler(http.server.BaseHTTPRequestHandler):
        server_version = "VideoDedupReview/1.0"

        def log_message(self, format: str, *args: object) -> None:
            if len(args) > 1 and str(args[1]).isdigit() and int(str(args[1])) < 400:
                return
            log(f"Web review: {format % args}")

        def _send_json(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _send_error_json(self, status: int, message: str) -> None:
            self._send_json({"ok": False, "error": message}, status)

        def _serve_html(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; media-src 'self' blob:; "
                "img-src 'self' data: blob:; connect-src 'self'",
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(html)

        def _serve_video(self, path_value: str) -> None:
            try:
                file_id = int(path_value.rsplit("/", 1)[-1])
                item = state.files[file_id]
            except (KeyError, ValueError):
                self._send_error_json(404, "Unknown video.")
                return
            video_path = Path(str(item["path"]))
            if not video_path.is_file():
                self._send_error_json(404, "Video file is no longer available.")
                return
            size = video_path.stat().st_size
            start, end = 0, max(0, size - 1)
            status = 200
            range_value = self.headers.get("Range")
            if range_value:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_value.strip())
                if not match or size == 0:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                start_raw, end_raw = match.groups()
                if not start_raw:
                    suffix = int(end_raw or 0)
                    if suffix <= 0:
                        start = size
                    else:
                        start = max(0, size - suffix)
                    end = size - 1
                else:
                    start = int(start_raw)
                    end = min(size - 1, int(end_raw)) if end_raw else size - 1
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206
            content_length = 0 if size == 0 else end - start + 1
            content_type = (
                mimetypes.guess_type(video_path.name)[0] or "application/octet-stream"
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "private, max-age=3600")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD" or content_length == 0:
                return
            try:
                with video_path.open("rb") as handle:
                    handle.seek(start)
                    remaining = content_length
                    while remaining:
                        chunk = handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            path_value = urllib.parse.urlsplit(self.path).path
            if path_value in {"/", "/index.html"}:
                self._serve_html()
            elif path_value == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif path_value == "/api/session":
                self._send_json(state.session_payload())
            elif path_value.startswith("/api/video/"):
                self._serve_video(path_value)
            else:
                self._send_error_json(404, "Not found.")

        def do_POST(self) -> None:
            path_value = urllib.parse.urlsplit(self.path).path
            if self.headers.get("X-Video-Dedup-Review") != "1":
                self._send_error_json(403, "Missing local review request header.")
                return
            try:
                content_length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._send_error_json(400, "Invalid content length.")
                return
            if not 0 < content_length <= 16 * 1024 * 1024:
                self._send_error_json(400, "Request body is empty or too large.")
                return
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Request body must be an object.")
                if path_value == "/api/recommendations":
                    result = state.recommend(
                        payload.get("groupIds") or [],
                        str(payload.get("strategy") or ""),
                    )
                    self._send_json({"ok": True, "decisions": result})
                elif path_value == "/api/plan":
                    self._send_json(state.save_plan(payload.get("decisions")))
                else:
                    self._send_error_json(404, "Not found.")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._send_error_json(400, str(exc))
            except OSError as exc:
                self._send_error_json(500, f"Could not save the plan: {exc}")

    return ReviewHandler


def web_review(args: argparse.Namespace) -> int:
    report_path, report = load_json(args.report)
    files = {int(item["id"]): item for item in report.get("files") or []}
    matches = list(report.get("matches") or [])
    if not matches:
        print("No duplicate matches were found; web review was not started.")
        return 0
    groups = connected_components(files, matches)
    interval = float(
        (report.get("settings") or {}).get("sample_interval_seconds") or 3.0
    )
    roots = [str(root) for root in (report.get("settings") or {}).get("roots") or []]
    plan_path = Path(args.plan).expanduser().resolve()
    decisions = (
        load_review_decisions(str(plan_path), report_path, groups, files)
        if plan_path.is_file()
        else {}
    )
    bundle_path = Path(__file__).resolve().parent / "review-ui" / "bundle.html"
    if not bundle_path.is_file():
        raise DedupError(
            f"Web review bundle is missing at {bundle_path}. Build it from review-ui first."
        )
    state = WebReviewState(
        report_path,
        plan_path,
        files,
        matches,
        groups,
        interval,
        roots,
        args.minimum_delete_coverage,
        decisions,
    )
    try:
        server = http.server.ThreadingHTTPServer(
            (args.host, args.port),
            make_web_review_handler(state, bundle_path.read_bytes()),
        )
    except OSError as exc:
        raise DedupError(
            f"Could not start web review on {args.host}:{args.port}: {exc}"
        ) from exc
    actual_port = int(server.server_address[1])
    display_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{display_host}:{actual_port}/"
    print(f"Web review is ready: {url}")
    print(f"Report: {report_path}")
    print(f"Plan:   {plan_path}")
    print(
        "Nothing is removed by this server. Save a plan in the browser, then run apply separately."
    )
    if not args.no_browser:
        opener = threading.Timer(0.4, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def review(args: argparse.Namespace) -> int:
    report_path, report = load_json(args.report)
    files = {int(item["id"]): item for item in report.get("files") or []}
    matches = report.get("matches") or []
    if not matches:
        print("No duplicate matches were found; no plan was created.")
        return 0
    interval = float(
        (report.get("settings") or {}).get("sample_interval_seconds") or 3.0
    )
    roots = [str(root) for root in (report.get("settings") or {}).get("roots") or []]
    groups = connected_components(files, matches)
    print(f"Reviewing {len(groups)} duplicate set(s) from {report_path}\n")
    decisions: dict[int, ReviewDecision]
    initial = (
        load_review_decisions(args.edit_plan, report_path, groups, files)
        if args.edit_plan
        else {}
    )
    if args.batch or args.edit_plan:
        if args.strategy != "manual":
            for group_number, group in enumerate(groups, 1):
                if group_number not in initial:
                    initial[group_number] = strategy_decision(
                        group,
                        args.strategy,
                        matches,
                        files,
                        interval,
                        args.minimum_delete_coverage,
                        roots,
                    )
            print(
                f"Prefilled undecided sets with {args.strategy}; batch commands can override them."
            )
        batch_decisions = batch_review(
            groups,
            files,
            matches,
            interval,
            roots,
            args.minimum_delete_coverage,
            initial,
        )
        if batch_decisions is None:
            return 1
        decisions = batch_decisions
    elif args.strategy == "manual":
        decisions = {}
        for group_number, group in enumerate(groups, 1):
            print_review_group(group_number, groups, files, matches, interval)
            while True:
                answer = (
                    input("Keep which file number(s)? [all / comma-separated / skip]: ")
                    .strip()
                    .lower()
                )
                if answer in {"all", "skip", ""}:
                    keepers = set(group)
                    break
                try:
                    selections = {int(part.strip()) for part in answer.split(",")}
                except ValueError:
                    print("Enter 'all', 'skip', or numbers such as 1 or 1,2.")
                    continue
                if selections and all(1 <= value <= len(group) for value in selections):
                    keepers = {group[value - 1] for value in selections}
                    break
                print("Selection is outside this set.")
            decisions[group_number] = ReviewDecision(
                keepers,
                [file_id for file_id in group if file_id not in keepers],
                "manual",
            )
            print()
    else:
        decisions = {}
        for group_number, group in enumerate(groups, 1):
            decision = strategy_decision(
                group,
                args.strategy,
                matches,
                files,
                interval,
                args.minimum_delete_coverage,
                roots,
            )
            decisions[group_number] = decision
            print(
                f"Set {group_number}/{len(groups)}: {len(decision.removal_order)} removal(s), "
                f"{len(decision.keepers)} keeper(s) using {args.strategy}"
            )
    verbose_actions = not (args.batch or args.edit_plan or args.strategy != "manual")
    actions = build_review_actions(
        groups,
        decisions,
        files,
        matches,
        interval,
        args.minimum_delete_coverage,
        verbose=verbose_actions,
    )
    plan = {
        "schema_version": 1,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_report": str(report_path),
        "minimum_delete_coverage": args.minimum_delete_coverage,
        "strategy": "batch" if args.batch or args.edit_plan else args.strategy,
        "decisions": _decision_payload(groups, decisions, files),
        "actions": actions,
    }
    plan_value = args.plan or args.edit_plan or "video-dedup-plan.json"
    plan_path = Path(plan_value).expanduser().resolve()
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"Saved a plan with {len(actions)} removal(s) to {plan_path}")
    print(
        f'Nothing has been changed. Review the JSON, then run: python video_dedup.py apply "{plan_path}"'
    )
    return 0


def apply_plan(args: argparse.Namespace) -> int:
    plan_path, plan = load_json(args.plan)
    actions = plan.get("actions") or []
    if not actions:
        print("The plan contains no actions.")
        return 0
    if args.permanent and not args.yes:
        confirmation = input(
            f"Permanently delete {len(actions)} file(s)? Type DELETE to continue: "
        ).strip()
        if confirmation != "DELETE":
            print("Cancelled; no files were changed.")
            return 1
    quarantine = None
    if not args.permanent:
        quarantine = (
            Path(args.quarantine).expanduser().resolve()
            if args.quarantine
            else plan_path.parent
            / f"video-dedup-quarantine-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        quarantine.mkdir(parents=True, exist_ok=False)
    applied = []
    failures = []
    for index, action in enumerate(actions, 1):
        path = Path(action["path"])
        try:
            stat = path.stat()
            if stat.st_size != int(action["size_bytes"]) or stat.st_mtime_ns != int(
                action["mtime_ns"]
            ):
                raise DedupError("file changed since the report; refusing to remove it")
            if args.permanent:
                path.unlink()
                destination = None
            else:
                assert quarantine is not None
                destination = quarantine / f"{index:05d}-{path.name}"
                shutil.move(str(path), str(destination))
            applied.append(
                {
                    "source": str(path),
                    "destination": str(destination) if destination else None,
                }
            )
        except Exception as exc:
            failures.append({"path": str(path), "error": str(exc)})
    result_path = plan_path.with_name(plan_path.stem + ".result.json")
    result = {
        "applied_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "permanent": args.permanent,
        "quarantine": str(quarantine) if quarantine else None,
        "applied": applied,
        "failures": failures,
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": not failures,
                "applied": len(applied),
                "failed": len(failures),
                "quarantine": str(quarantine) if quarantine else None,
                "result": str(result_path),
            },
            indent=2,
        )
    )
    return 0 if not failures else 2


def doctor(_args: argparse.Namespace) -> int:
    result = {
        "ok": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "tool_version": VERSION,
        "python": sys.version.split()[0],
        "ffmpeg": executable_version("ffmpeg"),
        "ffprobe": executable_version("ffprobe"),
        "write_actions_default": "quarantine",
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 2


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def nonnegative_depth(value: str) -> int:
    parsed = int(value)
    if parsed < -1:
        raise argparse.ArgumentTypeError("must be -1 (unlimited) or zero/greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-dedup",
        description="Find exact, re-encoded, partial, and concatenated video duplicates without deleting anything automatically.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "doctor", help="Check Python, FFmpeg, and safe-write defaults."
    ).set_defaults(func=doctor)

    scan_parser = sub.add_parser(
        "scan", help="Scan folders and write a read-only JSON duplicate report."
    )
    scan_parser.add_argument(
        "folders", nargs="+", help="One or more folders (or individual video files)."
    )
    scan_parser.add_argument(
        "--depth",
        type=nonnegative_depth,
        default=2,
        help="Subfolder depth: 0=root only, 1=one level, -1=unlimited (default: 2).",
    )
    scan_parser.add_argument(
        "--report", default="video-dedup-report.json", help="Output JSON report path."
    )
    scan_parser.add_argument(
        "--cache",
        default=".video-dedup-cache.sqlite3",
        help="Persistent incremental fingerprint cache.",
    )
    scan_parser.add_argument(
        "--workers",
        type=positive_int,
        default=min(4, max(1, os.cpu_count() or 1)),
        help="Concurrent FFmpeg processes (default: up to 4).",
    )
    scan_parser.add_argument(
        "--sample-interval",
        type=float,
        default=3.0,
        help="Seconds between confirmation frames (default: 3).",
    )
    scan_parser.add_argument(
        "--min-segment",
        type=float,
        default=9.0,
        help="Smallest duplicated segment to report, in seconds (default: 9).",
    )
    scan_parser.add_argument(
        "--hash-distance",
        type=int,
        default=20,
        help="Perceptual distance threshold; larger is more permissive (default: 20).",
    )
    scan_parser.add_argument(
        "--candidate-tokens",
        type=positive_int,
        default=512,
        help="Index tokens retained per video (default: 512).",
    )
    scan_parser.add_argument(
        "--candidate-shared",
        type=positive_int,
        default=2,
        help="Shared index tokens required for a candidate (default: 2).",
    )
    scan_parser.add_argument(
        "--max-token-frequency",
        type=positive_int,
        default=200,
        help="Ignore visual tokens occurring in more videos (default: 200).",
    )
    scan_parser.add_argument(
        "--max-candidates-per-video",
        type=positive_int,
        default=50,
        help="Safety cap for confirmation candidates per video (default: 50).",
    )
    scan_parser.add_argument(
        "--max-fast-frames",
        type=positive_int,
        default=2000,
        help="Maximum key frames retained per video (default: 2000).",
    )
    scan_parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="Retry unchanged files that previously failed instead of using cached errors.",
    )
    scan_parser.add_argument(
        "--extensions",
        default=",".join(sorted(DEFAULT_EXTENSIONS)),
        help="Comma-separated extensions to scan.",
    )
    scan_parser.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symlinked files and directories.",
    )
    scan_parser.set_defaults(func=scan)

    review_parser = sub.add_parser(
        "review", help="Interactively choose keepers and save a non-destructive plan."
    )
    review_parser.add_argument("report", help="JSON report produced by scan.")
    review_parser.add_argument(
        "--plan",
        help="Output decision-plan path (default: edited plan or video-dedup-plan.json).",
    )
    review_parser.add_argument(
        "--strategy",
        choices=REVIEW_STRATEGIES,
        default="manual",
        help="Keeper/removal strategy; manual remains the safe default.",
    )
    review_parser.add_argument(
        "--minimum-delete-coverage",
        type=float,
        default=95.0,
        help="Only plan removal when selected keepers cover at least this percentage (default: 95).",
    )
    review_parser.add_argument(
        "--batch",
        action="store_true",
        help="Open a batch command shell for range edits, undo, and compact review.",
    )
    review_parser.add_argument(
        "--edit-plan",
        help="Load decisions from an existing plan into batch review; writes back to it unless --plan is set.",
    )
    review_parser.set_defaults(func=review)

    web_review_parser = sub.add_parser(
        "web-review",
        help="Review duplicate sets visually in a local browser and save a plan.",
    )
    web_review_parser.add_argument("report", help="JSON report produced by scan.")
    web_review_parser.add_argument(
        "--plan",
        default="video-dedup-plan.json",
        help="Plan to create or resume (default: video-dedup-plan.json).",
    )
    web_review_parser.add_argument(
        "--minimum-delete-coverage",
        type=float,
        default=95.0,
        help="Only plan removal when selected keepers cover at least this percentage (default: 95).",
    )
    web_review_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface for the local review server (default: 127.0.0.1).",
    )
    web_review_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for the local review server; use 0 to select a free port (default: 8765).",
    )
    web_review_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically.",
    )
    web_review_parser.set_defaults(func=web_review)

    apply_parser = sub.add_parser(
        "apply", help="Apply a reviewed plan; quarantine is the default."
    )
    apply_parser.add_argument("plan", help="JSON plan produced by review.")
    apply_parser.add_argument(
        "--quarantine",
        help="Directory to move files into (default: timestamped folder beside the plan).",
    )
    apply_parser.add_argument(
        "--permanent",
        action="store_true",
        help="Permanently delete instead of moving to quarantine.",
    )
    apply_parser.add_argument(
        "--yes", action="store_true", help="Skip the DELETE prompt with --permanent."
    )
    apply_parser.set_defaults(func=apply_plan)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (
        getattr(args, "sample_interval", 1.0) <= 0
        or getattr(args, "min_segment", 1.0) <= 0
    ):
        parser.error("--sample-interval and --min-segment must be positive")
    if not 0 <= getattr(args, "hash_distance", 0) <= 136:
        parser.error("--hash-distance must be between 0 and 136")
    if not 0 <= getattr(args, "minimum_delete_coverage", 0) <= 100:
        parser.error("--minimum-delete-coverage must be between 0 and 100")
    if not 0 <= getattr(args, "port", 0) <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        return int(args.func(args))
    except DedupError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        if getattr(args, "command", None) == "web-review":
            print("Web review stopped. Saved plans remain available.", file=sys.stderr)
        else:
            print(
                "Interrupted. Completed fingerprints remain safely cached.",
                file=sys.stderr,
            )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
