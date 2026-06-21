import typer
from datetime import date
from dateutil.relativedelta import relativedelta

from milburn.config import Settings
from milburn.console import present_candles, present_report
from milburn.model import CandleRequest, Effort
from milburn.llm.factory import build_report_generator
from milburn.agent.graph import build_graph
from milburn.agent.state import AgentState
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
        start=start,
        end=end,
    )
    response = provider.fetch_candles(request)
    present_candles(response)



@app.command()
def predict(
    symbol: str = typer.Argument(..., help="The symbol of the asset to analyze"),
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
    prompt: str = typer.Option("", "--prompt", help="The prompt to use for the analysis"),
    effort: Effort = typer.Option(Effort.none, "--effort", help="The LLM effort level to use for the analysis")) -> None:
    """
    Analyze the performance of a given asset over a specified date range.
    """
    typer.echo(f"Analyzing {symbol} from {start} to {end} and frequency {frequency} with prompt: {prompt} and effort-level: {effort}")
    
    settings: Settings = Settings()
    report = build_report_generator(effort, settings)
    provider: TiingoProvider = TiingoProvider(settings)
    
    graph = build_graph(provider, report, settings)

    state: AgentState = AgentState(
        run_id="",
        prompt=prompt,
        symbol=normalize_symbol(symbol),
        frequency=normalize_frequency(frequency),
        start=convert_date(start),
        end=convert_date(end),
        data_provider=None,
        data_cache_key=None,
        candle_summary={},
        validation_issues=[],
        requested_actions=[],
        selected_tools=[],
        tool_outputs={},
        chart_path=None,
        model_profile=effort,
        report=None,
        consistency_check=None,
        warnings=[],
        traces=[],
    )
    result = graph.invoke(state)
    present_report(result)


