"""Run ProofOS's CI gates locally (used while GitHub Actions is unavailable).

  python scripts/ci_local.py            # all gates except end-to-end
  python scripts/ci_local.py --e2e      # include Playwright end-to-end tests
  python scripts/ci_local.py --only api,agent

Writes a JSON report to scripts/ci-reports/<timestamp>.json so each run is evidence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
NPM = shutil.which("npm") or "npm"
NPX = shutil.which("npx") or "npx"

SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai/anthropic key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{32,}\b")),
    ("assigned secret", re.compile(r"""(?i)[a-z0-9_]*(password|passwd|secret|token|api[_-]?key)["']?\s*[:=]\s*["'][^"'\s$]{12,}["']""")),
]
SECRET_ALLOW = re.compile(r"ci-only-|e2e-secret-|0123456789abcdef0123456789abcdef|DemoPassword123|example|placeholder|changeme-in-dev|your-|<[^>]+>", re.I)
SECRET_SKIP = re.compile(r"(^|/)(tests?|e2e)/|\.md$|\.lock$|package-lock\.json$|\.pyz$|\.png$|\.jpg$|\.pdf$|\.gitleaks\.toml$")


def secret_scan() -> tuple[bool, str]:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for name in files:
        if SECRET_SKIP.search(name):
            continue
        path = ROOT / name
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line) and not SECRET_ALLOW.search(line):
                    hits.append(f"{name}:{lineno}: {label}")
    return not hits, "\n".join(hits) or f"{len(files)} tracked files scanned, no secrets found"


def run(argv, cwd, env=None, timeout=1800) -> tuple[bool, str]:
    result = subprocess.run(argv, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True,
                            timeout=timeout, shell=sys.platform.startswith("win") and argv[0] in (NPM, NPX))
    tail = (result.stdout + result.stderr).strip().splitlines()[-6:]
    return result.returncode == 0, "\n".join(tail)


def migration_check() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        env = {"DATABASE_URL": f"sqlite:///{pathlib.Path(tmp, 'm.db').as_posix()}"}
        api = ROOT / "services" / "api"
        for argv in ([PY, "-m", "alembic", "upgrade", "head"], [PY, "-m", "alembic", "check"],
                     [PY, "-m", "alembic", "downgrade", "-1"], [PY, "-m", "alembic", "upgrade", "head"]):
            ok, out = run(argv, api, env)
            if not ok:
                return False, out
    return True, "upgrade, check, downgrade and re-upgrade passed"


GATES = {
    "secrets": secret_scan,
    "migrations": migration_check,
    "api": lambda: run([PY, "-m", "pytest", "-q", "-p", "no:warnings", "--cov=app", "--cov-fail-under=70"], ROOT / "services" / "api"),
    "proof": lambda: run([PY, "-m", "pytest", "-q", "-p", "no:warnings"], ROOT / "services" / "proof"),
    "mcp": lambda: run([PY, "-m", "pytest", "packages/mcp/tests", "-q", "-p", "no:warnings"], ROOT),
    "agent": lambda: run([PY, "-m", "pytest", "apps/agent/tests", "-q", "-p", "no:warnings", "-p", "no:cacheprovider"], ROOT),
    "agent-build": lambda: run([PY, "apps/agent/build.py", "--check"], ROOT),
    "web-build": lambda: run([NPM, "run", "build", "--workspace", "@proofos/web"], ROOT),
    "web-unit": lambda: run([NPM, "test", "--workspace", "@proofos/web"], ROOT),
    "pip-audit": lambda: run([PY, "-m", "pip_audit", "-r", "services/api/requirements.txt", "-r", "apps/agent/requirements.txt",
                              "-r", "services/proof/requirements.txt", "-r", "packages/mcp/requirements.txt"], ROOT),
    "npm-audit": lambda: run([NPM, "audit", "--omit=dev"], ROOT),
    "e2e": lambda: run([NPX, "playwright", "test"], ROOT / "apps" / "web", timeout=3600),
}
DEFAULT = [g for g in GATES if g != "e2e"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2e", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    gates = args.only.split(",") if args.only else DEFAULT + (["e2e"] if args.e2e else [])
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    report = {"commit": commit, "dirty_tree": dirty, "started": dt.datetime.now(dt.timezone.utc).isoformat(), "gates": {}}
    failed = []
    for name in gates:
        start = time.monotonic()
        try:
            ok, detail = GATES[name]()
        except Exception as exc:  # noqa: BLE001 - a crashed gate is a failed gate
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        seconds = round(time.monotonic() - start, 1)
        report["gates"][name] = {"passed": ok, "seconds": seconds, "detail": detail[-2000:]}
        print(f"{'PASS' if ok else 'FAIL'}  {name:12} {seconds:7.1f}s  {detail.splitlines()[-1] if detail else ''}"[:160])
        if not ok:
            failed.append(name)
    report["passed"] = not failed
    out = ROOT / "scripts" / "ci-reports" / f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{commit}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{'ALL GATES PASSED' if not failed else 'FAILED: ' + ', '.join(failed)}  ->  {out.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
