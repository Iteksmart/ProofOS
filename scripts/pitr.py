"""Point-in-time recovery for ProofOS Postgres: base backups, WAL shipping, and a replay drill.

  python scripts/pitr.py basebackup [--encrypt-key K --rclone-remote R]   physical base backup
  python scripts/pitr.py ship --encrypt-key K --rclone-remote R            ship new WAL segments offsite
  python scripts/pitr.py drill                                             prove replay past the base backup

Postgres archives every completed WAL segment into backups/wal-archive (see infra/docker-compose.yml).
`ship` gzips and encrypts each new segment and uploads it, then prunes local segments that are both
shipped and older than the oldest local base backup. `drill` restores the newest base backup into an
isolated throwaway container, replays the archived WAL, and checks that a marker written *after*
the base backup is present and that the proof ledger still verifies end to end.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKUPS = ROOT / "backups"
WAL_DIR = BACKUPS / "wal-archive"
BASE_DIR = BACKUPS / "base"
SHIPPED = BACKUPS / "wal-shipped.json"
CONTAINER = "infra-postgres-1"
IMAGE = "postgres:15-alpine"
WAL_NAME = re.compile(r"^[0-9A-F]{24}(\.partial|\.[0-9A-F]{8}\.backup)?$|^[0-9A-F]{8}\.history$")


def sh(argv, **kw):
    return subprocess.run(argv, check=True, capture_output=True, **kw)


def psql(sql: str, db: str = "proofos", container: str = CONTAINER) -> str:
    return sh(["docker", "exec", container, "psql", "-U", "proofos", "-d", db, "-Atc", sql], text=True).stdout.strip()


def fernet(key_file: str):
    from cryptography.fernet import Fernet

    return Fernet(pathlib.Path(key_file).read_bytes().strip())


def rclone() -> str:
    return shutil.which("rclone") or str(pathlib.Path.home() / "AppData/Local/Microsoft/WinGet/Links/rclone.exe")


def upload(path: pathlib.Path, remote: str) -> None:
    r = subprocess.run([rclone(), "copyto", str(path), f"{remote.rstrip('/')}/{path.name}", "--no-check-dest", "--retries", "5"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"upload of {path.name} failed: {r.stderr.strip()[-400:]}")


# --------------------------------------------------------------------------- base backup

def basebackup(args) -> int:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = BASE_DIR / stamp
    target.mkdir(parents=True)
    tar_gz = target / "base.tar.gz"
    proc = subprocess.Popen(["docker", "exec", CONTAINER, "pg_basebackup", "-U", "proofos", "-D", "-", "-Ft", "-X", "none",
                             "--checkpoint=fast", "-l", f"proofos-{stamp}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with gzip.open(tar_gz, "wb", compresslevel=6) as out:
        shutil.copyfileobj(proc.stdout, out, 1 << 20)
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        shutil.rmtree(target)
        raise SystemExit(f"pg_basebackup failed: {err[-400:]}")
    # The backup history file Postgres archives names the first WAL segment this backup needs.
    time.sleep(2)
    psql("select pg_switch_wal()")
    time.sleep(3)
    history = sorted(WAL_DIR.glob("*.backup"), key=lambda p: p.stat().st_mtime)
    label = history[-1].read_text(errors="replace") if history else ""
    start_wal = re.search(r"START WAL LOCATION: \S+ \(file ([0-9A-F]{24})\)", label)
    manifest = {"format": "proofos-basebackup/1", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "start_wal": start_wal.group(1) if start_wal else None, "label": f"proofos-{stamp}",
                "sha256": hashlib.sha256(tar_gz.read_bytes()).hexdigest(), "bytes": tar_gz.stat().st_size,
                "server_version": psql("show server_version")}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"base backup {stamp}: {manifest['bytes'] / 1e6:.1f} MB, starts at WAL {manifest['start_wal']}")
    if args.encrypt_key and args.rclone_remote:
        sealed = target / f"{stamp}.base.tar.gz.enc"
        sealed.write_bytes(fernet(args.encrypt_key).encrypt(tar_gz.read_bytes()))
        upload(sealed, f"{args.rclone_remote.rstrip('/')}/base")
        meta = target / f"{stamp}.manifest.json"
        shutil.copy2(target / "manifest.json", meta)
        upload(meta, f"{args.rclone_remote.rstrip('/')}/base")
        sealed.unlink()
        meta.unlink()
        print(f"  uploaded to {args.rclone_remote.rstrip('/')}/base/{stamp}.base.tar.gz.enc")
    for old in sorted(p for p in BASE_DIR.iterdir() if p.is_dir())[:-args.keep_local]:
        shutil.rmtree(old)
        print(f"  pruned local base backup {old.name}")
    return 0


# --------------------------------------------------------------------------- WAL shipping

def ship(args) -> int:
    shipped = set(json.loads(SHIPPED.read_text())) if SHIPPED.exists() else set()
    f = fernet(args.encrypt_key)
    remote = f"{args.rclone_remote.rstrip('/')}/wal"
    new = 0
    with tempfile.TemporaryDirectory() as tmp:
        for seg in sorted(p for p in WAL_DIR.iterdir() if WAL_NAME.match(p.name)):
            if seg.name in shipped:
                continue
            out = pathlib.Path(tmp) / f"{seg.name}.gz.enc"
            out.write_bytes(f.encrypt(gzip.compress(seg.read_bytes(), compresslevel=6)))
            upload(out, remote)
            out.unlink()
            shipped.add(seg.name)
            SHIPPED.write_text(json.dumps(sorted(shipped)), encoding="utf-8")
            new += 1
    # Prune: keep everything the oldest local base backup could still need.
    starts = [json.loads((d / "manifest.json").read_text()).get("start_wal") for d in BASE_DIR.iterdir()
              if (d / "manifest.json").exists()] if BASE_DIR.exists() else []
    starts = [s for s in starts if s]
    pruned = 0
    if starts:
        floor = min(starts)
        for seg in WAL_DIR.iterdir():
            if re.match(r"^[0-9A-F]{24}$", seg.name) and seg.name in shipped and seg.name < floor:
                seg.unlink()
                pruned += 1
    print(f"shipped {new} new WAL file(s) to {remote}; pruned {pruned} local; {len(shipped)} shipped in total")
    return 0


# --------------------------------------------------------------------------- drill

def _verify_ledger(rows: list[dict], public_key_hex: str) -> tuple[int, list[str]]:
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
    problems, previous = [], None
    for r in rows:
        canonical = base64.urlsafe_b64decode(r["canonical_bytes"])
        if hashlib.sha256(canonical).hexdigest() != r["payload_digest"]:
            problems.append(f"hash {r['id']}")
        try:
            key.verify(base64.urlsafe_b64decode(r["signature"]), canonical + r["prev_hash"].encode())
        except Exception:  # noqa: BLE001
            problems.append(f"signature {r['id']}")
        if previous is not None and r["prev_hash"] != previous:
            problems.append(f"chain {r['id']}")
        previous = r["payload_digest"]
    return len(rows), problems


def drill(args) -> int:
    import httpx

    bases = sorted(d for d in BASE_DIR.iterdir() if (d / "manifest.json").exists()) if BASE_DIR.exists() else []
    if not bases:
        raise SystemExit("no local base backup; run: python scripts/pitr.py basebackup")
    base = bases[-1]
    report: dict = {"base_backup": base.name, "started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "checks": {}}

    # Write a marker AFTER the base backup in a separate drill database, so replay is what brings it back.
    if not psql("select 1 from pg_database where datname='pitr_drill'", db="postgres"):
        psql("create database pitr_drill", db="postgres")
    psql("create table if not exists markers (id text primary key, written_at timestamptz default now())", db="pitr_drill")
    marker = secrets.token_hex(8)
    psql(f"insert into markers (id) values ('{marker}')", db="pitr_drill")
    live_head = psql("select payload_digest from proof_records order by created_at desc, id desc limit 1")
    live_count = int(psql("select count(*) from proof_records"))
    psql("select pg_switch_wal()")
    time.sleep(4)  # let the archiver copy the segment holding the marker

    public_key = httpx.get(args.api.rstrip("/") + "/v1/agent/server-key", timeout=15).json()["public_key"]
    vol, name = f"pitr-drill-{marker}", f"pitr-drill-{marker}"
    wal_mount = f"{WAL_DIR.resolve()}:/walsrc:ro"
    base_mount = f"{base.resolve()}:/base:ro"
    t0 = time.monotonic()
    try:
        sh(["docker", "volume", "create", vol])
        prep = ("set -e; tar xzf /base/base.tar.gz -C /data; touch /data/recovery.signal; "
                "printf \"restore_command = 'cp /walsrc/%%f %%p'\\nrecovery_target_timeline = 'latest'\\n"
                "archive_mode = off\\n\" >> /data/postgresql.auto.conf; chown -R postgres:postgres /data; chmod 700 /data")
        sh(["docker", "run", "--rm", "--network", "none", "-v", f"{vol}:/data", "-v", base_mount, IMAGE, "sh", "-c", prep])
        sh(["docker", "run", "-d", "--name", name, "--network", "none", "-v", f"{vol}:/var/lib/postgresql/data",
            "-v", wal_mount, IMAGE])
        ready = False
        for _ in range(180):
            r = subprocess.run(["docker", "exec", name, "psql", "-U", "proofos", "-d", "proofos", "-Atc",
                                "select pg_is_in_recovery()"], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip() == "f":
                ready = True
                break
            time.sleep(1)
        report["checks"]["recovery_completed"] = {"ok": ready}
        if ready:
            found = psql(f"select count(*) from markers where id='{marker}'", db="pitr_drill", container=name)
            report["checks"]["marker_after_base_backup_replayed"] = {"ok": found == "1", "marker": marker}
            out = psql("select json_agg(t) from (select id, canonical_bytes, payload_digest, prev_hash, signature "
                       "from proof_records order by created_at, id) t", container=name)
            rows = json.loads(out or "[]")
            count, problems = _verify_ledger(rows, public_key)
            report["checks"]["ledger_verifies"] = {"ok": not problems, "records": count, "problems": problems[:10]}
            head = rows[-1]["payload_digest"] if rows else None
            report["checks"]["matches_live_at_drill_time"] = {"ok": head == live_head and count == live_count,
                                                             "restored": count, "live": live_count}
    finally:
        logs = subprocess.run(["docker", "logs", "--tail", "5", name], capture_output=True, text=True)
        report["container_log_tail"] = (logs.stdout + logs.stderr).strip()[-600:]
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", "-f", vol], capture_output=True)
        psql(f"delete from markers where id='{marker}'", db="pitr_drill")

    report["measured"] = {"restore_and_replay_seconds": round(time.monotonic() - t0, 1)}
    report["passed"] = bool(report["checks"]) and all(c.get("ok") for c in report["checks"].values())
    (base / "pitr-drill-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for label, check in report["checks"].items():
        print(f"{'PASS' if check.get('ok') else 'FAIL'}  {label}")
    print(f"\nPITR drill {'PASSED' if report['passed'] else 'FAILED'} in {report['measured']['restore_and_replay_seconds']}s "
          f"(base backup {base.name}). Report: {base / 'pitr-drill-report.json'}")
    return 0 if report["passed"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("basebackup")
    b.add_argument("--encrypt-key", default="")
    b.add_argument("--rclone-remote", default="")
    b.add_argument("--keep-local", type=int, default=3)
    s = sub.add_parser("ship")
    s.add_argument("--encrypt-key", required=True)
    s.add_argument("--rclone-remote", required=True)
    d = sub.add_parser("drill")
    d.add_argument("--api", default="http://localhost:8000")
    args = ap.parse_args()
    WAL_DIR.mkdir(parents=True, exist_ok=True)
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    return {"basebackup": basebackup, "ship": ship, "drill": drill}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
