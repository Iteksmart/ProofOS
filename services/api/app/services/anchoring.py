"""Anchor the proof-chain head with RFC 3161 timestamps from an independent authority.

An anchor proves the ledger already contained a given head at the authority's
signed time, so a later rewrite of history is detectable without trusting
ProofOS's own signing key.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os

import httpx
from asn1crypto import cms, tsp
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
from sqlalchemy.orm import Session

from app.core.proof import canonical
from app.models.models import ProofAnchor, ProofRecord

# FreeTSA root CA (valid to 2041). Override with PROOF_TSA_TRUSTED_ROOTS.
FREETSA_ROOT_SHA256 = "a6379e7cecc05faa3cbf076013d745e327bbbaa38c0b9af22469d4701d18aabc"
_HASHES = {"sha1": hashes.SHA1, "sha256": hashes.SHA256, "sha384": hashes.SHA384, "sha512": hashes.SHA512}


def tsa_urls() -> list[str]:
    return [u.strip() for u in os.getenv("PROOF_TSA_URLS", "https://freetsa.org/tsr").split(",") if u.strip()]


def trusted_roots() -> set[str]:
    return {f.strip().lower() for f in os.getenv("PROOF_TSA_TRUSTED_ROOTS", FREETSA_ROOT_SHA256).split(",") if f.strip()}


def chain_head(db: Session) -> dict | None:
    last = db.query(ProofRecord).order_by(ProofRecord.created_at.desc(), ProofRecord.id.desc()).first()
    if not last:
        return None
    return {"chain_head": last.payload_digest, "last_record_id": last.id, "record_count": db.query(ProofRecord).count()}


def imprint_for(head: dict) -> bytes:
    return hashlib.sha256(canonical(head)).digest()


def request_token(url: str, imprint: bytes, transport: httpx.BaseTransport | None = None) -> bytes:
    nonce = int.from_bytes(os.urandom(8), "big")
    req = tsp.TimeStampReq({"version": 1, "message_imprint": {"hash_algorithm": {"algorithm": "sha256"}, "hashed_message": imprint},
        "nonce": nonce, "cert_req": True})
    with httpx.Client(timeout=20, transport=transport) as client:
        r = client.post(url, content=req.dump(), headers={"Content-Type": "application/timestamp-query"})
    r.raise_for_status()
    resp = tsp.TimeStampResp.load(r.content)
    if resp["status"]["status"].native not in ("granted", "granted_with_mods"):
        raise RuntimeError(f"timestamp authority refused the request: {resp['status']['status'].native}")
    token = resp["time_stamp_token"]
    tst = token["content"]["encap_content_info"]["content"].parsed
    if tst["nonce"].native != nonce:
        raise RuntimeError("timestamp response nonce does not match the request")
    return token.dump()


def _verify_signature(public_key, signature: bytes, data: bytes, hash_name: str) -> None:
    algorithm = _HASHES[hash_name]()
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(signature, data, ec.ECDSA(algorithm))
    elif isinstance(public_key, rsa.RSAPublicKey):
        public_key.verify(signature, data, padding.PKCS1v15(), algorithm)
    else:
        raise InvalidSignature("unsupported key type")


def verify_token(token_der: bytes, expected_imprint: bytes, roots: set[str] | None = None) -> dict:
    """Check the imprint, the authority's signature, its timestamping certificate and the pinned root."""
    roots = roots or trusted_roots()
    checks = {"imprint_matches": False, "signature_valid": False, "tsa_certificate_valid": False, "root_trusted": False}
    detail: dict = {}
    try:
        token = cms.ContentInfo.load(token_der)
        sd = token["content"]
        tst_der = sd["encap_content_info"]["content"].contents
        tst = tsp.TSTInfo.load(tst_der)
        imprint = tst["message_imprint"]
        checks["imprint_matches"] = imprint["hash_algorithm"]["algorithm"].native == "sha256" and imprint["hashed_message"].native == expected_imprint
        gen_time = tst["gen_time"].native
        detail["gen_time"] = gen_time.isoformat()
        certs = [x509.load_der_x509_certificate(c.chosen.dump()) for c in sd["certificates"] if c.name == "certificate"]
        signer = sd["signer_infos"][0]
        sid = signer["sid"].chosen
        tsa_cert = next(c for c in certs if c.serial_number == sid["serial_number"].native)
        detail["tsa_subject"] = tsa_cert.subject.rfc4514_string()
        hash_name = signer["digest_algorithm"]["algorithm"].native
        signed_attrs = signer["signed_attrs"]
        message_digest = next(a["values"][0].native for a in signed_attrs if a["type"].native == "message_digest")
        digest = hashes.Hash(_HASHES[hash_name]())
        digest.update(tst_der)
        attrs_der = b"\x31" + signed_attrs.dump()[1:]  # signature covers the attributes as a SET OF
        _verify_signature(tsa_cert.public_key(), signer["signature"].native, attrs_der, hash_name)
        checks["signature_valid"] = message_digest == digest.finalize()
        eku = tsa_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        in_validity = tsa_cert.not_valid_before_utc <= gen_time <= tsa_cert.not_valid_after_utc
        root = None
        for candidate in certs:
            if candidate is tsa_cert:
                continue
            try:
                tsa_cert.verify_directly_issued_by(candidate)
                root = candidate
                break
            except (ValueError, TypeError, InvalidSignature):
                continue
        checks["tsa_certificate_valid"] = ExtendedKeyUsageOID.TIME_STAMPING in eku and in_validity and root is not None
        if root is not None:
            fingerprint = root.fingerprint(hashes.SHA256()).hex()
            detail["root_sha256"] = fingerprint
            checks["root_trusted"] = fingerprint in roots
    except (StopIteration, ValueError, TypeError, KeyError, InvalidSignature, x509.ExtensionNotFound) as exc:
        detail["error"] = type(exc).__name__
    return {"verified": all(checks.values()), "checks": checks, **detail}


