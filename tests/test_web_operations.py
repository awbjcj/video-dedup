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

    def overlapping_state(self, exact_copy=True, sample_count=8):
        files = {file_id: dict(item) for file_id, item in self.state.files.items()}
        for file_id in (0, 1):
            files[file_id].update(duration_seconds=sample_count, detailed_sample_count=sample_count)
        for file_id in (2, 3):
            files[file_id].update(duration_seconds=4, detailed_sample_count=4)
        matches = [
            {'a_id': 0, 'b_id': 2, 'kind': 'perceptual', 'a_sample_ranges': [[0, 3]], 'b_sample_ranges': [[0, 3]]},
            {'a_id': 0, 'b_id': 3, 'kind': 'perceptual', 'a_sample_ranges': [[4, 7]], 'b_sample_ranges': [[0, 3]]},
            {'a_id': 4, 'b_id': 5, 'kind': 'exact'},
        ]
        if exact_copy:
            matches.extend([
                {'a_id': 0, 'b_id': 1, 'kind': 'exact'},
                {'a_id': 1, 'b_id': 2, 'kind': 'perceptual', 'a_sample_ranges': [[0, 3]], 'b_sample_ranges': [[0, 3]]},
                {'a_id': 1, 'b_id': 3, 'kind': 'perceptual', 'a_sample_ranges': [[4, 7]], 'b_sample_ranges': [[0, 3]]},
            ])
        report = json.loads(self.state.report_path.read_text(encoding='utf-8'))
        report.update(files=list(files.values()), matches=matches)
        self.state.report_path.write_text(json.dumps(report), encoding='utf-8')
        return vd.WebReviewState(self.state.report_path, self.state.plan_path, files, matches,
                                 [], 1.0, [str(self.root)], 95.0)

    def test_saved_plan_allows_reviewed_removal_shared_with_unreviewed_set(self):
        state = self.overlapping_state()
        self.assertEqual(state.groups, [[0, 1, 2], [0, 1, 3], [4, 5]])
        result = state.save_plan([{'groupId': 1, 'keeperIds': [1, 2]}])
        self.assertEqual(result['actionCount'], 1)
        self.assertEqual(result['unresolvedKeptCount'], 2)
        plan = json.loads(state.plan_path.read_text(encoding='utf-8'))
        self.assertEqual([action['path'] for action in plan['actions']], [str(self.paths[0])])
        self.assertTrue(all(path.exists() for path in self.paths))

    def test_shared_removal_clears_every_set_and_preserves_unreviewed_files(self):
        for permanent in (False, True):
            with self.subTest(permanent=permanent):
                state = self.overlapping_state()
                try:
                    result = state.apply_reviewed([{'groupId': 1, 'keeperIds': [1, 2]}],
                                                  permanent, 'DELETE' if permanent else '')
                except ValueError as exc:
                    self.fail(f'A coverage-safe shared removal was blocked: {exc}')
                self.assertTrue(result['ok'])
                self.assertEqual(result['appliedFileCount'], 1)
                self.assertEqual(result['appliedSetCount'], 1)
                self.assertFalse(self.paths[0].exists())
                self.assertTrue(all(path.exists() for path in self.paths[1:]))
                self.assertEqual(state.groups, [[1, 3], [4, 5]])
                self.assertEqual(result['session']['initialDecisions'], [])
                self.assertNotIn(0, state.source_files)
                self.assertFalse(any(0 in (match['a_id'], match['b_id']) for match in state.source_matches))
                if not permanent:
                    quarantined = list(Path(result['quarantinePath']).iterdir())
                    self.assertEqual([path.read_bytes() for path in quarantined], [b'video-0'])
                self.paths[0].write_bytes(b'video-0')
                stat = self.paths[0].stat()
                self.state.files[0].update(size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)

    def test_explicit_keeper_in_another_reviewed_set_still_blocks_shared_removal(self):
        state = self.overlapping_state()
        choices = [{'groupId': 1, 'keeperIds': [1, 2]}, {'groupId': 2, 'keeperIds': [0, 3]}]
        self.assertEqual(state.save_plan(choices)['actionCount'], 0)
        with self.assertRaisesRegex(ValueError, 'coverage-safe'):
            state.apply_reviewed(choices)
        self.assertTrue(all(path.exists() for path in self.paths))

    def test_shared_quarantine_stays_cleared_after_reloading_working_report(self):
        state = self.overlapping_state()
        choices = [{'groupId': 1, 'keeperIds': [1, 2]}]
        state.save_plan(choices, 'Before quarantine')
        run_directory = state.run_directory
        assert run_directory is not None
        original_scan = (run_directory / 'scan-report.json').read_bytes()
        state.apply_reviewed(choices)
        for report_path in (state.report_path, run_directory / 'report.json'):
            with self.subTest(report_path=report_path):
                report = json.loads(report_path.read_text(encoding='utf-8'))
                files = {item['id']: item for item in report['files']}
                restored = vd.WebReviewState(report_path, state.plan_path, files,
                                             report['matches'], [], 1.0, [str(self.root)], 95.0)
                self.assertEqual(restored.groups, [[1, 3], [4, 5]])
                self.assertNotIn(0, restored.source_files)
        self.assertEqual((run_directory / 'scan-report.json').read_bytes(), original_scan)

    def test_shared_removal_still_requires_minimum_coverage(self):
        state = self.overlapping_state(exact_copy=False, sample_count=12)
        choices = [{'groupId': 1, 'keeperIds': [2]}]
        self.assertEqual(state.save_plan(choices)['actionCount'], 0)
        with self.assertRaisesRegex(ValueError, 'coverage-safe'):
            state.apply_reviewed(choices)
        self.assertTrue(all(path.exists() for path in self.paths))

    def test_permanent_removal_checks_covering_file_in_unreviewed_set(self):
        state = self.overlapping_state(exact_copy=False)
        choices = [{'groupId': 1, 'keeperIds': [2]}]
        self.assertEqual(state.save_plan(choices)['actionCount'], 1)
        self.paths[3].write_bytes(b'changed-unreviewed-covering-file')
        result = state.apply_reviewed(choices, True, 'DELETE')
        self.assertEqual(result['appliedFileCount'], 0)
        self.assertEqual(result['failedFileCount'], 1)
        self.assertTrue(self.paths[0].exists())
        self.assertEqual(result['session']['initialDecisions'][0]['keeperIds'], [2])

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

    def test_globally_synchronized_empty_set_is_saved_but_unsafe_files_are_retained(self):
        choices = [{'groupId': 1, 'keeperIds': []}, {'groupId': 2, 'keeperIds': [3]}]
        try:
            saved = self.state.save_plan(choices)
        except ValueError as exc:
            self.fail(f'Global file selections must be validated by coverage: {exc}')
        self.assertEqual(saved['actionCount'], 1)
        restored = vd.load_review_decisions(str(self.state.plan_path), self.state.report_path,
                                           self.state.groups, self.state.files)
        self.assertEqual(restored[1].keepers, set())
        result = self.state.apply_reviewed(choices)
        self.assertEqual(result['appliedFileCount'], 1)
        self.assertTrue(self.paths[0].exists())
        self.assertTrue(self.paths[1].exists())
        self.assertFalse(self.paths[2].exists())
        self.assertEqual(result['session']['initialDecisions'][0]['keeperIds'], [])

    def test_empty_set_cannot_remove_last_copies_even_with_zero_coverage_threshold(self):
        self.state.minimum_coverage = 0
        choices = [{'groupId': 1, 'keeperIds': []}]
        self.assertEqual(self.state.save_plan(choices)['actionCount'], 0)
        with self.assertRaisesRegex(ValueError, 'coverage-safe'):
            self.state.apply_reviewed(choices)
        self.assertTrue(all(path.exists() for path in self.paths))

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
