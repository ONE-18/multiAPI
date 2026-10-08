from dataclasses import dataclass
from typing import Any


@dataclass
class ScriptRequest:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: Any


class Script:
    def run(self, request: ScriptRequest) -> Any:
        raise NotImplementedError