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
CREATE TABLE IF NOT EXISTS retest_suggestions (
    suggestion_id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(report_id),
    base_loss TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    best_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retest_receipts (
    receipt_id INTEGER PRIMARY KEY,
    suggestion_id INTEGER NOT NULL UNIQUE REFERENCES retest_suggestions(suggestion_id)
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

    def save_retest_suggestion(
        self,
        report_id: int,
        base_loss_value: Fraction,
        candidates: tuple[dict, ...],
        best: tuple[dict, ...],
    ) -> tuple[dict, dict]:
        candidates_json = json.dumps(candidates, sort_keys=True, default=self._fraction_default)
        best_json = json.dumps(best, sort_keys=True, default=self._fraction_default)
        with write_transaction(self.connection):
            suggestion_id = self.connection.execute(
                '''INSERT INTO retest_suggestions
                   (report_id, base_loss, candidates_json, best_json)
                   VALUES (?, ?, ?, ?)''',
                (report_id, str(base_loss_value), candidates_json, best_json),
            ).lastrowid
            receipt_id = self.connection.execute(
                'INSERT INTO retest_receipts (suggestion_id) VALUES (?)', (suggestion_id,)
            ).lastrowid
        suggestion = {
            'suggestion_id': suggestion_id,
            'report_id': report_id,
            'base_loss': base_loss_value,
            'candidates': candidates,
            'best': best,
        }
        receipt = {'receipt_id': receipt_id, 'suggestion_id': suggestion_id}
        return suggestion, receipt

    def load_retest_suggestion(self, suggestion_id: int) -> tuple[dict, dict] | None:
        if suggestion_id > 2**63 - 1:
            return None
        row = self.connection.execute(
            '''SELECT s.report_id, s.base_loss, s.candidates_json, s.best_json, r.receipt_id
               FROM retest_suggestions AS s
               JOIN retest_receipts AS r ON r.suggestion_id = s.suggestion_id
               WHERE s.suggestion_id = ?''',
            (suggestion_id,),
        ).fetchone()
        if row is None:
            return None
        report_id, base_loss_value, candidates_json, best_json, receipt_id = row
        candidates = tuple(self._load_candidate(entry) for entry in json.loads(candidates_json))
        best = tuple(json.loads(best_json))
        suggestion = {
            'suggestion_id': suggestion_id,
            'report_id': report_id,
            'base_loss': Fraction(base_loss_value),
            'candidates': candidates,
            'best': best,
        }
        receipt = {'receipt_id': receipt_id, 'suggestion_id': suggestion_id}
        return suggestion, receipt

    @staticmethod
    def _fraction_default(value):
        if isinstance(value, Fraction):
            return str(value)
        raise TypeError(f'unsupported stored value {type(value).__name__}')

    @staticmethod
    def _load_candidate(entry: dict) -> dict:
        result = dict(entry)
        for name in ('expected_loss', 'improvement'):
            result[name] = Fraction(result[name])
        return result
