from fractions import Fraction

from campaign.allocation import StationAllocation
from campaign.manifest import read_manifest, register
from campaign.reveal import require_revealed_count, reveal
from observations.revision import freeze, read_frozen_revision
from receipt.intake import read_accepted_piece, receive
from review.publication import publish
from review.readback import fetch
from station.codec import decode_v1
from station.issuance import issue
from tests import WorkflowCase, load_sample


class PrepareTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        self.fixture = load_sample('accident.json')

    def test_reinit(self):
        manifest = self.register_fixture(self.fixture)
        _, site_db, observations, station = self.open_site('A')
        revision = freeze(observations, manifest, 'A', self.fixture['trials']['A'])
        envelope = issue(observations, station, revision.revision_id)
        b_path, b_db, b_observations, b_station = self.open_site('B')
        b_revision = freeze(b_observations, manifest, 'B', self.fixture['trials']['B'])
        b_envelope = issue(b_observations, b_station, b_revision.revision_id)
        b_db.close()
        b_path.unlink()
        ids = self.accept_all(manifest.batch_id, (envelope, b_envelope))
        self.assertEqual(reveal(self.campaign, manifest.batch_id), 1)
        original = publish(self.campaign, self.receipts, self.reports, manifest.batch_id, ids, self.queries(self.fixture))

        for _ in range(2):
            for repository in (self.campaign, self.receipts, self.reports, observations, station):
                repository.initialize()
            repeated = register(self.campaign, manifest.batch_id, reversed(manifest.allocations), 1)
            self.assertEqual(repeated, manifest)
            self.assertEqual(read_manifest(self.campaign, manifest.batch_id), manifest)
            self.assertEqual(require_revealed_count(self.campaign, manifest.batch_id), 1)
            self.assertEqual(read_frozen_revision(observations, revision.revision_id), revision)
            self.assertEqual(issue(observations, station, revision.revision_id), envelope)
            self.assertEqual(receive(self.campaign, self.receipts, manifest.batch_id, envelope), ids[0])
            self.assertEqual(read_accepted_piece(self.receipts, ids[0]).piece, decode_v1(envelope))
            self.assertEqual(fetch(self.reports, original[0].report_id), original)
        self.assertEqual(self.publication_counts(), (1, 1))
        self.assertEqual(site_db.execute('SELECT COUNT(*) FROM frozen_revisions').fetchone(), (1,))

    def test_revision_history(self):
        manifest = self.register_fixture(self.fixture)
        _, connection, observations, station = self.open_site('A')
        original_rows = self.fixture['trials']['A']
        first = freeze(observations, manifest, 'A', original_rows)
        corrected_rows = [dict(original_rows[0], defect='5/2'), original_rows[1]]
        second = freeze(observations, manifest, 'A', corrected_rows)
        self.assertNotEqual(first.revision_id, second.revision_id)
        connection.close()

        _, _, observations, station = self.open_site('A')
        old = read_frozen_revision(observations, first.revision_id)
        new = read_frozen_revision(observations, second.revision_id)
        self.assertEqual((old, new), (first, second))
        self.assertEqual([trial.trial_id for trial in old.trials], ['a-1', 'a-2'])
        self.assertEqual(old.trials[0].weights.defect, Fraction(3))
        self.assertEqual(new.trials[0].weights.defect, Fraction(5, 2))
        self.assertEqual(decode_v1(issue(observations, station, first.revision_id)).count_evidence, (1, 4, 3))
        self.assertEqual(
            decode_v1(issue(observations, station, second.revision_id)).count_evidence,
            (1, Fraction(7, 2), Fraction(5, 2)),
        )

    def test_count_limits(self):
        allocations = (StationAllocation('A', 2), StationAllocation('B', 1))
        empty = register(self.campaign, 'zero', allocations, 0)
        full = register(self.campaign, 'full', allocations, 3)
        self.assertEqual((reveal(self.campaign, empty.batch_id), reveal(self.campaign, full.batch_id)), (0, 3))
        for batch_id, rows, total in (
            ('bad-negative', allocations, -1),
            ('bad-over', allocations, 4),
            ('bad-count-type', allocations, True),
            ('bad-capacity', (StationAllocation('A', 0),), 0),
            ('bad-capacity-type', (StationAllocation('A', True),), 0),
            ('bad-duplicate', (StationAllocation('A', 1), StationAllocation('A', 2)), 1),
            ('bad-empty', (), 0),
        ):
            with self.subTest(batch_id=batch_id), self.assertRaises(ValueError):
                register(self.campaign, batch_id, rows, total)
        for rows, total in ((allocations, 1), ((StationAllocation('A', 2),), 0)):
            with self.assertRaisesRegex(ValueError, 'conflicting registration'):
                register(self.campaign, 'zero', rows, total)
        self.center_db.close()
        self.open_center()
        with self.assertRaises(LookupError):
            read_manifest(self.campaign, 'bad-over')
        self.assertEqual(self.center_db.execute('SELECT COUNT(*) FROM campaign_batches').fetchone(), (2,))
        self.assertEqual(read_manifest(self.campaign, 'zero'), empty)
        self.assertEqual(require_revealed_count(self.campaign, 'full'), 3)

    def test_missing_trial(self):
        manifest = self.register_fixture(self.fixture)
        _, connection, observations, _ = self.open_site('A')
        with self.assertRaisesRegex(ValueError, 'coverage'):
            freeze(observations, manifest, 'A', self.fixture['trials']['A'][:1])
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM frozen_revisions').fetchone(), (0,))

    def test_duplicate_trial(self):
        manifest = self.register_fixture(self.fixture)
        _, connection, observations, _ = self.open_site('A')
        rows = self.fixture['trials']['A']
        original = freeze(observations, manifest, 'A', rows)
        with self.assertRaisesRegex(ValueError, 'duplicate trial'):
            freeze(observations, manifest, 'A', [rows[0], dict(rows[1], trial_id=rows[0]['trial_id'])])
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM frozen_revisions').fetchone(), (1,))
        self.assertEqual(read_frozen_revision(observations, original.revision_id), original)

    def test_invalid_weight(self):
        manifest = self.register_fixture(self.fixture)
        _, connection, observations, _ = self.open_site('A')
        a, b = self.fixture['trials']['A']
        for invalid in (
            {'trial_id': a['trial_id'], 'normal': 1},
            dict(a, normal=-1),
            dict(a, normal=0, defect=0),
            dict(a, defect='1/0'),
            dict(a, defect=0.5),
            dict(a, defect=True),
            dict(a, trial_id='  '),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                freeze(observations, manifest, 'A', [invalid, b])
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM frozen_revisions').fetchone(), (0,))
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM frozen_trials').fetchone(), (0,))
