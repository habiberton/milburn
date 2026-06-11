from langgraph.graph.state import CompiledStateGraph
from milburn.config import Settings
from milburn.provider import CandleProvider
from milburn.agent.state import AgentState

"""
Nodes to define: 
1. Fetch Candles
2. Analyze Data
3. Generate Report
"""

def build_graph(
        provider: CandleProvider,
        settings: Settings,
) -> CompiledStateGraph:
    
    def parse_request(state: AgentState) -> dict:
        