from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from receipt.intake import read_accepted_piece
from receipt.repository import ReceiptRepository
from review.repository import PublishedReport, ReportRepository
from review.retest_value import base_loss, expected_loss
from station.retest_codec import decode_retest


@dataclass(frozen=True, slots=True)
class _StoredSelection:
    """The exact piece selection adopted by a report, readable while the site is offline."""

    batch_id: str
    entries: tuple

    @property
    def receipt_ids(self) -> tuple[int, ...]:
        return tuple(entry.receipt_id for entry in self.entries)

    @property
    def station_ids(self) -> tuple[str, ...]:
        return tuple(entry.piece.station_id for entry in self.entries)


def _report_selection(receipts: ReceiptRepository, report: PublishedReport) -> _StoredSelection:
    entries = tuple(read_accepted_piece(receipts, receipt_id) for receipt_id in report.receipt_ids)
    return _StoredSelection(report.batch_id, entries)


def _parse_requests(candidates: Iterable[Mapping[str, object]]) -> tuple[dict, ...]:
    try:
        requests = tuple(candidates)
    except TypeError as exc:
        raise ValueError('candidates must be a nonempty ordered collection') from exc
    if not requests:
        raise ValueError('at least one retest candidate is required')
    parsed = []
    references = set()
    for line, request in enumerate(requests, start=1):
        if not isinstance(request, Mapping) or set(request) != {
            'retest_receipt_id',
            'candidate_id',
        }:
            raise ValueError(
                f'candidate request {line} must contain retest_receipt_id and candidate_id'
            )
        retest_receipt_id = request['retest_receipt_id']
        candidate_id = request['candidate_id']
        if type(retest_receipt_id) is not int or retest_receipt_id <= 0:
            raise ValueError(f'candidate request {line} requires a positive retest_receipt_id')
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError(f'candidate request {line} requires a nonempty candidate_id')
        reference = (retest_receipt_id, candidate_id)
        if reference in references:
            raise ValueError(f'duplicate candidate reference {reference!r}')
        references.add(reference)
        parsed.append({'retest_receipt_id': retest_receipt_id, 'candidate_id': candidate_id})
    return tuple(parsed)


def publish_retest(
    receipts: ReceiptRepository,
    reports: ReportRepository,
    report_id: int,
    candidates: Iterable[Mapping[str, object]],
) -> tuple[dict, dict]:
    if type(report_id) is not int or report_id <= 0:
        raise ValueError('report_id must be a positive integer')
    publication = reports.load_publication(report_id)
    if publication is None:
        raise LookupError(f'unknown report {report_id}')
    report, _ = publication
    requests = _parse_requests(candidates)

    selection = _report_selection(receipts, report)
    parent_entries = {entry.receipt_id: entry for entry in selection.entries}
    base = base_loss(report)

    evaluated = []
    for request in requests:
        retest_receipt_id = request['retest_receipt_id']
        candidate_id = request['candidate_id']
        accepted = receipts.read_retest(retest_receipt_id)
        if accepted is None:
            raise LookupError(f'unknown retest receipt {retest_receipt_id}')
        parent_receipt_id, envelope = accepted
        if parent_receipt_id not in parent_entries:
            raise ValueError(
                f'retest receipt {retest_receipt_id} does not belong to a piece selected '
                f'by report {report_id}'
            )
        piece = decode_retest(envelope)
        if candidate_id not in piece.candidates:
            raise LookupError(
                f'candidate {candidate_id!r} is absent from retest receipt {retest_receipt_id}'
            )
        parent_entry = parent_entries[parent_receipt_id]
        station_index = selection.station_ids.index(parent_entry.piece.station_id)
        loss = expected_loss(
            selection,
            report,
            station_index,
            piece.candidates[candidate_id],
        )
        evaluated.append(
            {
                'retest_receipt_id': retest_receipt_id,
                'candidate_id': candidate_id,
                'parent_receipt_id': parent_receipt_id,
                'expected_loss': loss,
                'improvement': base - loss,
            }
        )

    best_improvement = max(entry['improvement'] for entry in evaluated)
    best = tuple(
        {
            'retest_receipt_id': entry['retest_receipt_id'],
            'candidate_id': entry['candidate_id'],
        }
        for entry in evaluated
        if entry['improvement'] == best_improvement
    )
    return reports.save_retest_suggestion(report_id, base, tuple(evaluated), best)
