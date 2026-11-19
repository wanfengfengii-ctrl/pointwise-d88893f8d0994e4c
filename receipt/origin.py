from campaign.manifest import Manifest
from station.piece import StationPiece


def validate_origin(manifest: Manifest, piece: StationPiece) -> None:
    if piece.batch_id != manifest.batch_id:
        raise ValueError(f'piece {piece.issue_id!r} belongs to a different batch')
    capacity = manifest.capacity_for(piece.station_id)
    if capacity != piece.capacity:
        raise ValueError(f'piece capacity for station {piece.station_id!r} differs from manifest')
