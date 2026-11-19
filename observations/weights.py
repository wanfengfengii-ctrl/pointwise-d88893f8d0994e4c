from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class EvidenceWeights:
    normal: Fraction
    defect: Fraction


def _parse_fraction(value: object, field: str) -> Fraction:
    if type(value) is not int and not isinstance(value, (str, Fraction)):
        raise ValueError(f'{field} must be an exact rational weight')
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f'invalid {field} weight') from exc
    if result < 0:
        raise ValueError(f'{field} weight must be nonnegative')
    return result


def parse_weights(normal: object, defect: object) -> EvidenceWeights:
    weights = EvidenceWeights(_parse_fraction(normal, 'normal'), _parse_fraction(defect, 'defect'))
    if weights.normal == weights.defect == 0:
        raise ValueError('at least one trial weight must be positive')
    return weights
