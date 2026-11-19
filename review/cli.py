import argparse
from contextlib import closing, contextmanager
from dataclasses import asdict, is_dataclass
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest

from campaign.allocation import StationAllocation, validate_allocations
from campaign.manifest import Manifest, register
from campaign.repository import CampaignRepository
from campaign.reveal import reveal
from observations.repository import ObservationRepository
from observations.revision import freeze
from receipt.intake import receive
from receipt.repository import ReceiptRepository
from review.publication import publish
from review.readback import fetch
from review.repository import ReportRepository
from review.thresholds import Threshold
from station.issuance import issue
from station.repository import StationRepository
from storage import open_database


_ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding='utf-8'))


def _array(value: object, name: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f'{name} must be a JSON array')
    return value


def _allocations(value: object) -> tuple[StationAllocation, ...]:
    return validate_allocations(StationAllocation(**row) for row in _array(value, 'allocations'))


def _thresholds(value: object) -> tuple[Threshold, ...]:
    return tuple(Threshold(**row) for row in _array(value, 'thresholds'))


def _manifest(value: object) -> Manifest:
    if not isinstance(value, dict) or set(value) != {'batch_id', 'allocations'}:
        raise ValueError('manifest requires batch_id and allocations')
    batch_id = value['batch_id']
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError('batch_id must be a nonempty string')
    return Manifest(batch_id, _allocations(value['allocations']))


def _json_value(value: object) -> object:
    if isinstance(value, Fraction):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f'unsupported output value {type(value).__name__}')


def _emit(value: object) -> None:
    print(json.dumps(value, default=_json_value, ensure_ascii=False, sort_keys=True))


@contextmanager
def _center(path: Path):
    with closing(open_database(path)) as connection:
        campaign = CampaignRepository(connection)
        receipts = ReceiptRepository(connection)
        reports = ReportRepository(connection)
        for repository in (campaign, receipts, reports):
            repository.initialize()
        yield campaign, receipts, reports


@contextmanager
def _site(path: Path):
    with closing(open_database(path)) as connection:
        observations = ObservationRepository(connection)
        station = StationRepository(connection)
        observations.initialize()
        station.initialize()
        yield observations, station


def _register(args: argparse.Namespace) -> None:
    allocations = _allocations(_load(args.allocations))
    with _center(args.center) as (campaign, _, _):
        _emit(register(campaign, args.batch, allocations, args.sealed_count))


def _freeze(args: argparse.Namespace) -> None:
    manifest = _manifest(_load(args.manifest))
    rows = _array(_load(args.trials), 'trials')
    with _site(args.site) as (observations, _):
        revision = freeze(observations, manifest, args.station, rows)
        _emit({'revision_id': revision.revision_id})


def _issue(args: argparse.Namespace) -> None:
    with _site(args.site) as (observations, station):
        print(issue(observations, station, args.revision_id))


def _receive(args: argparse.Namespace) -> None:
    envelope = args.piece.read_text(encoding='utf-8')
    with _center(args.center) as (campaign, receipts, _):
        receipt_id = receive(campaign, receipts, args.batch, envelope)
        _emit({'receipt_id': receipt_id})


def _reveal(args: argparse.Namespace) -> None:
    with _center(args.center) as (campaign, _, _):
        _emit({'defect_count': reveal(campaign, args.batch)})


def _publish(args: argparse.Namespace) -> None:
    receipt_ids = _array(_load(args.receipt_ids), 'receipt_ids')
    thresholds = _thresholds(_load(args.thresholds))
    with _center(args.center) as (campaign, receipts, reports):
        report, receipt = publish(campaign, receipts, reports, args.batch, receipt_ids, thresholds)
        _emit({'report': report, 'receipt': receipt})


def _fetch(args: argparse.Namespace) -> None:
    with _center(args.center) as (_, _, reports):
        report, receipt = fetch(reports, args.report_id)
        _emit({'report': report, 'receipt': receipt})


def _demo(_: argparse.Namespace) -> None:
    fixture = _load(_ROOT / 'samples' / 'demo.json')
    with TemporaryDirectory(prefix='blind-review-') as directory:
        root = Path(directory)
        center_path = root / 'center.sqlite'
        with _center(center_path) as (campaign, receipts, reports):
            manifest = register(
                campaign, fixture['batch_id'], _allocations(fixture['allocations']), fixture['sealed_count']
            )
            envelopes = []
            for index, allocation in enumerate(manifest.allocations):
                site_path = root / f'site-{index}.sqlite'
                station_id = allocation.station_id
                with _site(site_path) as (observations, station):
                    revision = freeze(observations, manifest, station_id, fixture['trials'][station_id])
                    envelopes.append(issue(observations, station, revision.revision_id))
                site_path.unlink()

            receipt_ids = [receive(campaign, receipts, manifest.batch_id, text) for text in envelopes]
            reveal(campaign, manifest.batch_id)
            report, receipt = publish(
                campaign, receipts, reports, manifest.batch_id, receipt_ids, _thresholds(fixture['thresholds'])
            )
        with _center(center_path) as (_, _, reports):
            original, original_receipt = fetch(reports, report.report_id)
        if (original, original_receipt) != (report, receipt):
            raise ValueError('reopened center returned a different publication')
        _emit({'report': original, 'receipt': original_receipt})


def _verify(_: argparse.Namespace) -> int:
    suite = unittest.defaultTestLoader.discover(str(_ROOT / 'tests'), top_level_dir=str(_ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and result.testsRun else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Blind batch evidence and center risk review')
    commands = parser.add_subparsers(dest='command', required=True)
    operations = (
        ('register', _register, 'Register a sealed batch', (('center', Path), ('batch', str), ('allocations', Path), ('sealed_count', int))),
        ('freeze', _freeze, 'Freeze evidence in the site database', (('site', Path), ('manifest', Path), ('station', str), ('trials', Path))),
        ('issue', _issue, 'Issue the fixed V1 envelope', (('site', Path), ('revision_id', int))),
        ('receive', _receive, 'Accept an offline station envelope', (('center', Path), ('batch', str), ('piece', Path))),
        ('reveal', _reveal, 'Reveal the registered defect count', (('center', Path), ('batch', str))),
        ('publish', _publish, 'Publish an ordered two-station report', (('center', Path), ('batch', str), ('receipt_ids', Path), ('thresholds', Path))),
        ('fetch', _fetch, 'Read the original report and receipt', (('center', Path), ('report_id', int))),
        ('demo', _demo, 'Run the local offline workflow', ()),
        ('verify', _verify, 'Run the complete unittest suite', ()),
    )
    for name, handler, help_text, arguments in operations:
        command = commands.add_parser(name, help=help_text)
        command.set_defaults(handler=handler)
        for argument, converter in arguments:
            command.add_argument(argument, type=converter)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = args.handler(args)
    except (LookupError, ValueError, TypeError, OSError, sqlite3.Error) as exc:
        print(f'{args.command}: {exc}', file=sys.stderr)
        return 1
    return 0 if result is None else result


if __name__ == '__main__':
    raise SystemExit(main())
