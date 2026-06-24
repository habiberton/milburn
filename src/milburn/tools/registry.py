from collections.abc import Callable
from typing import Any
from milburn.tools.results import ToolResult

from pydantic import BaseModel

class ToolSpec(BaseModel):
    name: str
    description: str 
    function: Callable[..., ToolResult]
    default_params: dict[str, Any] = {}
    required_columns: list[str] = ["close"]