

from milburn.model import Frequency
from datetime import date


def normalize_symbol(symbol: str) -> str:
    return symbol.upper().strip()

def convert_date(date_str: date) -> str:
    return date_str.strftime("%Y-%m-%d")

def validate_date_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("Start date must be before end date")

def validate_frequency(frequency: str) -> str:
    normalized_frequency = frequency.lower().strip()
    if normalized_frequency not in Frequency:
        raise ValueError("Invalid frequency")
    return normalized_frequency

