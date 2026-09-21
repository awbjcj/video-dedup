from __future__ import annotations

import contextlib
import io
import itertools
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import video_dedup as vd  # noqa: E402


class RegionalFingerprintTests(unittest.TestCase):
    def test_moving_obstructions_survive_index_and_temporal_confirmation(self) -> None:
        rng = random.Random(71)
        left, right = [], []
        for index in range(12):
            frame = bytes(rng.randrange(20, 180) for _ in range(vd.EXTRACT_BYTES))
            changed = bytearray(frame)
            # Replace two entire tiles, moving the occlusions on every frame.
            for position in (index % 9, (index + 4) % 9):
                y, x = divmod(position, vd.REGION_GRID)
                for row in range(vd.FRAME_HEIGHT):
                    start = (y * vd.FRAME_HEIGHT + row) * vd.EXTRACT_WIDTH + x * vd.FRAME_WIDTH
                    changed[start:start + vd.FRAME_WIDTH] = bytes([255] * vd.FRAME_WIDTH)
            left.append(vd.regional_frame_sample(frame, float(index)))
            right.append(vd.regional_frame_sample(bytes(changed), float(index)))

        self.assertTrue(all(vd.whole_sample_distance(a, b) > 20 for a, b in zip(left, right)))
        records = [
            vd.VideoRecord(i, f"{i}.mp4", 1, 1, 12, 320, 240, "h264", samples, detailed_samples=samples)
            for i, samples in enumerate((left, right))
        ]
        self.assertIn((0, 1), vd.build_candidates(records, 512, 2, 200, 50))
        self.assertTrue(vd.fast_candidate_likely(records[0], records[1], 20, 9))
        match = vd.detailed_match(
            records[0], records[1], interval=1, threshold=20, min_segment=9
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["a_duplicated_percent"], 100)
        self.assertEqual(match["b_duplicated_percent"], 100)
        self.assertEqual(vd.matching_points(left, right, 0), [])

    def test_shared_logo_and_flat_background_tiles_are_not_enough(self) -> None:
        rng = random.Random(99)
        a = vd.regional_frame_sample(bytes(rng.randrange(256) for _ in range(vd.EXTRACT_BYTES)), 0)
        b = vd.regional_frame_sample(bytes(rng.randrange(256) for _ in range(vd.EXTRACT_BYTES)), 0)
        # Unrelated content sharing one textured logo.
        b = replace(b, regions=(a.regions[0], *b.regions[1:]))
        self.assertGreater(vd.sample_distance(a, b), 20)
        # Seven blank tiles must not count as seven matching content regions.
        flat = vd.frame_sample(bytes([0] * vd.FRAME_BYTES), 0)
        a = replace(a, regions=(*a.regions[:2], *((flat,) * 7)))
        b = replace(b, regions=(*b.regions[:2], *((flat,) * 7)))
        self.assertGreater(vd.sample_distance(a, b), 20)

    def test_regional_cache_round_trip_and_old_cache_reextraction(self) -> None:
        rng = random.Random(81)
        sample = vd.regional_frame_sample(bytes(rng.randrange(256) for _ in range(vd.EXTRACT_BYTES)), 3.0)
        self.assertEqual(vd.decode_samples(vd.encode_samples([sample])), [sample])
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "clip.mp4"
            path.write_bytes(b"fixture")
            stat = path.stat()
            metadata = {"duration": 12, "width": 320, "height": 240, "codec": "h264"}
            cache = vd.FingerprintCache(Path(raw) / "cache.sqlite3")
            try:
                # This is the actual pre-regional cache representation.
                old_blob = zlib.compress(vd.SAMPLE_STRUCT.pack(1, 2, 3, 0.0))
                for kind in ("fast", "detailed"):
                    cache.connection.execute(
                        "INSERT INTO fingerprints VALUES(?,?,?,?,?,?,?)",
                        (str(path), stat.st_size, stat.st_mtime_ns, kind, 0.0, json.dumps(metadata), old_blob),
                    )
                cache.connection.commit()
                self.assertIsNone(cache.get(str(path), stat.st_size, stat.st_mtime_ns, vd.DETAILED_CACHE_KIND, 0.0))
                with mock.patch.object(vd, "extract_fast", return_value=(metadata, [sample])) as extract:
                    records, failures = vd.load_fast_records([path], cache, 1, 12)
                    self.assertFalse(failures)
                    self.assertEqual(records[0].fast_samples, [sample])
                    extract.assert_called_once()
                with mock.patch.object(vd, "extract_fast", side_effect=AssertionError("cache missed")):
                    records, failures = vd.load_fast_records([path], cache, 1, 12)
                    self.assertFalse(failures)
                    self.assertEqual(records[0].fast_samples, [sample])
            finally:
                cache.close()

    def test_malformed_regional_cache_is_evicted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            cache = vd.FingerprintCache(Path(raw) / "cache.sqlite3")
            try:
                for data in (bytes([9]), bytes([5]) + bytes(200)):
                    cache.connection.execute(
                        "INSERT INTO fingerprints VALUES(?,?,?,?,?,?,?)",
                        ("broken.mp4", 1, 2, vd.FAST_CACHE_KIND, 0.0, "{}", zlib.compress(data)),
                    )
                    self.assertIsNone(cache.get("broken.mp4", 1, 2, vd.FAST_CACHE_KIND, 0.0))
            finally:
                cache.close()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class EncodedWatermarkTests(unittest.TestCase):
    @staticmethod
    def ffmpeg(*arguments: str) -> None:
        result = subprocess.run(["ffmpeg", "-v", "error", *arguments], capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stderr.decode("utf-8", "replace"))

    def test_scan_static_floating_and_different_watermarks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            encode = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "8", "-keyint_min", "8", "-sc_threshold", "0"]
            base = folder / "base.mp4"
            # Low-contrast footage makes a bright logo shift the global mean;
            # whole-frame aHash alone loses the unchanged picture underneath.
            self.ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=8:duration=15,lutyuv=y=96+val/8", *encode, str(base))
            variants = {
                "corner": ("white", "8", "8"),
                "center": ("white", "112", "84"),
                "floating": ("white", "(W-w)*(1+sin(t*1.7))/2", "(H-h)*(1+cos(t*1.1))/2"),
                "floating_translucent": ("black@0.6", "(W-w)*(1+cos(t*1.3))/2", "(H-h)*(1+sin(t*1.9))/2"),
            }

            def overlay(source: Path, name: str, color: str, x: str, y: str) -> None:
                self.ffmpeg(
                    "-i", str(source), "-f", "lavfi", "-i",
                    f"color={color}:size=96x64:rate=8:duration=15,format=rgba,drawgrid=w=16:h=16:t=2:c=red",
                    "-filter_complex", f"[0:v][1:v]overlay=x='{x}':y='{y}':eval=frame:shortest=1[v]",
                    "-map", "[v]", *encode, "-crf", "28",
                    "-g", "16" if name == "floating_translucent" else "8",
                    str(folder / f"{name}.mp4"),
                )

            for name, (color, x, y) in variants.items():
                overlay(base, name, color, x, y)
            self.ffmpeg(
                "-ss", "3", "-i", str(folder / "floating.mp4"), "-t", "12",
                "-vf", "scale=240:180", *encode, "-crf", "28", str(folder / "trimmed.mp4"),
            )
            unrelated = folder / "unrelated.mp4"
            self.ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x240:rate=8:duration=15", *encode, str(unrelated))
            overlay(unrelated, "unrelated_shared_logo", *variants["corner"])

            report = folder / "report.json"
            arguments = ["scan", str(folder), "--workers", "2", "--report", str(report), "--cache", str(folder / "cache.sqlite3")]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(vd.main(arguments), 0)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(payload["failures"])
            names = {item["id"]: Path(item["path"]).stem for item in payload["files"]}
            matches = {frozenset((names[item["a_id"]], names[item["b_id"]])): item for item in payload["matches"]}
            for a, b in itertools.combinations(["base", *variants], 2):
                with self.subTest(left=a, right=b):
                    match = matches.get(frozenset((a, b)))
                    self.assertIsNotNone(match)
                    assert match is not None
                    self.assertGreaterEqual(match["a_duplicated_percent"], 95)
                    self.assertGreaterEqual(match["b_duplicated_percent"], 95)
            for a in ["base", *variants]:
                for b in ("unrelated", "unrelated_shared_logo"):
                    self.assertNotIn(frozenset((a, b)), matches)
            trimmed = matches.get(frozenset(("base", "trimmed")))
            self.assertIsNotNone(trimmed)
            assert trimmed is not None
            trimmed_side = "a" if names[trimmed["a_id"]] == "trimmed" else "b"
            self.assertEqual(trimmed[f"{trimmed_side}_duplicated_percent"], 100)
            self.assertEqual(trimmed["overlap_seconds"], 12)
            # A cached rescan must retain the same matches without decoding.
            with mock.patch.object(vd, "extract_fast", side_effect=AssertionError("fast cache missed")), \
                 mock.patch.object(vd, "extract_detailed", side_effect=AssertionError("detail cache missed")), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(vd.main(arguments), 0)
            cached = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(cached["failures"])
            self.assertEqual(cached["matches"], payload["matches"])


if __name__ == "__main__":
    unittest.main()
