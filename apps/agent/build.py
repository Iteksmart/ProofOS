"""Build proofos-agent.pyz reproducibly and publish it to the API's download folder.

  python build.py            # build dist/proofos-agent.pyz and copy it to the API
  python build.py --check    # fail if the published build differs from the source
  python build.py --binary   # also build a standalone executable with PyInstaller

The archive is byte-for-byte reproducible (sorted entries, fixed timestamps),
so anyone can rebuild it from source and compare the SHA-256 the server signs.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import pathlib
import shutil
import subprocess
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
PACKAGE = HERE / "proofos_agent"
DIST = HERE / "dist" / "proofos-agent.pyz"
PUBLISHED = HERE.parent.parent / "services" / "api" / "app" / "agent_dist" / "proofos-agent.pyz"
SHEBANG = b"#!/usr/bin/env python3\n"
EPOCH = (2026, 1, 1, 0, 0, 0)


def build() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        files = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
        entries = [("__main__.py", b"from proofos_agent.cli import main\nmain()\n")]
        entries += [(p.relative_to(HERE).as_posix(), p.read_bytes().replace(b"\r\n", b"\n")) for p in files]
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return SHEBANG + buffer.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--binary", action="store_true")
    args = ap.parse_args()
    data = build()
    digest = hashlib.sha256(data).hexdigest()
    if args.check:
        published = PUBLISHED.read_bytes() if PUBLISHED.exists() else b""
        if published != data:
            raise SystemExit(f"published agent is stale; run python apps/agent/build.py (source sha256 {digest})")
        print(f"published agent matches source ({digest})")
        return
    for target in (DIST, PUBLISHED):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    print(f"built {DIST} and {PUBLISHED}\nsha256 {digest}  size {len(data)}")
    if args.binary:
        if not shutil.which("pyinstaller"):
            raise SystemExit("pip install pyinstaller to build a standalone executable")
        subprocess.run(["pyinstaller", "--onefile", "--name", "proofos-agent", "--distpath", str(HERE / "dist"),
                        "--paths", str(HERE), str(PACKAGE / "__main__.py")], check=True)


if __name__ == "__main__":
    sys.exit(main())
