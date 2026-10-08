from script_api import Script, ScriptRequest


class Script(Script):
    def run(self, request: ScriptRequest) -> dict[str, object]:
        return {
            "method": request.method,
            "message": "Example script response",
            "query": request.query,
        }