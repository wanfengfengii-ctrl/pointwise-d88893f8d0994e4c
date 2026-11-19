from review.repository import PublicationReceipt, PublishedReport, ReportRepository


def fetch(repository: ReportRepository, report_id: int) -> tuple[PublishedReport, PublicationReceipt]:
    if type(report_id) is not int or report_id <= 0:
        raise ValueError('report_id must be a positive integer')
    publication = repository.load_publication(report_id)
    if publication is None:
        raise LookupError(f'unknown report {report_id}')
    return publication
