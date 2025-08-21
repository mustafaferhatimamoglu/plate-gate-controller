import csv
from dataclasses import dataclass
from typing import Dict, Optional, Set


@dataclass
class RuleSets:
    allowed: Set[str]
    denied: Set[str]
    watchlist: Dict[str, Optional[str]]  # plate -> group (optional)
    ignored: Set[str]


def _load_csv_set(path: str) -> Set[str]:
    s: Set[str] = set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if not row:
                    continue
                s.add(row[0].strip().upper())
    except FileNotFoundError:
        pass
    return s


def _load_watchlist(path: str) -> Dict[str, Optional[str]]:
    m: Dict[str, Optional[str]] = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if not row:
                    continue
                plate = row[0].strip().upper()
                grp = row[1].strip() if len(row) > 1 and row[1].strip() else None
                m[plate] = grp
    except FileNotFoundError:
        pass
    return m


def load_rules(allowed_csv: str, denied_csv: str, watchlist_csv: str, ignored_csv: Optional[str] = None) -> RuleSets:
    allowed = _load_csv_set(allowed_csv)
    denied = _load_csv_set(denied_csv)
    watch = _load_watchlist(watchlist_csv)
    ignored = _load_csv_set(ignored_csv) if ignored_csv else set()
    return RuleSets(allowed=allowed, denied=denied, watchlist=watch, ignored=ignored)


def decide(rules: RuleSets, plate: str) -> str:
    plate_u = (plate or "").upper()
    if not plate_u:
        return "unknown"
    if plate_u in rules.ignored:
        return "ignore"
    if plate_u in rules.denied:
        return "deny"
    if plate_u in rules.allowed:
        return "allow"
    if plate_u in rules.watchlist:
        return "watch"
    return "unknown"
