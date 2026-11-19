from uuid import uuid4

from observations.repository import ObservationRepository
from observations.revision import read_frozen_revision
from station.codec import decode_v1, encode_v1
from station.evidence import build_count_evidence
from station.piece import StationPiece
from station.repository import StationRepository
from station.retest_codec import CandidateEvidence, RetestPiece, encode_retest
from station.retest_evidence import build_candidate_evidence


def issue(observations: ObservationRepository, station: StationRepository, revision_id: int) -> str:
    if type(revision_id) is not int or revision_id <= 0:
        raise ValueError('revision_id must be a positive integer')
    existing = station.get_by_revision(revision_id)
    if existing is not None:
        return existing

    revision = read_frozen_revision(observations, revision_id)
    piece = StationPiece(
        batch_id=revision.batch_id,
        station_id=revision.station_id,
        capacity=revision.capacity,
        issue_id=uuid4().hex,
        revision_id=str(revision.revision_id),
        count_evidence=build_count_evidence(revision),
    )
    return station.save_issued(revision_id, piece.issue_id, encode_v1(piece))


def issue_retest(
    observations: ObservationRepository, station: StationRepository, revision_id: int
) -> str:
    if type(revision_id) is not int or revision_id <= 0:
        raise ValueError('revision_id must be a positive integer')
    existing = station.get_retest_by_revision(revision_id)
    if existing is not None:
        return existing

    # Unknown revisions surface as LookupError through the revision readback.
    revision = read_frozen_revision(observations, revision_id)
    parent_envelope = station.get_by_revision(revision_id)
    if parent_envelope is None:
        raise ValueError(f'revision {revision_id} has no issued V1 piece')
    if not revision.candidates:
        raise ValueError(f'revision {revision_id} has no frozen candidates')

    candidates = {
        binding.candidate_id: CandidateEvidence(
            *build_candidate_evidence(revision, binding.trial_id)
        )
        for binding in revision.candidates
    }
    # The companion binds the exact issued V1 piece and its revision identity.
    parent = decode_v1(parent_envelope)
    piece = RetestPiece(
        batch_id=revision.batch_id,
        station_id=revision.station_id,
        capacity=revision.capacity,
        issue_id=parent.issue_id,
        revision_id=str(revision.revision_id),
        candidates=candidates,
    )
    return station.save_retest(revision_id, encode_retest(piece))
