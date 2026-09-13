from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gateway.runner import CodexFailure, CodexRunner, CodexTimeout, RunnerSettings


logger = logging.getLogger("codex_gateway")
MAX_REQUEST_BYTES = 1024 * 1024


class GenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requestId: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    prompt: str = Field(min_length=1)


def create_app(*, runner=None, token: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        credential = token if token is not None else os.getenv("CODEX_GATEWAY_TOKEN", "")
        if len(credential) < 32 or not credential.isascii() or any(char.isspace() for char in credential):
            raise ValueError("CODEX_GATEWAY_TOKEN must be an ASCII token of at least 32 characters without whitespace.")
        application.state.token = credential
        application.state.runner = runner if runner is not None else CodexRunner(RunnerSettings.from_env())
        application.state.busy = False
        yield

    application = FastAPI(
        title="Codex Gateway", lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,
    )

    @application.get("/health")
    async def health():
        return {"status": "ok", "service": "codex-gateway"}

    @application.get("/ready")
    async def ready():
        available = await application.state.runner.ready()
        return JSONResponse(
            {"status": "ready" if available else "not_ready"},
            status_code=200 if available else 503,
        )

    @application.post("/v1/generate")
    async def generate(request: Request):
        expected = f"Bearer {application.state.token}".encode("ascii")
        supplied = request.headers.get("authorization", "").encode("utf-8")
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(401, "Invalid gateway credentials.", headers={"WWW-Authenticate": "Bearer"})
        # Read and limit the actual body, including chunked requests, after auth.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_REQUEST_BYTES:
                raise HTTPException(413, "Request body is too large.")
        try:
            payload = GenerationInput.model_validate_json(body)
        except (ValidationError, ValueError):
            raise HTTPException(422, "Expected requestId and a nonempty prompt only.") from None
        if not payload.prompt.strip():
            raise HTTPException(422, "Prompt cannot be empty.")
        if application.state.busy:
            raise HTTPException(429, "Codex gateway is busy.", headers={"Retry-After": "5"})
        # No await between the availability check and assignment: one event loop,
        # one Uvicorn worker, one replica. This is admission control, not a queue.
        application.state.busy = True
        started = time.monotonic()
        tasks = []
        outcome = "failed"
        try:
            if not await application.state.runner.ready():
                raise HTTPException(503, "Codex is not ready. Check CLI installation and login status.")

            async def disconnected():
                # The request body has been consumed. Waiting on receive directly
                # is cancellable even when the CLI finishes immediately.
                while True:
                    message = await request.receive()
                    if message["type"] == "http.disconnect":
                        return

            execution = asyncio.create_task(application.state.runner.run(payload.prompt))
            disconnect = asyncio.create_task(disconnected())
            tasks = [execution, disconnect]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if execution not in done:
                outcome = "disconnected"
                raise HTTPException(499, "Client disconnected.")
            output = await execution
            outcome = "completed"
            return {"requestId": payload.requestId, "output": output}
        except CodexTimeout:
            outcome = "timeout"
            raise HTTPException(504, "Codex execution timed out.") from None
        except CodexFailure as error:
            logger.warning("requestId=%s errorType=%s", payload.requestId, type(error).__name__)
            raise HTTPException(502, "Codex execution failed. Check server login and configuration.") from None
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            application.state.busy = False
            logger.info("requestId=%s status=%s duration=%.3f", payload.requestId, outcome, time.monotonic() - started)

    return application


app = create_app()
