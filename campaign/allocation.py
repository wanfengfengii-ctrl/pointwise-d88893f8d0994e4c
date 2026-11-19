from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StationAllocation:
    station_id: str
    capacity: int


def validate_allocations(allocations: Iterable[StationAllocation]) -> tuple[StationAllocation, ...]:
    try:
        rows = tuple(allocations)
    except TypeError as exc:
        raise ValueError('allocations must be a collection of station allocations') from exc
    if not rows:
        raise ValueError('a batch requires at least one station')

    station_ids = set()
    for row in rows:
        if not isinstance(row, StationAllocation):
            raise ValueError('expected a station allocation')
        if not isinstance(row.station_id, str) or not row.station_id.strip():
            raise ValueError('station_id must be a nonempty string')
        if type(row.capacity) is not int or row.capacity <= 0:
            raise ValueError('station capacity must be a positive integer')
        if row.station_id in station_ids:
            raise ValueError(f'duplicate station {row.station_id!r}')
        station_ids.add(row.station_id)
    return tuple(sorted(rows, key=lambda row: row.station_id))


def total_capacity(allocations: Iterable[StationAllocation]) -> int:
    return sum(row.capacity for row in allocations)
