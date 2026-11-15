import re
from typing import Any

from jobmecloud.config.settings import DAYS, Day
from jobmecloud.db.models import WatchlistEmployer
from jobmecloud.importers.tracker import Sheet, cell_text

WATCHLIST_FIELDS = ("name", "priority", "rotation_day", "careers_url")

_KEYWORDS = {
    "name": ("employer", "company", "organization", "name"),
    "priority": ("priority",),
    "rotation_day": ("rotation", "day"),
    "careers_url": ("careers", "url", "link"),
}
_PRIORITIES = {
    "p1": 1, "1": 1, "high": 1,
    "p2": 2, "2": 2, "medium": 2, "med": 2,
    "p3": 3, "3": 3, "low": 3, "conditional": 3,
}
_DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_URL = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)


def suggest_watchlist_mapping(columns: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}
    used: set[int] = set()
    for field in WATCHLIST_FIELDS:
        mapping[field] = None
        for i, col in enumerate(columns):
            if i not in used and any(k in col.lower() for k in _KEYWORDS[field]):
                mapping[field] = col
                used.add(i)
                break
    return mapping


def map_priority(raw: str) -> int:
    """P1/High -> 1, P2/Medium -> 2, P3/Low/Conditional -> 3; anything else -> 2."""
    return _PRIORITIES.get(raw.strip().lower(), 2)


def map_day(raw: str) -> Day | None:
    """The weekday the text starts with, e.g. 'Monday - Portland' -> 'mon'."""
    match = re.match(r"\s*([a-z]+)", raw.lower())
    if not match or len(match.group(1)) < 3:
        return None
    word = match.group(1)
    for key, full in zip(DAYS, _DAY_NAMES):
        if full.startswith(word):
            return key
    return None


def rows_to_employers(
    sheet: Sheet, mapping: dict[str, str | None]
) -> tuple[list[WatchlistEmployer], int]:
    index = {f: sheet.columns.index(c) for f, c in mapping.items() if c and c in sheet.columns}

    def get(row: list[Any], field: str) -> str:
        i = index.get(field)
        return cell_text(row[i]) if i is not None and i < len(row) else ""

    employers: list[WatchlistEmployer] = []
    skipped = 0
    for row in sheet.rows:
        name = get(row, "name")
        if not name:
            skipped += 1
            continue
        url = _URL.search(get(row, "careers_url"))
        employers.append(WatchlistEmployer(
            name=name,
            priority=map_priority(get(row, "priority")),
            rotation_day=map_day(get(row, "rotation_day")),
            careers_url=url.group(0).rstrip(".)") if url else None,
        ))
    return employers, skipped
