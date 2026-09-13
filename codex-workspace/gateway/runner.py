from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import psutil


class CodexFailure(RuntimeError):
    """An execution failure with no prompt, credential, or CLI output attached."""


class CodexTimeout(CodexFailure):
    pass


@dataclass(frozen=True)
class RunnerSettings:
    executable: str = "codex"
    workdir: Path = Path("/opt/codex-gateway/workspace")
    model: str = ""
    timeout_seconds: int = 600
    max_output_bytes: int = 2 * 1024 * 1024

    @classmethod
    def from_env(cls) -> RunnerSettings:
        timeout = int(os.getenv("CODEX_TIMEOUT_SECONDS", "600"))
        if not 1 <= timeout <= 3600:
            raise ValueError("CODEX_TIMEOUT_SECONDS must be between 1 and 3600.")
        workdir = Path(os.getenv("CODEX_WORKDIR", "/opt/codex-gateway/workspace"))
        if not workdir.is_dir():
            raise ValueError("The configured Codex working directory must exist.")
        return cls(
            executable=os.getenv("CODEX_CLI_PATH", "codex"),
            workdir=workdir,
            model=os.getenv("CODEX_MODEL", "").strip(),
            timeout_seconds=timeout,
        )


def child_environment() -> dict[str, str]:
    # The gateway bearer token and unrelated application credentials must never
    # be inherited by Codex or model-generated shell commands.
    allowed = {
        "HOME", "USERPROFILE", "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "PATHEXT", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
        "LANG", "LANGUAGE", "LC_ALL", "TZ", "CODEX_HOME", "SSL_CERT_FILE",
        "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY",
        "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    }
    allowed_upper = {name.upper() for name in allowed}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed_upper}


async def stop_process(process: asyncio.subprocess.Process) -> None:
    """Stop the owned process tree before releasing the gateway's only slot."""
    children = []
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        pass
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for child in reversed(children):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()
    if children:
        await asyncio.to_thread(psutil.wait_procs, children, timeout=5)


class CodexRunner:
    def __init__(self, settings: RunnerSettings):
        self.settings = settings
        self._ready_at = 0.0
        self._ready = False
        self._ready_lock = asyncio.Lock()

    async def _start(self, *arguments: str, stdin=None):
        return await asyncio.create_subprocess_exec(
            self.settings.executable,
            *arguments,
            cwd=str(self.settings.workdir),
            env=child_environment(),
            stdin=stdin,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    async def ready(self) -> bool:
        async with self._ready_lock:
            now = asyncio.get_running_loop().time()
            if now < self._ready_at:
                return self._ready
            process = None
            try:
                process = await self._start("login", "status", stdin=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(process.wait(), timeout=5)
                self._ready = process.returncode == 0
            except (OSError, asyncio.TimeoutError):
                self._ready = False
            finally:
                if process is not None and process.returncode is None:
                    await stop_process(process)
            self._ready_at = asyncio.get_running_loop().time() + 5
            return self._ready

    async def run(self, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="codex-gateway-") as temporary:
            output = Path(temporary) / "final.txt"
            arguments = [
                "exec", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "-c", 'approval_policy="never"',
                "--color", "never", "--output-last-message", str(output),
            ]
            if self.settings.model:
                arguments.extend(["--model", self.settings.model])
            arguments.append("-")
            process = None
            try:
                process = await self._start(*arguments, stdin=asyncio.subprocess.PIPE)
                await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=self.settings.timeout_seconds,
                )
                if process.returncode != 0:
                    self._ready_at = 0
                    raise CodexFailure(f"Codex exited with code {process.returncode}.")
                if not output.is_file() or output.stat().st_size > self.settings.max_output_bytes:
                    raise CodexFailure("Codex did not produce a final response within the size limit.")
                result = output.read_text(encoding="utf-8").strip()
                if not result:
                    raise CodexFailure("Codex returned an empty final response.")
                return result
            except asyncio.TimeoutError as exc:
                raise CodexTimeout("Codex execution timed out.") from exc
            except (OSError, UnicodeError) as exc:
                raise CodexFailure("Codex could not execute or read its final response.") from exc
            finally:
                if process is not None:
                    # Also remove descendants if the CLI exited but left children.
                    await stop_process(process)
