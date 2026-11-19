from fractions import Fraction
import json
import sqlite3

from campaign.reveal import reveal
from observations.revision import freeze
from receipt.intake import receive
from receipt.retest_intake import receive_retest
from review.publication import publish
from review.retest_publication import publish_retest
from review.retest_readback import fetch_retest
from station.issuance import issue, issue_retest
from tests import WorkflowCase, load_sample


class RetestWorkflowCase(WorkflowCase):
    """Shared fixture wiring driven directly from samples/retest.json scenarios."""

    def setUp(self):
        super().setUp()
        self.fixture = load_sample('accident.json')
        self.retest_sample = load_sample('retest.json')
        self.manifest = self.register_fixture(self.fixture)
        self.batch_id = self.manifest.batch_id
        self.thresholds = self.queries(self.fixture)

    def _site(self, station_id):
        _, _, observations, station = self.open_site(station_id)
        return observations, station

    def _rows_with_overrides(self, station_id, overrides):
        rows = self.fixture['trials'][station_id]
        result = []
        for row in rows:
            new_row = dict(row)
            if station_id in overrides and row['trial_id'] in overrides[station_id]:
                new_row['defect'] = overrides[station_id][row['trial_id']]
            result.append(new_row)
        return result

    def freeze_issue_accept(
        self, station_id, rows, bindings, site_obs=None, site_station=None
    ):
        if site_obs is None:
            site_obs, site_station = self._site(station_id)
        revision = freeze(site_obs, self.manifest, station_id, rows, bindings)
        v1 = issue(site_obs, site_station, revision.revision_id)
        companion = issue_retest(site_obs, site_station, revision.revision_id)
        parent_id = receive(self.campaign, self.receipts, self.batch_id, v1)
        retest_id = receive_retest(self.receipts, parent_id, companion)
        return parent_id, retest_id, revision

    def publish_report(self, parent_ids):
        reveal(self.campaign, self.batch_id)
        report, receipt = publish(
            self.campaign, self.receipts, self.reports,
            self.batch_id, tuple(parent_ids), self.thresholds,
        )
        return report, receipt


