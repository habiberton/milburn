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

def present_report(final_state: dict) -> None:
    report = final_state.get("report")
    if report is None:
        console.print("[red]No report was produced.[/red]")
        return

    console.print(f"\n[bold]{report['summary']}[/bold]\n")

    if report["signals"]:
        table = Table(title="Signals")
        table.add_column("Category"); table.add_column("Confidence")
        table.add_column("Claim"); table.add_column("Evidence")
        for s in report["signals"]:
            evidence = ", ".join(f"{e['tool']}.{e['field']}={e['value']}" for e in s["evidence"])
            table.add_row(s["category"], s["confidence"], s["claim"], evidence or "—")
        console.print(table)

    for label, key in [("Conflicts", "conflicts"), ("Warnings", "warnings"), ("Next steps", "next_steps")]:
        if report[key]:
            console.print(f"\n[bold]{label}[/bold]")
            for item in report[key]:
                console.print(f"  • {item}")

    console.print(f"\n[dim]run_id: {final_state['run_id']}[/dim]")
