from collections.abc import Sequence

from observations.intake import TrialEvidence


def validate_coverage(trials: Sequence[TrialEvidence], capacity: int) -> None:
    seen = set()
    for trial in trials:
        if trial.trial_id in seen:
            raise ValueError(f'duplicate trial {trial.trial_id!r}')
        seen.add(trial.trial_id)
    if len(trials) != capacity:
        raise ValueError(f'trial coverage is {len(trials)}, expected station capacity {capacity}')
