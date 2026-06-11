import typer
from datetime import date
from dateutil.relativedelta import relativedelta
from typing import Optional

from milburn.config import Settings
from milburn.model import CandleRequest
from milburn.providers.tiingo_provider import TiingoProvider
from milburn.helper import convert_date, is_date_range_valid, is_frequency_valid, normalize_frequency, normalize_symbol, parse_date

app = typer.Typer(help="Milburn - Your technical-analysis agentic assistant")

@app.command()
def doctor(
    models: bool = typer.Option(False, "--models", help="Show available models")) -> None:
    """
    Check the health of Milburn.
    """
    typer.echo("Milburn is running correctly.")


@app.command()
def fetch(
    symbol: str = typer.Argument(..., help="The symbol of the asset to fetch data for"),
    frequency: str = typer.Option("daily", "--frequency", help="The frequency of the candles"),
    start: date = typer.Option(
          date.today() - relativedelta(months=1),
          "--start",
          parser=parse_date,
          help="Start date (YYYY-MM-DD)",
      ),
      end: date = typer.Option(
          date.today(),
          "--end",
          parser=parse_date,
          help="End date (YYYY-MM-DD)",
      ),
    ) -> None:
    """
    Fetch historical candle data for a given symbol and date range.
    """
    typer.echo(f"Fetching candles for {symbol} with frequency={frequency}, start={start}, end={end}")

    if not is_date_range_valid(start, end):
        typer.echo("Invalid date range.")
        return

    if not is_frequency_valid(frequency):
        typer.echo("Invalid frequency.")
        return
    
    settings = Settings()
    provider = TiingoProvider(settings)
    request = CandleRequest(
        symbol=normalize_symbol(symbol),
        frequency=normalize_frequency(frequency),
        start=convert_date(start),
        end=convert_date(end),
    )
    response = provider.fetch_candles(request)
    typer.echo(f"Retrieved {response.metadata.rows} candles for {symbol}")



@app.command()
def predict(
    symbol: str = typer.Argument(..., help="The symbol of the asset to analyze"),
    start: date = typer.Option(
          date.today() - relativedelta(months=1),
          "--start",
          parser=parse_date,
          help="Start date (YYYY-MM-DD)",
      ),
      end: date = typer.Option(
          date.today(),
          "--end",
          parser=parse_date,
          help="End date (YYYY-MM-DD)",
      ),
    prompt: str = typer.Option("", "--prompt", help="The prompt to use for the analysis"),
    llm: str = typer.Option("fake", "--llm", help="The LLM to use for the analysis")) -> None:
    """
    Analyze the performance of a given asset over a specified date range.
    """
    typer.echo(f"Analyzing {symbol} from {start} to {end} with prompt: {prompt} and LLM: {llm}")
