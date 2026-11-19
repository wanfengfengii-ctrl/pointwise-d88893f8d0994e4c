from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class StationPiece:
    batch_id: str
    station_id: str
    capacity: int
    issue_id: str
    revision_id: str
    count_evidence: tuple[Fraction, ...]


def validate_piece(piece: StationPiece) -> None:
    for field in ('batch_id', 'station_id', 'issue_id', 'revision_id'):
        value = getattr(piece, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{field} must be a nonempty string')
    if type(piece.capacity) is not int or piece.capacity <= 0:
        raise ValueError('piece capacity must be a positive integer')
    if not isinstance(piece.count_evidence, tuple) or len(piece.count_evidence) != piece.capacity + 1:
        raise ValueError('count evidence must cover zero through station capacity')
    for weight in piece.count_evidence:
        if not isinstance(weight, Fraction) or weight < 0:
            raise ValueError('count evidence requires nonnegative fractions')
    if not any(piece.count_evidence):
        raise ValueError('count evidence requires at least one positive weight')
