import sqlite3

from storage import initialize_schema, write_transaction


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS accepted_pieces (
    receipt_id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    envelope TEXT NOT NULL,
    canonical_envelope TEXT NOT NULL,
    UNIQUE (batch_id, station_id, issue_id)
);
CREATE TABLE IF NOT EXISTS accepted_retest_pieces (
    retest_receipt_id INTEGER PRIMARY KEY,
    parent_receipt_id INTEGER NOT NULL UNIQUE REFERENCES accepted_pieces(receipt_id),
    envelope TEXT NOT NULL,
    canonical_envelope TEXT NOT NULL
);
'''


class ReceiptRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def accept_piece(
        self, batch_id: str, station_id: str, issue_id: str, envelope: str, canonical: str
    ) -> int:
        with write_transaction(self.connection):
            existing = self.connection.execute(
                '''SELECT receipt_id, canonical_envelope FROM accepted_pieces
                   WHERE batch_id = ? AND station_id = ? AND issue_id = ?''',
                (batch_id, station_id, issue_id),
            ).fetchone()
            if existing is not None:
                receipt_id, existing_content = existing
                if existing_content != canonical:
                    raise ValueError(f'conflicting content for issue {issue_id!r}')
                return receipt_id
            cursor = self.connection.execute(
                '''INSERT INTO accepted_pieces
                   (batch_id, station_id, issue_id, envelope, canonical_envelope)
                   VALUES (?, ?, ?, ?, ?)''',
                (batch_id, station_id, issue_id, envelope, canonical),
            )
        return cursor.lastrowid

    def read_piece(self, receipt_id: int) -> str | None:
        # A positive number beyond SQLite's rowid range cannot refer to a row.
        if receipt_id > 2**63 - 1:
            return None
        row = self.connection.execute(
            'SELECT envelope FROM accepted_pieces WHERE receipt_id = ?', (receipt_id,)
        ).fetchone()
        return None if row is None else row[0]

    def accept_retest(
        self,
        parent_receipt_id: int,
        envelope: str,
        canonical: str,
        is_synonymous,
        conflict_message: str,
    ) -> int:
        with write_transaction(self.connection):
            existing = self.connection.execute(
                '''SELECT retest_receipt_id, envelope FROM accepted_retest_pieces
                   WHERE parent_receipt_id = ?''',
                (parent_receipt_id,),
            ).fetchone()
            if existing is not None:
                retest_receipt_id, first_envelope = existing
                if not is_synonymous(first_envelope):
                    raise ValueError(conflict_message)
                return retest_receipt_id
            cursor = self.connection.execute(
                '''INSERT INTO accepted_retest_pieces
                   (parent_receipt_id, envelope, canonical_envelope)
                   VALUES (?, ?, ?)''',
                (parent_receipt_id, envelope, canonical),
            )
        return cursor.lastrowid

    def read_retest(self, retest_receipt_id: int) -> tuple[int, str] | None:
        if retest_receipt_id > 2**63 - 1:
            return None
        row = self.connection.execute(
            '''SELECT parent_receipt_id, envelope FROM accepted_retest_pieces
               WHERE retest_receipt_id = ?''',
            (retest_receipt_id,),
        ).fetchone()
        return None if row is None else (row[0], row[1])
