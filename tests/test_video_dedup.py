from __future__ import annotations

import json
import http.client
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import video_dedup as vd  # noqa: E402


class FingerprintTests(unittest.TestCase):
    @staticmethod
    def write_three_group_report(root: Path) -> tuple[Path, list[Path]]:
        paths = [
            root / "a0.mp4", root / "keeper-zero.mp4",
            root / "a1.mp4", root / "keeper-one.mp4",
            root / "a2.mp4", root / "keeper-two.mp4",
        ]
        report = root / "report.json"
        report.write_text(json.dumps({
            "settings": {"roots": [str(root)], "sample_interval_seconds": 1.0},
            "files": [
                {
                    "id": index, "path": str(path), "size_bytes": 10 + index,
                    "mtime_ns": 100 + index, "duration_seconds": 5,
                    "width": 100, "height": 100, "detailed_sample_count": None,
                }
                for index, path in enumerate(paths)
            ],
            "matches": [
                {"a_id": 0, "b_id": 1, "kind": "exact"},
                {"a_id": 2, "b_id": 3, "kind": "exact"},
                {"a_id": 4, "b_id": 5, "kind": "exact"},
            ],
        }), encoding="utf-8")
        return report, paths

    def test_frame_hash_changes_with_visual_content(self) -> None:
        dark = bytes([10] * vd.FRAME_BYTES)
        gradient = bytes((row * 20 + col * 3) % 256 for row in range(8) for col in range(9))
        first = vd.frame_sample(dark, 0.0)
        second = vd.frame_sample(gradient, 0.0)
        self.assertNotEqual((first.dhash, first.ahash, first.mean), (second.dhash, second.ahash, second.mean))

    def test_directional_coverage_for_contained_clip(self) -> None:
        clip_samples = [vd.Sample(index, index, 100, float(index)) for index in range(8)]
        other = [vd.Sample(10_000 + index, 10_000 + index, 30, float(index)) for index in range(8)]
        compilation_samples = clip_samples + other
        clip = vd.VideoRecord(0, "clip.mp4", 1, 1, 8, 1, 1, "x", [], detailed_samples=clip_samples)
        compilation = vd.VideoRecord(1, "comp.mp4", 2, 1, 16, 1, 1, "x", [], detailed_samples=compilation_samples)

        match = vd.detailed_match(clip, compilation, interval=1.0, threshold=0, min_segment=3.0)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["a_duplicated_percent"], 100.0)
        self.assertEqual(match["b_duplicated_percent"], 50.0)

    def test_flat_frames_do_not_create_a_perceptual_match(self) -> None:
        flat = [vd.Sample(0, 0xFFFFFFFFFFFFFFFF, 16, float(index)) for index in range(12)]
        left = vd.VideoRecord(0, "left.mp4", 1, 1, 12, 1, 1, "x", flat, detailed_samples=flat)
        right = vd.VideoRecord(1, "right.mp4", 1, 1, 12, 1, 1, "x", flat, detailed_samples=flat)

        self.assertFalse(vd.fast_candidate_likely(left, right, threshold=20, min_segment=3.0))
        self.assertIsNone(vd.detailed_match(left, right, interval=1.0, threshold=20, min_segment=3.0))

    def test_candidate_limit_is_symmetric_instead_of_id_biased(self) -> None:
        videos = [
            vd.VideoRecord(index, f"{index}.mp4", 1, 1, 5, 1, 1, "x", [vd.Sample(index + 1, index + 1, 1, 0.0)])
            for index in range(3)
        ]
        tokens = {
            id(videos[0].fast_samples): [10, 20],
            id(videos[1].fast_samples): [10],
            id(videos[2].fast_samples): [20],
        }
        with mock.patch.object(vd, "selected_tokens", side_effect=lambda samples, _limit: tokens[id(samples)]):
            candidates = vd.build_candidates(videos, 10, 1, 10, 1)

        self.assertEqual(candidates, {(0, 1), (0, 2)})

    def test_depth_is_relative_to_each_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "root.mp4").touch()
            (root / "one").mkdir()
            (root / "one" / "one.mp4").touch()
            (root / "one" / "two").mkdir()
            (root / "one" / "two" / "two.mp4").touch()

            depth_zero = vd.discover_videos([str(root)], 0, {".mp4"}, False)
            depth_one = vd.discover_videos([str(root)], 1, {".mp4"}, False)

            self.assertEqual([path.name for path in depth_zero], ["root.mp4"])
            self.assertEqual({path.name for path in depth_one}, {"root.mp4", "one.mp4"})

    def test_browser_preview_mode_covers_mpeg_family_and_native_sources(self) -> None:
        self.assertTrue(vd.browser_can_play_source(Path("clip.mp4"), "h264"))
        self.assertTrue(vd.browser_can_play_source(Path("clip.webm"), "vp9"))
        self.assertFalse(vd.browser_can_play_source(Path("clip.mp4"), "mpeg4"))
        self.assertFalse(vd.browser_can_play_source(Path("clip.mpeg"), "mpeg2video"))
        self.assertTrue(
            {
                ".asf", ".divx", ".m1v", ".m2v", ".m4peg", ".mpe", ".mp2",
                ".mp4v", ".mpeg", ".mpeg4", ".mpg", ".mpv", ".vob",
            }
            <= vd.DEFAULT_EXTENSIONS
        )

    def test_exact_duplicate_coverage_is_transitive(self) -> None:
        files = {
            index: {"duration_seconds": 5.0, "detailed_sample_count": None}
            for index in range(3)
        }
        matches = [
            {"a_id": 0, "b_id": 1, "kind": "exact"},
            {"a_id": 0, "b_id": 2, "kind": "exact"},
        ]

        coverage, sources = vd.covered_by(2, {1}, matches, files, 1.0)

        self.assertEqual(coverage, 100.0)
        self.assertEqual(sources, [1])

    def test_automatic_name_and_depth_strategies_choose_requested_file_first(self) -> None:
        root = Path("C:/videos")
        matches = [{"a_id": 0, "b_id": 1, "kind": "exact"}]
        cases = [
            (
                "delete-shallower",
                root / "shallow.mp4",
                root / "nested" / "deep.mp4",
            ),
            (
                "delete-shorter-name",
                root / "a.mp4",
                root / "descriptive-name.mp4",
            ),
            (
                "delete-numbered-name",
                root / "clip2.mp4",
                root / "descriptive-name.mp4",
            ),
        ]
        for strategy, first, second in cases:
            with self.subTest(strategy=strategy):
                files = {
                    0: {"path": str(first), "duration_seconds": 5, "size_bytes": 1},
                    1: {"path": str(second), "duration_seconds": 5, "size_bytes": 1},
                }
                removals = vd.automatic_removal_order(
                    [0, 1], strategy, matches, files, 1.0, 95.0, [str(root)]
                )
                self.assertEqual(removals, [0])

    def test_fully_covered_strategy_keeps_the_covering_video(self) -> None:
        files = {
            0: {"path": "clip.mp4", "duration_seconds": 10, "detailed_sample_count": 10, "size_bytes": 1},
            1: {"path": "compilation.mp4", "duration_seconds": 10, "detailed_sample_count": 10, "size_bytes": 2},
        }
        matches = [{
            "a_id": 0,
            "b_id": 1,
            "kind": "perceptual",
            "a_sample_ranges": [[0, 9]],
            "b_sample_ranges": [[0, 4]],
        }]

        removals = vd.automatic_removal_order(
            [0, 1], "delete-fully-covered", matches, files, 1.0, 95.0, []
        )

        self.assertEqual(removals, [0])

    def test_automatic_strategy_never_removes_the_last_copy(self) -> None:
        files = {
            index: {"path": f"C:/videos/{index}.mp4", "duration_seconds": 5, "size_bytes": 1}
            for index in range(3)
        }
        matches = [
            {"a_id": 0, "b_id": 1, "kind": "exact"},
            {"a_id": 0, "b_id": 2, "kind": "exact"},
        ]

        removals = vd.automatic_removal_order(
            [0, 1, 2], "delete-shorter-name", matches, files, 1.0, 95.0, ["C:/videos"]
        )

        self.assertEqual(len(removals), 2)

    def test_review_strategy_writes_a_noninteractive_ordered_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            short_name = root / "a.mp4"
            long_name = root / "descriptive-video-name.mp4"
            report = root / "report.json"
            plan = root / "plan.json"
            report.write_text(json.dumps({
                "settings": {"roots": [str(root)], "sample_interval_seconds": 1.0},
                "files": [
                    {
                        "id": 0, "path": str(short_name), "size_bytes": 10, "mtime_ns": 1,
                        "duration_seconds": 5, "width": 100, "height": 100,
                        "detailed_sample_count": None,
                    },
                    {
                        "id": 1, "path": str(long_name), "size_bytes": 10, "mtime_ns": 1,
                        "duration_seconds": 5, "width": 100, "height": 100,
                        "detailed_sample_count": None,
                    },
                ],
                "matches": [{"a_id": 0, "b_id": 1, "kind": "exact"}],
            }), encoding="utf-8")

            with mock.patch("builtins.input", side_effect=AssertionError("strategy must not prompt")):
                code = vd.main([
                    "review", str(report), "--plan", str(plan),
                    "--strategy", "delete-shorter-name",
                ])

            self.assertEqual(code, 0)
            payload = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual(payload["strategy"], "delete-shorter-name")
            self.assertEqual([action["path"] for action in payload["actions"]], [str(short_name)])

    def test_number_specs_support_ranges_and_reject_invalid_values(self) -> None:
        self.assertEqual(vd.parse_number_spec("1,3-5,3", 6, "set range"), [1, 3, 4, 5])
        self.assertEqual(vd.parse_number_spec("all", 3, "set range"), [1, 2, 3])
        for invalid in ("", "0", "4", "3-1", "1,,2"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                vd.parse_number_spec(invalid, 3, "set range")

    def test_batch_review_supports_range_edits_overrides_and_undo(self) -> None:
        files = {
            index: {
                "path": f"C:/videos/{'short' if index % 2 == 0 else 'descriptive-name'}-{index}.mp4",
                "size_bytes": 10 + index, "duration_seconds": 5,
                "width": 100, "height": 100, "detailed_sample_count": None,
            }
            for index in range(6)
        }
        groups = [[0, 1], [2, 3], [4, 5]]
        matches = [
            {"a_id": 0, "b_id": 1, "kind": "exact"},
            {"a_id": 2, "b_id": 3, "kind": "exact"},
            {"a_id": 4, "b_id": 5, "kind": "exact"},
        ]
        commands = [
            "strategy 1-3 delete-shorter-name",
            "keep 2 1",
            "undo",
            "keep 2 2",
            "skip 3",
            "done",
        ]

        with mock.patch("builtins.input", side_effect=commands):
            decisions = vd.batch_review(groups, files, matches, 1.0, ["C:/videos"], 95.0)

        assert decisions is not None
        self.assertEqual(decisions[1].method, "delete-shorter-name")
        self.assertEqual(decisions[2].keepers, {3})
        self.assertEqual(decisions[3].keepers, {4, 5})
        self.assertEqual(decisions[3].removal_order, [])

    def test_batch_plan_can_be_reopened_and_changed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            report, paths = self.write_three_group_report(root)
            plan = root / "plan.json"
            with mock.patch("builtins.input", side_effect=["keep all 2", "done"]):
                first_code = vd.main(["review", str(report), "--batch", "--plan", str(plan)])

            with mock.patch("builtins.input", side_effect=["keep 1 1", "done"]):
                edit_code = vd.main(["review", str(report), "--edit-plan", str(plan)])

            self.assertEqual(first_code, 0)
            self.assertEqual(edit_code, 0)
            payload = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual(payload["strategy"], "batch")
            self.assertEqual(len(payload["decisions"]), 3)
            self.assertEqual(
                [action["path"] for action in payload["actions"]],
                [str(paths[1]), str(paths[2]), str(paths[4])],
            )

    def test_batch_done_requires_confirmation_before_retaining_unresolved_sets(self) -> None:
        files = {
            index: {
                "path": f"C:/videos/{index}.mp4", "size_bytes": 1,
                "duration_seconds": 5, "width": 1, "height": 1,
            }
            for index in range(2)
        }
        groups = [[0, 1]]
        matches = [{"a_id": 0, "b_id": 1, "kind": "exact"}]

        with mock.patch("builtins.input", side_effect=["done", "n", "skip all", "done"]):
            decisions = vd.batch_review(groups, files, matches, 1.0, [], 95.0)

        assert decisions is not None
        self.assertEqual(decisions[1].method, "keep-all")

    def test_web_review_state_recommends_and_saves_a_compatible_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            report_path, paths = self.write_three_group_report(root)
            _, report = vd.load_json(str(report_path))
            files = {int(item["id"]): item for item in report["files"]}
            matches = report["matches"]
            groups = vd.connected_components(files, matches)
            plan_path = root / "web-plan.json"
            state = vd.WebReviewState(
                report_path, plan_path, files, matches, groups, 1.0, [str(root)], 95.0
            )

            session = state.session_payload()
            recommendations = state.recommend([1, 2], "delete-shorter-name")
            result = state.save_plan([{"groupId": 1, "keeperIds": [1], "method": "web-manual"}])

            self.assertEqual(session["summary"]["groupCount"], 3)
            self.assertEqual(session["summary"]["fileCount"], 6)
            self.assertEqual(len(recommendations), 2)
            self.assertEqual(result["actionCount"], 1)
            self.assertEqual(result["unresolvedKeptCount"], 2)
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["strategy"], "web")
            self.assertEqual(payload["actions"][0]["path"], str(paths[0]))
            self.assertEqual(len(payload["decisions"]), 3)

    def test_web_review_state_supports_concurrent_plan_saves(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            report_path, paths = self.write_three_group_report(root)
            _, report = vd.load_json(str(report_path))
            files = {int(item["id"]): item for item in report["files"]}
            matches = report["matches"]
            groups = vd.connected_components(files, matches)
            plan_path = root / "web-plan.json"
            state = vd.WebReviewState(
                report_path, plan_path, files, matches, groups, 1.0, [str(root)], 95.0
            )
            real_replace = vd.os.replace
            errors: list[BaseException] = []
            replace_guard = threading.Lock()
            active_replaces = 0
            maximum_active_replaces = 0

            def synchronized_replace(source: Path, destination: Path) -> None:
                nonlocal active_replaces, maximum_active_replaces
                with replace_guard:
                    active_replaces += 1
                    maximum_active_replaces = max(maximum_active_replaces, active_replaces)
                try:
                    time.sleep(0.05)
                    real_replace(source, destination)
                finally:
                    with replace_guard:
                        active_replaces -= 1

            def save(keeper_id: int) -> None:
                try:
                    state.save_plan([
                        {"groupId": 1, "keeperIds": [keeper_id], "method": "web-manual"}
                    ])
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(vd.os, "replace", side_effect=synchronized_replace):
                threads = [
                    threading.Thread(target=save, args=(keeper_id,))
                    for keeper_id in (0, 1)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(maximum_active_replaces, 1)
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertIn(payload["decisions"][0]["keeper_paths"], [[str(paths[0])], [str(paths[1])]])

    def test_web_review_handler_serves_session_and_video_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            report_path, paths = self.write_three_group_report(root)
            paths[0].write_bytes(b"video-bytes")
            _, report = vd.load_json(str(report_path))
            files = {int(item["id"]): item for item in report["files"]}
            matches = report["matches"]
            groups = vd.connected_components(files, matches)
            state = vd.WebReviewState(
                report_path, root / "plan.json", files, matches, groups,
                1.0, [str(root)], 95.0,
            )
            server = vd.http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0), vd.make_web_review_handler(state, b"<html>review</html>"),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            try:
                connection.request("GET", "/api/session")
                session_response = connection.getresponse()
                session_payload = json.loads(session_response.read())
                self.assertEqual(session_response.status, 200)
                self.assertEqual(session_payload["summary"]["groupCount"], 3)
                first_file = session_payload["groups"][0]["files"][0]
                self.assertEqual(first_file["previewMode"], "transcoded")
                self.assertEqual(first_file["videoUrl"], "/api/preview/0")

                connection.request("GET", "/api/video/0", headers={"Range": "bytes=1-4"})
                video_response = connection.getresponse()
                self.assertEqual(video_response.status, 206)
                self.assertEqual(video_response.getheader("Content-Range"), "bytes 1-4/11")
                self.assertEqual(video_response.read(), b"ideo")

                body = json.dumps({
                    "groupIds": [1], "strategy": "delete-fully-covered",
                }).encode()
                connection.request(
                    "POST", "/api/recommendations", body=body,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
                )
                blocked_response = connection.getresponse()
                blocked_response.read()
                self.assertEqual(blocked_response.status, 403)

                connection.request(
                    "POST", "/api/recommendations", body=body,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                        "X-Video-Dedup-Review": "1",
                    },
                )
                recommend_response = connection.getresponse()
                recommend_payload = json.loads(recommend_response.read())
                self.assertEqual(recommend_response.status, 200)
                self.assertEqual(recommend_payload["decisions"][0]["groupId"], 1)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_probe_retries_with_larger_analysis_window(self) -> None:
        payload = json.dumps({
            "streams": [{"duration": "3.5", "width": 320, "height": 180, "codec_name": "h264"}],
            "format": {"duration": "3.5"},
        }).encode()
        with mock.patch.object(vd, "run_checked", side_effect=[vd.DedupError("ordinary probe failed"), payload]) as run:
            metadata, timestamps = vd.probe_video(Path("hard-to-probe.ts"), include_keyframes=False)

        self.assertEqual(metadata["duration"], 3.5)
        self.assertEqual(timestamps, [])
        self.assertEqual(run.call_count, 2)
        self.assertIn("-analyzeduration", run.call_args_list[1].args[0])

    def test_cache_discards_a_corrupt_fingerprint_row(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            cache = vd.FingerprintCache(Path(raw) / "cache.sqlite3")
            cache.connection.execute(
                "INSERT INTO fingerprints(path,size,mtime_ns,kind,interval,metadata,samples) VALUES(?,?,?,?,?,?,?)",
                ("broken.mp4", 1, 2, vd.FAST_CACHE_KIND, 0.0, "{}", b"not-zlib"),
            )
            cache.connection.commit()

            self.assertIsNone(cache.get("broken.mp4", 1, 2, vd.FAST_CACHE_KIND, 0.0))
            self.assertEqual(cache.connection.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0], 0)
            cache.close()

    def test_unchanged_failures_are_cached_but_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "broken.mp4"
            path.write_bytes(b"not a video")
            cache = vd.FingerprintCache(Path(raw) / "cache.sqlite3")
            with mock.patch.object(vd, "extract_fast", side_effect=vd.DedupError("invalid media")) as extract:
                records, failures = vd.load_fast_records([path], cache, 1, 12)
                self.assertEqual(records, [])
                self.assertEqual(failures[0]["error"], "invalid media")
                self.assertEqual(extract.call_count, 1)

            with mock.patch.object(vd, "extract_fast") as extract:
                records, failures = vd.load_fast_records([path], cache, 1, 12)
                self.assertEqual(records, [])
                self.assertTrue(failures[0]["cached"])
                extract.assert_not_called()

            with mock.patch.object(vd, "extract_fast", side_effect=vd.DedupError("still invalid")) as extract:
                vd.load_fast_records([path], cache, 1, 12, retry_failures=True)
                self.assertEqual(extract.call_count, 1)
            cache.close()

    def test_exact_hashes_are_reused_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            first = folder / "first.mp4"
            second = folder / "second.mp4"
            first.write_bytes(b"same bytes")
            second.write_bytes(b"same bytes")
            records = []
            for index, path in enumerate((first, second)):
                stat = path.stat()
                records.append(vd.VideoRecord(index, str(path), stat.st_size, stat.st_mtime_ns, 1, 1, 1, "x", []))
            cache = vd.FingerprintCache(folder / "cache.sqlite3")

            self.assertEqual(vd.compute_exact_groups(records, 2, cache), [[0, 1]])
            for record in records:
                record.sha256 = None
            with mock.patch.object(vd, "file_sha256", side_effect=AssertionError("cache miss")) as file_hash:
                self.assertEqual(vd.compute_exact_groups(records, 2, cache), [[0, 1]])
                file_hash.assert_not_called()
            cache.close()

    def test_exact_hash_read_error_does_not_abort_scan(self) -> None:
        records = [
            vd.VideoRecord(index, f"missing-{index}.mp4", 10, 1, 1, 1, 1, "x", [])
            for index in range(2)
        ]
        failures: list[dict] = []
        groups = vd.compute_exact_groups(records, 2, failures=failures)

        self.assertEqual(groups, [])
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(item["error"].startswith("exact hashing:") for item in failures))

    def test_apply_moves_to_quarantine_and_records_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "duplicate.mp4"
            source.write_bytes(b"video")
            stat = source.stat()
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "actions": [{
                    "path": str(source), "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }]
            }), encoding="utf-8")
            quarantine = root / "quarantine"

            code = vd.main(["apply", str(plan), "--quarantine", str(quarantine)])

            self.assertEqual(code, 0)
            self.assertFalse(source.exists())
            self.assertEqual([path.read_bytes() for path in quarantine.iterdir()], [b"video"])
            result = json.loads((root / "plan.result.json").read_text(encoding="utf-8"))
            self.assertEqual(len(result["applied"]), 1)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class EndToEndVideoTests(unittest.TestCase):
    def ffmpeg(self, *arguments: str) -> None:
        subprocess.run(
            ["ffmpeg", "-v", "error", *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_mpeg_source_streams_as_fragmented_mp4_preview(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            source = folder / "legacy.mpeg"
            self.ffmpeg(
                "-f", "lavfi", "-i", "testsrc2=size=96x54:rate=8:duration=1",
                "-c:v", "mpeg2video", "-f", "mpeg", "-y", str(source),
            )
            files = {
                0: {
                    "id": 0,
                    "path": str(source),
                    "size_bytes": source.stat().st_size,
                    "mtime_ns": source.stat().st_mtime_ns,
                    "duration_seconds": 1,
                    "width": 96,
                    "height": 54,
                    "codec": "mpeg2video",
                    "detailed_sample_count": None,
                }
            }
            state = vd.WebReviewState(
                folder / "report.json", folder / "plan.json", files, [], [[0]],
                1.0, [str(folder)], 95.0,
            )
            server = vd.http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0), vd.make_web_review_handler(state, b"<html></html>"),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_address[1], timeout=15,
            )
            try:
                connection.request("GET", "/api/preview/0")
                response = connection.getresponse()
                body = response.read()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "video/mp4")
                self.assertIn(b"ftyp", body[:64])
                self.assertIn(b"moov", body)
                self.assertIn(b"moof", body)
                self.assertIn(b"mdat", body)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_reencode_and_two_part_compilation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            clip_a = folder / "clip-a.mp4"
            clip_a_small = folder / "clip-a-small.mp4"
            clip_b = folder / "clip-b.mp4"
            compilation = folder / "compilation.mp4"
            report = folder / "report.json"
            cache = folder / "cache.sqlite3"
            encode = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "8", "-keyint_min", "8", "-sc_threshold", "0"]

            self.ffmpeg("-f", "lavfi", "-i", "testsrc2=size=128x72:rate=8:duration=6", *encode, "-y", str(clip_a))
            self.ffmpeg("-f", "lavfi", "-i", "smptebars=size=128x72:rate=8:duration=6", *encode, "-y", str(clip_b))
            self.ffmpeg("-i", str(clip_a), "-vf", "scale=96:54", "-c:v", "libx264", "-crf", "32", "-g", "8", "-keyint_min", "8", "-sc_threshold", "0", "-an", "-y", str(clip_a_small))
            self.ffmpeg(
                "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=8:duration=6",
                "-f", "lavfi", "-i", "smptebars=size=128x72:rate=8:duration=6",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                *encode, "-y", str(compilation),
            )

            code = vd.main([
                "scan", str(folder), "--depth", "0", "--sample-interval", "0.5",
                "--min-segment", "2", "--workers", "2", "--report", str(report),
                "--cache", str(cache),
            ])
            self.assertEqual(code, 0)
            payload = json.loads(report.read_text(encoding="utf-8"))
            by_name = {Path(item["path"]).name: item["id"] for item in payload["files"]}

            def match_for(left: str, right: str) -> dict:
                wanted = {by_name[left], by_name[right]}
                return next(item for item in payload["matches"] if {item["a_id"], item["b_id"]} == wanted)

            reencoded = match_for("clip-a.mp4", "clip-a-small.mp4")
            self.assertEqual(reencoded["a_duplicated_percent"], 100.0)
            self.assertEqual(reencoded["b_duplicated_percent"], 100.0)

            a_in_compilation = match_for("clip-a.mp4", "compilation.mp4")
            b_in_compilation = match_for("clip-b.mp4", "compilation.mp4")
            self.assertIn(100.0, (a_in_compilation["a_duplicated_percent"], a_in_compilation["b_duplicated_percent"]))
            self.assertIn(50.0, (a_in_compilation["a_duplicated_percent"], a_in_compilation["b_duplicated_percent"]))
            self.assertIn(100.0, (b_in_compilation["a_duplicated_percent"], b_in_compilation["b_duplicated_percent"]))
            self.assertIn(50.0, (b_in_compilation["a_duplicated_percent"], b_in_compilation["b_duplicated_percent"]))


if __name__ == "__main__":
    unittest.main()
