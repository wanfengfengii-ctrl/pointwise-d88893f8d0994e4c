from fractions import Fraction
from itertools import product
from math import prod

from review.repository import PublishedReport
from station.retest_codec import CandidateEvidence


def base_loss(report: PublishedReport) -> Fraction:
    risk = report.probabilities.first
    return min(risk, Fraction(1) - risk)


def _branch_totals(
    selection,
    report: PublishedReport,
    station_index: int,
    branch: tuple[Fraction, ...],
) -> tuple[Fraction, Fraction]:
    """Return (total mass, event mass) for one retest outcome branch.

    The candidate station's V1 vector is replaced by the condition branch while
    every other station keeps the exact evidence selected by the report. Only
    total-count K combinations survive, matching the report's own conditioning.
    The first threshold event is evaluated on the threshold station's count in
    each surviving combination.
    """
    threshold = report.thresholds[0]
    threshold_index = selection.station_ids.index(threshold.station_id)

    supports = []
    for index, entry in enumerate(selection.entries):
        vector = branch if index == station_index else entry.piece.count_evidence
        supports.append(tuple((count, weight) for count, weight in enumerate(vector) if weight))

    total_mass = Fraction(0)
    event_mass = Fraction(0)
    for combination in product(*supports):
        counts = tuple(count for count, _ in combination)
        if sum(counts) != report.defect_count:
            continue
        weight = prod((entry[1] for entry in combination), start=Fraction(1))
        total_mass += weight
        if counts[threshold_index] >= threshold.minimum:
            event_mass += weight
    return total_mass, event_mass


def expected_loss(
    selection,
    report: PublishedReport,
    station_index: int,
    evidence: CandidateEvidence,
) -> Fraction:
    """Probability-weighted minimum misjudgement loss after an error-free retest.

    Conditioning is only on the two error-free retest outcomes (the candidate is
    normal, or defective). For an outcome with total mass T and event mass E,
    the conditional threshold risk is E/T, so the minimum conditional loss is
    min(E/T, 1 - E/T) = min(E, T - E) / T. The outcome's real probability is
    T / D where D is the total mass across both outcomes; its contribution to
    the expected loss is min(E, T - E) / D. An outcome of zero mass contributes
    zero. All arithmetic is exact Fraction arithmetic.
    """
    normal_total, normal_event = _branch_totals(
        selection, report, station_index, evidence.normal
    )
    defect_total, defect_event = _branch_totals(
        selection, report, station_index, evidence.defect
    )
    denominator = normal_total + defect_total
    if denominator == 0:
        raise ValueError('retest candidate has no compatible evidence for the revealed count')

    weighted_minimum = Fraction(0)
    for total, event in ((normal_total, normal_event), (defect_total, defect_event)):
        if total == 0:
            # A zero-quality retest outcome contributes zero by contract.
            continue
        weighted_minimum += min(event, total - event)
    return weighted_minimum / denominator
