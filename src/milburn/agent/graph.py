from langgraph.graph.state import CompiledStateGraph
from milburn.config import Settings
from milburn.llm.base import ReportGenerator
from milburn.provider import CandleProvider
from milburn.agent.state import AgentState
from milburn.helper import is_date_range_valid, is_frequency_valid, make_run_id, normalize_frequency, normalize_symbol, convert_date

"""
Nodes to define: 
1. Fetch Candles
2. Analyze Data
3. Generate Report
"""

def build_graph(
        provider: CandleProvider,
        report_generator: ReportGenerator,
        settings: Settings,
) -> CompiledStateGraph:
    
    def parse_request(state: AgentState) -> dict:
        if not is_date_range_valid(state["start"], state["end"]):
            raise ValueError("Invalid date range.")
        if not is_frequency_valid(state["frequency"]):
            raise ValueError("Invalid frequency.")
        if not state["symbol"]:
            raise ValueError("Invalid symbol.")
        
        run_id = make_run_id()
        symbol = normalize_symbol(state["symbol"])
        frequency = normalize_frequency(state["frequency"])
        start = convert_date(state["start"])
        end = convert_date(state["end"])

        

        