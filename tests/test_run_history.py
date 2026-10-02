import argparse
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import run_store
import video_dedup as vd
import test_video_dedup as fixtures


class RunHistoryTests(unittest.TestCase):
    def state(self, root):
        report_path, _ = fixtures.FingerprintTests.write_three_group_report(root)
        report = run_store.read_json(report_path)
        return vd.WebReviewState(report_path, root / 'plan.json',
                                 {item['id']: item for item in report['files']},
                                 report['matches'], [], 1, [str(root)], 95)

    def test_scan_history_keeps_success_failure_and_previous_export(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            args = argparse.Namespace(report=str(root / 'report.json'), folders=[raw])
            def scanner(options):
                run_store.write_json(Path(options.report), {'summary': {'scanned_files': 2}, 'settings': {'roots': [raw]}})
                return 0
            with mock.patch.object(vd, '_scan', side_effect=scanner):
                vd.scan(args)
                first = run_store.read_json(root / 'report.json')
                vd.scan(args)
            second = run_store.read_json(root / 'report.json')
            self.assertNotEqual(first['run_id'], second['run_id'])
            self.assertEqual(run_store.read_json(Path(first['run_directory']) / 'scan-report.json'), first)
            with mock.patch.object(vd, '_scan', side_effect=vd.DedupError('decode failed')):
                with self.assertRaises(vd.DedupError):
                    vd.scan(args)
            self.assertEqual(run_store.read_json(root / 'report.json'), second)
            manifests = [run_store.read_json(p) for p in (root / 'runs').glob('*/run.json')]
            self.assertEqual(sorted(m['status'] for m in manifests), ['completed', 'completed', 'failed'])
            self.assertTrue(all(m['started_at'] and m['finished_at'] for m in manifests))

    def test_named_snapshots_rename_load_and_restart(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = self.state(root)
            choices = [{'groupId': 1, 'keeperIds': [1], 'method': 'manual'}]
            state.save_plan(choices, 'First pass')
            first = run_store.list_plans(state.runs_root)['items'][0]
            state.save_plan([], 'Second pass')
            self.assertEqual(run_store.list_plans(state.runs_root)['total'], 2)
            state.rename_saved_plan({**first, 'name': '保留 / final pass'})
            path = run_store.plan_path(state.runs_root, first['runId'], first['id'])
            self.assertEqual(run_store.read_json(path)['name'], '保留 / final pass')
            state.update_settings({'minimumDeleteCoverage': 99, 'minimumDuplicatePercent': 95, 'minimumDuration': 20})
            payload = state.load_saved_plan(first)
            self.assertEqual(payload['initialDecisions'], choices)
            self.assertEqual(payload['settings']['minimumDeleteCoverage'], 95)
            self.assertEqual(payload['summary']['groupCount'], 3)
            restarted = self.state(root)
            self.assertEqual(restarted.load_saved_plan(first)['initialDecisions'], choices)
            self.assertEqual(run_store.read_json(state.plan_path)['name'], '保留 / final pass')

    def test_invalid_names_ids_and_busy_load_leave_state_unchanged(self):
        with tempfile.TemporaryDirectory() as raw:
            state = self.state(Path(raw))
            for name in ['', ' ', 'x' * 121, 'bad\nname', 3]:
                with self.assertRaises(ValueError):
                    state.save_plan([], name)
            self.assertFalse(state.runs_root.exists())
            for value in ['..', '../outside', '/absolute', 'a\\b']:
                with self.assertRaises(ValueError):
                    state.load_saved_plan({'runId': value, 'id': 'plan'})
            state.save_plan([], 'Empty review')
            plan = run_store.list_plans(state.runs_root)['items'][0]
            before = state.session_payload()
            state.operation_lock.acquire()
            try:
                with self.assertRaises(ValueError):
                    state.load_saved_plan(plan)
            finally:
                state.operation_lock.release()
            self.assertEqual(state.session_payload(), before)

    def test_http_catalog_load_rename_and_errors(self):
        with tempfile.TemporaryDirectory() as raw:
            state = self.state(Path(raw))
            state.save_plan([], 'Initial')
            server = vd.http.server.ThreadingHTTPServer(('127.0.0.1', 0), vd.make_web_review_handler(state, b''))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            def request(method, path, data=None):
                connection.request(method, path, json.dumps(data) if data is not None else None,
                                   {'X-Video-Dedup-Review': '1', 'Content-Type': 'application/json'})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            try:
                status, listing = request('GET', '/api/plans?page=1&pageSize=1')
                self.assertEqual(status, 200)
                self.assertEqual(listing['total'], 1)
                plan = listing['items'][0]
                self.assertEqual(request('POST', '/api/plans/rename', {**plan, 'name': 'Renamed'})[0], 200)
                self.assertEqual(request('POST', '/api/plans/load', plan)[0], 200)
                self.assertEqual(request('GET', '/api/plans?page=0')[0], 400)
                self.assertEqual(request('POST', '/api/plans/load', {**plan, 'id': 'missing'})[0], 404)
                self.assertEqual(request('POST', '/api/plans/load', {**plan, 'id': '../bad'})[0], 400)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join()

    def test_startup_restores_snapshot_settings_from_run_report(self):
        with tempfile.TemporaryDirectory() as raw:
            state = self.state(Path(raw))
            choices = [{'groupId': 1, 'keeperIds': [1], 'method': 'manual'}]
            state.minimum_coverage = 99
            state.save_plan(choices, 'Restart me')
            entry = run_store.list_plans(state.runs_root)['items'][0]
            state.load_saved_plan(entry)
            captured = {}
            def handler(restored, _bundle):
                captured['session'] = restored.session_payload()
                return object
            server = mock.Mock(server_address=('127.0.0.1', 8765))
            with mock.patch.object(vd, 'make_web_review_handler', side_effect=handler), mock.patch.object(vd.http.server, 'ThreadingHTTPServer', return_value=server):
                self.assertEqual(vd.main(['web-review', str(state.report_path), '--no-browser']), 0)
            self.assertEqual(captured['session']['initialDecisions'], choices)
            self.assertEqual(captured['session']['minimumCoverage'], 99)

    def test_loading_another_run_restores_its_source_and_empty_decisions(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = self.state(root)
            first.save_plan([], 'Empty first run')
            entry = run_store.list_plans(first.runs_root)['items'][0]
            other = root / 'other'
            other.mkdir()
            second = self.state(other)
            second.runs_root = first.runs_root
            second.save_plan([{'groupId': 2, 'keeperIds': [3]}], 'Second run')
            loaded = second.load_saved_plan(entry)
            self.assertEqual(loaded['initialDecisions'], [])
            self.assertEqual(loaded['settings']['roots'], [str(root)])
            self.assertEqual(run_store.list_plans(first.runs_root, 1, 1)['total'], 2)

    def test_failed_atomic_replace_preserves_existing_json(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'test.json'
            run_store.write_json(path, {'value': 'before'})
            with mock.patch.object(run_store.os, 'replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    run_store.write_json(path, {'value': 'after'})
            self.assertEqual(run_store.read_json(path), {'value': 'before'})
            self.assertEqual(list(path.parent.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
