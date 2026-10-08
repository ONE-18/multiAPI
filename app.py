from pathlib import Path
import json
import logging
import os
import asyncio
import sys
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="General API")
CONFIG_PATH = Path(os.getenv("CONFIG_JSON_PATH", "endpoints"))
SCRIPT_TIMEOUT = float(os.getenv("SCRIPT_TIMEOUT", "10"))
SUPPORTED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
dynamic_routes = []


def read_file_endpoints() -> list[tuple[str, str, Path | Any]]:
    if not CONFIG_PATH.is_dir():
        logger.error("Endpoint directory does not exist: %s", CONFIG_PATH)
        raise RuntimeError(f"CONFIG_JSON_PATH must be a directory: {CONFIG_PATH}")

    endpoints = []
    for file_path in sorted(path for path in CONFIG_PATH.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(CONFIG_PATH)
        if len(relative_path.parts) < 2:
            # raise ValueError(
            #     f"{file_path}: file must be inside an HTTP method directory"
            # )
            logger.warning(
                "Skipping %s: file must be inside an HTTP method directory",
                file_path,
            )
            continue

        method = relative_path.parts[0].upper()
        if method not in SUPPORTED_METHODS:
            logger.error("Unsupported HTTP method %r in file %s", method, file_path)
            raise ValueError(f"{file_path}: unsupported HTTP method {method!r}")

        route_path = "/" + Path(
            *relative_path.parts[1:]
        ).with_suffix("").as_posix()
        if file_path.suffix == ".json":
            with file_path.open(encoding="utf-8") as endpoint_file:
                endpoint = json.load(endpoint_file)
        elif file_path.suffix == ".py":
            endpoint = file_path
        else:
            continue
        endpoints.append((route_path, method, endpoint))
        logger.info("Loaded endpoint %s %s from %s", method, route_path, file_path)

    logger.info("Loaded %d endpoint(s) from %s", len(endpoints), CONFIG_PATH)
    return endpoints


def register_file_endpoint(route_path: str, method: str, endpoint: Path | Any) -> None:

    if isinstance(endpoint, Path):

        async def serve_script(request: Request) -> JSONResponse:
            try:
                body = await request.body()
                try:
                    body = json.loads(body) if body else None
                except json.JSONDecodeError:
                    body = body.decode("utf-8", errors="replace")

                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(Path(__file__).with_name("script_runner.py")),
                    str(endpoint),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                payload = {
                    "method": request.method,
                    "path": request.url.path,
                    "query": dict(request.query_params),
                    "headers": dict(request.headers),
                    "body": body,
                }
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(json.dumps(payload).encode("utf-8")),
                    timeout=SCRIPT_TIMEOUT,
                )
            except asyncio.TimeoutError as error:
                process.kill()
                await process.wait()
                raise HTTPException(status_code=504, detail="Script timed out") from error

            if process.returncode != 0:
                logger.error("Script %s failed: %s", endpoint, stderr.decode().strip())
                raise HTTPException(status_code=500, detail="Script execution failed")

            try:
                result = json.loads(stdout)
            except json.JSONDecodeError as error:
                raise HTTPException(status_code=500, detail="Script returned invalid JSON") from error
            return JSONResponse(content=result)

        handler = serve_script
    else:

        def serve_file(response_body: Any = endpoint) -> JSONResponse:
            return JSONResponse(content=response_body)

        handler = serve_file

    app.add_api_route(
        route_path,
        handler,
        methods=[method],
    )
    dynamic_routes.append(app.routes[-1])
    logger.info("Registered endpoint %s %s", method, route_path)


def register_file_endpoints() -> None:
    endpoints = read_file_endpoints()
    removed_routes = len(dynamic_routes)
    for route in dynamic_routes:
        app.router.routes.remove(route)
    dynamic_routes.clear()
    for route_path, method, response_body in endpoints:
        register_file_endpoint(route_path, method, response_body)
    logger.info(
        "Endpoint registration completed: %d removed, %d registered",
        removed_routes,
        len(dynamic_routes),
    )


@app.post("/reload")
def reload_endpoints() -> dict[str, str]:
    try:
        register_file_endpoints()
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        logger.exception("Failed to reload endpoints")
        raise HTTPException(status_code=500, detail=str(error)) from error
    logger.info("Endpoints reloaded successfully")
    return {"status": "reloaded"}

@app.get("/list")
def list_endpoints() -> list[dict[str, str]]:
    logger.info("Listing %d endpoint(s)", len(dynamic_routes))
    return [
        {"path": route.path, "method": sorted(route.methods)[0]}
        for route in dynamic_routes
    ]

register_file_endpoints()
