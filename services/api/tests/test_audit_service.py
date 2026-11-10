from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from app.models.models import ProofRecord, Ticket
from app.services.audit import run_audit


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return self._rows


class _Db:
    def __init__(self, tickets=(), proofs=()):
        self._rows = {Ticket: list(tickets), ProofRecord: list(proofs)}

    def query(self, model):
        return _Query(self._rows.get(model, []))


def _proof(n, org_id, prev_hash):
    return SimpleNamespace(id=f"r{n}", org_id=org_id, payload_digest=f"d{n}", prev_hash=prev_hash, created_at=dt.datetime(2026, 1, 1, 0, 0, n))


def _chain_findings(proofs, org_id):
    findings, _score = run_audit(_Db(proofs=proofs), org_id=org_id, kind="compliance")
    return [f for f in findings if "hash-chain" in f["title"]]


def test_interleaved_tenants_do_not_report_a_broken_chain():
    # One global chain written alternately by two orgs: intact, but neither
    # org's own records link directly to each other.
    proofs = [_proof(1, 1, "0" * 64), _proof(2, 2, "d1"), _proof(3, 1, "d2"), _proof(4, 2, "d3")]

    assert _chain_findings(proofs, org_id=1) == []
    assert _chain_findings(proofs, org_id=2) == []


def test_tampered_link_is_reported_only_to_the_owning_org():
    proofs = [_proof(1, 1, "0" * 64), _proof(2, 2, "d1"), _proof(3, 1, "tampered"), _proof(4, 2, "d3")]

    broken = _chain_findings(proofs, org_id=1)
    assert len(broken) == 1 and "r3" in broken[0]["detail"]
    assert _chain_findings(proofs, org_id=2) == []


@pytest.mark.parametrize("tzinfo", [None, dt.timezone.utc], ids=["naive-sqlite", "aware-postgres"])
def test_sla_breach_detection_handles_naive_and_aware_due_dates(tzinfo):
    past = dt.datetime(2020, 1, 1, tzinfo=tzinfo)
    future = dt.datetime(2999, 1, 1, tzinfo=tzinfo)
    tickets = [
        SimpleNamespace(id=1, title="late", due_at=past, status="open"),
        SimpleNamespace(id=2, title="on time", due_at=future, status="open"),
        SimpleNamespace(id=3, title="closed late", due_at=past, status="closed"),
    ]

    findings, _score = run_audit(_Db(tickets), org_id=1, kind="compliance")

    breached = [f for f in findings if "breached SLA" in f["title"]]
    assert len(breached) == 1
    assert breached[0]["title"] == "1 ticket(s) breached SLA"
    assert "#1 late" in breached[0]["detail"]
