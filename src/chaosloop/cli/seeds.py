import argparse
import re
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class Seeds:
    ranges: tuple[range, ...]

    def __iter__(self) -> Iterator[int]:
        for span in self.ranges:
            yield from span


def parse_seeds(text: str) -> Seeds:
    """Ranges are inclusive, ordering and intentional duplicates are preserved."""
    spans = []
    for part in text.split(","):
        match = re.fullmatch(r"\s*(-?\d+)\s*(?:-\s*(-?\d+)\s*)?", part)
        if match is None:
            raise argparse.ArgumentTypeError("seeds must look like 100-200,500 or 1,5,9")
        start = int(match[1])
        end = int(match[2]) if match[2] is not None else start
        if end < start:
            raise argparse.ArgumentTypeError("seed range end must be >= start")
        spans.append(range(start, end + 1))
    return Seeds(tuple(spans))