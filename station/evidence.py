from fractions import Fraction

from observations.revision import FrozenRevision


def build_count_evidence(revision: FrozenRevision) -> tuple[Fraction, ...]:
    coefficients = [Fraction(1)]
    for trial in revision.trials:
        normal, defect = trial.weights.normal, trial.weights.defect
        extended = [Fraction(0)] * (len(coefficients) + 1)
        for count, weight in enumerate(coefficients):
            extended[count] += weight * normal
            extended[count + 1] += weight * defect
        coefficients = extended
    return tuple(coefficients)
