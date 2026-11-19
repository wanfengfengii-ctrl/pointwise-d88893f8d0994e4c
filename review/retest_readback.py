from review.repository import ReportRepository


def fetch_retest(reports: ReportRepository, suggestion_id: int) -> tuple[dict, dict]:
    if type(suggestion_id) is not int or suggestion_id <= 0:
        raise ValueError('suggestion_id must be a positive integer')
    stored = reports.load_retest_suggestion(suggestion_id)
    if stored is None:
        raise LookupError(f'unknown retest suggestion {suggestion_id}')
    return stored
