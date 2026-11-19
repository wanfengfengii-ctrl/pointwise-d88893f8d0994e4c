import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tests import ROOT, load_sample


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments, succeeds=True):
        completed = subprocess.run(
            [sys.executable, '-B', '-m', 'review.cli', *(str(value) for value in arguments)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if succeeds:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(completed.stdout, '')
        return completed.stderr

    def write_json(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_seven_business_commands(self):
        fixture = load_sample('accident.json')
        batch_id = fixture['batch_id']
        with TemporaryDirectory(prefix='blind-review-cli-') as directory:
            root = Path(directory)
            center = root / 'center.sqlite'
            allocations = self.write_json(root / 'allocations.json', fixture['allocations'])
            registered = self.run_cli('register', center, batch_id, allocations, fixture['sealed_count'])
            self.assertEqual(registered, {'batch_id': batch_id, 'allocations': fixture['allocations']})
            manifest = self.write_json(root / 'manifest.json', registered)
            pieces = []
            for row in fixture['allocations']:
                station_id = row['station_id']
                site = root / f'{station_id}.sqlite'
                rows = self.write_json(root / f'{station_id}-trials.json', fixture['trials'][station_id])
                frozen = self.run_cli('freeze', site, manifest, station_id, rows)
                envelope = self.run_cli('issue', site, frozen['revision_id'])
                self.assertEqual(envelope['version'], 1)
                self.assertEqual(envelope['station_id'], station_id)
                pieces.append(self.write_json(root / f'{station_id}-piece.json', envelope))
                site.unlink()
            ids = [self.run_cli('receive', center, batch_id, piece)['receipt_id'] for piece in pieces]
            receipts = self.write_json(root / 'receipts.json', ids)
            thresholds = self.write_json(root / 'thresholds.json', fixture['thresholds'])
            self.assertIn('still sealed', self.run_cli('publish', center, batch_id, receipts, thresholds, succeeds=False))
            self.assertEqual(self.run_cli('reveal', center, batch_id), {'defect_count': 1})
            publication = self.run_cli('publish', center, batch_id, receipts, thresholds)
            report = publication['report']
            self.assertEqual(report['receipt_ids'], ids)
            self.assertEqual(report['thresholds'], fixture['thresholds'])
            self.assertEqual(report['probabilities'], {'first': '2/3', 'second': '1/3', 'joint': '0'})
            self.assertEqual(publication['receipt']['report_id'], report['report_id'])
            self.assertEqual(self.run_cli('fetch', center, report['report_id']), publication)
            self.assertIn('unknown report', self.run_cli('fetch', center, 999, succeeds=False))

    def test_demo(self):
        result = self.run_cli('demo')
        self.assertEqual(result['report']['batch_id'], 'B-demo')
        self.assertEqual(result['report']['defect_count'], 1)
        self.assertEqual(result['report']['probabilities'], {'first': '1/2', 'second': '1/2', 'joint': '0'})
        self.assertEqual(len(result['report']['receipt_ids']), 2)
        self.assertEqual(result['receipt']['report_id'], result['report']['report_id'])
