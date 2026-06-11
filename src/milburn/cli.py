import typer
from datetime import date
from dateutil.relativedelta import relativedelta
from typing import Literal

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
    start: str = typer.Option((date.today() - relativedelta(months=1)), "--start", help="The start date of the date range"),
    end: str = typer.Option(date.today(), "--end", help="The end date of the date range")) -> None:
    """
    Fetch historical candle data for a given symbol and date range.
    """
    typer.echo(f"Fetching candles for {symbol} with frequency={frequency}, start={start}, end={end}")

    


@app.command()
def predict(
    symbol: str = typer.Argument(..., help="The symbol of the asset to analyze"),
    start: str = typer.Option((date.today() - relativedelta(months=1)), "--start", help="The start date of the date range"),
    end: str = typer.Option(date.today(), "--end", help="The end date of the date range"),
    prompt: str = typer.Option("", "--prompt", help="The prompt to use for the analysis"),
    llm: str = typer.Option("fake", "--llm", help="The LLM to use for the analysis")) -> None:
    """
    Analyze the performance of a given asset over a specified date range.
    """
    typer.echo(f"Analyzing {symbol} from {start} to {end} with prompt: {prompt} and LLM: {llm}")
