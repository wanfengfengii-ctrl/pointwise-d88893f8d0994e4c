from fractions import Fraction
import json
import re

from station.piece import StationPiece, validate_piece


_FIELDS = {'version', 'batch_id', 'station_id', 'capacity', 'issue_id', 'revision_id', 'count_evidence'}
_FRACTION_TEXT = re.compile(r'-?[0-9]+(?:/[0-9]+)?')


def encode_v1(piece: StationPiece) -> str:
    validate_piece(piece)
    payload = {
        'version': 1,
        'batch_id': piece.batch_id,
        'station_id': piece.station_id,
        'capacity': piece.capacity,
        'issue_id': piece.issue_id,
        'revision_id': piece.revision_id,
        'count_evidence': [str(weight) for weight in piece.count_evidence],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate envelope field {key!r}')
        result[key] = value
    return result


def _decode_weight(value: object) -> Fraction:
    if not isinstance(value, str) or _FRACTION_TEXT.fullmatch(value) is None:
        raise ValueError('count evidence entries must be rational strings')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('invalid count evidence fraction') from exc


def decode_v1(envelope: str) -> StationPiece:
    if not isinstance(envelope, str):
        raise ValueError('station envelope must be JSON text')
    try:
        payload = json.loads(envelope, object_pairs_hook=_unique_fields)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid station envelope JSON') from exc
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise ValueError('invalid station envelope fields')
    if type(payload['version']) is not int or payload['version'] != 1:
        raise ValueError('unsupported station envelope version')
    if not isinstance(payload['count_evidence'], list):
        raise ValueError('count evidence must be an array')

    piece = StationPiece(
        batch_id=payload['batch_id'],
        station_id=payload['station_id'],
        capacity=payload['capacity'],
        issue_id=payload['issue_id'],
        revision_id=payload['revision_id'],
        count_evidence=tuple(_decode_weight(value) for value in payload['count_evidence']),
    )
    validate_piece(piece)
    return piece
