"""Ollama-backed report generator.

Stub for now -- the real implementation lands in Step 9 of the predict
walkthrough (ChatOllama construction, prompt assembly, parse-validate-retry).
It exists here so the factory's ollama branch has something to construct.
"""

from milburn.llm.base import ReportInput
from milburn.llm.config import ModelProfile
from milburn.model import AnalysisReport


class OllamaReportGenerator:
    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile

    def generate_report(self, input: ReportInput) -> AnalysisReport:
        raise NotImplementedError(
            "Step 9: OllamaReportGenerator is not implemented yet."
        )
