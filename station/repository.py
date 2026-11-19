import sqlite3

from storage import initialize_schema, write_transaction


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS issued_pieces (
    revision_id INTEGER PRIMARY KEY REFERENCES frozen_revisions(revision_id),
    issue_id TEXT NOT NULL UNIQUE,
    envelope TEXT NOT NULL
);
'''


class StationRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def get_by_revision(self, revision_id: int) -> str | None:
        row = self.connection.execute(
            'SELECT envelope FROM issued_pieces WHERE revision_id = ?', (revision_id,)
        ).fetchone()
        return None if row is None else row[0]

    def save_issued(self, revision_id: int, issue_id: str, envelope: str) -> str:
        with write_transaction(self.connection):
            existing = self.get_by_revision(revision_id)
            if existing is not None:
                return existing
            self.connection.execute(
                'INSERT INTO issued_pieces (revision_id, issue_id, envelope) VALUES (?, ?, ?)',
                (revision_id, issue_id, envelope),
            )
        return envelope
