from pydantic import BaseModel
from typing import Literal

class ModelProfile(BaseModel):
    name: str
    provider: Literal["fake", "ollama", "openai"]
    model: str
    base_url: str | None = None
    temperature: float = 0.1
    top_p: float = 0.9
    num_ctx: int = 8192
    num_predict: int = 2048
    seed: int | None = None
    timeout_secs: int = 180