from fractions import Fraction
import json

from observations.revision import freeze, read_frozen_revision
from station.codec import decode_v1
from station.issuance import issue, issue_retest
from station.retest_codec import decode_retest, encode_retest
from tests import WorkflowCase, load_sample


class FreezeCandidateTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        self.fixture = load_sample('accident.json')
        self.manifest = self.register_fixture(self.fixture)
        self.bindings = [
            {'candidate_id': 'R-17', 'trial_id': 'a-1'},
            {'candidate_id': 'R-42', 'trial_id': 'a-2'},
        ]

    def test_freeze_with_and_without_candidates(self):
        _, connection, observations, station = self.open_site('A')
        plain = freeze(observations, self.manifest, 'A', self.fixture['trials']['A'])
        self.assertEqual(plain.candidates, ())
        bound = freeze(
            observations, self.manifest, 'A', self.fixture['trials']['A'], self.bindings
        )
        self.assertEqual(
            [binding.candidate_id for binding in bound.candidates], ['R-17', 'R-42']
        )
        self.assertEqual(
            [binding.trial_id for binding in bound.candidates], ['a-1', 'a-2']
        )
        # Readback after reopening the site database.
        connection.close()
        _, _, observations, station = self.open_site('A')
        reread = read_frozen_revision(observations, bound.revision_id)
        self.assertEqual(reread, bound)
        self.assertEqual(read_frozen_revision(observations, plain.revision_id).candidates, ())

    def test_invalid_bindings_leave_no_rows(self):
        _, connection, observations, _ = self.open_site('A')
        rows = self.fixture['trials']['A']
        cases = (
            [{'candidate_id': 'R-17'}],
            [{'candidate_id': '   ', 'trial_id': 'a-1'}],
            [{'candidate_id': 'R-17', 'trial_id': 'a-1', 'extra': 1}],
            [{'candidate_id': 'R-17', 'trial_id': 'a-1'},
             {'candidate_id': 'R-17', 'trial_id': 'a-2'}],
            [{'candidate_id': 'R-17', 'trial_id': 'a-1'},
             {'candidate_id': 'R-42', 'trial_id': 'a-1'}],
            [{'candidate_id': 'R-99', 'trial_id': 'missing'}],
        )
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                freeze(observations, self.manifest, 'A', rows, invalid)
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM frozen_revisions').fetchone(), (0,))
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM frozen_candidates').fetchone(), (0,))

    def test_non_iterable_binding(self):
        _, _, observations, _ = self.open_site('A')
        with self.assertRaises(ValueError):
            freeze(
                observations,
                self.manifest,
                'A',
                self.fixture['trials']['A'],
                object(),
            )


class IssueRetestTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        self.fixture = load_sample('accident.json')
        self.manifest = self.register_fixture(self.fixture)
        self.bindings = [
            {'candidate_id': 'R-17', 'trial_id': 'a-1'},
            {'candidate_id': 'R-42', 'trial_id': 'a-2'},
        ]

    def _freeze_bound(self, station_id='A', bindings=None, rows=None):
        _, _, observations, station = self.open_site(station_id)
        bindings = self.bindings if bindings is None else bindings
        rows = self.fixture['trials'][station_id] if rows is None else rows
        revision = freeze(observations, self.manifest, station_id, rows, bindings)
        return observations, station, revision

    def test_companion_identity_and_evidence(self):
        observations, station, revision = self._freeze_bound()
        v1_envelope = issue(observations, station, revision.revision_id)
        companion_envelope = issue_retest(observations, station, revision.revision_id)
        parent = decode_v1(v1_envelope)
        companion = decode_retest(companion_envelope)
        payload = json.loads(companion_envelope)
        self.assertEqual(
            set(payload),
            {'batch_id', 'station_id', 'capacity', 'issue_id', 'revision_id', 'candidates'},
        )
        # Exact V1 identity is bound into the companion.
        self.assertEqual(companion.batch_id, parent.batch_id)
        self.assertEqual(companion.station_id, parent.station_id)
        self.assertEqual(companion.capacity, parent.capacity)
        self.assertEqual(companion.issue_id, parent.issue_id)
        self.assertEqual(companion.revision_id, parent.revision_id)
        self.assertEqual(set(companion.candidates), {'R-17', 'R-42'})
        for evidence in companion.candidates.values():
            self.assertEqual(len(evidence.normal), parent.capacity + 1)
            self.assertEqual(len(evidence.defect), parent.capacity + 1)
            self.assertEqual(evidence.normal[-1], 0)
            self.assertEqual(evidence.defect[0], 0)
            summed = tuple(n + d for n, d in zip(evidence.normal, evidence.defect))
            # Common scale factor 1: branches partition the original V1 vector.
            self.assertEqual(summed, parent.count_evidence)

    def test_reissue_is_stable(self):
        observations, station, revision = self._freeze_bound()
        issue(observations, station, revision.revision_id)
        first = issue_retest(observations, station, revision.revision_id)
        second = issue_retest(observations, station, revision.revision_id)
        self.assertEqual(first, second)
        self.assertEqual(encode_retest(decode_retest(first)), first)

    def test_requires_v1_first(self):
        observations, station, revision = self._freeze_bound()
        with self.assertRaisesRegex(ValueError, 'no issued V1 piece'):
            issue_retest(observations, station, revision.revision_id)

    def test_requires_candidates(self):
        _, _, observations, station = self.open_site('A')
        revision = freeze(observations, self.manifest, 'A', self.fixture['trials']['A'])
        issue(observations, station, revision.revision_id)
        with self.assertRaisesRegex(ValueError, 'no frozen candidates'):
            issue_retest(observations, station, revision.revision_id)

    def test_unknown_revision(self):
        _, connection, observations, station = self.open_site('A')
        with self.assertRaisesRegex(LookupError, 'unknown revision'):
            issue_retest(observations, station, 999)
        self.assertEqual(
            connection.execute('SELECT COUNT(*) FROM issued_retest_pieces').fetchone(), (0,)
        )

    def test_original_trial_mapping_stays_at_station(self):
        observations, station, revision = self._freeze_bound()
        issue(observations, station, revision.revision_id)
        envelope = issue_retest(observations, station, revision.revision_id)
        # Opaque candidate labels only; the original trial ids never leave the site.
        payload = json.loads(envelope)
        for candidate in payload['candidates'].values():
            self.assertEqual(set(candidate), {'normal', 'defect'})
        stored = read_frozen_revision(observations, revision.revision_id)
        self.assertEqual(
            {binding.candidate_id: binding.trial_id for binding in stored.candidates},
            {'R-17': 'a-1', 'R-42': 'a-2'},
        )

    def test_correction_resubmits_full_revision_with_bindings(self):
        observations, station, _ = self._freeze_bound()
        first_rows = self.fixture['trials']['A']
        corrected = [dict(first_rows[0], defect='5/2'), first_rows[1]]
        second = freeze(observations, self.manifest, 'A', corrected, self.bindings)
        issue(observations, station, second.revision_id)
        envelope = issue_retest(observations, station, second.revision_id)
        companion = decode_retest(envelope)
        parent = decode_v1(issue(observations, station, second.revision_id))
        for evidence in companion.candidates.values():
            summed = tuple(n + d for n, d in zip(evidence.normal, evidence.defect))
            self.assertEqual(summed, parent.count_evidence)
        # Original revision remains readable with its own bindings.
        first = read_frozen_revision(observations, 1)
        self.assertEqual(len(first.candidates), 2)
        self.assertEqual(first.trials[0].weights.defect, Fraction(3))
