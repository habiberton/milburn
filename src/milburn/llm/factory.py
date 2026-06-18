"""Profile loading and generator construction.

The --llm flag is just a key into this factory: it resolves a profile name
from profiles.yaml and returns a concrete ReportGenerator. The graph
closes over whatever this returns and never knows which backend it got.
"""

from pathlib import Path
from typing import Any

import yaml

from milburn.config import Settings
from milburn.llm.base import ReportGenerator
from milburn.llm.config import ModelProfile
from milburn.llm.fake_report_generator import FakeReportGenerator
from milburn.llm.ollama_report_generator import OllamaReportGenerator

_PROFILES_PATH = Path(__file__).parent / "profiles.yaml"


def _load_profiles() -> dict[str, dict[str, Any]]:
    with _PROFILES_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{_PROFILES_PATH} must map profile names to configs.")
    return data


def get_model_profile(name: str, settings: Settings) -> ModelProfile:
    """Resolve a profile by name, with a clear error for unknown names."""
    profiles = _load_profiles()
    if name not in profiles:
        available = ", ".join(sorted(profiles))
        raise ValueError(f"Unknown model profile {name!r}. Available: {available}.")

    config = dict(profiles[name])
    # The YAML keys profiles by name, so the name itself isn't in the body.
    config.setdefault("name", name)
    # Default an Ollama base_url from settings when the profile omits one.
    if config.get("provider") == "ollama" and not config.get("base_url"):
        config["base_url"] = settings.ollama_base_url
    return ModelProfile(**config)


def build_report_generator(profile_name: str, settings: Settings) -> ReportGenerator:
    """Map a profile name to a concrete generator instance."""
    profile = get_model_profile(profile_name, settings)

    if profile.provider == "fake":
        return FakeReportGenerator()
    if profile.provider == "ollama":
        return OllamaReportGenerator(profile)
    raise ValueError(f"Unsupported provider {profile.provider!r} for profile {profile_name!r}.")
