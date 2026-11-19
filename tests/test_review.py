from fractions import Fraction
import json

from campaign.allocation import StationAllocation
from campaign.manifest import register
from campaign.reveal import require_revealed_count, reveal
from review.publication import publish
from review.readback import fetch
from review.thresholds import Threshold
from tests import WorkflowCase, load_sample


class ReviewTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        self.fixture = load_sample('accident.json')

    def _publish(self, batch_id, ids, thresholds=None):
        queries = self.queries(self.fixture) if thresholds is None else thresholds
        return publish(self.campaign, self.receipts, self.reports, batch_id, ids, queries)

    def test_reveal_repeat(self):
        manifest = self.register_fixture(self.fixture)
        self.assertEqual(reveal(self.campaign, manifest.batch_id), 1)
        self.center_db.close()
        self.open_center()
        self.assertEqual(reveal(self.campaign, manifest.batch_id), 1)
        self.assertEqual(reveal(self.campaign, manifest.batch_id), 1)
        self.assertEqual(require_revealed_count(self.campaign, manifest.batch_id), 1)
        with self.assertRaisesRegex(LookupError, 'unknown batch'):
            reveal(self.campaign, 'absent')

    def test_reveal_required(self):
        manifest = self.register_fixture(self.fixture)
        ids = self.accept_all(manifest.batch_id, self.independent_pieces())
        with self.assertRaisesRegex(ValueError, 'still sealed'):
            self._publish(manifest.batch_id, ids)
        self.assertEqual(self.publication_counts(), (0, 0))

    def test_neutral_stations(self):
        fixture = load_sample('demo.json')
        manifest = self.register_fixture(fixture)
        ids = self.accept_all(manifest.batch_id, self.issue_offline(manifest, fixture['trials']))
        reveal(self.campaign, manifest.batch_id)
        report, receipt = self._publish(manifest.batch_id, ids, self.queries(fixture))
        self.assertEqual(report.probabilities.as_tuple(), (Fraction(1, 2), Fraction(1, 2), Fraction(0)))
        self.assertEqual(receipt.report_id, report.report_id)

    def test_accident_chain(self):
        fixture = self.fixture
        manifest = self.register_fixture(fixture)
        envelopes = self.issue_offline(manifest, fixture['trials'])
        self.assertFalse(any(self.scratch.glob('site-*.sqlite')))
        ids = self.accept_all(manifest.batch_id, envelopes)
        self.assertEqual(reveal(self.campaign, manifest.batch_id), 1)
        report, receipt = self._publish(manifest.batch_id, ids)
        expected = (Fraction(2, 3), Fraction(1, 3), Fraction(0))
        actual = report.probabilities.as_tuple()
        self.assertEqual(actual, expected, 'BLIND_BATCH_RISK_MISMATCH')
        self.center_db.close()
        self.open_center()
        saved, saved_receipt = fetch(self.reports, report.report_id)
        self.assertEqual((saved, saved_receipt), (report, receipt))
        self.assertEqual(saved.receipt_ids, ids)
        self.assertEqual(saved.defect_count, fixture['sealed_count'])
        self.assertEqual(saved.thresholds, self.queries(fixture))
        self.assertEqual(saved_receipt.report_id, saved.report_id)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v5.accident_chain',
            'input': fixture,
            'expected': [str(value) for value in expected],
            'actual': [str(value) for value in actual],
            'downstream_expected': {
                'receipt_ids': ids,
                'probabilities': [str(value) for value in expected],
                'receipt_report_id': report.report_id,
            },
            'downstream_actual': {
                'receipt_ids': saved.receipt_ids,
                'probabilities': [str(value) for value in saved.probabilities.as_tuple()],
                'receipt_report_id': saved_receipt.report_id,
            },
            'code_paths': ['station/evidence.py', 'receipt/intake.py', 'review/distribution.py', 'review/thresholds.py', 'review/publication.py', 'review/readback.py'],
            'oracle': 'Enumerate the three possible single-defect trial identities. Their weights are 3, 1 and 2. A receives 4 of 6, B receives 2 of 6, and no assignment meets both thresholds.',
        }, ensure_ascii=False, sort_keys=True))

    def test_independent_pieces(self):
        manifest = self.register_fixture(self.fixture)
        ids = self.accept_all(manifest.batch_id, self.independent_pieces())
        reveal(self.campaign, manifest.batch_id)
        report, _ = self._publish(manifest.batch_id, ids)
        self.assertEqual(report.probabilities.as_tuple(), (Fraction(2, 3), Fraction(1, 3), Fraction(0)))
        self.assertEqual(report.receipt_ids, ids)

    def test_secondary_total(self):
        # A's pair contributes 3; the two A-and-B assignments contribute 6 and 2.
        envelopes = self.independent_pieces()
        cases = (
            (1, (Fraction(2, 3), Fraction(1, 3), Fraction(0))),
            (2, (Fraction(1), Fraction(8, 11), Fraction(8, 11))),
        )
        for total, expected in cases:
            with self.subTest(total=total):
                self.center_db.close()
                self.open_center(self.scratch / f'center-{total}.sqlite')
                manifest = self.register_fixture(self.fixture, defect_count=total)
                ids = self.accept_all(manifest.batch_id, envelopes)
                self.assertEqual(reveal(self.campaign, manifest.batch_id), total)
                report, _ = self._publish(manifest.batch_id, ids)
                self.assertEqual(report.probabilities.as_tuple(), expected)
                self.assertEqual(report.defect_count, total)

    def test_order_and_other_station(self):
        allocations = tuple(StationAllocation(name, 1) for name in ('A', 'B', 'C'))
        manifest = register(self.campaign, 'three', allocations, 1)
        trials = {
            name: [{'trial_id': name.lower(), 'normal': 1, 'defect': weight}]
            for name, weight in (('A', 3), ('B', 2), ('C', 1))
        }
        ids = self.accept_all(manifest.batch_id, self.issue_offline(manifest, trials))
        reveal(self.campaign, manifest.batch_id)
        thresholds = (Threshold('B', 1), Threshold('A', 1))
        report, _ = self._publish(manifest.batch_id, tuple(reversed(ids)), thresholds)
        self.assertEqual(report.thresholds, thresholds)
        self.assertEqual(report.receipt_ids, tuple(reversed(ids)))
        self.assertEqual(report.probabilities.as_tuple(), (Fraction(1, 3), Fraction(1, 2), Fraction(0)))

    def test_threshold_edges(self):
        manifest = self.register_fixture(self.fixture)
        ids = self.accept_all(manifest.batch_id, self.independent_pieces())
        reveal(self.campaign, manifest.batch_id)
        report, _ = self._publish(manifest.batch_id, ids, (Threshold('A', 0), Threshold('B', 2)))
        self.assertEqual(report.probabilities.as_tuple(), (Fraction(1), Fraction(0), Fraction(0)))
        for invalid in (
            (Threshold('C', 1), Threshold('B', 1)),
            (Threshold('A', 1), Threshold('A', 1)),
            (Threshold('A', -1), Threshold('B', 1)),
            (Threshold('A', True), Threshold('B', 1)),
            (Threshold('A', 1),),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self._publish(manifest.batch_id, ids, invalid)
        self.assertEqual(self.publication_counts(), (1, 1))

    def test_no_artifacts(self):
        manifest = self.register_fixture(self.fixture)
        trials = {
            station: [dict(trial, defect=0) for trial in rows]
            for station, rows in self.fixture['trials'].items()
        }
        ids = self.accept_all(manifest.batch_id, self.issue_offline(manifest, trials))
        reveal(self.campaign, manifest.batch_id)
        with self.assertRaisesRegex(ValueError, 'no compatible evidence'):
            self._publish(manifest.batch_id, ids)
        self.assertEqual(self.publication_counts(), (0, 0))
        self.assertEqual(self.center_db.execute('SELECT COUNT(*) FROM accepted_pieces').fetchone(), (2,))
