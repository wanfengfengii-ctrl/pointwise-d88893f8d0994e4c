from campaign.repository import CampaignRepository


def reveal(repository: CampaignRepository, batch_id: str) -> int:
    return repository.reveal_count(batch_id)


def require_revealed_count(repository: CampaignRepository, batch_id: str) -> int:
    count = repository.load_revealed_count(batch_id)
    if count is None:
        raise ValueError(f'defect count for batch {batch_id!r} is still sealed')
    return count
