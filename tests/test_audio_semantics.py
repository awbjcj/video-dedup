"""Synthetic media and fake-provider regression tests for advisory audio review."""

import concurrent.futures
import http.client
import io
import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
import wave
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import audio_semantics as audio
import video_dedup as vd
from openai_credit_meter import OpenAICreditMeter


class AudioReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.meter = OpenAICreditMeter(self.root / "credits.sqlite3", "video",
            "2026-11-10T00:00:00Z", "2026-12-10T00:00:00Z",
            clock=lambda: datetime(2026, 11, 21, tzinfo=timezone.utc))
        self.files = {}
        for index in (0, 1):
            path = self.root / f"video-{index}.mp4"
            path.write_bytes(b"synthetic-video")
            stat = path.stat()
            self.files[index] = {"id": index, "path": str(path), "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "duration_seconds": 200.0}
        self.matches = [{"a_id": 0, "b_id": 1, "kind": "perceptual",
            "a_sample_ranges": [[0, 1]], "b_sample_ranges": [[3, 4]],
            "aligned_ranges": [{"a_start_seconds": 2, "b_start_seconds": 14, "duration_seconds": 2}]}]
        self.clips = [audio.AudioClip(struct.pack("<h", n) * audio.SAMPLE_RATE * 2) for n in (1000, 2000)]
        self.transcribe = mock.Mock(return_value={"text": "A sufficiently long spoken test sentence.",
            "languages": [{"code": "en"}], "usage": {"type": "duration", "seconds": 2}})
        self.extract = mock.Mock(side_effect=lambda item, start, duration: self.clips[item["id"]])
        self.reviewer = audio.AudioReviewer(self.root / "evidence", self.meter, "fake-key",
                                            transcribe=self.transcribe, extract=self.extract)

    def test_paired_intervals_and_cache_preserve_cost_and_evidence(self):
        result = self.reviewer.review(self.files, self.matches, 1)
        self.assertEqual(result["evidence"][0]["status"], "similar_speech")
        self.assertEqual(self.extract.call_args_list[0].args[1:], (2.0, 2.0))
        self.assertEqual(self.extract.call_args_list[1].args[1:], (14.0, 2.0))
        self.assertEqual(self.transcribe.call_count, 2)
        self.assertEqual(self.meter.snapshot()["spent_micros"], 300)
        second = self.reviewer.review(self.files, self.matches, 1)
        self.assertEqual(self.transcribe.call_count, 2)
        self.assertTrue(second["evidence"][0]["aTranscript"]["cached"])
        self.assertEqual(self.reviewer.saved(result["groupKey"]), second)

    def test_exact_old_report_silence_identical_and_no_audio_skip_provider(self):
        self.reviewer.review(self.files, [{"a_id": 0, "b_id": 1, "kind": "exact"}], 1)
        self.reviewer.review(self.files, [{"a_id": 0, "b_id": 1, "kind": "perceptual"}], 1)
        self.extract.assert_not_called()
        for clips, status in (([None, self.clips[1]], "missing_audio"),
                              ([self.clips[0]] * 2, "identical_audio"),
                              ([audio.AudioClip(b"\x00\x00" * audio.SAMPLE_RATE * 2), self.clips[1]], "silent_audio")):
            self.extract.side_effect = lambda item, start, duration: clips[item["id"]]
            result = self.reviewer.review(self.files, self.matches, 1)
            self.assertEqual(result["evidence"][0]["status"], status)
        self.transcribe.assert_not_called()
        self.assertEqual(self.meter.snapshot()["spent_micros"], 0)

    def test_unknown_submission_is_held_and_not_retried(self):
        self.transcribe.side_effect = audio.AudioReviewError("Provider timeout")
        result = self.reviewer.review(self.files, self.matches, 1)
        self.assertTrue(result["partial"])
        self.assertEqual(self.meter.snapshot()["reserved_micros"], 225)
        self.reviewer.review(self.files, self.matches, 1)
        self.assertEqual(self.transcribe.call_count, 1)
        self.assertEqual(self.meter.snapshot()["reserved_micros"], 225)

    def test_missing_usage_keeps_hold_but_caches_text(self):
        self.transcribe.return_value.pop("usage")
        result = self.reviewer.review(self.files, self.matches, 1)
        self.assertEqual(result["evidence"][0]["aTranscript"]["accounting"], "held")
        self.assertEqual(self.meter.snapshot()["reserved_micros"], 450)
        self.reviewer.review(self.files, self.matches, 1)
        self.assertEqual(self.transcribe.call_count, 2)

    def test_held_transcript_reconciliation_updates_cache_without_upload(self):
        self.transcribe.return_value.pop("usage")
        self.reviewer.review(self.files, self.matches, 1)
        with self.reviewer._db() as db:
            keys = [row[0] for row in db.execute("SELECT id FROM transcripts WHERE state = 'ready'")]
        for key in keys:
            self.reviewer.reconcile_transcription(key, 150)
        result = self.reviewer.review(self.files, self.matches, 1)
        self.assertEqual(self.transcribe.call_count, 2)
        self.assertEqual(self.meter.snapshot()["reserved_micros"], 0)
        self.assertEqual(self.meter.snapshot()["spent_micros"], 300)
        self.assertEqual(result["evidence"][0]["aTranscript"]["accounting"], "settled")

    def test_budget_failure_occurs_before_any_upload(self):
        self.meter.reserve("other-work", 30_000_000)
        result = self.reviewer.review(self.files, self.matches, 1)
        self.assertEqual(result["evidence"][0]["status"], "unavailable")
        self.transcribe.assert_not_called()

    def test_pre_submission_failure_can_be_retried_without_duplicate_upload(self):
        submitted = self.meter.submitted
        with mock.patch.object(self.meter, "submitted", side_effect=audio.CreditBudgetError("temporary storage error")):
            first = self.reviewer.review(self.files, self.matches, 1)
        self.assertTrue(first["partial"])
        self.transcribe.assert_not_called()
        self.assertEqual(self.meter.snapshot()["reserved_micros"], 0)
        self.assertEqual(self.meter.submitted, submitted)

        second = self.reviewer.review(self.files, self.matches, 1)
        self.assertFalse(second["partial"])
        self.assertEqual(self.transcribe.call_count, 2)
        self.assertEqual(self.meter.snapshot()["spent_micros"], 300)

    def test_concurrent_same_audio_is_submitted_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.reviewer._transcript, self.clips[0]) for _ in range(4)]
            for future in futures:
                try:
                    future.result()
                except audio.AudioReviewError:
                    pass  # In-progress workers fail closed rather than duplicate the request.
        self.assertEqual(self.transcribe.call_count, 1)

    def test_modified_source_rejected_before_upload(self):
        Path(self.files[0]["path"]).write_bytes(b"changed source")
        with self.assertRaises(audio.AudioReviewError):
            self.reviewer.review(self.files, self.matches, 1)
        self.transcribe.assert_not_called()

    def test_missing_source_reports_rescan_instead_of_plan_error(self):
        Path(self.files[0]["path"]).unlink()
        with self.assertRaisesRegex(audio.AudioReviewError, "Rescan"):
            self.reviewer.review(self.files, self.matches, 1)
        self.transcribe.assert_not_called()

    def test_uncertain_transcription_can_be_retried_only_after_reconciliation(self):
        self.transcribe.side_effect = audio.AudioReviewError("Provider timeout")
        first = self.reviewer.review(self.files, self.matches, 1)
        self.assertTrue(first["partial"])
        with self.reviewer._db() as db:
            cache_key, reservation_id = db.execute("SELECT id, reservation FROM transcripts WHERE state = 'unknown'").fetchone()
        self.reviewer.review(self.files, self.matches, 1)
        self.assertEqual(self.transcribe.call_count, 1)

        self.reviewer.reconcile_transcription(cache_key, 100)
        self.assertEqual(self.meter.inspect(reservation_id)["state"], "settled")
        self.transcribe.side_effect = None
        second = self.reviewer.review(self.files, self.matches, 1)
        self.assertFalse(second["partial"])
        self.assertEqual(self.transcribe.call_count, 3)
        self.assertEqual(self.meter.snapshot()["spent_micros"], 400)

    def test_reconciliation_can_resume_after_ledger_commit(self):
        self.transcribe.side_effect = audio.AudioReviewError("Provider timeout")
        self.reviewer.review(self.files, self.matches, 1)
        with self.reviewer._db() as db:
            cache_key, reservation_id = db.execute("SELECT id, reservation FROM transcripts WHERE state = 'unknown'").fetchone()
        allow_retry = self.meter.allow_retry_after_settlement

        def interrupt_after_ledger_commit(reservation):
            allow_retry(reservation)
            raise RuntimeError("simulated interruption")

        with mock.patch.object(self.meter, "allow_retry_after_settlement", side_effect=interrupt_after_ledger_commit):
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                self.reviewer.reconcile_transcription(cache_key, 100)
        self.assertEqual(self.meter.inspect(reservation_id)["state"], "settled")
        self.reviewer.reconcile_transcription(cache_key, 100)
        self.transcribe.side_effect = None
        self.assertFalse(self.reviewer.review(self.files, self.matches, 1)["partial"])
        self.assertEqual(self.transcribe.call_count, 3)
        self.assertEqual(self.meter.snapshot()["spent_micros"], 400)

    def test_reconciliation_refuses_a_transcription_still_in_progress(self):
        reservation = self.meter.reserve("audio", 100, "audio:pending")
        self.meter.submitted(reservation.id)
        with self.reviewer._db() as db:
            db.execute("INSERT INTO transcripts VALUES (?, 'pending', NULL, ?)", ("pending", reservation.id))
        with self.assertRaises(audio.AudioReviewError):
            self.reviewer.reconcile_transcription("pending", 100)
        self.assertEqual(self.meter.inspect(reservation.id)["state"], "submitted")

    def test_stopped_pending_recovery_finds_unlinked_reservation(self):
        reservation = self.meter.reserve("audio", 100, "audio:pending")
        with self.reviewer._db() as db:
            db.execute("INSERT INTO transcripts VALUES ('pending', 'pending', NULL, NULL)")
        self.reviewer.reconcile_transcription("pending", 0, confirm_stopped=True)
        self.assertEqual(self.meter.inspect(reservation.id)["state"], "settled")
        self.meter.reserve("audio", 100, "audio:pending")
        with self.reviewer._db() as db:
            self.assertIsNone(db.execute("SELECT * FROM transcripts WHERE id = 'pending'").fetchone())

    def test_stopped_pending_recovery_before_reservation_has_no_charge(self):
        with self.reviewer._db() as db:
            db.execute("INSERT INTO transcripts VALUES ('pending', 'pending', NULL, NULL)")
        with self.assertRaises(audio.AudioReviewError):
            self.reviewer.reconcile_transcription("pending", 1, confirm_stopped=True)
        self.reviewer.reconcile_transcription("pending", 0, confirm_stopped=True)
        self.assertEqual(self.meter.snapshot()["spent_micros"], 0)

    def test_stopped_pending_recovery_accepts_a_released_reservation(self):
        reservation = self.meter.reserve("audio", 100, "audio:pending")
        self.meter.release(reservation.id)
        with self.reviewer._db() as db:
            db.execute("INSERT INTO transcripts VALUES ('pending', 'pending', NULL, ?)", (reservation.id,))
        with self.assertRaises(audio.AudioReviewError):
            self.reviewer.reconcile_transcription("pending", 1, confirm_stopped=True)
        self.reviewer.reconcile_transcription("pending", 0, confirm_stopped=True)
        self.meter.reserve("audio", 100, "audio:pending")

    def test_language_and_short_speech_are_not_equivalence(self):
        result = audio.compare_text({"text": "one", "languages": []}, {"text": "one", "languages": []})
        self.assertEqual(result["status"], "unknown")
        result = audio.compare_text({"text": "hello world long sentence", "languages": ["en"]},
                                    {"text": "bonjour le monde francais", "languages": ["fr"]})
        self.assertEqual(result["status"], "different_language")

    def test_opt_in_requires_credentials_and_budget(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(audio.AudioReviewer.from_env(self.root))
        with mock.patch.dict("os.environ", {"VIDEO_DEDUP_AUDIO_REVIEW_ENABLED": "true",
                                            "OPENAI_API_KEY": "generic"}, clear=True):
            with self.assertRaises(audio.AudioReviewError):
                audio.AudioReviewer.from_env(self.root)
        with mock.patch.dict("os.environ", {"VIDEO_DEDUP_AUDIO_REVIEW_ENABLED": "true",
                "OPENAI_OFFICIAL_BUDGET_ENABLED": "true",
                "OPENAI_CREDIT_CYCLE_START": "2026-11-10T00:00:00Z",
                "OPENAI_CREDIT_CYCLE_END": "2026-12-10T00:00:00Z",
                "OPENAI_CREDIT_LEDGER_PATH": str(self.root / "no-key.sqlite3")}, clear=True):
            with self.assertRaisesRegex(audio.AudioReviewError, "Set OPENAI_API_KEY"):
                audio.AudioReviewer.from_env(self.root, env_file=self.root / "missing.env")

    def test_api_key_from_dotenv_takes_precedence_without_exporting_other_values(self):
        env_file = self.root / ".env"
        env_file.write_text("# local settings\nexport OPENAI_API_KEY='file-key' # comment\nUNRELATED=value\n", encoding="utf-8")
        settings = {"VIDEO_DEDUP_AUDIO_REVIEW_ENABLED": "true", "OPENAI_OFFICIAL_BUDGET_ENABLED": "true",
                    "OPENAI_CREDIT_CYCLE_START": "2026-11-10T00:00:00Z", "OPENAI_CREDIT_CYCLE_END": "2026-12-10T00:00:00Z",
                    "OPENAI_CREDIT_LEDGER_PATH": str(self.root / "from-env.sqlite3"),
                    "OPENAI_API_KEY": "environment-key", "OPENAI_OFFICIAL_API_KEY": "legacy-key"}
        with mock.patch.dict("os.environ", settings, clear=True):
            reviewer = audio.AudioReviewer.from_env(self.root / "dotenv-evidence", env_file=env_file)
            self.assertEqual(reviewer.api_key, "file-key")
            self.assertNotIn("UNRELATED", os.environ)
            env_file.unlink()
            self.assertEqual(audio.AudioReviewer.from_env(self.root / "env-evidence", env_file=env_file).api_key, "environment-key")
            del os.environ["OPENAI_API_KEY"]
            self.assertEqual(audio.AudioReviewer.from_env(self.root / "legacy-evidence", env_file=env_file).api_key, "legacy-key")

    def test_invalid_dotenv_key_fails_without_exposing_its_value(self):
        env_file = self.root / ".env"
        env_file.write_text("OPENAI_API_KEY='secret-unclosed\n", encoding="utf-8")
        with self.assertRaises(audio.AudioReviewError) as error:
            audio._dotenv_api_key(env_file)
        self.assertNotIn("secret-unclosed", str(error.exception))

    def test_web_action_requires_consent_current_group_and_does_not_change_decisions(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            state = vd.WebReviewState(self.root / "report.json", self.root / "plan.json",
                self.files, self.matches, [[0, 1]], 1, [str(self.root)], 95)
        state.audio_reviewer = self.reviewer
        key = state.group_payloads[0]["audioReviewKey"]
        for payload in ({"groupId": 1, "groupKey": key},
                        {"groupId": True, "groupKey": key, "confirmUpload": True},
                        {"groupId": 1, "groupKey": "stale", "confirmUpload": True}):
            with self.assertRaises(ValueError):
                state.review_audio(payload)
        state.decisions = {1: vd.ReviewDecision({0, 1}, [], "web-keep-all")}
        result = state.review_audio({"groupId": 1, "groupKey": key, "confirmUpload": True})
        self.assertTrue(result["ok"])
        self.assertEqual(state.decisions[1].keepers, {0, 1})
        self.assertFalse(state.plan_path.exists())
        self.assertTrue(all(Path(item["path"]).exists() for item in self.files.values()))

    def test_alignment_keeps_reordered_and_gapped_intervals_separate(self):
        samples = [vd.Sample(0, 0, 100, float(n)) for n in range(20)]
        ranges = vd.aligned_time_ranges([(0, 10, 0), (1, 11, 0), (3, 0, 0), (4, 1, 0)],
                                       samples, samples, 1, 20, 20)
        self.assertEqual(ranges, [{"a_start_seconds": 0, "b_start_seconds": 10, "duration_seconds": 2},
                                  {"a_start_seconds": 3, "b_start_seconds": 0, "duration_seconds": 2}])

    def test_http_action_checks_header_consent_and_returns_saved_evidence(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            state = vd.WebReviewState(self.root / "report.json", self.root / "plan.json",
                self.files, self.matches, [[0, 1]], 1, [str(self.root)], 95)
        state.audio_reviewer = self.reviewer
        server = vd.http.server.ThreadingHTTPServer(("127.0.0.1", 0), vd.make_web_review_handler(state, b"test"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        payload = {"groupId": 1, "groupKey": state.group_payloads[0]["audioReviewKey"], "confirmUpload": True}
        def post(path, headers, body=payload):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            try:
                connection.request("POST", path, json.dumps(body), headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        try:
            status, _ = post("/api/audio-review", {})
            self.assertEqual(status, 403)
            self.transcribe.assert_not_called()
            headers = {"X-Video-Dedup-Review": "1", "Content-Type": "application/json"}
            status, _ = post("/api/audio-review", headers, {**payload, "confirmUpload": False})
            self.assertEqual(status, 400)
            self.transcribe.assert_not_called()
            status, result = post("/api/audio-review", headers)
            self.assertEqual(status, 200)
            status, saved = post("/api/audio-review/saved", headers)
            self.assertEqual(status, 200)
            self.assertEqual(saved["result"], result)
            self.assertEqual(self.transcribe.call_count, 2)
            self.assertEqual(state.decisions, {})
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_provider_transport_is_official_and_has_no_path_in_upload(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"text":"test"}'
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch("urllib.request.build_opener", return_value=opener):
            audio.official_transcribe("fake-key", self.clips[0])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/audio/transcriptions")
        self.assertIn(b'filename="matched-clip.wav"', request.data)
        self.assertNotIn(str(self.root).encode(), request.data)
        with self.assertRaises(audio.AudioReviewError):
            audio._NoRedirect().redirect_request(None, None, 307, "", {}, "https://example.invalid")

    def test_malformed_provider_json_leaves_a_reviewable_partial_result(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"not json"
        opener = mock.Mock()
        opener.open.return_value = response
        self.reviewer.transcribe = audio.official_transcribe
        with mock.patch("urllib.request.build_opener", return_value=opener):
            result = self.reviewer.review(self.files, self.matches, 1)
        self.assertTrue(result["partial"])
        self.assertEqual(result["evidence"][0]["status"], "unavailable")
        self.assertEqual(self.meter.snapshot()["reserved_micros"], 225)
        self.assertEqual(self.reviewer.saved(result["groupKey"]), result)

    def test_interrupted_provider_read_leaves_a_reviewable_partial_result(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b"partial")
        opener = mock.Mock()
        opener.open.return_value = response
        self.reviewer.transcribe = audio.official_transcribe
        with mock.patch("urllib.request.build_opener", return_value=opener):
            result = self.reviewer.review(self.files, self.matches, 1)
        self.assertTrue(result["partial"])
        self.assertEqual(result["evidence"][0]["status"], "unavailable")
        self.assertEqual(self.meter.snapshot()["reserved_micros"], 225)
        self.assertEqual(self.reviewer.saved(result["groupKey"]), result)

    def test_decoder_rejects_audio_longer_than_requested(self):
        probe = subprocess.CompletedProcess([], 0, stdout=b'{"streams": [{"index": 0}]}')
        decoded = subprocess.CompletedProcess([], 0, stdout=b"\x01\x00" * audio.SAMPLE_RATE * 61)
        with mock.patch("shutil.which", return_value="ffmpeg"), mock.patch("subprocess.run", side_effect=[probe, decoded]):
            with self.assertRaises(audio.AudioReviewError):
                audio.extract_clip(self.files[0], 0, 60)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_real_decoder_extracts_only_selected_interval(self):
        path = self.root / "tone.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(audio.SAMPLE_RATE)
            output.writeframes(b"\x00\x00" * audio.SAMPLE_RATE + self.clips[0].pcm)
        stat = path.stat()
        item = {"path": str(path), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        clip = audio.extract_clip(item, 1, 2)
        self.assertEqual(clip.digest, self.clips[0].digest)
        self.assertEqual(clip.seconds, 2)
        self.assertFalse(clip.silent)


if __name__ == "__main__":
    unittest.main()
