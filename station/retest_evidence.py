from fractions import Fraction

from observations.revision import FrozenRevision
from station.evidence import build_count_evidence


def _branch(
    revision: FrozenRevision, target_trial_id: str, *, normal: bool
) -> tuple[Fraction, ...]:
    coefficients = [Fraction(1)]
    for trial in revision.trials:
        if trial.trial_id == target_trial_id:
            picked = trial.weights.normal if normal else trial.weights.defect
            extended = [Fraction(0)] * (len(coefficients) + 1)
            if normal:
                for count, weight in enumerate(coefficients):
                    extended[count] += weight * picked
            else:
                for count, weight in enumerate(coefficients):
                    extended[count + 1] += weight * picked
        else:
            normal_weight, defect_weight = trial.weights.normal, trial.weights.defect
            extended = [Fraction(0)] * (len(coefficients) + 1)
            for count, weight in enumerate(coefficients):
                extended[count] += weight * normal_weight
                extended[count + 1] += weight * defect_weight
        coefficients = extended
    return tuple(coefficients)


def build_candidate_evidence(
    revision: FrozenRevision, trial_id: str
) -> tuple[tuple[Fraction, ...], tuple[Fraction, ...]]:
    """Return (normal branch, defect branch) for one bound candidate.

    The two branches partition the revision's original V1 count vector:
    summing them position by point reproduces the original vector exactly,
    so their common positive scale factor is 1.
    """
    normal_branch = _branch(revision, trial_id, normal=True)
    defect_branch = _branch(revision, trial_id, normal=False)
    original = build_count_evidence(revision)
    if tuple(n + d for n, d in zip(normal_branch, defect_branch)) != original:
        raise ValueError('candidate branches must partition the original count evidence')
    if normal_branch[-1] != 0 or defect_branch[0] != 0:
        raise ValueError('candidate branch boundary weights must be zero')
    return normal_branch, defect_branch
