from collections.abc import Iterable
from dataclasses import dataclass

from campaign.manifest import Manifest
from receipt.intake import AcceptedPiece, read_accepted_piece
from receipt.origin import validate_origin
from receipt.repository import ReceiptRepository


@dataclass(frozen=True, slots=True)
class SelectedPieces:
    batch_id: str
    entries: tuple[AcceptedPiece, ...]

    @property
    def receipt_ids(self) -> tuple[int, ...]:
        return tuple(entry.receipt_id for entry in self.entries)

    @property
    def station_ids(self) -> tuple[str, ...]:
        return tuple(entry.piece.station_id for entry in self.entries)


def select_pieces(
    receipts: ReceiptRepository, manifest: Manifest, receipt_ids: Iterable[int]
) -> SelectedPieces:
    try:
        ids = tuple(receipt_ids)
    except TypeError as exc:
        raise ValueError('receipt_ids must be a collection of positive integers') from exc
    if any(type(receipt_id) is not int or receipt_id <= 0 for receipt_id in ids):
        raise ValueError('receipt_ids must be positive integers')
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate receipt ID in selection')

    entries = []
    stations = set()
    for receipt_id in ids:
        accepted = read_accepted_piece(receipts, receipt_id)
        validate_origin(manifest, accepted.piece)
        station_id = accepted.piece.station_id
        if station_id in stations:
            raise ValueError(f'multiple pieces selected for station {station_id!r}')
        stations.add(station_id)
        entries.append(accepted)

    missing = {row.station_id for row in manifest.allocations} - stations
    if missing:
        raise ValueError(f'selection is missing stations {sorted(missing)!r}')
    return SelectedPieces(manifest.batch_id, tuple(entries))
