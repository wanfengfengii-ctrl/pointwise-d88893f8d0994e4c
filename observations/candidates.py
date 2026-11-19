from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from observations.intake import TrialEvidence


@dataclass(frozen=True, slots=True)
class CandidateBinding:
    candidate_id: str
    trial_id: str


def parse_candidate_bindings(
    candidates: Iterable[Mapping[str, object]], trials: tuple[TrialEvidence, ...]
) -> tuple[CandidateBinding, ...]:
    try:
        submitted = tuple(candidates)
    except TypeError as exc:
        raise ValueError('candidate bindings must be a collection of rows') from exc
    trial_ids = {trial.trial_id for trial in trials}
    bindings: list[CandidateBinding] = []
    seen_candidates: set[str] = set()
    seen_trials: set[str] = set()
    for line, row in enumerate(submitted, start=1):
        if not isinstance(row, Mapping) or set(row) != {'candidate_id', 'trial_id'}:
            raise ValueError(
                f'candidate row {line} must contain candidate_id and trial_id'
            )
        candidate_id = row['candidate_id']
        trial_id = row['trial_id']
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError(f'candidate row {line} requires a nonempty candidate_id')
        if not isinstance(trial_id, str) or not trial_id.strip():
            raise ValueError(f'candidate row {line} requires a nonempty trial_id')
        if candidate_id in seen_candidates:
            raise ValueError(f'duplicate candidate_id {candidate_id!r} in revision')
        if trial_id in seen_trials:
            raise ValueError(f'trial {trial_id!r} is bound to more than one candidate')
        if trial_id not in trial_ids:
            raise ValueError(
                f'candidate {candidate_id!r} binds unknown trial {trial_id!r}'
            )
        seen_candidates.add(candidate_id)
        seen_trials.add(trial_id)
        bindings.append(CandidateBinding(candidate_id, trial_id))
    return tuple(bindings)