def anchor_now(db: Session, transport: httpx.BaseTransport | None = None, force: bool = False) -> ProofAnchor | None:
    """Timestamp the current head unless it is already anchored. Tries each authority in turn."""
    head = chain_head(db)
    if not head:
        return None
    latest = db.query(ProofAnchor).order_by(ProofAnchor.id.desc()).first()
    if latest and latest.chain_head == head["chain_head"] and not force:
        return latest
    imprint = imprint_for(head)
    errors = []
    for url in tsa_urls():
        try:
            token = request_token(url, imprint, transport)
        except Exception as exc:  # noqa: BLE001 - try the next authority
            errors.append(f"{url}: {type(exc).__name__}")
            continue
        check = verify_token(token, imprint)
        if not check["checks"]["imprint_matches"] or not check["checks"]["signature_valid"]:
            errors.append(f"{url}: token failed verification")
            continue
        anchor = ProofAnchor(**head, imprint=imprint.hex(), tsa_url=url, token=base64.b64encode(token).decode(),
            gen_time=dt.datetime.fromisoformat(check["gen_time"]))
        db.add(anchor)
        db.commit()
        db.refresh(anchor)
        return anchor
    raise RuntimeError("no timestamp authority produced a valid token: " + "; ".join(errors))


def verify_anchor(db: Session, anchor: ProofAnchor) -> dict:
    """Re-check the token, and that the anchored head is still in the ledger unaltered."""
    head = {"chain_head": anchor.chain_head, "last_record_id": anchor.last_record_id, "record_count": anchor.record_count}
    result = verify_token(base64.b64decode(anchor.token), imprint_for(head))
    record = db.get(ProofRecord, anchor.last_record_id)
    result["checks"]["head_still_in_ledger"] = bool(record and record.payload_digest == anchor.chain_head)
    result["verified"] = all(result["checks"].values())
    return result
