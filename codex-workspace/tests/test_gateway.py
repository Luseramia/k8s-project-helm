import asyncio
import json
import os
import socket
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import psutil
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gateway.app import create_app, MAX_REQUEST_BYTES
from gateway.runner import CodexRunner, RunnerSettings, CodexFailure, CodexTimeout, child_environment


TOKEN = "test-only-" + "x" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class FakeRunner:
    def __init__(self):
        self.available = True
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.hold = False
        self.error = None
        self.output = "คำตอบ"

    async def ready(self):
        return self.available

    async def run(self, prompt):
        self.calls.append(prompt)
        self.started.set()
        try:
            if self.hold:
                await self.release.wait()
            if self.error:
                raise self.error
            return self.output
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@asynccontextmanager
async def tcp_server(application):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, log_level="error", timeout_graceful_shutdown=2))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.02)
        if not server.started:
            raise RuntimeError("Test HTTP server did not start.")
        yield port
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runner = FakeRunner()
        self.application = create_app(runner=self.runner, token=TOKEN)
        self.lifespan = self.application.router.lifespan_context(self.application)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.application), base_url="http://gateway")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def post(self, prompt="คำถาม", **extra):
        return await self.client.post("/v1/generate", json={"requestId": "req-1", "prompt": prompt, **extra}, headers=HEADERS)

    async def test_auth_is_checked_before_parsing_body(self):
        response = await self.client.post("/v1/generate", content="not json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.runner.calls, [])

    async def test_success_and_safe_logs(self):
        with self.assertLogs("codex_gateway", level="INFO") as logs:
            response = await self.post("PRIVATE_PROMPT")
        self.assertEqual(response.json(), {"requestId": "req-1", "output": "คำตอบ"})
        self.assertEqual(self.runner.calls, ["PRIVATE_PROMPT"])
        self.assertNotIn("PRIVATE_PROMPT", str(logs.output))
        self.assertNotIn(TOKEN, str(logs.output))

    async def test_rejects_command_flags_empty_prompt_and_oversize_body(self):
        self.assertEqual((await self.post(command="rm something")).status_code, 422)
        self.assertEqual((await self.post("  ")).status_code, 422)
        self.assertEqual((await self.post("x" * MAX_REQUEST_BYTES)).status_code, 413)
        async def chunks():
            yield b"x" * (MAX_REQUEST_BYTES // 2)
            yield b"y" * (MAX_REQUEST_BYTES // 2 + 1)
        response = await self.client.post("/v1/generate", content=chunks(), headers=HEADERS)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.runner.calls, [])

    async def test_one_active_execution_and_slot_released(self):
        self.runner.hold = True
        first = asyncio.create_task(self.post())
        await asyncio.wait_for(self.runner.started.wait(), 2)
        self.assertEqual((await self.post()).status_code, 429)
        self.assertEqual(len(self.runner.calls), 1)
        self.runner.release.set()
        self.assertEqual((await first).status_code, 200)
        self.assertEqual((await self.post()).status_code, 200)

    async def test_health_readiness_and_generation_failures(self):
        self.runner.available = False
        self.assertEqual((await self.client.get("/health")).status_code, 200)
        self.assertEqual((await self.client.get("/ready")).status_code, 503)
        self.assertEqual((await self.post()).status_code, 503)
        self.assertEqual(self.runner.calls, [])
        self.runner.available = True
        for error, code in [(CodexFailure("SECRET_DETAIL"), 502), (CodexTimeout("SECRET_DETAIL"), 504)]:
            self.runner.error = error
            with self.assertLogs("codex_gateway", level="INFO") as logs:
                response = await self.post()
            self.assertEqual(response.status_code, code)
            self.assertNotIn("SECRET_DETAIL", response.text)
            self.assertNotIn("SECRET_DETAIL", str(logs.output))
            self.assertFalse(self.application.state.busy)

    async def test_request_cancellation_releases_execution(self):
        self.runner.hold = True
        request = asyncio.create_task(self.post())
        await asyncio.wait_for(self.runner.started.wait(), 2)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertTrue(self.runner.cancelled.is_set())
        self.assertFalse(self.application.state.busy)

    async def test_missing_token_prevents_startup(self):
        for token in ["", "short", "x" * 32 + "\n"]:
            application = create_app(runner=self.runner, token=token)
            with self.assertRaises(ValueError):
                async with application.router.lifespan_context(application):
                    pass

    async def test_real_http_disconnect_cancels_codex(self):
        runner = FakeRunner()
        runner.hold = True
        application = create_app(runner=runner, token=TOKEN)
        async with tcp_server(application) as port:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            body = json.dumps({"requestId": "disconnect", "prompt": "hello"}).encode()
            writer.write((
                f"POST /v1/generate HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {TOKEN}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
            ).encode() + body)
            await writer.drain()
            await asyncio.wait_for(runner.started.wait(), 2)
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(runner.cancelled.wait(), 3)
            for _ in range(100):
                if not application.state.busy:
                    break
                await asyncio.sleep(0.01)
            self.assertFalse(application.state.busy)


FAKE_CLI = '''import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
if args == ["login", "status"]:
    sys.exit(1 if pathlib.Path("logged-out").exists() else 0)
prompt = sys.stdin.buffer.read().decode("utf-8")
assert args[0] == "exec" and "--ephemeral" in args
assert args[args.index("--sandbox") + 1] == "read-only"
assert 'approval_policy="never"' in args
assert "CODEX_GATEWAY_TOKEN" not in os.environ
assert "CODEX_REMOTE_TOKEN" not in os.environ
if prompt == "spawn":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    pathlib.Path("child.pid").write_text(str(child.pid))
    time.sleep(60)
elif prompt == "fail":
    print("PRIVATE_ERROR", file=sys.stderr)
    sys.exit(2)
elif prompt == "empty":
    sys.exit(0)
else:
    output = pathlib.Path(args[args.index("--output-last-message") + 1])
    output.write_text(prompt, encoding="utf-8")
'''


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        script = self.directory / "fake_cli.py"
        script.write_text(FAKE_CLI, encoding="utf-8")
        original = asyncio.create_subprocess_exec
        async def launch(executable, *args, **kwargs):
            return await original(sys.executable, str(script), *args, **kwargs)
        self.mock = patch("gateway.runner.asyncio.create_subprocess_exec", side_effect=launch)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.runner = CodexRunner(RunnerSettings(executable="fake-codex", workdir=self.directory, timeout_seconds=1))

    async def wait_for_child(self):
        marker = self.directory / "child.pid"
        for _ in range(100):
            if marker.exists():
                return int(marker.read_text())
            await asyncio.sleep(0.02)
        self.fail("The child process did not start.")

    async def test_real_process_handles_unicode_and_auth_readiness(self):
        with patch.dict(os.environ, {"CODEX_GATEWAY_TOKEN": TOKEN, "CODEX_REMOTE_TOKEN": TOKEN}):
            self.assertTrue(await self.runner.ready())
            self.assertEqual(await self.runner.run('ภาษาไทย\n{"quoted":"text"}'), 'ภาษาไทย\n{"quoted":"text"}')
        (self.directory / "logged-out").touch()
        self.runner._ready_at = 0
        self.assertFalse(await self.runner.ready())

    async def test_process_timeout_kills_child(self):
        running = asyncio.create_task(self.runner.run("spawn"))
        child_pid = await self.wait_for_child()
        with self.assertRaises(CodexTimeout):
            await running
        self.assertFalse(psutil.pid_exists(child_pid))

    async def test_process_cancellation_kills_child(self):
        running = asyncio.create_task(self.runner.run("spawn"))
        child_pid = await self.wait_for_child()
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertFalse(psutil.pid_exists(child_pid))

    async def test_cli_failure_and_missing_final_message_are_rejected(self):
        for prompt in ["fail", "empty"]:
            with self.assertRaises(CodexFailure) as error:
                await self.runner.run(prompt)
            self.assertNotIn("PRIVATE_ERROR", str(error.exception))
