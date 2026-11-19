from dataclasses import dataclass
from fractions import Fraction
import json
import sqlite3

from review.thresholds import RiskProbabilities, Threshold
from storage import initialize_schema, write_transaction


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS reports (
    report_id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL,
    defect_count TEXT NOT NULL,
    receipt_ids_json TEXT NOT NULL,
    thresholds_json TEXT NOT NULL,
    probabilities_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publication_receipts (
    receipt_id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL UNIQUE REFERENCES reports(report_id)
);
'''


@dataclass(frozen=True, slots=True)
class PublishedReport:
    report_id: int
    batch_id: str
    defect_count: int
    receipt_ids: tuple[int, ...]
    thresholds: tuple[Threshold, Threshold]
    probabilities: RiskProbabilities


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    receipt_id: int
    report_id: int


class ReportRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        initialize_schema(self.connection, _SCHEMA)

    def save_publication(
        self,
        batch_id: str,
        defect_count: int,
        receipt_ids: tuple[int, ...],
        thresholds: tuple[Threshold, Threshold],
        probabilities: RiskProbabilities,
    ) -> tuple[PublishedReport, PublicationReceipt]:
        selected_json = json.dumps(receipt_ids)
        thresholds_json = json.dumps([(query.station_id, query.minimum) for query in thresholds])
        probabilities_json = json.dumps([str(value) for value in probabilities.as_tuple()])
        with write_transaction(self.connection):
            report_id = self.connection.execute(
                '''INSERT INTO reports
                   (batch_id, defect_count, receipt_ids_json, thresholds_json, probabilities_json)
                   VALUES (?, ?, ?, ?, ?)''',
                (batch_id, str(defect_count), selected_json, thresholds_json, probabilities_json),
            ).lastrowid
            receipt_id = self.connection.execute(
                'INSERT INTO publication_receipts (report_id) VALUES (?)', (report_id,)
            ).lastrowid
        return (
            PublishedReport(report_id, batch_id, defect_count, receipt_ids, thresholds, probabilities),
            PublicationReceipt(receipt_id, report_id),
        )

    def load_publication(self, report_id: int) -> tuple[PublishedReport, PublicationReceipt] | None:
        if report_id > 2**63 - 1:
            return None
        row = self.connection.execute(
            '''SELECT r.batch_id, r.defect_count, r.receipt_ids_json, r.thresholds_json,
                      r.probabilities_json, p.receipt_id
               FROM reports AS r JOIN publication_receipts AS p ON p.report_id = r.report_id
               WHERE r.report_id = ?''',
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        batch_id, defect_count, ids, queries, probabilities, receipt_id = row
        first, second = (Threshold(station_id, minimum) for station_id, minimum in json.loads(queries))
        report = PublishedReport(
            report_id,
            batch_id,
            int(defect_count),
            tuple(json.loads(ids)),
            (first, second),
            RiskProbabilities(*(Fraction(value) for value in json.loads(probabilities))),
        )
        return report, PublicationReceipt(receipt_id, report_id)
