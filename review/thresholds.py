from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from receipt.selection import SelectedPieces
from review.distribution import iter_weighted_counts


@dataclass(frozen=True, slots=True)
class Threshold:
    station_id: str
    minimum: int


@dataclass(frozen=True, slots=True)
class RiskProbabilities:
    first: Fraction
    second: Fraction
    joint: Fraction

    def as_tuple(self) -> tuple[Fraction, Fraction, Fraction]:
        return self.first, self.second, self.joint


def validate_thresholds(
    selection: SelectedPieces, thresholds: Iterable[Threshold]
) -> tuple[Threshold, Threshold]:
    try:
        queries = tuple(thresholds)
    except TypeError as exc:
        raise ValueError('exactly two station thresholds are required') from exc
    if len(queries) != 2:
        raise ValueError('exactly two station thresholds are required')
    stations = selection.station_ids
    for query in queries:
        if not isinstance(query, Threshold):
            raise ValueError('expected a station threshold')
        if not isinstance(query.station_id, str) or query.station_id not in stations:
            raise ValueError(f'unknown threshold station {query.station_id!r}')
        if type(query.minimum) is not int or query.minimum < 0:
            raise ValueError('threshold minimum must be a nonnegative integer')
    first, second = queries
    if first.station_id == second.station_id:
        raise ValueError('threshold stations must be distinct')
    return first, second


def evaluate_thresholds(
    selection: SelectedPieces, defect_count: int, thresholds: Iterable[Threshold]
) -> RiskProbabilities:
    first, second = validate_thresholds(selection, thresholds)
    stations = selection.station_ids
    first_index, second_index = stations.index(first.station_id), stations.index(second.station_id)
    total = first_weight = second_weight = joint_weight = Fraction(0)

    for counts, weight in iter_weighted_counts(selection, defect_count):
        total += weight
        first_met = counts[first_index] >= first.minimum
        second_met = counts[second_index] >= second.minimum
        if first_met:
            first_weight += weight
        if second_met:
            second_weight += weight
        if first_met and second_met:
            joint_weight += weight

    if total == 0:
        raise ValueError('no compatible evidence for the revealed defect count')
    return RiskProbabilities(first_weight / total, second_weight / total, joint_weight / total)
