"""A local RFC 3161 timestamp authority for offline tests."""
from __future__ import annotations

import datetime as dt
import hashlib

import httpx
from asn1crypto import algos, cms, core, tsp
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


class LocalTsa:
    def __init__(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        self.root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.root = (x509.CertificateBuilder().subject_name(_name("Test Root")).issuer_name(_name("Test Root"))
            .public_key(self.root_key.public_key()).serial_number(1).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365)).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(self.root_key, hashes.SHA256()))
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cert = (x509.CertificateBuilder().subject_name(_name("Test TSA")).issuer_name(self.root.subject)
            .public_key(self.key.public_key()).serial_number(2).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
            .sign(self.root_key, hashes.SHA256()))
        self.root_sha256 = self.root.fingerprint(hashes.SHA256()).hex()
        self.requests = 0

    def respond(self, request_der: bytes) -> bytes:
        self.requests += 1
        req = tsp.TimeStampReq.load(request_der)
        tst = tsp.TSTInfo({"version": 1, "policy": "1.2.3.4", "message_imprint": req["message_imprint"],
            "serial_number": self.requests, "gen_time": dt.datetime.now(dt.timezone.utc).replace(microsecond=0), "nonce": req["nonce"]})
        tst_der = tst.dump()
        signed_attrs = cms.CMSAttributes([
            cms.CMSAttribute({"type": "content_type", "values": ["tst_info"]}),
            cms.CMSAttribute({"type": "message_digest", "values": [hashlib.sha256(tst_der).digest()]}),
        ])
        signature = self.key.sign(b"\x31" + signed_attrs.dump()[1:], ec.ECDSA(hashes.SHA256()))
        tsa_cert = asn1_x509.Certificate.load(self.cert.public_bytes(serialization.Encoding.DER))
        root_cert = asn1_x509.Certificate.load(self.root.public_bytes(serialization.Encoding.DER))
        signer = cms.SignerInfo({"version": "v1",
            "sid": cms.SignerIdentifier({"issuer_and_serial_number": cms.IssuerAndSerialNumber({"issuer": tsa_cert.issuer, "serial_number": tsa_cert.serial_number})}),
            "digest_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}), "signed_attrs": signed_attrs,
            "signature_algorithm": algos.SignedDigestAlgorithm({"algorithm": "sha256_ecdsa"}), "signature": signature})
        signed_data = cms.SignedData({"version": "v3", "digest_algorithms": [algos.DigestAlgorithm({"algorithm": "sha256"})],
            "encap_content_info": {"content_type": "tst_info", "content": core.ParsableOctetString(tst_der)},
            "certificates": [tsa_cert, root_cert], "signer_infos": [signer]})
        token = cms.ContentInfo({"content_type": "signed_data", "content": signed_data})
        return tsp.TimeStampResp({"status": {"status": "granted"}, "time_stamp_token": token}).dump()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(lambda request: httpx.Response(200, content=self.respond(request.content),
            headers={"Content-Type": "application/timestamp-reply"}))
