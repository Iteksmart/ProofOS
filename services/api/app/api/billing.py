"""Monthly billing from contracts and billable ticket time; issued invoices are signed."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import canonical, decode_canonical, emit, verify
from app.core.security import actor_of, get_current_user
from app.models.models import Customer, Device, Invoice, ProofRecord, Ticket, TimeEntry
from app.api.customers import active_contract

router = APIRouter()
_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _reader(user) -> None:
    if user.role not in {"admin", "manager", "auditor"}:
        raise HTTPException(status_code=403, detail="billing is limited to admin, manager and auditor roles")


def _bounds(period: str) -> tuple[dt.datetime, dt.datetime]:
    if not _PERIOD.match(period):
        raise HTTPException(status_code=422, detail="period must be YYYY-MM")
    year, month = int(period[:4]), int(period[5:])
    start = dt.datetime(year, month, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=dt.timezone.utc)
    return start, end


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def _line(description: str, quantity: float, unit_price: float) -> dict:
    return {"description": description, "quantity": round(quantity, 2), "unit_price": _money(unit_price), "amount": _money(quantity * unit_price)}


def _billable_minutes(db: Session, org_id: int, start: dt.datetime, end: dt.datetime) -> dict[int | None, int]:
    rows = db.query(Ticket.customer_id, TimeEntry.minutes).join(Ticket, TimeEntry.ticket_id == Ticket.id).filter(
        TimeEntry.org_id == org_id, TimeEntry.billable.is_(True), TimeEntry.created_at >= start, TimeEntry.created_at < end).all()
    out: dict[int | None, int] = {}
    for customer_id, minutes in rows:
        out[customer_id] = out.get(customer_id, 0) + int(minutes or 0)
    return out


def compute(db: Session, org_id: int, customer: Customer, minutes: int) -> dict:
    contract = active_contract(db, customer.id)
    hours = minutes / 60
    device_count = db.query(Device).filter(Device.org_id == org_id, Device.customer_id == customer.id).count()
    lines: list[dict] = []
    note = ""
    if not contract:
        note = "No active contract: time is listed but not priced."
        if hours:
            lines.append(_line("Support hours (no contract)", hours, 0))
    elif contract.kind == "hourly":
        if hours:
            lines.append(_line("Support hours", hours, contract.hourly_rate))
    elif contract.kind == "retainer":
        lines.append(_line(f"Monthly retainer ({contract.included_hours:g} hours included)", 1, contract.monthly_fee))
        overage = max(0.0, hours - contract.included_hours)
        if overage:
            lines.append(_line("Hours beyond retainer", overage, contract.hourly_rate))
    else:
        lines.append(_line("Fixed monthly fee", 1, contract.monthly_fee))
    if contract and contract.per_device_fee and device_count:
        lines.append(_line("Managed endpoints", device_count, contract.per_device_fee))
    return {"customer_id": customer.id, "customer": customer.name, "contract": contract.kind if contract else None,
        "billable_hours": round(hours, 2), "devices": device_count, "lines": lines,
        "total": _money(sum(line["amount"] for line in lines)), "note": note}


@router.get("/preview")
def preview(period: str = Query(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _reader(user)
    start, end = _bounds(period)
    minutes = _billable_minutes(db, user.org_id, start, end)
    issued = {i.customer_id: i.id for i in db.query(Invoice).filter(Invoice.org_id == user.org_id, Invoice.period == period).all()}
    customers = db.query(Customer).filter(Customer.org_id == user.org_id).order_by(Customer.name).all()
    rows = [{**compute(db, user.org_id, c, minutes.get(c.id, 0)), "invoice_id": issued.get(c.id)} for c in customers]
    return {"period": period, "customers": rows, "total": _money(sum(r["total"] for r in rows)),
        "unassigned_billable_hours": round(minutes.get(None, 0) / 60, 2)}


class InvoiceIn(BaseModel):
    customer_id: int = Field(gt=0)
    period: str


def _lines_digest(lines: list[dict]) -> str:
    return hashlib.sha256(canonical({"lines": lines})).hexdigest()


def _invoice_out(db: Session, inv: Invoice, customer_name: str) -> dict:
    lines = json.loads(inv.lines or "[]")
    record = db.get(ProofRecord, inv.proof_id) if inv.proof_id else None
    payload = (decode_canonical(record) or {}).get("payload", {}) if record else {}
    signature_ok = bool(record and verify(record)["verified"])
    matches = signature_ok and payload.get("lines_sha256") == _lines_digest(lines) and payload.get("total") == inv.total
    return {"id": inv.id, "customer_id": inv.customer_id, "customer": customer_name, "period": inv.period, "lines": lines,
        "total": inv.total, "created_at": inv.created_at, "proof_id": inv.proof_id, "verified": matches,
        "verification": "Lines and total match the signed record." if matches else "Stored invoice does not match its signed record."}


@router.post("/invoices", status_code=201)
def issue_invoice(payload: InvoiceIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")
    start, end = _bounds(payload.period)
    if start > dt.datetime.now(dt.timezone.utc):
        raise HTTPException(status_code=422, detail="cannot invoice a future period")
    customer = db.query(Customer).filter(Customer.id == payload.customer_id, Customer.org_id == user.org_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="customer not found in organization")
    if db.query(Invoice).filter(Invoice.org_id == user.org_id, Invoice.customer_id == customer.id, Invoice.period == payload.period).first():
        raise HTTPException(status_code=409, detail="an invoice for this customer and period was already issued")
    result = compute(db, user.org_id, customer, _billable_minutes(db, user.org_id, start, end).get(customer.id, 0))
    if not result["lines"] or result["total"] <= 0:
        raise HTTPException(status_code=422, detail="nothing billable for this customer and period")
    inv = Invoice(org_id=user.org_id, customer_id=customer.id, period=payload.period, lines=json.dumps(result["lines"]), total=result["total"])
    db.add(inv)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="an invoice for this customer and period was already issued") from exc
    record = emit(db, "billing.invoice.issued", {"invoice_id": inv.id, "customer_id": customer.id, "period": payload.period,
        "total": inv.total, "lines_sha256": _lines_digest(result["lines"])}, actor_of(user), {"org_id": user.org_id}, {"reason": "issue invoice"})
    inv.proof_id = record.id
    db.commit()
    return _invoice_out(db, inv, customer.name)


@router.get("/invoices")
def list_invoices(db: Session = Depends(get_db), user=Depends(get_current_user)):
    _reader(user)
    names = {c.id: c.name for c in db.query(Customer).filter(Customer.org_id == user.org_id).all()}
    rows = db.query(Invoice).filter(Invoice.org_id == user.org_id).order_by(Invoice.period.desc(), Invoice.id.desc()).limit(500).all()
    return [_invoice_out(db, inv, names.get(inv.customer_id, "?")) for inv in rows]


def _load_invoice(db: Session, user, invoice_id: int) -> Invoice:
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.org_id == user.org_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="invoice not found in organization")
    return inv


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _reader(user)
    inv = _load_invoice(db, user, invoice_id)
    customer = db.get(Customer, inv.customer_id)
    return _invoice_out(db, inv, customer.name if customer else "?")


@router.get("/invoices/{invoice_id}/csv")
def invoice_csv(invoice_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _reader(user)
    data = get_invoice(invoice_id, db, user)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    safe = lambda v: "'" + v if isinstance(v, str) and v[:1] in "=+-@\t\r" else v  # noqa: E731 - spreadsheet formula guard
    writer.writerow(["Invoice", data["id"], "Customer", safe(data["customer"]), "Period", data["period"]])
    writer.writerow(["Description", "Quantity", "Unit price", "Amount"])
    for line in data["lines"]:
        writer.writerow([safe(line["description"]), line["quantity"], line["unit_price"], line["amount"]])
    writer.writerow(["Total", "", "", data["total"]])
    writer.writerow(["Signed proof", data["proof_id"], "Verified", data["verified"]])
    return Response(buffer.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="proofos-invoice-{data["id"]}-{data["period"]}.csv"'})
