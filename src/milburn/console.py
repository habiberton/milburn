import random, subprocess, threading
from rich.console import Console
from rich.table import Table
from langgraph.graph.state import CompiledStateGraph

from milburn.agent.state import AgentState
from milburn.model import CandleResponse, GraphNode

console = Console()

_THINKING_WORDS = [
      "Cogitating", "Pondering", "Conjuring", "Noodling", "Brewing",
      "Percolating", "Ruminating", "Crunching", "Finagling", "Spelunking",
      "Synthesizing", "Marinating", "Tinkering", "Wrangling", "Divining",
  ]

_PHASES: dict[str, tuple[str, str]] = {
      "parse_request":   (":face_with_rolling_eyes:", "Reading your prompt…"),
      "load_ohlcv":      (":money_with_wings:", "Fetching market data…"),
      "select_tools":    (":mag_right:", "Gathering tools…"),
      "run_tools":       (":fire:", "Computing indicators…"),
      "generate_report": (":thinking_face:",f"{random.choice(_THINKING_WORDS)}"),
}


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


def run_with_status(graph: CompiledStateGraph, state: AgentState) -> dict:
    final_state: dict = state
    current: str | None = None

    with console.status(f"{random.choice(_THINKING_WORDS)}…", spinner="dots2") as status:
        for mode, chunk in graph.stream(state, stream_mode=["debug", "values"]):
            if mode == "debug" and chunk["type"] == "task":
                node = chunk["payload"]["name"]
                if current is not None:
                    console.print(current)                    
                emoji, label = _PHASES.get(node, ("⚙️", f"Running {node}...")) 
                current = f"{emoji} {label}"                     
                status.update(current)                             
            elif mode == "values":
                final_state = chunk

    if current is not None:
        console.print(current)
    return final_state
    
def run_with_monopoly_gif(graph, state, gif="monopoly_running.gif") -> dict:
      result = {}
      def work():
          result["state"] = graph.invoke(state)
      t = threading.Thread(target=work); t.start()
      anim = subprocess.Popen(["chafa", "--size", "40x20", gif]) 
      t.join()           
      anim.terminate()      
      return result["state"]