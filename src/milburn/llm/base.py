from pydantic import BaseModel
from typing import Any, Protocol

from milburn.model import AnalysisReport


class ReportInput(BaseModel):
    prompt: str
    candle_summary: dict[str, Any]
    validation_issues: list[dict[str, Any]]
    tool_outputs: dict[str, Any]
    chart_path: str | None

class ReportGenerator(Protocol):
    def generate_report(self, input: ReportInput) -> AnalysisReport:
        ...