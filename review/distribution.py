from collections.abc import Iterator
from fractions import Fraction
from itertools import product
from math import prod

from receipt.selection import SelectedPieces


def iter_weighted_counts(
    selection: SelectedPieces, defect_count: int
) -> Iterator[tuple[tuple[int, ...], Fraction]]:
    supports = [
        tuple((count, weight) for count, weight in enumerate(entry.piece.count_evidence) if weight)
        for entry in selection.entries
    ]
    for combination in product(*supports):
        counts = tuple(count for count, _ in combination)
        if sum(counts) == defect_count:
            weight = prod((weight for _, weight in combination), start=Fraction(1))
            yield counts, weight
