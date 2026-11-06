# Okta SSO (SAML 2.0) setup

ProofOS is a SAML service provider. Okta is the identity provider (IdP). The flow:

```
Browser → ProofOS "Sign in with Okta" → Okta login → SAML POST to /v1/sso/acs → JWT → app
```

## 1. Configure Okta

1. In the Okta Admin Console, go to **Applications → Create App Integration → SAML 2.0**.
2. Give it a name (e.g. "ProofOS").
3. **Single sign-on URL** (ACS): `https://<your-proofos-host>/v1/sso/acs`
   **Audience URI / SP Entity ID**: `https://<your-proofos-host>/sp`
   (These are configurable via `SAML_ACS_URL` and `SAML_ENTITY_ID`.)
4. **Attribute statements**: add `email` → `user.email`, and set the **Name ID format** to `EmailAddress`.
5. Save, then on the **Sign On** tab → **View SAML setup instructions** → copy the **Identity Provider metadata URL** (or download the metadata XML).

## 2. Configure ProofOS

```ini
SAML_IDP_METADATA_URL=https://<your-okta-org>.okta.com/app/<app-id>/sso/saml/metadata
SAML_ENTITY_ID=https://<your-proofos-host>/sp
SAML_ACS_URL=https://<your-proofos-host>/v1/sso/acs
WEB_URL=https://<your-proofos-web-host>
```

You can also fetch ProofOS's SP metadata at `GET /v1/sso/sp-metadata` and paste it into Okta (instead of hand-entering the ACS/entity ID).

## 3. Map users

The SAML assertion's email (`NameID` or the `email` attribute) must match a ProofOS user.
Create users in **Admin → Users** (or via `POST /v1/auth/users`) with the same email.

## 4. Verify

```powershell
# SP metadata (paste into Okta)
curl https://<host>/v1/sso/sp-metadata

# Config status
curl https://<host>/v1/sso/config?org_id=1
```

Once configured, clicking **Sign in with Okta** (or navigating to `/v1/sso/login`) completes the flow.

## Notes

- Live assertion validation uses `python3-saml` (already in `requirements.txt`), with signature/`Issuer`/`Audience`/`Conditions` checks enforced (`strict: true`).
- This is app-level SSO: users map to their org by email. For per-tenant identity enforcement (e.g. "org A only accepts @acme.com"), add a domain→org mapping.
