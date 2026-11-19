from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from campaign.manifest import Manifest
from observations.coverage import validate_coverage
from observations.intake import TrialEvidence, parse_trials
from observations.repository import ObservationRepository


@dataclass(frozen=True, slots=True)
class FrozenRevision:
    revision_id: int
    batch_id: str
    station_id: str
    capacity: int
    trials: tuple[TrialEvidence, ...]


def freeze(
    repository: ObservationRepository,
    manifest: Manifest,
    station_id: str,
    rows: Iterable[Mapping[str, object]],
) -> FrozenRevision:
    capacity = manifest.capacity_for(station_id)
    trials = parse_trials(rows)
    validate_coverage(trials, capacity)
    revision_id = repository.save_frozen(manifest.batch_id, station_id, capacity, trials)
    return FrozenRevision(revision_id, manifest.batch_id, station_id, capacity, trials)


def read_frozen_revision(repository: ObservationRepository, revision_id: int) -> FrozenRevision:
    if type(revision_id) is not int or revision_id <= 0:
        raise ValueError('revision_id must be a positive integer')
    stored = repository.load_frozen(revision_id)
    if stored is None:
        raise LookupError(f'unknown revision {revision_id}')
    return FrozenRevision(revision_id, *stored)
