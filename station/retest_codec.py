from dataclasses import dataclass, field
from fractions import Fraction
import json
import re

from station.codec import _unique_fields  # reuse the strict duplicate-field hook
from station.piece import StationPiece


_FIELDS = {'batch_id', 'station_id', 'capacity', 'issue_id', 'revision_id', 'candidates'}
_CANDIDATE_FIELDS = {'normal', 'defect'}
_FRACTION_TEXT = re.compile(r'-?[0-9]+(?:/[0-9]+)?')


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    normal: tuple[Fraction, ...]
    defect: tuple[Fraction, ...]


@dataclass(frozen=True, slots=True)
class RetestPiece:
    batch_id: str
    station_id: str
    capacity: int
    issue_id: str
    revision_id: str
    candidates: dict[str, CandidateEvidence] = field(default_factory=dict)


def _decode_branch(value: object, capacity: int, branch: str) -> tuple[Fraction, ...]:
    if not isinstance(value, list) or len(value) != capacity + 1:
        raise ValueError(f'candidate {branch} evidence must have {capacity + 1} entries')
    weights: list[Fraction] = []
    for entry in value:
        if not isinstance(entry, str) or _FRACTION_TEXT.fullmatch(entry) is None:
            raise ValueError(f'candidate {branch} evidence entries must be rational strings')
        try:
            weight = Fraction(entry)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f'invalid candidate {branch} evidence fraction') from exc
        if weight < 0:
            raise ValueError(f'candidate {branch} evidence requires nonnegative fractions')
        weights.append(weight)
    return tuple(weights)


def validate_retest_piece(piece: RetestPiece) -> None:
    for name in ('batch_id', 'station_id', 'issue_id', 'revision_id'):
        value = getattr(piece, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{name} must be a nonempty string')
    if type(piece.capacity) is not int or piece.capacity <= 0:
        raise ValueError('piece capacity must be a positive integer')
    if not isinstance(piece.candidates, dict) or not piece.candidates:
        raise ValueError('retest piece requires a nonempty candidate object')
    for candidate_id, evidence in piece.candidates.items():
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError('candidate_id must be a nonempty string')
        if not isinstance(evidence, CandidateEvidence):
            raise ValueError('candidate value must encode two evidence branches')
        for branch_name, branch in (
            ('normal', evidence.normal),
            ('defect', evidence.defect),
        ):
            if not isinstance(branch, tuple) or len(branch) != piece.capacity + 1:
                raise ValueError(
                    f'candidate {candidate_id!r} {branch_name} branch must cover zero through capacity'
                )
            if any(not isinstance(weight, Fraction) or weight < 0 for weight in branch):
                raise ValueError(
                    f'candidate {candidate_id!r} {branch_name} branch requires nonnegative fractions'
                )
        if evidence.normal[-1] != 0:
            raise ValueError(f'candidate {candidate_id!r} normal branch must be zero at full capacity')
        if evidence.defect[0] != 0:
            raise ValueError(f'candidate {candidate_id!r} defect branch must be zero at zero defects')
        if not any(evidence.normal) and not any(evidence.defect):
            raise ValueError(f'candidate {candidate_id!r} requires at least one positive weight')


def encode_retest(piece: RetestPiece) -> str:
    validate_retest_piece(piece)
    candidates = {
        candidate_id: {
            'normal': [str(weight) for weight in evidence.normal],
            'defect': [str(weight) for weight in evidence.defect],
        }
        for candidate_id, evidence in sorted(piece.candidates.items())
    }
    payload = {
        'batch_id': piece.batch_id,
        'station_id': piece.station_id,
        'capacity': piece.capacity,
        'issue_id': piece.issue_id,
        'revision_id': piece.revision_id,
        'candidates': candidates,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def decode_retest(envelope: str) -> RetestPiece:
    if not isinstance(envelope, str):
        raise ValueError('retest envelope must be JSON text')
    try:
        payload = json.loads(envelope, object_pairs_hook=_unique_fields)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid retest envelope JSON') from exc
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise ValueError('invalid retest envelope fields')
    capacity = payload['capacity']
    if type(capacity) is not int or capacity <= 0:
        raise ValueError('piece capacity must be a positive integer')
    raw_candidates = payload['candidates']
    if not isinstance(raw_candidates, dict) or not raw_candidates:
        raise ValueError('retest envelope requires a nonempty candidate object')
    candidates: dict[str, CandidateEvidence] = {}
    for candidate_id, raw_evidence in raw_candidates.items():
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError('candidate_id must be a nonempty string')
        if not isinstance(raw_evidence, dict) or set(raw_evidence) != _CANDIDATE_FIELDS:
            raise ValueError(
                f'candidate {candidate_id!r} value must contain normal and defect branches'
            )
        candidates[candidate_id] = CandidateEvidence(
            _decode_branch(raw_evidence['normal'], capacity, 'normal'),
            _decode_branch(raw_evidence['defect'], capacity, 'defect'),
        )
    piece = RetestPiece(
        batch_id=payload['batch_id'],
        station_id=payload['station_id'],
        capacity=capacity,
        issue_id=payload['issue_id'],
        revision_id=payload['revision_id'],
        candidates=candidates,
    )
    validate_retest_piece(piece)
    return piece


def common_positive_ratio(
    left: tuple[Fraction, ...], right: tuple[Fraction, ...]
) -> Fraction | None:
    """Return r > 0 with left == r * right, or None.

    Two all-zero vectors are equivalent (any positive r works), so a unit ratio
    is returned. A zero left entry is only compatible with a zero right entry.
    """
    ratio: Fraction | None = None
    for left_weight, right_weight in zip(left, right, strict=True):
        if right_weight == 0:
            if left_weight != 0:
                return None
            continue
        candidate = left_weight / right_weight
        if candidate <= 0:
            return None
        if ratio is None:
            ratio = candidate
        elif ratio != candidate:
            return None
    return Fraction(1) if ratio is None else ratio


def branches_partition_original(
    evidence: CandidateEvidence, original: tuple[Fraction, ...]
) -> Fraction | None:
    """Common scale r with normal + defect == r * original; r must be a single positive rational."""
    return common_positive_ratio(
        tuple(n + d for n, d in zip(evidence.normal, evidence.defect)), original
    )


def matches_parent_identity(piece: RetestPiece, parent: StationPiece) -> None:
    if (
        piece.batch_id != parent.batch_id
        or piece.station_id != parent.station_id
        or piece.capacity != parent.capacity
        or piece.issue_id != parent.issue_id
        or piece.revision_id != parent.revision_id
    ):
        raise ValueError('retest companion identity does not match its parent V1 piece')
