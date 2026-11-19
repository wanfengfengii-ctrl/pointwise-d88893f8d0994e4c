from dataclasses import dataclass

from campaign.manifest import read_manifest
from campaign.repository import CampaignRepository
from receipt.origin import validate_origin
from receipt.repository import ReceiptRepository
from station.codec import decode_v1, encode_v1
from station.piece import StationPiece


@dataclass(frozen=True, slots=True)
class AcceptedPiece:
    receipt_id: int
    piece: StationPiece
    envelope: str


def receive(
    campaign: CampaignRepository, receipts: ReceiptRepository, batch_id: str, envelope: str
) -> int:
    manifest = read_manifest(campaign, batch_id)
    piece = decode_v1(envelope)
    validate_origin(manifest, piece)
    return receipts.accept_piece(
        piece.batch_id, piece.station_id, piece.issue_id, envelope, encode_v1(piece)
    )


def read_accepted_piece(receipts: ReceiptRepository, receipt_id: int) -> AcceptedPiece:
    if type(receipt_id) is not int or receipt_id <= 0:
        raise ValueError('receipt_id must be a positive integer')
    envelope = receipts.read_piece(receipt_id)
    if envelope is None:
        raise LookupError(f'unknown receipt {receipt_id}')
    return AcceptedPiece(receipt_id, decode_v1(envelope), envelope)
