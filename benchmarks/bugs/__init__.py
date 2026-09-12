"""Intentionally broken in-memory programs; none is a claim about stdlib bugs."""

from . import (
    b01_lost_update,
    b02_cache_stampede,
    b03_transfer,
)

BUGS = (
    b01_lost_update,
    b02_cache_stampede,
    b03_transfer,
)
