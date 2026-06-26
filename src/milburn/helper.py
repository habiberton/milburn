import json
from uuid import uuid7

from milburn.model import Frequency
from datetime import date
from typing import Any


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

def print_json(msg: str, input: Any):
    def fallback(o: Any) -> Any:
        if callable(o):
            return getattr(o, "__qualname__", None) or getattr(o, "__name__", None) or repr(o)
        if hasattr(o, "model_dump"):           
            return o.model_dump()
        if hasattr(o, "__dataclass_fields__"):  
            import dataclasses
            return dataclasses.asdict(o)
        if isinstance(o, (set, frozenset)):
            return sorted(o, key=str)
        return str(o)
    print(f"{msg}: {json.dumps(input, indent=2, default=fallback, ensure_ascii=False, skipkeys=True)}")