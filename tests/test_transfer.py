from fractions import Fraction
import json

from campaign.manifest import register
from campaign.reveal import require_revealed_count
from observations.revision import freeze
from receipt.intake import read_accepted_piece, receive
from receipt.selection import select_pieces
from station.codec import decode_v1
from station.issuance import issue
from tests import WorkflowCase, load_sample


class TransferTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        self.fixture = load_sample('accident.json')
        self.manifest = self.register_fixture(self.fixture)
        self.batch_id = self.manifest.batch_id

    def test_station_coefficients(self):
        _, _, observations, station = self.open_site('A')
        revision = freeze(observations, self.manifest, 'A', self.fixture['trials']['A'])
        envelope = issue(observations, station, revision.revision_id)
        piece = decode_v1(envelope)
        self.assertEqual(piece.count_evidence, (Fraction(1), Fraction(4), Fraction(3)))
        payload = json.loads(envelope)
        self.assertEqual(set(payload), {'version', 'batch_id', 'station_id', 'capacity', 'issue_id', 'revision_id', 'count_evidence'})
        self.assertEqual((piece.batch_id, piece.station_id, piece.capacity), (self.batch_id, 'A', 2))
        self.assertEqual(piece.revision_id, str(revision.revision_id))
        self.assertTrue(piece.issue_id)
        self.assertEqual(issue(observations, station, revision.revision_id), envelope)
        with self.assertRaisesRegex(ValueError, 'still sealed'):
            require_revealed_count(self.campaign, self.batch_id)

    def test_offline_receive(self):
        envelopes = self.issue_offline(self.manifest, self.fixture['trials'])
        self.assertFalse((self.scratch / 'site-A.sqlite').exists())
        self.assertFalse((self.scratch / 'site-B.sqlite').exists())
        ids = self.accept_all(self.batch_id, envelopes)
        self.center_db.close()
        self.open_center()
        for receipt_id, envelope in zip(ids, envelopes, strict=True):
            accepted = read_accepted_piece(self.receipts, receipt_id)
            self.assertEqual(accepted.envelope, envelope)
            self.assertEqual(accepted.piece, decode_v1(envelope))

    def test_unknown_revision(self):
        _, connection, observations, station = self.open_site('A')
        with self.assertRaisesRegex(LookupError, 'unknown revision'):
            issue(observations, station, 999)
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM issued_pieces').fetchone(), (0,))

    def test_invalid_envelope(self):
        envelope, _ = self.independent_pieces()
        valid = json.loads(envelope)
        missing = dict(valid)
        del missing['count_evidence']
        invalid = [
            json.dumps(dict(valid, version=2)),
            json.dumps(dict(valid, version=True)),
            json.dumps(missing),
            json.dumps(dict(valid, count_evidence=['1', '4'])),
            json.dumps(dict(valid, count_evidence=['1', '1/0', '3'])),
            json.dumps(dict(valid, count_evidence=['1', '-1', '3'])),
            json.dumps(dict(valid, count_evidence=['0', '0', '0'])),
            json.dumps(dict(valid, trial_id='raw-trial')),
            envelope[:-1] + ', "version": 1}',
            '{',
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                receive(self.campaign, self.receipts, self.batch_id, payload)
        self.assertEqual(self.center_db.execute('SELECT COUNT(*) FROM accepted_pieces').fetchone(), (0,))

    def test_station_quota(self):
        envelope, _ = self.independent_pieces()
        piece = json.loads(envelope)
        for invalid, message in (
            (dict(piece, station_id='C'), 'unknown station'),
            (dict(piece, capacity=1, count_evidence=['1', '2']), 'differs from manifest'),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                receive(self.campaign, self.receipts, self.batch_id, json.dumps(invalid))
        self.assertEqual(self.center_db.execute('SELECT COUNT(*) FROM accepted_pieces').fetchone(), (0,))

    def test_foreign_same_quota(self):
        first, second = self.independent_pieces()
        accepted = receive(self.campaign, self.receipts, self.batch_id, first)
        other = register(self.campaign, 'other-batch', self.manifest.allocations, 1)
        foreign = json.dumps(dict(json.loads(second), batch_id=other.batch_id))
        with self.assertRaisesRegex(ValueError, 'different batch'):
            receive(self.campaign, self.receipts, self.batch_id, foreign)
        self.assertEqual(self.center_db.execute('SELECT COUNT(*) FROM accepted_pieces').fetchone(), (1,))
        self.assertEqual(read_accepted_piece(self.receipts, accepted).envelope, first)

    def test_receipt_retry(self):
        first, _ = self.independent_pieces()
        original = receive(self.campaign, self.receipts, self.batch_id, first)
        value = json.loads(first)
        value['count_evidence'][0] = '2/2'
        equivalent = json.dumps(value, indent=4)
        self.assertEqual(receive(self.campaign, self.receipts, self.batch_id, equivalent), original)
        value['count_evidence'][1] = '5'
        with self.assertRaisesRegex(ValueError, 'conflicting content'):
            receive(self.campaign, self.receipts, self.batch_id, json.dumps(value))
        self.assertEqual(read_accepted_piece(self.receipts, original).envelope, first)
        self.assertEqual(self.center_db.execute('SELECT COUNT(*) FROM accepted_pieces').fetchone(), (1,))

    def test_selection_cover(self):
        first, second = self.independent_pieces()
        a, b = self.accept_all(self.batch_id, (first, second))
        alternate = json.dumps(dict(json.loads(first), issue_id='alternate-A', revision_id='revision-A-2'))
        a2 = receive(self.campaign, self.receipts, self.batch_id, alternate)
        selection = select_pieces(self.receipts, self.manifest, (b, a))
        self.assertEqual(selection.receipt_ids, (b, a))
        self.assertEqual(selection.station_ids, ('B', 'A'))
        with self.assertRaisesRegex(LookupError, 'unknown receipt'):
            select_pieces(self.receipts, self.manifest, (a, 999))
        for ids, error in (((a, a), 'duplicate'), ((a, a2), 'multiple pieces'), ((a,), 'missing stations')):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, error):
                select_pieces(self.receipts, self.manifest, ids)
        self.assertEqual(self.center_db.execute('SELECT COUNT(*) FROM accepted_pieces').fetchone(), (3,))
