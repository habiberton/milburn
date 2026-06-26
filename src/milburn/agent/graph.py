from datetime import date
from langgraph.graph import START, END
from langgraph.graph.state import CompiledStateGraph, StateGraph
from milburn.config import Settings
from milburn.data.intent import identify_intent
from milburn.llm.base import ReportGenerator, ReportInput
from milburn.provider import CandleProvider
from milburn.agent.state import AgentState
from milburn.helper import is_date_range_valid, is_frequency_valid, make_run_id, normalize_frequency, normalize_symbol
from milburn.model import CandleRequest, CandleSummary, AnalysisReport, GraphNode, CandleResponse
from milburn.data.context import summarize_candles
from milburn.tools.registry import tool_selection, tool_runner, ToolRegistry, ToolResult

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
        registry: ToolRegistry,
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
                categories = identify_intent(state["prompt"])

                return {
                        "run_id": run_id,
                        "symbol": symbol,
                        "frequency": frequency,
                        "indicator_categories": categories,
                }

        def load_ohlcv(state: AgentState) -> dict:
                request = CandleRequest(
                        symbol=state["symbol"],
                        frequency=state["frequency"],
                        start=date.fromisoformat(state["start"]),
                        end=date.fromisoformat(state["end"]),
                )
                response: CandleResponse = provider.fetch_candles(request)
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
        
        def select_tools(state: AgentState) -> dict:
                categories = state["indicator_categories"]
                validation_issues=state["validation_issues"]
                selected_tools: list[str] = tool_selection(categories, validation_issues)
                return {
                        "selected_tools": selected_tools
                }
        
        def run_tools(state: AgentState) -> dict:
                request = CandleRequest(
                        symbol=state["symbol"],
                        frequency=state["frequency"],
                        start=date.fromisoformat(state["start"]),
                        end=date.fromisoformat(state["end"]),
                )
                response: CandleResponse = provider.fetch_candles(request)

                tools: list[str] = state["selected_tools"]
                results: dict[str, ToolResult] = tool_runner(tools, response.frame, registry)

                return {
                        "tool_outputs": {name: tr.model_dump(mode="json") for name, tr in results.items()}
                }


        
        builder: StateGraph = StateGraph(AgentState)

        ## Adding core nodes
        builder.add_node(GraphNode.PARSE_REQUEST, parse_request)
        builder.add_node(GraphNode.LOAD_OHLCV, load_ohlcv)
        builder.add_node(GraphNode.SELECT_TOOLS, select_tools)
        builder.add_node(GraphNode.RUN_TOOLS, run_tools)
        builder.add_node(GraphNode.GENERATE_REPORT, generate_report)

        ## Adding relationship edges
        builder.add_edge(START, GraphNode.PARSE_REQUEST)
        builder.add_edge(GraphNode.PARSE_REQUEST, GraphNode.LOAD_OHLCV)
        builder.add_edge(GraphNode.LOAD_OHLCV, GraphNode.SELECT_TOOLS)
        builder.add_edge(GraphNode.SELECT_TOOLS, GraphNode.RUN_TOOLS)
        builder.add_edge(GraphNode.RUN_TOOLS, GraphNode.GENERATE_REPORT)
        builder.add_edge(GraphNode.GENERATE_REPORT, END)

        return builder.compile()




        