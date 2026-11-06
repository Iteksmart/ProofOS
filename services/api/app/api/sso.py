from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.proof import emit
from app.core.security import actor_of, create_access_token, get_current_user
from app.models.models import SsoConfig, User
from app.schemas.schemas import SsoConfigIn, SsoConfigOut
from app.services import google_sso

settings = get_settings()
router = APIRouter()


def _saml_settings_dict() -> dict:
    """Build python3-saml settings from SP config + the Okta/IdP metadata URL."""
    if not settings.saml_idp_metadata_url:
        raise ValueError("SAML_IDP_METADATA_URL not configured")
    idp_data = OneLogin_Saml2_IdPMetadataParser.parse_remote(settings.saml_idp_metadata_url)
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": settings.saml_entity_id,
            "assertionConsumerService": {
                "url": settings.saml_acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": idp_data.get("idp", {}),
    }


def _scope(user, org_id: int) -> None:
    if user.org_id != org_id and user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="org scope mismatch")


@router.get("/config", response_model=SsoConfigOut)
def get_config(org_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    c = db.query(SsoConfig).filter(SsoConfig.org_id == org_id).first()
    if not c:
        c = SsoConfig(org_id=org_id)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


@router.post("/config", response_model=SsoConfigOut)
def upsert_config(org_id: int, payload: SsoConfigIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _scope(user, org_id)
    c = db.query(SsoConfig).filter(SsoConfig.org_id == org_id).first()
    if not c:
        c = SsoConfig(org_id=org_id)
        db.add(c)
    c.provider = payload.provider
    c.entity_id = payload.entity_id
    c.metadata_url = payload.metadata_url
    c.enabled = payload.enabled
    db.commit()
    db.refresh(c)
    emit(db, "sso.config.updated", {"org_id": org_id, "provider": c.provider, "enabled": c.enabled}, actor_of(user), {"org_id": org_id}, {"reason": "SSO/SAML config"})
    return c


@router.get("/sp-metadata")
def sp_metadata():
    """Service-provider metadata (ProofOS as the SP). Point your IdP here or paste this XML."""
    entity_id = settings.saml_entity_id
    acs = settings.saml_acs_url
    xml = f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity_id}">
  <md:SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="{acs}" index="0" isDefault="true"/>
  </md:SPSSODescriptor>
</md:EntityDescriptor>"""
    return Response(content=xml, media_type="application/xml")


@router.post("/acs")
async def acs(request: Request, db: Session = Depends(get_db)):
    """SAML Assertion Consumer Service — validates the Okta/IdP response (python3-saml)."""
    if not settings.saml_idp_metadata_url:
        raise HTTPException(status_code=400, detail="SAML not configured — set SAML_IDP_METADATA_URL (Okta IdP metadata URL)")
    form = await request.form()
    req = {
        "http_host": request.headers.get("host", ""),
        "script_name": "/v1/sso/acs",
        "server_port": request.url.port or (443 if request.url.scheme == "https" else 80),
        "https": "on" if request.url.scheme == "https" else "off",
        "post_data": dict(form),
    }
    try:
        auth = OneLogin_Saml2_Auth(req, _saml_settings_dict())
        auth.process_response()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SAML validation failed: {e}")
    if not auth.is_authenticated():
        raise HTTPException(status_code=401, detail="SAML response not authenticated")

    email = auth.get_nameid()
    attrs = auth.get_attributes()
    if not email and attrs.get("email"):
        email = attrs["email"][0]
    if not email:
        raise HTTPException(status_code=401, detail="no email in SAML assertion")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=403, detail=f"No ProofOS user for {email} — ask an admin to create it first")
    token = create_access_token(str(user.id), {"email": user.email, "role": user.role, "org_id": user.org_id})
    emit(db, "auth.saml_sso", {"email": email, "nameid": auth.get_nameid()}, actor_of(user), {"org_id": user.org_id}, {"reason": "SAML SSO login"})
    if settings.web_url:
        return RedirectResponse(f"{settings.web_url.rstrip('/')}/?sso_token={token}")
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "email": user.email, "role": user.role, "org_id": user.org_id}}


@router.get("/google")
def google_status():
    return {"configured": google_sso.configured(), "client_id_set": bool(settings.google_client_id)}


@router.get("/google/login")
def google_login(state: str = "proofos"):
    if not google_sso.configured():
        raise HTTPException(status_code=400, detail="Google SSO not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
    return RedirectResponse(google_sso.build_auth_url(state))


@router.get("/google/callback")
def google_callback(code: str | None = None, state: str | None = None, db: Session = Depends(get_db)):
    if not code:
        raise HTTPException(status_code=400, detail="missing authorization code")
    if not google_sso.configured():
        raise HTTPException(status_code=400, detail="Google SSO not configured")
    try:
        tokens = google_sso.exchange_code(code)
    except Exception:
        raise HTTPException(status_code=400, detail="failed to exchange authorization code")
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="no id_token returned")
    try:
        claims = google_sso.verify_id_token(id_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid Google id_token: {e}")

    email = claims.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="no email in Google claims")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=403, detail=f"No ProofOS user for {email} — ask an admin to create it first")
    token = create_access_token(str(user.id), {"email": user.email, "role": user.role, "org_id": user.org_id})
    emit(db, "auth.google_sso", {"email": email, "sub": claims.get("sub")}, actor_of(user), {"org_id": user.org_id}, {"reason": "Google SSO login"})
    if settings.web_url:
        return RedirectResponse(f"{settings.web_url.rstrip('/')}/?sso_token={token}")
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "email": user.email, "role": user.role, "org_id": user.org_id}}
