"""Run a verified command: choose the interpreter, stream output, enforce timeouts, support cancel."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

MAX_CAPTURE = 1_000_000
FLUSH_SECONDS = 0.5
FLUSH_BYTES = 4096
INTERPRETERS = {"sh", "bash", "powershell", "pwsh", "cmd", "python"}


def interpreter_of(body: str) -> tuple[str, str]:
    """A first line `#proofos:shell=powershell` picks the interpreter; otherwise the OS default shell."""
    first, _, rest = body.partition("\n")
    if first.strip().lower().startswith("#proofos:shell="):
        name = first.strip().split("=", 1)[1].strip().lower()
        if name in INTERPRETERS:
            return name, rest
    return ("cmd" if sys.platform.startswith("win") else "sh"), body


def _command(shell: str, body: str, workdir: str) -> tuple[list[str] | str, bool, str | None]:
    """Returns (argv-or-string, use_shell, temp_file)."""
    if shell == "cmd":
        return body, True, None
    if shell == "sh":
        return ["/bin/sh", "-c", body], False, None
    suffix = {"bash": ".sh", "powershell": ".ps1", "pwsh": ".ps1", "python": ".py"}[shell]
    fd, path = tempfile.mkstemp(suffix=suffix, dir=workdir, prefix="job-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
    if shell == "bash":
        return ["bash", path], False, path
    if shell in {"powershell", "pwsh"}:
        exe = "powershell.exe" if shell == "powershell" else "pwsh"
        return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path], False, path
    if getattr(sys, "frozen", False):
        raise RuntimeError("python jobs need a Python interpreter; this agent is a frozen binary")
    return [sys.executable, "-I", path], False, path


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        import psutil

        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except Exception:  # noqa: BLE001 - fall back to the direct child
        try:
            proc.kill()
        except OSError:
            pass


class Running:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.cancelled = threading.Event()


def run(body: str, *, timeout: int, workdir: str, on_output: Callable[[str], None], handle: Running | None = None) -> tuple[str, int]:
    """Execute and return (captured output, exit code). on_output receives chunks while it runs."""
    handle = handle or Running()
    shell, script = interpreter_of(body)
    if not script.strip():
        return "", 0
    pathlib.Path(workdir).mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        argv, use_shell, temp = _command(shell, script, workdir)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0
        handle.proc = subprocess.Popen(argv, shell=use_shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, cwd=workdir, creationflags=flags, start_new_session=not sys.platform.startswith("win"))
    except Exception as exc:  # noqa: BLE001
        if temp:
            os.unlink(temp)
        return f"could not start {shell}: {exc}", 127

    captured: list[str] = []
    size = 0
    pending: list[str] = []
    lock = threading.Lock()
    last_flush = [time.monotonic()]

    def flush() -> None:
        with lock:
            if not pending:
                return
            chunk = "".join(pending)
            pending.clear()
            last_flush[0] = time.monotonic()
        try:
            on_output(chunk)
        except Exception:  # noqa: BLE001 - streaming is best effort; the final result is authoritative
            pass

    def reader() -> None:
        nonlocal size
        assert handle.proc and handle.proc.stdout
        for raw in iter(lambda: handle.proc.stdout.read1(4096) if hasattr(handle.proc.stdout, "read1") else handle.proc.stdout.read(4096), b""):
            text = raw.decode("utf-8", errors="replace")
            with lock:
                if size < MAX_CAPTURE:
                    captured.append(text[: MAX_CAPTURE - size])
                    size += len(text)
                pending.append(text)
                due = sum(len(p) for p in pending) >= FLUSH_BYTES
            if due:
                flush()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    outcome = None
    while handle.proc.poll() is None:
        if handle.cancelled.is_set():
            kill_tree(handle.proc)
            outcome = ("\n[cancelled by operator]\n", 130)
            break
        if time.monotonic() > deadline:
            kill_tree(handle.proc)
            outcome = (f"\n[timed out after {timeout}s; process tree killed]\n", 124)
            break
        if time.monotonic() - last_flush[0] >= FLUSH_SECONDS:
            flush()
        time.sleep(0.1)
    handle.proc.wait()
    thread.join(timeout=5)
    flush()
    if temp:
        try:
            os.unlink(temp)
        except OSError:
            pass
    text = "".join(captured)
    if size > MAX_CAPTURE:
        text += f"\n[output truncated at {MAX_CAPTURE} characters]\n"
    if outcome:
        on_output(outcome[0])
        return text + outcome[0], outcome[1]
    return text, handle.proc.returncode
