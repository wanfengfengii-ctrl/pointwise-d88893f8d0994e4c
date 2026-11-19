from fractions import Fraction
import json

from observations.revision import freeze
from receipt.intake import receive
from receipt.retest_intake import read_accepted_retest, receive_retest
from station.codec import decode_v1
from station.issuance import issue, issue_retest
from station.retest_codec import decode_retest, encode_retest
from tests import WorkflowCase, load_sample


class RetestIntakeTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        self.fixture = load_sample('accident.json')
        self.manifest = self.register_fixture(self.fixture)
        self.bindings = [
            {'candidate_id': 'R-17', 'trial_id': 'a-1'},
            {'candidate_id': 'R-42', 'trial_id': 'a-2'},
        ]

    def _issued_companion(self, station_id='A', bindings=None):
        _, connection, observations, station = self.open_site(station_id)
        bindings = self.bindings if bindings is None else bindings
        revision = freeze(
            observations, self.manifest, station_id,
            self.fixture['trials'][station_id], bindings
        )
        v1 = issue(observations, station, revision.revision_id)
        companion = issue_retest(observations, station, revision.revision_id)
        return connection, v1, companion

    def _parent_id(self, v1):
        return receive(self.campaign, self.receipts, self.manifest.batch_id, v1)

    def test_accept_and_readback(self):
        connection, v1, companion = self._issued_companion()
        parent_id = self._parent_id(v1)
        retest_id = receive_retest(self.receipts, parent_id, companion)
        self.assertIsInstance(retest_id, int)
        self.assertGreater(retest_id, 0)
        record = read_accepted_retest(self.receipts, retest_id)
        self.assertEqual(
            record, {'parent_receipt_id': parent_id, 'envelope': companion}
        )

    def test_accept_works_after_site_disconnect(self):
        connection, v1, companion = self._issued_companion()
        path = self.scratch / 'site-A.sqlite'
        connection.close()
        path.unlink()
        parent_id = self._parent_id(v1)
        retest_id = receive_retest(self.receipts, parent_id, companion)
        self.assertEqual(
            read_accepted_retest(self.receipts, retest_id)['envelope'], companion
        )

    def test_unknown_parent_is_lookup_error(self):
        _, v1, companion = self._issued_companion()
        with self.assertRaises(LookupError):
            receive_retest(self.receipts, 999, companion)
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM accepted_retest_pieces').fetchone(),
            (0,),
        )

    def test_identity_mismatch_rejected(self):
        _, v1, companion = self._issued_companion()
        parent_id = self._parent_id(v1)
        # A second, distinct V1 issue for a different revision is a different parent.
        _, _, observations_b, station_b = self.open_site('A')
        revision_b = freeze(
            observations_b, self.manifest, 'A', self.fixture['trials']['A'], self.bindings
        )
        v1_b = issue(observations_b, station_b, revision_b.revision_id)
        companion_b = issue_retest(observations_b, station_b, revision_b.revision_id)
        parent_b = self._parent_id(v1_b)
        # companion_b's identity matches parent_b, not parent_id.
        with self.assertRaisesRegex(ValueError, 'identity does not match'):
            receive_retest(self.receipts, parent_id, companion_b)
        # The legitimate pairing still succeeds.
        self.assertIsInstance(
            receive_retest(self.receipts, parent_b, companion_b), int
        )

    def test_evidence_scale_violation_rejected(self):
        _, v1, companion = self._issued_companion()
        parent_id = self._parent_id(v1)
        piece = decode_retest(companion)
        evidence = piece.candidates['R-17']
        tampered = dict(piece.candidates)
        # Break the common scale: shift a single weight so the sum no longer
        # equals the original vector times one positive rational.
        tampered['R-17'] = type(evidence)(
            evidence.normal,
            evidence.defect[:-1] + (evidence.defect[-1] + Fraction(1),),
        )
        bad = encode_retest(
            type(piece)(
                piece.batch_id, piece.station_id, piece.capacity, piece.issue_id,
                piece.revision_id, tampered,
            )
        )
        with self.assertRaisesRegex(ValueError, 'share one positive scale'):
            receive_retest(self.receipts, parent_id, bad)
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM accepted_retest_pieces').fetchone(),
            (0,),
        )

    def test_synonymous_resubmit_keeps_first_envelope(self):
        _, v1, companion = self._issued_companion()
        parent_id = self._parent_id(v1)
        first_id = receive_retest(self.receipts, parent_id, companion)

        piece = decode_retest(companion)
        scale = Fraction(7, 3)
        scaled = {
            candidate_id: type(evidence)(
                tuple(weight * scale for weight in evidence.normal),
                tuple(weight * scale for weight in evidence.defect),
            )
            for candidate_id, evidence in piece.candidates.items()
        }
        scaled_piece = type(piece)(
            piece.batch_id, piece.station_id, piece.capacity, piece.issue_id,
            piece.revision_id, scaled,
        )
        # Different JSON formatting and key ordering must not affect synonymy.
        rescaled_envelope = json.dumps(json.loads(encode_retest(scaled_piece)), indent=3)
        second_id = receive_retest(self.receipts, parent_id, rescaled_envelope)
        self.assertEqual(second_id, first_id)
        record = read_accepted_retest(self.receipts, first_id)
        self.assertEqual(record['envelope'], companion)
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM accepted_retest_pieces').fetchone(),
            (1,),
        )

    def test_conflicting_resubmit_rejected(self):
        _, v1, companion = self._issued_companion()
        parent_id = self._parent_id(v1)
        first_id = receive_retest(self.receipts, parent_id, companion)

        piece = decode_retest(companion)
        # Swap the two candidates' evidence. Each candidate still partitions the
        # original vector, so intake validation passes, but the branches stored for
        # each candidate id are no longer jointly proportional: a synonymy conflict.
        swapped = {
            'R-17': piece.candidates['R-42'],
            'R-42': piece.candidates['R-17'],
        }
        swapped_piece = type(piece)(
            piece.batch_id, piece.station_id, piece.capacity, piece.issue_id,
            piece.revision_id, swapped,
        )
        with self.assertRaisesRegex(ValueError, 'conflicting retest content'):
            receive_retest(self.receipts, parent_id, encode_retest(swapped_piece))

        # A different candidate set on the same parent is also a conflict.
        dropped = dict(piece.candidates)
        del dropped['R-42']
        dropped_piece = type(piece)(
            piece.batch_id, piece.station_id, piece.capacity, piece.issue_id,
            piece.revision_id, dropped,
        )
        with self.assertRaisesRegex(ValueError, 'conflicting retest content'):
            receive_retest(self.receipts, parent_id, encode_retest(dropped_piece))

        self.assertEqual(
            read_accepted_retest(self.receipts, first_id)['envelope'], companion
        )
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM accepted_retest_pieces').fetchone(),
            (1,),
        )

    def test_invalid_envelopes_rejected(self):
        _, v1, companion = self._issued_companion()
        parent_id = self._parent_id(v1)
        valid = json.loads(companion)
        malformed = [
            '{',
            json.dumps(dict(valid, capacity=0)),
            json.dumps(dict(valid, candidates={})),
            json.dumps(dict(valid, issue_id='  ')),
        ]
        evidence = next(iter(valid['candidates'].values()))
        wrong_length = dict(valid)
        wrong_length['candidates'] = {
            'X': {'normal': evidence['normal'][:-1], 'defect': evidence['defect'][:-1]}
        }
        malformed.append(json.dumps(wrong_length))
        bad_boundary = dict(valid)
        candidate_id = next(iter(bad_boundary['candidates']))
        bad_boundary['candidates'][candidate_id]['normal'][-1] = '1'
        malformed.append(json.dumps(bad_boundary))
        for payload in malformed:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                receive_retest(self.receipts, parent_id, payload)
        self.assertEqual(
            self.center_db.execute('SELECT COUNT(*) FROM accepted_retest_pieces').fetchone(),
            (0,),
        )

    def test_unknown_retest_receipt_lookup(self):
        with self.assertRaises(LookupError):
            read_accepted_retest(self.receipts, 12345)
        for invalid in (0, -1, True, '1'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                read_accepted_retest(self.receipts, invalid)

    def test_repeat_initialization_keeps_data(self):
        _, v1, companion = self._issued_companion()
        parent_id = self._parent_id(v1)
        retest_id = receive_retest(self.receipts, parent_id, companion)
        for repository in (self.campaign, self.receipts, self.reports):
            repository.initialize()
        self.assertEqual(
            read_accepted_retest(self.receipts, retest_id)['envelope'], companion
        )

    def test_all_zero_branch_rescaling_stays_synonymous(self):
        # A trial with zero normal weight produces an all-zero normal branch;
        # scaling an all-zero vector keeps it all-zero and stays proportional.
        rows = [
            dict(self.fixture['trials']['A'][0], normal=0),
            self.fixture['trials']['A'][1],
        ]
        _, connection, observations, station = self.open_site('A')
        revision = freeze(observations, self.manifest, 'A', rows, self.bindings)
        v1 = issue(observations, station, revision.revision_id)
        companion = issue_retest(observations, station, revision.revision_id)
        parent_id = self._parent_id(v1)
        first_id = receive_retest(self.receipts, parent_id, companion)

        piece = decode_retest(companion)
        self.assertEqual(sum(piece.candidates['R-17'].normal), 0)
        scaled = {
            candidate_id: type(evidence)(
                tuple(weight * 5 for weight in evidence.normal),
                tuple(weight * 5 for weight in evidence.defect),
            )
            for candidate_id, evidence in piece.candidates.items()
        }
        rescaled = type(piece)(
            piece.batch_id, piece.station_id, piece.capacity, piece.issue_id,
            piece.revision_id, scaled,
        )
        self.assertEqual(
            receive_retest(self.receipts, parent_id, encode_retest(rescaled)),
            first_id,
        )
        self.assertEqual(
            read_accepted_retest(self.receipts, first_id)['envelope'], companion
        )
