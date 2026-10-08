import importlib.util
import json
import sys
from pathlib import Path

from script_api import Script, ScriptRequest


def main() -> None:
    script_path = Path(sys.argv[1]).resolve()
    spec = importlib.util.spec_from_file_location("endpoint_script", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    script_class = getattr(module, "Script", None)
    if not isinstance(script_class, type) or not issubclass(script_class, Script):
        raise TypeError(f"{script_path} must define a Script subclass")

    payload = json.load(sys.stdin)
    request = ScriptRequest(**payload)
    result = script_class().run(request)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()