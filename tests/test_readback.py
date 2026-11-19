from fractions import Fraction
import sqlite3

from campaign.reveal import reveal
from observations.revision import freeze
from receipt.intake import receive
from review.publication import publish
from review.readback import fetch
from review.thresholds import Threshold
from station.issuance import issue
from tests import WorkflowCase, load_sample


class ReadbackTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        self.fixture = load_sample('accident.json')
        self.manifest = self.register_fixture(self.fixture)
        self.batch_id = self.manifest.batch_id
        self.thresholds = self.queries(self.fixture)

    def _publish(self, ids, thresholds=None):
        if thresholds is None:
            thresholds = self.thresholds
        return publish(self.campaign, self.receipts, self.reports, self.batch_id, ids, thresholds)

    def _station_a(self):
        path, db, observations, station = self.open_site('A')
        original = freeze(observations, self.manifest, 'A', self.fixture['trials']['A'])
        a = receive(self.campaign, self.receipts, self.batch_id, issue(observations, station, original.revision_id))
        _, b_piece = self.independent_pieces()
        b = receive(self.campaign, self.receipts, self.batch_id, b_piece)
        return path, db, observations, station, (a, b)

    def _correct_a(self, observations, station):
        first, second = self.fixture['trials']['A']
        revised = freeze(observations, self.manifest, 'A', [dict(first, defect=5), second])
        return receive(self.campaign, self.receipts, self.batch_id, issue(observations, station, revised.revision_id))

    def test_explicit_receipts(self):
        _, _, observations, station, original_ids = self._station_a()
        new_id = self._correct_a(observations, station)
        self.assertNotEqual(new_id, original_ids[0])
        reveal(self.campaign, self.batch_id)
        report, _ = self._publish(original_ids)
        self.assertEqual(report.receipt_ids, original_ids)
        self.assertEqual(report.probabilities.as_tuple(), (Fraction(2, 3), Fraction(1, 3), Fraction(0)))

    def test_history_by_number(self):
        path, db, observations, station, original_ids = self._station_a()
        reveal(self.campaign, self.batch_id)
        first, first_receipt = self._publish(original_ids)
        revised_id = self._correct_a(observations, station)
        revised_ids = (revised_id, original_ids[1])
        second, second_receipt = self._publish(revised_ids)
        self.assertNotEqual(first.report_id, second.report_id)
        self.assertNotEqual(first_receipt.receipt_id, second_receipt.receipt_id)
        self.assertEqual(second.receipt_ids, revised_ids)
        self.assertEqual(second.probabilities.as_tuple(), (Fraction(3, 4), Fraction(1, 4), Fraction(0)))
        db.close()
        path.unlink()
        self.center_db.close()
        self.open_center()
        original, original_receipt = fetch(self.reports, first.report_id)
        self.assertEqual((original, original_receipt), (first, first_receipt))
        self.assertEqual(original.receipt_ids, original_ids)
        self.assertEqual((original.batch_id, original.defect_count, original.thresholds), (self.batch_id, 1, self.thresholds))
        self.assertEqual(original.probabilities.as_tuple(), (Fraction(2, 3), Fraction(1, 3), Fraction(0)))
        self.assertEqual(original_receipt.report_id, first.report_id)
        self.assertEqual(fetch(self.reports, second.report_id), (second, second_receipt))
        self.assertEqual(self.publication_counts(), (2, 2))

    def test_unknown_report(self):
        with self.assertRaisesRegex(LookupError, 'unknown report'):
            fetch(self.reports, 999)
        self.assertEqual(self.publication_counts(), (0, 0))

    def test_rollback_reopen(self):
        ids = self.accept_all(self.batch_id, self.independent_pieces())
        reveal(self.campaign, self.batch_id)
        original = self._publish(ids)
        self.center_db.executescript('''
            CREATE TABLE commit_parent (report_id INTEGER PRIMARY KEY);
            CREATE TABLE commit_child (
                report_id INTEGER REFERENCES commit_parent(report_id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fail_receipt_commit AFTER INSERT ON publication_receipts
            BEGIN
                INSERT INTO commit_child (report_id) VALUES (NEW.report_id);
            END;
        ''')
        trace = []
        self.center_db.set_trace_callback(trace.append)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                self._publish(ids, (Threshold('A', 0), Threshold('B', 1)))
        finally:
            self.center_db.set_trace_callback(None)
        commands = [statement.strip().upper() for statement in trace]
        self.assertIn('COMMIT', commands)
        self.assertIn('ROLLBACK', commands)
        self.assertLess(commands.index('COMMIT'), commands.index('ROLLBACK'))
        self.assertFalse(self.center_db.in_transaction)
        self.assertEqual(self.publication_counts(), (1, 1))
        self.assertEqual(self.center_db.execute('SELECT COUNT(*) FROM commit_child').fetchone(), (0,))
        self.center_db.close()
        self.open_center()
        self.assertEqual(self.publication_counts(), (1, 1))
        self.assertEqual(fetch(self.reports, original[0].report_id), original)
