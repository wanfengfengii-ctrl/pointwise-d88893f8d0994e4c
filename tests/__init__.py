import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from campaign.allocation import StationAllocation
from campaign.manifest import register
from campaign.repository import CampaignRepository
from observations.repository import ObservationRepository
from observations.revision import freeze
from receipt.intake import receive
from receipt.repository import ReceiptRepository
from review.repository import ReportRepository
from review.thresholds import Threshold
from station.issuance import issue
from station.repository import StationRepository
from storage import open_database


ROOT = Path(__file__).resolve().parents[1]


def load_sample(name):
    return json.loads((ROOT / 'samples' / name).read_text(encoding='utf-8'))


class WorkflowCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='blind-review-test-')
        self.addCleanup(directory.cleanup)
        self.scratch = Path(directory.name)
        self.center_path = self.scratch / 'center.sqlite'
        self.open_center()

    def connect(self, path):
        connection = open_database(path)
        self.addCleanup(connection.close)
        return connection

    def open_center(self, path=None):
        self.center_db = self.connect(self.center_path if path is None else path)
        self.campaign = CampaignRepository(self.center_db)
        self.receipts = ReceiptRepository(self.center_db)
        self.reports = ReportRepository(self.center_db)
        for repository in (self.campaign, self.receipts, self.reports):
            repository.initialize()

    def open_site(self, station_id):
        path = self.scratch / f'site-{station_id}.sqlite'
        connection = self.connect(path)
        observations = ObservationRepository(connection)
        station = StationRepository(connection)
        observations.initialize()
        station.initialize()
        return path, connection, observations, station

    def register_fixture(self, fixture, defect_count=None):
        if defect_count is None:
            defect_count = fixture['sealed_count']
        allocations = tuple(StationAllocation(**row) for row in fixture['allocations'])
        return register(self.campaign, fixture['batch_id'], allocations, defect_count)

    def independent_pieces(self):
        return tuple(json.dumps(row) for row in load_sample('independent-v1.json'))

    def accept_all(self, batch_id, envelopes):
        return tuple(receive(self.campaign, self.receipts, batch_id, envelope) for envelope in envelopes)

    def issue_offline(self, manifest, trials_by_station):
        envelopes = []
        for allocation in manifest.allocations:
            station_id = allocation.station_id
            path, connection, observations, station = self.open_site(station_id)
            revision = freeze(observations, manifest, station_id, trials_by_station[station_id])
            envelopes.append(issue(observations, station, revision.revision_id))
            connection.close()
            path.unlink()
        return tuple(envelopes)

    def queries(self, fixture):
        return tuple(Threshold(**row) for row in fixture['thresholds'])

    def publication_counts(self):
        return (
            self.center_db.execute('SELECT COUNT(*) FROM reports').fetchone()[0],
            self.center_db.execute('SELECT COUNT(*) FROM publication_receipts').fetchone()[0],
        )
