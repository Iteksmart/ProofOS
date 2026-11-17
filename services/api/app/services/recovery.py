"""Recovery requires fresh, signed, consecutive probe observations after execution."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from app.core.proof import canonical, decode_canonical, verify
from app.models.models import ProofRecord, RecoveryObservation, RecoveryPolicy, Script, ScriptRun
from app.services.privileged import utc


def policy_body(policy):
    return {"run_id": policy.run_id, "kind": policy.kind, "target": policy.target, "expected_status": policy.expected_status,
        "max_latency_ms": policy.max_latency_ms, "samples_required": policy.samples_required}


def fingerprint(policy):
    return hashlib.sha256(canonical(policy_body(policy))).hexdigest()


def evaluate(db, run):
    policy = db.query(RecoveryPolicy).filter(RecoveryPolicy.run_id == run.id, RecoveryPolicy.org_id == run.org_id).first()
    if not policy:
        return {"state": "unconfigured", "verified": False, "observations": []}
    observations = db.query(RecoveryObservation).filter(RecoveryObservation.policy_id == policy.id,
        RecoveryObservation.org_id == run.org_id).order_by(RecoveryObservation.created_at.desc(), RecoveryObservation.id.desc()).limit(policy.samples_required).all()
    results = []
    for observation in observations:
        proof = db.get(ProofRecord, observation.proof_id)
        body = decode_canonical(proof) if proof else None
        stored = json.loads(observation.payload)
        intact = bool(proof and proof.org_id == run.org_id and verify(proof)["verified"] and body and
            body.get("payload", {}).get("observation") == stored and stored.get("policy_sha256") == fingerprint(policy)
            and stored.get("run_id") == run.id)
        results.append({**stored, "intact": intact, "proof_id": observation.proof_id})
    state = "pending"
    execution_ok = False
    if run.completed_at is not None and run.exit_code == 0:
        script = db.get(Script, run.script_id)
        command_hash = hashlib.sha256((script.body if script else "").encode()).hexdigest()
        output_hash = hashlib.sha256(run.output.encode()).hexdigest()
        for proof in db.query(ProofRecord).filter(ProofRecord.org_id == run.org_id, ProofRecord.what == "script.completed").yield_per(200):
            payload = (decode_canonical(proof) or {}).get("payload", {})
            if payload.get("run_id") == run.id and payload.get("command_sha256") == command_hash and payload.get("output_sha256") == output_hash and payload.get("exit_code") == 0 and verify(proof)["verified"]:
                execution_ok = True
    if run.completed_at is None:
        state = "awaiting_execution"
    elif run.exit_code != 0 or not execution_ok:
        state = "execution_unverified"
    elif results and any(not r["intact"] for r in results):
        state = "evidence_invalid"
    elif results and (datetime.now(timezone.utc) - datetime.fromisoformat(results[0]["observed_at"])) > timedelta(minutes=5):
        state = "stale"
    elif results and not results[0]["passed"]:
        state = "failed"
    elif len(results) == policy.samples_required and all(r["passed"] for r in results):
        times = [datetime.fromisoformat(r["observed_at"]) for r in results]
        if min(times) >= utc(run.completed_at) and all((times[i] - times[i+1]).total_seconds() >= 1 for i in range(len(times)-1)):
            state = "healthy"
    return {"state": state, "verified": state == "healthy", "policy": policy_body(policy), "observations": results,
        "scope": "Configured HTTP/TCP probe only; does not assert whole-system recovery or endpoint integrity."}
