from collections.abc import Iterable

from campaign.manifest import read_manifest
from campaign.repository import CampaignRepository
from campaign.reveal import require_revealed_count
from receipt.repository import ReceiptRepository
from receipt.selection import select_pieces
from review.repository import PublicationReceipt, PublishedReport, ReportRepository
from review.thresholds import Threshold, evaluate_thresholds, validate_thresholds


def publish(
    campaign: CampaignRepository,
    receipts: ReceiptRepository,
    reports: ReportRepository,
    batch_id: str,
    receipt_ids: Iterable[int],
    thresholds: Iterable[Threshold],
) -> tuple[PublishedReport, PublicationReceipt]:
    manifest = read_manifest(campaign, batch_id)
    defect_count = require_revealed_count(campaign, manifest.batch_id)
    selection = select_pieces(receipts, manifest, receipt_ids)
    queries = validate_thresholds(selection, thresholds)
    probabilities = evaluate_thresholds(selection, defect_count, queries)
    return reports.save_publication(
        selection.batch_id, defect_count, selection.receipt_ids, queries, probabilities
    )
