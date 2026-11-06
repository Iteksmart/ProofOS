# Firebase Cloud Messaging (push notifications)

ProofOS sends alerts/events to mobile and browser devices via **Firebase Cloud Messaging (FCM)**.

## Why Firebase?

- **FCM push** — alerts reach phones/browsers (the highest-value Firebase integration for an RMM/ops platform).
- Firebase **Auth** is *not* used — ProofOS already has username/password, Google (OIDC), and Okta (SAML) SSO.
- **Firestore** is *not* used — ProofOS is relational (Postgres) + hash-chained proof; a NoSQL store would break the integrity model.
- Firebase **Storage/Hosting** can host the React SPA or ticket attachments if you want (optional).

## Setup

1. In the **Firebase Console**, create a project → **Project settings → Service accounts → Generate new private key** (downloads a JSON file).
2. Set the project ID (also in project settings):

```ini
FCM_PROJECT_ID=my-project
FCM_SERVICE_ACCOUNT_JSON=<paste the JSON, or a path to the .json file>
```

3. Register each user's device token (from the FCM web SDK or mobile SDK):

```powershell
curl -X POST https://<host>/v1/push/register \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"org_id":1,"user_id":1,"fcm_token":"<device-token>","platform":"web"}'
```

4. Verify:

```powershell
curl -X POST "https://<host>/v1/push/test?org_id=1" -H "Authorization: Bearer <jwt>"
```

## How it works

- `POST /v1/push/register` — store an FCM device token (deduplicated).
- `GET /v1/push?org_id=` — list registered tokens.
- `POST /v1/push/test?org_id=` — send a test push to every token in the org.
- Alerts raised by monitoring/status-sync automatically broadcast to the org's registered tokens (FCM channel in `services/notifier.py`), alongside Slack/email/webhook.

## Notes

- FCM delivery uses the **HTTP v1 API** with a Google service-account OAuth token (`google-auth` + `httpx`); no extra heavy SDK.
- Push is best-effort and never blocks alerting.
- For browser push, you also need a VAPID key + service worker in the web app; the API side is ready to receive and send to any token.
