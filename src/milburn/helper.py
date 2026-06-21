from uuid import uuid7

from milburn.model import Frequency
from datetime import date


def normalize_symbol(symbol: str) -> str:
    return symbol.upper().strip()

def convert_date(date_str: date) -> str:
    return date_str.strftime("%Y-%m-%d")

def is_date_range_valid(start: str | date, end: str | date) -> bool:
    s = date.fromisoformat(start) if isinstance(start, str) else start
    e = date.fromisoformat(end) if isinstance(end, str) else end
    return s <= e

def normalize_frequency(frequency: str) -> str:
    return frequency.lower().strip()

def is_frequency_valid(frequency: str) -> bool:
    normalized_frequency = normalize_frequency(frequency)
    return normalized_frequency in Frequency

def parse_date(value: str | date) -> date:
    """Idempotent date parser for Typer: accepts ISO strings and date objects."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)

def make_run_id() -> str:
    return f"{uuid7()}"