"""Customers (client companies), their contacts, contracts and assigned endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, get_current_user
from app.models.models import Contact, Contract, Customer, Device, Invoice, PatchPolicy, Ticket

router = APIRouter()


def _writer(user) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="admin/manager only")


def _load(db: Session, user, customer_id: int) -> Customer:
    row = db.query(Customer).filter(Customer.id == customer_id, Customer.org_id == user.org_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="customer not found in organization")
    return row


def _contract_out(c: Contract | None) -> dict | None:
    if not c:
        return None
    return {"id": c.id, "kind": c.kind, "hourly_rate": c.hourly_rate, "monthly_fee": c.monthly_fee,
        "included_hours": c.included_hours, "per_device_fee": c.per_device_fee, "active": c.active}


def active_contract(db: Session, customer_id: int) -> Contract | None:
    return db.query(Contract).filter(Contract.customer_id == customer_id, Contract.active.is_(True)).order_by(Contract.id.desc()).first()


class CustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    domain: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=50)
    notes: str = Field(default="", max_length=5000)


@router.get("")
def list_customers(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(Customer).filter(Customer.org_id == user.org_id).order_by(Customer.name).all()
    devices = dict(db.query(Device.customer_id, func.count(Device.id)).filter(Device.org_id == user.org_id).group_by(Device.customer_id).all())
    offline = dict(db.query(Device.customer_id, func.count(Device.id)).filter(Device.org_id == user.org_id, Device.status != "online").group_by(Device.customer_id).all())
    tickets = dict(db.query(Ticket.customer_id, func.count(Ticket.id)).filter(Ticket.org_id == user.org_id,
        Ticket.status.notin_(["closed", "resolved", "cancelled"])).group_by(Ticket.customer_id).all())
    return [{"id": c.id, "name": c.name, "domain": c.domain, "phone": c.phone, "notes": c.notes,
        "devices": devices.get(c.id, 0), "devices_offline": offline.get(c.id, 0), "open_tickets": tickets.get(c.id, 0),
        "contract": _contract_out(active_contract(db, c.id))} for c in rows]


@router.post("", status_code=201)
def create_customer(payload: CustomerIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    name = payload.name.strip()
    if db.query(Customer).filter(Customer.org_id == user.org_id, func.lower(Customer.name) == name.lower()).first():
        raise HTTPException(status_code=409, detail="a customer with this name already exists")
    row = Customer(org_id=user.org_id, name=name, domain=payload.domain.strip(), phone=payload.phone.strip(), notes=payload.notes)
    db.add(row)
    db.flush()
    emit(db, "customer.created", {"customer_id": row.id, "name": name}, actor_of(user), {"org_id": user.org_id}, {"reason": "new customer"})
    return {"id": row.id, "name": row.name, "domain": row.domain, "phone": row.phone, "notes": row.notes}


@router.get("/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    c = _load(db, user, customer_id)
    devices = db.query(Device).filter(Device.org_id == user.org_id, Device.customer_id == c.id).order_by(Device.hostname).all()
    tickets = db.query(Ticket).filter(Ticket.org_id == user.org_id, Ticket.customer_id == c.id).order_by(Ticket.id.desc()).limit(50).all()
    contacts = db.query(Contact).filter(Contact.customer_id == c.id, Contact.org_id == user.org_id).order_by(Contact.name).all()
    return {"id": c.id, "name": c.name, "domain": c.domain, "phone": c.phone, "notes": c.notes,
        "contract": _contract_out(active_contract(db, c.id)),
        "contacts": [{"id": x.id, "name": x.name, "email": x.email, "phone": x.phone, "role": x.role} for x in contacts],
        "devices": [{"id": d.id, "hostname": d.hostname, "os": d.os, "status": d.status, "device_type": d.device_type} for d in devices],
        "tickets": [{"id": t.id, "title": t.title, "status": t.status, "priority": t.priority, "created_at": t.created_at} for t in tickets]}


@router.put("/{customer_id}")
def update_customer(customer_id: int, payload: CustomerIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    c = _load(db, user, customer_id)
    name = payload.name.strip()
    clash = db.query(Customer).filter(Customer.org_id == user.org_id, func.lower(Customer.name) == name.lower(), Customer.id != c.id).first()
    if clash:
        raise HTTPException(status_code=409, detail="a customer with this name already exists")
    c.name, c.domain, c.phone, c.notes = name, payload.domain.strip(), payload.phone.strip(), payload.notes
    emit(db, "customer.updated", {"customer_id": c.id, "name": name}, actor_of(user), {"org_id": user.org_id}, {"reason": "edit customer"})
    return {"id": c.id, "name": c.name, "domain": c.domain, "phone": c.phone, "notes": c.notes}


@router.delete("/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    c = _load(db, user, customer_id)
    if db.query(Invoice).filter(Invoice.customer_id == c.id).first():
        raise HTTPException(status_code=409, detail="customers with issued invoices cannot be deleted")
    db.query(Device).filter(Device.customer_id == c.id).update({Device.customer_id: None}, synchronize_session=False)
    db.query(Ticket).filter(Ticket.customer_id == c.id).update({Ticket.customer_id: None}, synchronize_session=False)
    db.query(PatchPolicy).filter(PatchPolicy.customer_id == c.id).update({PatchPolicy.customer_id: None}, synchronize_session=False)
    db.query(Contact).filter(Contact.customer_id == c.id).delete(synchronize_session=False)
    db.query(Contract).filter(Contract.customer_id == c.id).delete(synchronize_session=False)
    name = c.name
    db.delete(c)
    emit(db, "customer.deleted", {"customer_id": customer_id, "name": name}, actor_of(user), {"org_id": user.org_id}, {"reason": "remove customer"})
    return {"ok": True}


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str = Field(default="", max_length=50)
    role: str = Field(default="", max_length=100)


@router.post("/{customer_id}/contacts", status_code=201)
def add_contact(customer_id: int, payload: ContactIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    c = _load(db, user, customer_id)
    row = Contact(org_id=user.org_id, customer_id=c.id, name=payload.name.strip(), email=str(payload.email or ""), phone=payload.phone.strip(), role=payload.role.strip())
    db.add(row)
    db.flush()
    emit(db, "customer.contact.added", {"customer_id": c.id, "contact_id": row.id}, actor_of(user), {"org_id": user.org_id}, {"reason": "add contact"})
    return {"id": row.id, "name": row.name, "email": row.email, "phone": row.phone, "role": row.role}


@router.delete("/{customer_id}/contacts/{contact_id}")
def remove_contact(customer_id: int, contact_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    _load(db, user, customer_id)
    row = db.query(Contact).filter(Contact.id == contact_id, Contact.customer_id == customer_id, Contact.org_id == user.org_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="contact not found")
    db.delete(row)
    emit(db, "customer.contact.removed", {"customer_id": customer_id, "contact_id": contact_id}, actor_of(user), {"org_id": user.org_id}, {"reason": "remove contact"})
    return {"ok": True}


class ContractIn(BaseModel):
    kind: Literal["hourly", "retainer", "fixed"]
    hourly_rate: float = Field(default=0, ge=0, le=100000)
    monthly_fee: float = Field(default=0, ge=0, le=10000000)
    included_hours: float = Field(default=0, ge=0, le=10000)
    per_device_fee: float = Field(default=0, ge=0, le=100000)


@router.put("/{customer_id}/contract")
def set_contract(customer_id: int, payload: ContractIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    c = _load(db, user, customer_id)
    db.query(Contract).filter(Contract.customer_id == c.id, Contract.active.is_(True)).update({Contract.active: False}, synchronize_session=False)
    row = Contract(org_id=user.org_id, customer_id=c.id, active=True, **payload.model_dump())
    db.add(row)
    db.flush()
    emit(db, "customer.contract.set", {"customer_id": c.id, "contract_id": row.id, **payload.model_dump()}, actor_of(user), {"org_id": user.org_id}, {"reason": "set contract"})
    return _contract_out(row)


class AssignIn(BaseModel):
    device_ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/{customer_id}/devices")
def assign_devices(customer_id: int, payload: AssignIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _writer(user)
    c = _load(db, user, customer_id)
    ids = sorted(set(payload.device_ids))
    rows = db.query(Device).filter(Device.org_id == user.org_id, Device.id.in_(ids)).all()
    if len(rows) != len(ids):
        raise HTTPException(status_code=404, detail="one or more devices are not in this organization")
    for d in rows:
        d.customer_id = c.id
    emit(db, "customer.devices.assigned", {"customer_id": c.id, "device_ids": ids}, actor_of(user), {"org_id": user.org_id}, {"reason": "assign endpoints"})
    return {"assigned": len(rows)}
