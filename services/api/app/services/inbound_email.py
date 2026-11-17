"""Turn inbound email (Postmark, Mailgun, SendGrid-JSON or a generic shape) into tickets and replies."""
from __future__ import annotations

import datetime as dt
import re
from email.utils import parseaddr

from sqlalchemy.orm import Session

from app.models.models import Contact, Customer, IntegrationConnection, Ticket, TicketComment

_TICKET_REF = re.compile(r"\[(?:ticket\s*)?#(\d{1,9})\]", re.IGNORECASE)
_QUOTED = re.compile(r"\n(?:On .{0,200}wrote:|-{2,} ?Original Message ?-{2,}|From: .+\nSent: )", re.IGNORECASE)


def parse(data: dict) -> dict:
    """Normalise provider payloads to sender / subject / text / message_id."""
    full = data.get("FromFull") if isinstance(data.get("FromFull"), dict) else {}
    sender = full.get("Email") or data.get("from") or data.get("From") or data.get("sender") or ""
    _, address = parseaddr(str(sender))
    subject = str(data.get("subject") or data.get("Subject") or "").strip()
    text = str(data.get("text") or data.get("TextBody") or data.get("body-plain") or data.get("stripped-text") or "")
    message_id = str(data.get("message_id") or data.get("MessageID") or data.get("Message-Id") or "")
    address = address.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
        raise ValueError("a valid sender address is required")
    if not subject and not text.strip():
        raise ValueError("subject or body required")
    return {"sender": address[:255], "subject": (subject or "(no subject)")[:500], "text": text[:20000], "message_id": message_id[:255]}


def strip_quoted(text: str) -> str:
    """Keep only the new part of a reply: drop quoted history and '>' lines."""
    match = _QUOTED.search("\n" + text)
    body = text[: match.start() - 1] if match and match.start() > 0 else text
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">")).strip() or text.strip()


def match_customer(db: Session, org_id: int, sender: str) -> int | None:
    contact = db.query(Contact).filter(Contact.org_id == org_id, Contact.email.ilike(sender)).first()
    if contact:
        return contact.customer_id
    domain = sender.rsplit("@", 1)[1]
    customer = db.query(Customer).filter(Customer.org_id == org_id, Customer.domain.ilike(domain)).first()
    return customer.id if customer else None


def ingest(db: Session, connection: IntegrationConnection, data: dict) -> dict:
    mail = parse(data)
    org_id = connection.org_id
    customer_id = match_customer(db, org_id, mail["sender"])
    ref = _TICKET_REF.search(mail["subject"])
    if ref:
        ticket = db.query(Ticket).filter(Ticket.id == int(ref.group(1)), Ticket.org_id == org_id).first()
        # Only the original requester, or someone from the same customer, may add to an existing ticket.
        if ticket and (ticket.requester_email == mail["sender"] or (customer_id and ticket.customer_id == customer_id)):
            comment = TicketComment(ticket_id=ticket.id, org_id=org_id, author=mail["sender"], body=strip_quoted(mail["text"]), public=True)
            db.add(comment)
            if ticket.status in {"resolved", "pending"}:
                ticket.status = "open"
            db.flush()
            return {"action": "replied", "ticket_id": ticket.id, "comment_id": comment.id, "customer_id": ticket.customer_id}
    # Mail providers retry; the same message within a short window is a duplicate.
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)
    duplicate = db.query(Ticket).filter(Ticket.org_id == org_id, Ticket.requester_email == mail["sender"],
        Ticket.title == mail["subject"], Ticket.body == mail["text"], Ticket.created_at >= since).first()
    if duplicate:
        return {"action": "duplicate", "ticket_id": duplicate.id, "customer_id": duplicate.customer_id}
    from app.api.tickets import _severity, _sla_due

    ticket = Ticket(org_id=org_id, title=mail["subject"], body=mail["text"], priority="normal",
        severity=_severity("normal", mail["subject"], mail["text"]), customer_id=customer_id,
        requester_email=mail["sender"], due_at=_sla_due("normal"))
    db.add(ticket)
    db.flush()
    return {"action": "created", "ticket_id": ticket.id, "customer_id": customer_id}
