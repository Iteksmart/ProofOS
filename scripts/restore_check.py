"""Restore drill: restore a ProofOS backup into an isolated throwaway database and prove it is good.

  python scripts/restore_check.py backups/20261117T200000Z

Checks, all recorded in <backup>/restore-report.json:
  1. every file matches its manifest SHA-256
  2. the dump restores into a fresh Postgres container (never the live database)
  3. schema version and row counts match the manifest
  4. every ledger record re-hashes, its Ed25519 signature verifies against the public key
     captured at backup time, and the hash chain is unbroken (both in the export and in
     the restored database), with the same head as the manifest
Reports the measured restore time (RTO) and the age of the data (the loss window if
restored now). The throwaway container is always removed.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import pathlib
import secrets
import subprocess
import sys
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backup import LEDGER_SQL, TABLES, sha256  # noqa: E402

IMAGE = os.getenv("RESTORE_IMAGE", "postgres:15-alpine")  # match the production major version


def run(argv, **kw):
    return subprocess.run(argv, check=True, capture_output=True, text=True, **kw)


def verify_ledger(records: list[dict], public_key_hex: str) -> dict:
    key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
    bad_hash, bad_sig, breaks = [], [], []
    previous = None
    for rec in records:
        canonical = base64.urlsafe_b64decode(rec["canonical_bytes"])
        if hashlib.sha256(canonical).hexdigest() != rec["payload_digest"]:
            bad_hash.append(rec["id"])
        try:
            key.verify(base64.urlsafe_b64decode(rec["signature"]), canonical + rec["prev_hash"].encode())
        except (InvalidSignature, ValueError):
            bad_sig.append(rec["id"])
        if previous is not None and rec["prev_hash"] != previous:
            breaks.append(rec["id"])
        previous = rec["payload_digest"]
    return {"records": len(records), "hash_failures": bad_hash[:20], "signature_failures": bad_sig[:20],
            "chain_breaks": breaks[:20], "head_digest": previous,
            "ok": not bad_hash and not bad_sig and not breaks}


def unpack(archive: pathlib.Path, key_file: pathlib.Path) -> pathlib.Path:
    """Decrypt an offsite .tar.enc copy into a sibling folder and return it."""
    import io
    import tarfile

    from cryptography.fernet import Fernet

    data = Fernet(key_file.read_bytes().strip()).decrypt(archive.read_bytes())
    out = archive.parent / (archive.name.removesuffix(".tar.enc") + "-restored")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(out, filter="data")
    return next(out.iterdir())


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        raise SystemExit(__doc__)
    t0 = time.monotonic()
    folder = pathlib.Path(args[0])
    if folder.name.endswith(".tar.enc"):
        if len(args) != 3 or args[1] != "--key":
            raise SystemExit("usage: restore_check.py <backup>.tar.enc --key KEYFILE")
        folder = unpack(folder, pathlib.Path(args[2]))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    report: dict = {"backup": folder.name, "backup_created_at": manifest["created_at"],
                    "started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "checks": {}}

    mismatched = [name for name, meta in manifest["files"].items() if sha256(folder / name) != meta["sha256"]]
    report["checks"]["file_integrity"] = {"ok": not mismatched, "mismatched": mismatched}

    exported = [json.loads(line) for line in (folder / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    key = manifest["ledger"]["signing_public_key"]
    export_check = verify_ledger(exported, key)
    export_check["ok"] = export_check["ok"] and export_check["head_digest"] == manifest["ledger"]["head_digest"]
    report["checks"]["ledger_export"] = export_check

    name = f"proofos-restore-check-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    try:
        run(["docker", "run", "-d", "--rm", "--name", name, "--network", "none", "-e", "POSTGRES_USER=proofos",
             "-e", f"POSTGRES_PASSWORD={password}", "-e", "POSTGRES_DB=proofos", IMAGE])
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "proofos", "-d", "proofos"], capture_output=True).returncode == 0:
                break
            time.sleep(1)
        time.sleep(2)  # the image restarts once after initdb
        for _ in range(30):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "proofos", "-d", "proofos"], capture_output=True).returncode == 0:
                break
            time.sleep(1)
        run(["docker", "cp", str(folder / "proofos.dump"), f"{name}:/tmp/proofos.dump"])
        restore = subprocess.run(["docker", "exec", name, "pg_restore", "-U", "proofos", "-d", "proofos", "--no-owner",
                                  "--exit-on-error", "/tmp/proofos.dump"], capture_output=True, text=True)
        report["checks"]["database_restore"] = {"ok": restore.returncode == 0, "detail": restore.stderr[-500:]}

        def q(sql: str) -> str:
            return run(["docker", "exec", name, "psql", "-U", "proofos", "-d", "proofos", "-At", "-c", sql]).stdout

        version = q("select version_num from alembic_version").strip()
        counts = {}
        for table in TABLES:
            try:
                counts[table] = int(q(f"select count(*) from {table}").strip())
            except subprocess.CalledProcessError:
                counts[table] = None
        diffs = {t: {"expected": manifest["row_counts"].get(t), "restored": c} for t, c in counts.items() if c != manifest["row_counts"].get(t)}
        report["checks"]["schema_and_rows"] = {"ok": version == manifest["source"]["alembic_version"] and not diffs,
            "alembic_version": version, "row_count_differences": diffs}

        restored = [json.loads(line) for line in q(LEDGER_SQL).splitlines() if line.strip()]
        db_check = verify_ledger(restored, key)
        db_check["ok"] = db_check["ok"] and db_check["head_digest"] == manifest["ledger"]["head_digest"]
        report["checks"]["ledger_in_restored_db"] = db_check
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    rto = time.monotonic() - t0
    age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(manifest["created_at"])
    report["measured"] = {"restore_and_verify_seconds": round(rto, 1), "data_age_minutes": round(age.total_seconds() / 60, 1)}
    report["passed"] = all(c.get("ok") for c in report["checks"].values())
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    (folder / "restore-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for label, check in report["checks"].items():
        print(f"{'PASS' if check.get('ok') else 'FAIL'}  {label}")
    print(f"\nRestore drill {'PASSED' if report['passed'] else 'FAILED'}: restored and verified in {rto:.1f}s; "
          f"data age {report['measured']['data_age_minutes']} min. Report: {folder / 'restore-report.json'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
