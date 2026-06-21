from datetime import date
from langgraph.graph import START, END
from langgraph.graph.state import CompiledStateGraph, StateGraph
from milburn.config import Settings
from milburn.data.intent import identify_intent
from milburn.llm.base import ReportGenerator, ReportInput
from milburn.provider import CandleProvider
from milburn.agent.state import AgentState
from milburn.helper import is_date_range_valid, is_frequency_valid, make_run_id, normalize_frequency, normalize_symbol
from milburn.model import CandleRequest, CandleSummary, AnalysisReport, GraphNode
from milburn.data.context import summarize_candles

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
                actions = identify_intent(state["prompt"])

                return {
                        "run_id": run_id,
                        "symbol": symbol,
                        "frequency": frequency,
                        "requested_actions": actions,
                }

        def load_ohlcv(state: AgentState) -> dict:
                request = CandleRequest(
                        symbol=state["symbol"],
                        frequency=state["frequency"],
                        start=date.fromisoformat(state["start"]),
                        end=date.fromisoformat(state["end"]),
                )
                response = provider.fetch_candles(request)
                c_summary: CandleSummary = summarize_candles(response)

                return {
                        "candle_summary": c_summary.model_dump(mode="json")
                }
                
        def generate_report(state: AgentState) -> dict:
                report_input: ReportInput = ReportInput(
                        prompt=state["prompt"],
                        candle_summary=state["candle_summary"],
                        validation_issues=state["validation_issues"],
                        tool_outputs=state["tool_outputs"],
                        chart_path=state["chart_path"]
                )
                report: AnalysisReport = report_generator.generate_report(report_input)
                return {
                        "report": report.model_dump(mode="json")
                }
        
        builder: StateGraph = StateGraph(AgentState)

        ## Adding core nodes
        builder.add_node(GraphNode.PARSE_REQUEST, parse_request)
        builder.add_node(GraphNode.LOAD_OHLCV, load_ohlcv)
        builder.add_node(GraphNode.GENERATE_REPORT, generate_report)

        ## Adding relationship edges
        builder.add_edge(START, GraphNode.PARSE_REQUEST)
        builder.add_edge(GraphNode.PARSE_REQUEST, GraphNode.LOAD_OHLCV)
        builder.add_edge(GraphNode.LOAD_OHLCV, GraphNode.GENERATE_REPORT)
        builder.add_edge(GraphNode.GENERATE_REPORT, END)

        return builder.compile()




        