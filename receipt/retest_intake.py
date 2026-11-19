from receipt.intake import read_accepted_piece
from receipt.repository import ReceiptRepository
from station.retest_codec import (
    RetestPiece,
    branches_partition_original,
    common_positive_ratio,
    decode_retest,
    encode_retest,
    matches_parent_identity,
)


def _validate_against_parent(piece: RetestPiece, original_evidence: tuple) -> None:
    for candidate_id, evidence in piece.candidates.items():
        ratio = branches_partition_original(evidence, original_evidence)
        if ratio is None or ratio <= 0:
            raise ValueError(
                f'candidate {candidate_id!r} branches do not share one positive scale '
                'with the original V1 evidence'
            )


def _is_synonymous(piece: RetestPiece, stored_envelope: str) -> bool:
    stored = decode_retest(stored_envelope)
    if set(stored.candidates) != set(piece.candidates):
        return False
    for candidate_id, evidence in piece.candidates.items():
        previous = stored.candidates[candidate_id]
        if common_positive_ratio(evidence.normal, previous.normal) is None:
            return False
        if common_positive_ratio(evidence.defect, previous.defect) is None:
            return False
    return True


def receive_retest(receipts: ReceiptRepository, parent_receipt_id: int, envelope: str) -> int:
    if type(parent_receipt_id) is not int or parent_receipt_id <= 0:
        raise ValueError('parent_receipt_id must be a positive integer')
    # Unknown parent receipt numbers surface as LookupError; nothing is written.
    parent = read_accepted_piece(receipts, parent_receipt_id)
    piece = decode_retest(envelope)
    matches_parent_identity(piece, parent.piece)
    _validate_against_parent(piece, parent.piece.count_evidence)
    canonical = encode_retest(piece)
    conflict_message = (
        f'conflicting retest content for parent receipt {parent_receipt_id}'
    )
    return receipts.accept_retest(
        parent_receipt_id,
        envelope,
        canonical,
        lambda stored_envelope: _is_synonymous(piece, stored_envelope),
        conflict_message,
    )


def read_accepted_retest(receipts: ReceiptRepository, retest_receipt_id: int) -> dict:
    if type(retest_receipt_id) is not int or retest_receipt_id <= 0:
        raise ValueError('retest_receipt_id must be a positive integer')
    stored = receipts.read_retest(retest_receipt_id)
    if stored is None:
        raise LookupError(f'unknown retest receipt {retest_receipt_id}')
    parent_receipt_id, envelope = stored
    return {'parent_receipt_id': parent_receipt_id, 'envelope': envelope}
