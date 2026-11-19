from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from observations.weights import EvidenceWeights, parse_weights


@dataclass(frozen=True, slots=True)
class TrialEvidence:
    trial_id: str
    weights: EvidenceWeights


def parse_trials(rows: Iterable[Mapping[str, object]]) -> tuple[TrialEvidence, ...]:
    try:
        submitted = iter(rows)
    except TypeError as exc:
        raise ValueError('trial evidence must be a collection of rows') from exc
    trials = []
    for line, row in enumerate(submitted, start=1):
        if not isinstance(row, Mapping) or set(row) != {'trial_id', 'normal', 'defect'}:
            raise ValueError(f'trial row {line} must contain trial_id, normal and defect')
        trial_id = row['trial_id']
        if not isinstance(trial_id, str) or not trial_id.strip():
            raise ValueError(f'trial row {line} requires a nonempty trial_id')
        try:
            weights = parse_weights(row['normal'], row['defect'])
        except ValueError as exc:
            raise ValueError(f'trial {trial_id!r}: {exc}') from exc
        trials.append(TrialEvidence(trial_id, weights))
    return tuple(trials)
