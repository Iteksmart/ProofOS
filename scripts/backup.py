"""Back up ProofOS: database dump, independent ledger export, signing public key, SHA-256 manifest.

  python scripts/backup.py                         # backups/<timestamp>/ from the local Docker stack
  python scripts/backup.py --encrypt-key KEYFILE   # also write an encrypted .tar.enc for offsite copy
  python scripts/backup.py --copy-to E:\\offsite    # copy the (encrypted) archive to another location
  python scripts/backup.py --new-key KEYFILE       # create an encryption key (store it apart from backups)

The ledger export lets the proof chain be verified from the backup alone, without
restoring the database or trusting the server that produced it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tarfile

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
TABLES = ["orgs", "users", "devices", "tickets", "script_runs", "proof_records", "proof_anchors", "customers", "invoices"]
LEDGER_SQL = ("copy (select row_to_json(p) from (select id, org_id, what, canonical_bytes, payload_digest, prev_hash, "
              "signature, signing_key_id, created_at from proof_records order by created_at, id) p) to stdout")


def sh(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, check=True, capture_output=True, **kw)


def container_env(container: str, name: str, default: str) -> str:
    try:
        return sh(["docker", "exec", container, "printenv", name], text=True).stdout.strip() or default
    except subprocess.CalledProcessError:
        return default


def psql(container: str, user: str, db: str, sql: str) -> str:
    return sh(["docker", "exec", container, "psql", "-U", user, "-d", db, "-At", "-c", sql], text=True).stdout


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="infra-postgres-1")
    ap.add_argument("--api", default="http://localhost:8000", help="used to record the ledger's signing public key")
    ap.add_argument("--out", default=str(ROOT / "backups"))
    ap.add_argument("--encrypt-key", default="", help="Fernet key file; writes <backup>.tar.enc")
    ap.add_argument("--copy-to", default="", help="directory for an offsite copy of the archive")
    ap.add_argument("--new-key", default="", help="create a new encryption key file and exit")
    args = ap.parse_args()

    from cryptography.fernet import Fernet

    if args.new_key:
        path = pathlib.Path(args.new_key)
        if path.exists():
            raise SystemExit(f"{path} already exists; refusing to overwrite a key")
        path.write_bytes(Fernet.generate_key())
        print(f"Wrote {path}. Store it separately from the backups; without it encrypted backups cannot be restored.")
        return 0

    started = dt.datetime.now(dt.timezone.utc)
    user = container_env(args.container, "POSTGRES_USER", "proofos")
    db = container_env(args.container, "POSTGRES_DB", "proofos")
    target = pathlib.Path(args.out) / started.strftime("%Y%m%dT%H%M%SZ")
    target.mkdir(parents=True)

    dump = target / "proofos.dump"
    with dump.open("wb") as handle:
        subprocess.run(["docker", "exec", args.container, "pg_dump", "-U", user, "-d", db, "-Fc", "--no-owner"],
                       stdout=handle, check=True)
    ledger = target / "ledger.jsonl"
    ledger.write_text(psql(args.container, user, db, LEDGER_SQL), encoding="utf-8")
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

    key = httpx.get(args.api.rstrip("/") + "/v1/agent/server-key", timeout=15).json()["public_key"]
    (target / "signing-public-key.txt").write_text(key + "\n", encoding="utf-8")

    counts = {}
    for table in TABLES:
        try:
            counts[table] = int(psql(args.container, user, db, f"select count(*) from {table}").strip())
        except subprocess.CalledProcessError:
            counts[table] = None
    manifest = {
        "format": "proofos-backup/1",
        "created_at": started.isoformat(),
        "source": {"container": args.container, "database": db,
                   "alembic_version": psql(args.container, user, db, "select version_num from alembic_version").strip()},
        "row_counts": counts,
        "ledger": {"records": len(records), "head_digest": records[-1]["payload_digest"] if records else None,
                   "signing_public_key": key},
        "files": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(target.iterdir())},
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Backup written to {target}")
    print(f"  database dump {manifest['files']['proofos.dump']['bytes'] / 1e6:.1f} MB, ledger {len(records)} records, "
          f"schema {manifest['source']['alembic_version']}")

    if args.encrypt_key:
        archive = target.with_suffix(".tar")
        with tarfile.open(archive, "w") as tar:
            tar.add(target, arcname=target.name)
        sealed = target.parent / (target.name + ".tar.enc")
        sealed.write_bytes(Fernet(pathlib.Path(args.encrypt_key).read_bytes().strip()).encrypt(archive.read_bytes()))
        archive.unlink()
        (target.parent / (sealed.name + ".sha256")).write_text(f"{sha256(sealed)}  {sealed.name}\n", encoding="utf-8")
        print(f"  encrypted archive {sealed.name} ({sealed.stat().st_size / 1e6:.1f} MB)")
        if args.copy_to:
            dest = pathlib.Path(args.copy_to)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sealed, dest / sealed.name)
            shutil.copy2(target.parent / (sealed.name + ".sha256"), dest)
            print(f"  copied to {dest}")
    elif args.copy_to:
        raise SystemExit("--copy-to requires --encrypt-key: never copy an unencrypted backup offsite")
    print(f"Verify with: python scripts/restore_check.py {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
