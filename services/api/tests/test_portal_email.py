"""Email-to-ticket and the customer portal."""
from __future__ import annotations

from app.services.inbound_email import strip_quoted


def _email_connection(c, org_id):
    created = c.post(f"/v1/integrations/connections?org_id={org_id}", json={"name": "Support inbox", "provider": "email"}).json()
    return created["webhook_path"], {"X-Integration-Token": created["token"]}


def test_strip_quoted_reply():
    assert strip_quoted("Still broken.\n\nOn Mon, 2 Nov 2026 Alice wrote:\n> old text") == "Still broken."
    assert strip_quoted("Thanks\n> quoted") == "Thanks"
    assert strip_quoted("> only quoted") == "> only quoted"


def test_email_creates_ticket_matches_customer_threads_replies_and_dedupes(auth_client):
    c, org_id, _ = auth_client
    acme = c.post("/v1/customers", json={"name": "Mail Acme", "domain": "mail-acme.test"}).json()
    globex = c.post("/v1/customers", json={"name": "Mail Globex", "domain": "globex.test"}).json()
    c.post(f"/v1/customers/{globex['id']}/contacts", json={"name": "Hank", "email": "hank@gmail.com"})
    path, auth = _email_connection(c, org_id)

    postmark = {"FromFull": {"Email": "Wendy@Mail-Acme.test"}, "Subject": "Printer offline", "TextBody": "Third floor printer is down", "MessageID": "a1"}
    first = c.post(path, headers=auth, json=postmark).json()
    assert first["action"] == "created" and first["customer_id"] == acme["id"]
    t = c.get(f"/v1/tickets/{first['ticket_id']}").json()
    assert t["requester_email"] == "wendy@mail-acme.test" and t["severity"] == "P1" and t["customer_id"] == acme["id"]
    assert c.post(path, headers=auth, json=postmark).json() == {"action": "duplicate", "ticket_id": first["ticket_id"], "customer_id": acme["id"]}

    # Mailgun posts form fields; a known contact maps to the customer even from a free-mail domain.
    form = c.post(path, headers={**auth, "Content-Type": "application/x-www-form-urlencoded"},
        content="sender=Hank%20%3Chank%40gmail.com%3E&subject=VPN&body-plain=Cannot%20connect").json()
    assert form["action"] == "created" and form["customer_id"] == globex["id"]

    reply = {"from": "wendy@mail-acme.test", "subject": f"Re: [#{first['ticket_id']}] Printer offline",
             "text": "Still down after restart.\n\nOn Tue, support wrote:\n> We restarted it"}
    threaded = c.post(path, headers=auth, json=reply).json()
    assert threaded["action"] == "replied" and threaded["ticket_id"] == first["ticket_id"]
    comments = c.get(f"/v1/tickets/{first['ticket_id']}/comments").json()
    assert comments[-1]["body"] == "Still down after restart." and comments[-1]["public"] is True

    # An outsider citing the ticket number gets a new ticket, not access to the existing one.
    outsider = c.post(path, headers=auth, json={**reply, "from": "mallory@evil.test"}).json()
    assert outsider["action"] == "created" and outsider["ticket_id"] != first["ticket_id"] and outsider["customer_id"] is None

    assert c.post(path, headers=auth, json={"from": "not-an-address", "subject": "x"}).status_code == 422
    assert c.post(path, headers={"X-Integration-Token": "wrong"}, json=postmark).status_code == 401


def test_portal_link_scopes_customer_hides_internal_notes_and_revokes(auth_client):
    c, org_id, _ = auth_client
    acme = c.post("/v1/customers", json={"name": "Portal Acme"}).json()
    other = c.post("/v1/customers", json={"name": "Portal Other"}).json()
    mine = c.post("/v1/tickets", json={"org_id": org_id, "title": "Laptop slow", "customer_id": acme["id"]}).json()
    theirs = c.post("/v1/tickets", json={"org_id": org_id, "title": "Other ticket", "customer_id": other["id"]}).json()
    c.post(f"/v1/tickets/{mine['id']}/comments", json={"body": "internal: user is difficult"})
    c.post(f"/v1/tickets/{mine['id']}/comments", json={"body": "We are replacing the disk", "public": True})

    link = c.post("/v1/portal/links", json={"customer_id": acme["id"], "contact_email": "Boss@acme.test", "days": 7})
    assert link.status_code == 201 and link.json()["path"].startswith("/portal#")
    portal = {"X-Portal-Token": link.json()["token"], "Authorization": ""}

    me = c.get("/v1/portal/me", headers=portal).json()
    assert me["customer"]["name"] == "Portal Acme" and [t["id"] for t in me["tickets"]] == [mine["id"]]
    detail = c.get(f"/v1/portal/tickets/{mine['id']}", headers=portal).json()
    assert [x["body"] for x in detail["comments"]] == ["We are replacing the disk"]
    assert c.get(f"/v1/portal/tickets/{theirs['id']}", headers=portal).status_code == 404

    opened = c.post("/v1/portal/tickets", headers=portal, json={"title": "Need a new mailbox", "priority": "high"}).json()
    staff_view = c.get(f"/v1/tickets/{opened['id']}").json()
    assert staff_view["customer_id"] == acme["id"] and staff_view["requester_email"] == "boss@acme.test"
    c.post(f"/v1/tickets/{mine['id']}/comments", headers=portal, json={"body": "ignored: wrong auth"})
    assert c.post(f"/v1/portal/tickets/{mine['id']}/comments", headers=portal, json={"body": "Thanks!"}).status_code == 201
    assert c.get(f"/v1/portal/tickets/{mine['id']}", headers=portal).json()["comments"][-1]["author"] == "boss@acme.test"

    assert c.post(f"/v1/portal/links/{link.json()['id']}/revoke").json()["active"] is False
    assert c.get("/v1/portal/me", headers=portal).status_code == 401
    assert c.get("/v1/portal/me", headers={"X-Portal-Token": "guess", "Authorization": ""}).status_code == 401
    assert c.post("/v1/portal/links", json={"customer_id": 999999, "contact_email": "a@b.test"}).status_code == 404
