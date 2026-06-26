"""Ollama-backed report generator.

Stub for now -- the real implementation lands in Step 9 of the predict
walkthrough (ChatOllama construction, prompt assembly, parse-validate-retry).
It exists here so the factory's ollama branch has something to construct.
"""

import json
from pathlib import Path

from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage

from milburn.llm.base import ReportInput
from milburn.llm.config import ModelProfile
from milburn.model import AnalysisReport

PROMPTS = Path(__file__).parent.parent / "prompts"

class OllamaReportGenerator:
    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile
        self._system_prompt = (PROMPTS / "report_system.md").read_text()
        self._llm = ChatOllama(
            verbose=True,
            model=profile.model,
            base_url=profile.base_url,
            temperature=profile.temperature,
            top_p=profile.top_p,
            num_ctx=profile.num_ctx,
            num_predict=profile.num_predict,
            seed=profile.seed,
            format=AnalysisReport.model_json_schema()
        )

    # Pattern: parse -> validate -> retry -> degrade
    def generate_report(self, input: ReportInput) -> AnalysisReport:
        messages = [
            SystemMessage(self._system_prompt),
            HumanMessage(self._build_user_message(input))
        ]
        last_error: Exception | None = None
        for _ in range(2):
            try: 
                response = self._llm.invoke(messages)
                return AnalysisReport.model_validate_json(response.content)
            except Exception as e:
                last_error = e
                messages.append(HumanMessage(
                    "Your previous response was not valid against the schema. "
                    "Respond with ONLY a JSON object matching it."
                ))
        return self._degraded_report(last_error)

    def _build_user_message(self, input: ReportInput) -> str:
        return (
            f"User request:`n{input.prompt or '(none)'}\n\n"
            f"candle_summary:\n{json.dumps(input.candle_summary, indent=2)}\n\n"
            f"tool_outputs:\n{json.dumps(input.tool_outputs, indent=2)}\n\n"
        )

    def _degraded_report(self, error: Exception | None) -> AnalysisReport:
        return AnalysisReport(
            summary="Report generation failed to produce a valid structured response.",
            data={},
            signals=[],
            conflicts=[],
            warnings=[f"model output invalid after retries: {error}"],
            next_steps=["Re-run, lower the temp, or inspect tool_outputs"]
        )