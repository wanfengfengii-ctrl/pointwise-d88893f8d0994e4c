from collections.abc import Iterable
from dataclasses import dataclass

from campaign.allocation import StationAllocation, total_capacity, validate_allocations
from campaign.repository import CampaignRepository


@dataclass(frozen=True, slots=True)
class Manifest:
    batch_id: str
    allocations: tuple[StationAllocation, ...]

    def capacity_for(self, station_id: str) -> int:
        for allocation in self.allocations:
            if allocation.station_id == station_id:
                return allocation.capacity
        raise ValueError(f'unknown station {station_id!r} in batch {self.batch_id!r}')


def register(
    repository: CampaignRepository,
    batch_id: str,
    allocations: Iterable[StationAllocation],
    sealed_count: int,
) -> Manifest:
    _validate_batch_id(batch_id)
    station_rows = validate_allocations(allocations)
    if type(sealed_count) is not int or not 0 <= sealed_count <= total_capacity(station_rows):
        raise ValueError('sealed defect count is outside batch capacity')
    repository.register_sealed(batch_id, station_rows, sealed_count)
    return Manifest(batch_id, station_rows)


def read_manifest(repository: CampaignRepository, batch_id: str) -> Manifest:
    _validate_batch_id(batch_id)
    allocations = repository.load_allocations(batch_id)
    if allocations is None:
        raise LookupError(f'unknown batch {batch_id!r}')
    return Manifest(batch_id, allocations)


def _validate_batch_id(batch_id: str) -> None:
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError('batch_id must be a nonempty string')
