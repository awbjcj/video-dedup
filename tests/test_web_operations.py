import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import video_dedup as vd
import test_video_dedup as fixtures


class WebOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        report_path, self.paths = fixtures.FingerprintTests().write_three_group_report(self.root)
        _, report = vd.load_json(str(report_path))
        for index, item in enumerate(report['files']):
            self.paths[index].write_bytes(f'video-{index}'.encode())
            stat = self.paths[index].stat()
            item.update(size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        report_path.write_text(json.dumps(report), encoding='utf-8')
        files = {int(item['id']): item for item in report['files']}
        self.state = vd.WebReviewState(report_path, self.root / 'plan.json', files, report['matches'], vd.connected_components(files, report['matches']), 1.0, [str(self.root)], 95.0)
        self.decisions = [{'groupId': 1, 'keeperIds': [1], 'method': 'web-manual'}]
        self.settings = dict(minimumDeleteCoverage=95, minimumDuplicatePercent=0, minimumDuration=0, sampleInterval=1, minimumSegment=6, hashDistance=20)

    def test_permanent_requires_confirmation_and_preserves_keeper(self):
        with self.assertRaisesRegex(ValueError, 'DELETE'):
            self.state.apply_reviewed(self.decisions, True)
        self.assertTrue(self.paths[0].exists())
        result = self.state.apply_reviewed(self.decisions, True, 'DELETE')
        self.assertFalse(self.paths[0].exists())
        self.assertTrue(self.paths[1].exists())
        self.assertIsNone(result['quarantinePath'])
        self.assertTrue(json.loads(Path(result['resultPath']).read_text())['permanent'])
        self.assertEqual(self.state.get_apply_status()['completed'], 1)
        self.assertEqual(self.state.get_apply_status()['state'], 'completed')

    def test_changed_file_is_refused_for_permanent_delete(self):
        self.paths[0].write_bytes(b'changed')
        result = self.state.apply_reviewed(self.decisions, True, 'DELETE')
        self.assertEqual(result['failedFileCount'], 1)
        self.assertTrue(self.paths[0].exists())

    def test_changed_keeper_is_refused_for_permanent_delete(self):
        self.paths[1].write_bytes(b'changed-keeper')
        result = self.state.apply_reviewed(self.decisions, True, 'DELETE')
        self.assertEqual(result['failedFileCount'], 1)
        self.assertTrue(self.paths[0].exists())

    def test_folder_validation_and_multiple_roots(self):
        other = self.root / 'second'
        other.mkdir()
        command, _ = self.state._rescan_command({**self.settings, 'roots': [str(other), str(self.root), str(other)]})
        self.assertEqual(command[3:5], [str(other), str(self.root)])
        for roots in ([], 'bad', [str(self.root / 'missing')], ['']):
            with self.subTest(roots=roots), self.assertRaises(ValueError):
                self.state._rescan_command({**self.settings, 'roots': roots})

    def test_progress_is_readable_during_quarantine_and_mutations_rejected(self):
        move = vd.shutil.move
        def observe(source, destination):
            status = self.state.get_apply_status()
            self.assertEqual(status['state'], 'running')
            self.assertEqual(status['total'], 1)
            for action in (lambda: self.state.save_plan(self.decisions), lambda: self.state.start_rescan(self.settings), lambda: self.state.apply_reviewed(self.decisions), lambda: self.state.update_settings(self.settings)):
                with self.assertRaisesRegex(ValueError, 'active'):
                    action()
            return move(source, destination)
        with mock.patch.object(vd.shutil, 'move', side_effect=observe):
            self.state.apply_reviewed(self.decisions)
        self.assertEqual(self.state.get_apply_status()['completed'], 1)

    def test_scan_streams_stage_counts_and_unlocks(self):
        entered = threading.Event()
        resume = threading.Event()
        class Lines:
            def __iter__(self):
                yield 'Fast fingerprints: 2/4\n'
                entered.set()
                resume.wait(5)
        process = mock.MagicMock()
        process.__enter__.return_value = process
        process.stdout = Lines()
        process.wait.return_value = 0
        report = json.loads(self.state.report_path.read_text(encoding='utf-8'))
        report['run_directory'] = str(self.root)
        with mock.patch.object(vd.subprocess, 'Popen', return_value=process), mock.patch.object(vd, 'load_json', return_value=(self.state.report_path, report)):
            self.state.start_rescan(self.settings)
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.state.get_rescan_status()['completed'], 2)
            with self.assertRaises(ValueError):
                self.state.apply_reviewed(self.decisions)
            resume.set()
            self.assertTrue(self.state.operation_lock.acquire(timeout=5))
            self.state.operation_lock.release()
        self.assertEqual(self.state.get_rescan_status()['state'], 'completed', self.state.get_rescan_status())
