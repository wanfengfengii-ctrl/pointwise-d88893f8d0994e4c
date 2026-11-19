import sqlite3

from campaign.allocation import StationAllocation
from storage import initialize_schema, write_transaction


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS campaign_batches (
    batch_id TEXT PRIMARY KEY NOT NULL,
    sealed_count TEXT NOT NULL,
    revealed INTEGER NOT NULL DEFAULT 0 CHECK (revealed IN (0, 1))
);
CREATE TABLE IF NOT EXISTS campaign_allocations (
    batch_id TEXT NOT NULL REFERENCES campaign_batches(batch_id),
    station_id TEXT NOT NULL,
    capacity TEXT NOT NULL,
    PRIMARY KEY (batch_id, station_id)
);
'''


class CampaignRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def register_sealed(
        self, batch_id: str, allocations: tuple[StationAllocation, ...], sealed_count: int
    ) -> None:
        with write_transaction(self.connection):
            existing = self.connection.execute(
                'SELECT sealed_count FROM campaign_batches WHERE batch_id = ?', (batch_id,)
            ).fetchone()
            if existing is not None:
                if int(existing[0]) != sealed_count or self.load_allocations(batch_id) != allocations:
                    raise ValueError(f'conflicting registration for batch {batch_id!r}')
                return

            self.connection.execute(
                'INSERT INTO campaign_batches (batch_id, sealed_count) VALUES (?, ?)',
                (batch_id, str(sealed_count)),
            )
            self.connection.executemany(
                'INSERT INTO campaign_allocations (batch_id, station_id, capacity) VALUES (?, ?, ?)',
                ((batch_id, row.station_id, str(row.capacity)) for row in allocations),
            )

    def load_allocations(self, batch_id: str) -> tuple[StationAllocation, ...] | None:
        rows = self.connection.execute(
            '''SELECT station_id, capacity FROM campaign_allocations
               WHERE batch_id = ? ORDER BY station_id''',
            (batch_id,),
        ).fetchall()
        if not rows:
            return None
        return tuple(StationAllocation(station_id, int(capacity)) for station_id, capacity in rows)

    def reveal_count(self, batch_id: str) -> int:
        with write_transaction(self.connection):
            row = self.connection.execute(
                'SELECT sealed_count, revealed FROM campaign_batches WHERE batch_id = ?', (batch_id,)
            ).fetchone()
            if row is None:
                raise LookupError(f'unknown batch {batch_id!r}')
            count, revealed = row
            if not revealed:
                self.connection.execute(
                    'UPDATE campaign_batches SET revealed = 1 WHERE batch_id = ?', (batch_id,)
                )
            return int(count)

    def load_revealed_count(self, batch_id: str) -> int | None:
        row = self.connection.execute(
            '''SELECT CASE WHEN revealed = 1 THEN sealed_count END
               FROM campaign_batches WHERE batch_id = ?''',
            (batch_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown batch {batch_id!r}')
        return None if row[0] is None else int(row[0])