class RetestValueTests(RetestWorkflowCase):
    def _build_original_world(self):
        case = self.retest_sample['cases']['original']
        parent_a, retest_a, _ = self.freeze_issue_accept(
            'A', self.fixture['trials']['A'], case['candidate_bindings']['A']
        )
        parent_b, _, _ = self.freeze_issue_accept(
            'B', self.fixture['trials']['B'],
            [{'candidate_id': 'S-08', 'trial_id': 'b-1'}],
        )
        report, _ = self.publish_report((parent_a, parent_b))
        return report, retest_a

    def test_original_scenario_values(self):
        report, retest_a = self._build_original_world()
        case = self.retest_sample['cases']['original']
        requests = [
            {'retest_receipt_id': retest_a, 'candidate_id': candidate_id}
            for _, candidate_id in case['request_order']
        ]
        suggestion, receipt = publish_retest(
            self.receipts, self.reports, report.report_id, requests
        )
        expected = case['expected']
        self.assertEqual(suggestion['base_loss'], Fraction(expected['base_loss']))
        self.assertEqual(
            [entry['expected_loss'] for entry in suggestion['candidates']],
            [Fraction(value) for value in expected['expected_loss']],
        )
        self.assertEqual(
            [entry['improvement'] for entry in suggestion['candidates']],
            [Fraction(value) for value in expected['improvement']],
        )
        self.assertEqual(
            [(entry['retest_receipt_id'], entry['candidate_id'])
             for entry in suggestion['best']],
            [(retest_a, candidate_id) for _, candidate_id in expected['best']],
        )
        # Request order is preserved everywhere.
        self.assertEqual(
            [entry['candidate_id'] for entry in suggestion['candidates']],
            [candidate_id for _, candidate_id in case['request_order']],
        )
        self.assertEqual(receipt['suggestion_id'], suggestion['suggestion_id'])
        self.assertIsInstance(receipt['receipt_id'], int)
        self.assertIsInstance(suggestion['suggestion_id'], int)

    def test_swapped_scenario_values(self):
        case = self.retest_sample['cases']['swapped']
        parent_a, retest_a, _ = self.freeze_issue_accept(
            'A', self.fixture['trials']['A'], case['candidate_bindings']['A']
        )
        parent_b, _, _ = self.freeze_issue_accept(
            'B', self.fixture['trials']['B'],
            [{'candidate_id': 'S-08', 'trial_id': 'b-1'}],
        )
        report, _ = self.publish_report((parent_a, parent_b))
        requests = [
            {'retest_receipt_id': retest_a, 'candidate_id': candidate_id}
            for _, candidate_id in case['request_order']
        ]
        suggestion, _ = publish_retest(
            self.receipts, self.reports, report.report_id, requests
        )
        expected = case['expected']
        self.assertEqual(suggestion['base_loss'], Fraction(expected['base_loss']))
        self.assertEqual(
            [entry['expected_loss'] for entry in suggestion['candidates']],
            [Fraction(value) for value in expected['expected_loss']],
        )
        self.assertEqual(
            [entry['candidate_id'] for entry in suggestion['best']],
            [candidate_id for _, candidate_id in expected['best']],
        )

    def test_zero_branch_and_tie_scenario(self):
        case = self.retest_sample['cases']['zero_and_tie']
        rows_a = self._rows_with_overrides('A', case['defect_overrides'])
        parent_a, retest_a, _ = self.freeze_issue_accept(
            'A', rows_a, case['candidate_bindings']['A']
        )
        parent_b, retest_b, _ = self.freeze_issue_accept(
            'B', self.fixture['trials']['B'], case['candidate_bindings']['B']
        )
        report, _ = self.publish_report((parent_a, parent_b))
        retest_by_station = {'A': retest_a, 'B': retest_b}
        requests = [
            {'retest_receipt_id': retest_by_station[station], 'candidate_id': candidate_id}
            for station, candidate_id in case['request_order']
        ]
        suggestion, receipt = publish_retest(
            self.receipts, self.reports, report.report_id, requests
        )
        expected = case['expected']
        self.assertEqual(suggestion['base_loss'], Fraction(expected['base_loss']))
        self.assertEqual(
            [entry['expected_loss'] for entry in suggestion['candidates']],
            [Fraction(value) for value in expected['expected_loss']],
        )
        self.assertEqual(
            [entry['improvement'] for entry in suggestion['candidates']],
            [Fraction(value) for value in expected['improvement']],
        )
        # All tied optima are returned, in request order.
        self.assertEqual(
            [(entry['retest_receipt_id'], entry['candidate_id'])
             for entry in suggestion['best']],
            [
                (retest_by_station[station], candidate_id)
                for station, candidate_id in expected['best']
            ],
        )
        # Each entry records its exact parent receipt.
        parents = [entry['parent_receipt_id'] for entry in suggestion['candidates']]
        self.assertEqual(parents, [parent_b, parent_a, parent_a])

    def test_original_and_swapped_coexist_as_two_revisions(self):
        # Two station-A revisions frozen in the same site database; each gets its
        # own V1 issue and companion, and each report only accepts its own piece.
        observations, station = self._site('A')
        original_case = self.retest_sample['cases']['original']
        swapped_case = self.retest_sample['cases']['swapped']
        parent_orig, retest_orig, _ = self.freeze_issue_accept(
            'A', self.fixture['trials']['A'],
            original_case['candidate_bindings']['A'], observations, station,
        )
        parent_swap, retest_swap, _ = self.freeze_issue_accept(
            'A', self.fixture['trials']['A'],
            swapped_case['candidate_bindings']['A'], observations, station,
        )
        self.assertNotEqual(parent_orig, parent_swap)
        parent_b, _, _ = self.freeze_issue_accept(
            'B', self.fixture['trials']['B'],
            [{'candidate_id': 'S-08', 'trial_id': 'b-1'}],
        )
        report_orig, _ = self.publish_report((parent_orig, parent_b))
        report_swap, _ = publish(
            self.campaign, self.receipts, self.reports,
            self.batch_id, (parent_swap, parent_b), self.thresholds,
        )
        for report in (report_orig, report_swap):
            self.assertEqual(
                report.probabilities.as_tuple(),
                (Fraction(2, 3), Fraction(1, 3), Fraction(0)),
            )
        # Using the swapped companion against the original report must be rejected.
        bad_requests = [
            {'retest_receipt_id': retest_swap, 'candidate_id': candidate_id}
            for _, candidate_id in swapped_case['request_order']
        ]
        with self.assertRaisesRegex(ValueError, 'does not belong to a piece selected'):
            publish_retest(self.receipts, self.reports, report_orig.report_id, bad_requests)
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM retest_suggestions').fetchone(), (0,)
        )

    def test_unknown_candidate_in_accepted_companion_is_lookup_error(self):
        report, retest_a = self._build_original_world()
        with self.assertRaisesRegex(LookupError, 'absent'):
            publish_retest(
                self.receipts, self.reports, report.report_id,
                [{'retest_receipt_id': retest_a, 'candidate_id': 'GHOST'}],
            )
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM retest_suggestions').fetchone(), (0,)
        )

    def test_unknown_retest_receipt_is_lookup_error(self):
        report, _ = self._build_original_world()
        with self.assertRaises(LookupError):
            publish_retest(
                self.receipts, self.reports, report.report_id,
                [{'retest_receipt_id': 999, 'candidate_id': 'R-17'}],
            )

    def test_duplicate_references_and_bad_requests_rejected(self):
        report, retest_a = self._build_original_world()
        bad_collections = (
            [],
            [{'retest_receipt_id': retest_a, 'candidate_id': 'R-17'},
             {'retest_receipt_id': retest_a, 'candidate_id': 'R-17'}],
            [{'retest_receipt_id': retest_a}],
            [{'retest_receipt_id': 0, 'candidate_id': 'R-17'}],
            [{'retest_receipt_id': retest_a, 'candidate_id': '   '}],
        )
        for requests in bad_collections:
            with self.subTest(requests=requests), self.assertRaises(ValueError):
                publish_retest(self.receipts, self.reports, report.report_id, requests)
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM retest_suggestions').fetchone(), (0,)
        )
        with self.assertRaises(ValueError):
            publish_retest(self.receipts, self.reports, report.report_id, None)

    def test_unknown_report_is_lookup_error(self):
        with self.assertRaises(LookupError):
            publish_retest(
                self.receipts, self.reports, 777,
                [{'retest_receipt_id': 1, 'candidate_id': 'R-17'}],
            )

    def test_suggestion_and_receipt_commit_together_with_rollback(self):
        report, retest_a = self._build_original_world()
        requests = [
            {'retest_receipt_id': retest_a, 'candidate_id': candidate_id}
            for candidate_id in ('R-17', 'R-42')
        ]
        # Force the receipt insert (same transaction, deferred FK) to fail at commit.
        self.center_db.executescript('''
            CREATE TABLE commit_parent (suggestion_id INTEGER PRIMARY KEY);
            CREATE TABLE commit_child (
                suggestion_id INTEGER REFERENCES commit_parent(suggestion_id)
                DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fail_retest_receipt AFTER INSERT ON retest_receipts
            BEGIN
                INSERT INTO commit_child (suggestion_id) VALUES (NEW.suggestion_id);
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
            publish_retest(self.receipts, self.reports, report.report_id, requests)
        self.assertFalse(self.center_db.in_transaction)
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM retest_suggestions').fetchone(), (0,)
        )
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM retest_receipts').fetchone(), (0,)
        )
        # Retry after the failure leaves a clean, successful result.
        self.center_db.execute('DROP TRIGGER fail_retest_receipt')
        suggestion, receipt = publish_retest(
            self.receipts, self.reports, report.report_id, requests
        )
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM retest_suggestions').fetchone(), (1,)
        )
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM retest_receipts').fetchone(), (1,)
        )
        # Reopen the center database and collect the archived result by number.
        self.center_db.close()
        self.open_center()
        fetched, fetched_receipt = fetch_retest(self.reports, suggestion['suggestion_id'])
        self.assertEqual(fetched, suggestion)
        self.assertEqual(fetched_receipt, receipt)
        self.assertEqual(fetched['report_id'], report.report_id)

    def test_fetch_unknown_suggestion(self):
        for invalid in (4242,):
            with self.assertRaisesRegex(LookupError, 'unknown retest suggestion'):
                fetch_retest(self.reports, invalid)
        for invalid in (0, -2, True):
            with self.assertRaises(ValueError):
                fetch_retest(self.reports, invalid)

    def test_all_zero_branch_allowed_but_governed_by_contract(self):
        # A trial with zero normal weight yields an all-zero normal branch; the
        # companion still partitions the original evidence and remains admissible.
        rows = [
            dict(self.fixture['trials']['A'][0], normal=0),
            self.fixture['trials']['A'][1],
        ]
        bindings = [
            {'candidate_id': 'R-17', 'trial_id': 'a-1'},
            {'candidate_id': 'R-42', 'trial_id': 'a-2'},
        ]
        parent_a, retest_a, _ = self.freeze_issue_accept('A', rows, bindings)
        parent_b, _, _ = self.freeze_issue_accept(
            'B', self.fixture['trials']['B'],
            [{'candidate_id': 'S-08', 'trial_id': 'b-1'}],
        )
        report, _ = self.publish_report((parent_a, parent_b))
        from station.retest_codec import decode_retest
        from receipt.retest_intake import read_accepted_retest
        record = read_accepted_retest(self.receipts, retest_a)
        piece = decode_retest(record['envelope'])
        self.assertEqual(sum(piece.candidates['R-17'].normal), 0)
        self.assertTrue(any(piece.candidates['R-17'].defect))
        suggestion, _ = publish_retest(
            self.receipts, self.reports, report.report_id,
            [{'retest_receipt_id': retest_a, 'candidate_id': 'R-17'}],
        )
        # The zero-mass normal outcome contributes zero; a finite loss remains.
        self.assertGreaterEqual(suggestion['candidates'][0]['expected_loss'], 0)
        self.assertEqual(
            suggestion['candidates'][0]['improvement'],
            suggestion['base_loss'] - suggestion['candidates'][0]['expected_loss'],
        )
