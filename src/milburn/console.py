from rich.console import Console
from rich.table import Table

from milburn.model import CandleResponse

console = Console()

def present_candles(response: CandleResponse) -> None:
    metadata = response.metadata
    table = Table(title=f"{metadata.symbol} ({metadata.frequency})")
    for column in response.frame.columns:
        table.add_column(column)
    for _, row in response.frame.iterrows():
        table.add_row(*[str(row[column]) for column in response.frame.columns])
    console.print(table)
