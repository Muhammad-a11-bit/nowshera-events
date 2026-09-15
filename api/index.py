import os
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

ACCESS_COOKIE = "nowshera_access_token"
REFRESH_COOKIE = "nowshera_refresh_token"

app = FastAPI(
    title="Nowshera Events API",
    version="1.0.0",
    description="FastAPI backend for Nowshera Events Co.",
)


class LoginBody(BaseModel):
    email: str
    password: str = Field(min_length=6)


class SignupBody(LoginBody):
    full_name: str = Field(min_length=2, max_length=120)


class EventCreate(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    description: str = ""
    starts_at: str
    ends_at: str | None = None
    location: str = Field(min_length=2, max_length=240)
    capacity: int = Field(gt=0)
    status: str = "draft"


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    location: str | None = Field(default=None, min_length=2, max_length=240)
    capacity: int | None = Field(default=None, gt=0)
    status: str | None = None


def ensure_config():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(
            status_code=500,
            detail="Missing SUPABASE_URL or SUPABASE_PUBLISHABLE_KEY in .env",
        )


def headers(access_token: str | None = None, prefer: str | None = None):
    ensure_config()
    h = {
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
    }
    if access_token:
        h["Authorization"] = f"Bearer {access_token}"
    if prefer:
        h["Prefer"] = prefer
    return h


async def sb_request(
    method: str,
    path: str,
    *,
    access_token: str | None = None,
    params: dict[str, Any] | None = None,
    payload: Any = None,
    prefer: str | None = None,
):
    ensure_config()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                method,
                f"{SUPABASE_URL}{path}",
                headers=headers(access_token, prefer),
                params=params,
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not connect to Supabase") from exc

    if response.status_code >= 400:
        message = "Supabase request failed"
        try:
            data = response.json()
            if isinstance(data, dict):
                message = (
                    data.get("message")
                    or data.get("msg")
                    or data.get("error_description")
                    or data.get("error")
                    or message
                )
        except Exception:
            if response.text:
                message = response.text[:500]
        code = response.status_code if response.status_code < 500 else 502
        raise HTTPException(status_code=code, detail=str(message))

    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def set_auth_cookies(response: Response, auth_data: dict):
    access = auth_data.get("access_token")
    refresh = auth_data.get("refresh_token")
    expires = int(auth_data.get("expires_in") or 3600)

    if access:
        response.set_cookie(
            ACCESS_COOKIE,
            access,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite="lax",
            max_age=expires,
            path="/",
        )

    if refresh:
        response.set_cookie(
            REFRESH_COOKIE,
            refresh,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
            path="/",
        )


def clear_auth_cookies(response: Response):
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if not origin:
        return
    expected = f"{request.url.scheme}://{request.headers.get('host')}"
    if origin.rstrip("/") != expected.rstrip("/"):
        raise HTTPException(status_code=403, detail="Cross-origin request blocked")


async def user_from_token(token: str):
    user = await sb_request("GET", "/auth/v1/user", access_token=token)
    if not isinstance(user, dict) or not user.get("id"):
        raise HTTPException(status_code=401, detail="Invalid session")
    user["_access_token"] = token
    return user


async def require_user(
    token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in")
    return await user_from_token(token)


async def get_profile(user: dict):
    rows = await sb_request(
        "GET",
        "/rest/v1/profiles",
        access_token=user["_access_token"],
        params={
            "id": f"eq.{user['id']}",
            "select": "id,full_name,role,created_at,updated_at",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


async def require_admin(user: dict = Depends(require_user)):
    profile = await get_profile(user)
    if not profile or profile.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    user["_profile"] = profile
    return user


@app.get("/", include_in_schema=False)
async def website():
    return FileResponse(ROOT / "index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(ROOT / "admin.html")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_KEY),
    }


@app.post("/api/auth/login")
async def login(body: LoginBody, response: Response, request: Request):
    same_origin(request)
    data = await sb_request(
        "POST",
        "/auth/v1/token",
        params={"grant_type": "password"},
        payload={"email": body.email, "password": body.password},
    )
    set_auth_cookies(response, data)
    return {"authenticated": True}


@app.post("/api/auth/signup")
async def signup(body: SignupBody, response: Response, request: Request):
    same_origin(request)
    data = await sb_request(
        "POST",
        "/auth/v1/signup",
        payload={
            "email": body.email,
            "password": body.password,
            "data": {"full_name": body.full_name},
        },
    )

    if isinstance(data, dict) and data.get("access_token"):
        set_auth_cookies(response, data)
        return {"authenticated": True}

    session = data.get("session") if isinstance(data, dict) else None
    if isinstance(session, dict) and session.get("access_token"):
        set_auth_cookies(response, session)
        return {"authenticated": True}

    return {"authenticated": False}


@app.post("/api/auth/refresh")
async def refresh(
    response: Response,
    request: Request,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
):
    same_origin(request)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    data = await sb_request(
        "POST",
        "/auth/v1/token",
        params={"grant_type": "refresh_token"},
        payload={"refresh_token": refresh_token},
    )
    set_auth_cookies(response, data)
    return {"refreshed": True}


@app.post("/api/auth/logout")
async def logout(
    response: Response,
    request: Request,
    token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
):
    same_origin(request)
    if token:
        try:
            await sb_request("POST", "/auth/v1/logout", access_token=token, payload={})
        except HTTPException:
            pass
    clear_auth_cookies(response)
    return {"signed_out": True}


@app.get("/api/auth/session")
async def auth_session(user: dict = Depends(require_user)):
    profile = await get_profile(user)
    return {
        "user": {"id": user.get("id"), "email": user.get("email")},
        "profile": profile,
    }


@app.get("/api/events/upcoming")
async def upcoming_events():
    return await sb_request(
        "POST",
        "/rest/v1/rpc/public_upcoming_events",
        payload={},
    )


@app.get("/api/registrations/me")
async def my_registrations(user: dict = Depends(require_user)):
    return await sb_request(
        "GET",
        "/rest/v1/registrations",
        access_token=user["_access_token"],
        params={
            "user_id": f"eq.{user['id']}",
            "select": "id,status,registered_at,cancelled_at,event_id,events(title,starts_at,location,status)",
            "order": "registered_at.desc",
        },
    )


@app.post("/api/events/{event_id}/register")
async def register_event(
    event_id: str,
    request: Request,
    user: dict = Depends(require_user),
):
    same_origin(request)
    return await sb_request(
        "POST",
        "/rest/v1/rpc/register_for_event",
        access_token=user["_access_token"],
        payload={"p_event_id": event_id},
    )


@app.post("/api/registrations/{registration_id}/cancel")
async def cancel_registration(
    registration_id: str,
    request: Request,
    user: dict = Depends(require_user),
):
    same_origin(request)
    return await sb_request(
        "POST",
        "/rest/v1/rpc/cancel_my_registration",
        access_token=user["_access_token"],
        payload={"p_registration_id": registration_id},
    )


@app.get("/api/admin/stats")
async def admin_stats(user: dict = Depends(require_admin)):
    return await sb_request(
        "POST",
        "/rest/v1/rpc/admin_dashboard_stats",
        access_token=user["_access_token"],
        payload={},
    )


@app.get("/api/admin/events")
async def admin_events(user: dict = Depends(require_admin)):
    return await sb_request(
        "GET",
        "/rest/v1/event_availability",
        access_token=user["_access_token"],
        params={"select": "*", "order": "starts_at.desc"},
    )


@app.post("/api/admin/events")
async def create_event(
    body: EventCreate,
    request: Request,
    user: dict = Depends(require_admin),
):
    same_origin(request)
    payload = body.model_dump()
    payload["created_by"] = user["id"]
    return await sb_request(
        "POST",
        "/rest/v1/events",
        access_token=user["_access_token"],
        payload=payload,
        prefer="return=representation",
    )


@app.patch("/api/admin/events/{event_id}")
async def update_event(
    event_id: str,
    body: EventUpdate,
    request: Request,
    user: dict = Depends(require_admin),
):
    same_origin(request)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields supplied")
    return await sb_request(
        "PATCH",
        "/rest/v1/events",
        access_token=user["_access_token"],
        params={"id": f"eq.{event_id}"},
        payload=payload,
        prefer="return=representation",
    )


@app.get("/api/admin/events/{event_id}/attendees")
async def admin_attendees(
    event_id: str,
    user: dict = Depends(require_admin),
):
    return await sb_request(
        "POST",
        "/rest/v1/rpc/admin_event_attendees",
        access_token=user["_access_token"],
        payload={"p_event_id": event_id},
    )


@app.get("/api/admin/reports/summary")
async def reports_summary(user: dict = Depends(require_admin)):
    token = user["_access_token"]

    events = await sb_request(
        "GET",
        "/rest/v1/event_availability",
        access_token=token,
        params={"select": "*", "order": "starts_at.desc"},
    )

    registrations = await sb_request(
        "GET",
        "/rest/v1/registrations",
        access_token=token,
        params={"select": "id,status,event_id"},
    )

    total_capacity = sum(int(e.get("capacity") or 0) for e in events)
    active = sum(1 for r in registrations if r.get("status") == "active")
    cancelled = sum(1 for r in registrations if r.get("status") == "cancelled")

    return {
        "total_events": len(events),
        "total_capacity": total_capacity,
        "active_registrations": active,
        "cancelled_registrations": cancelled,
        "remaining_capacity": max(total_capacity - active, 0),
        "events": events,
    }


if __name__ == "__main__":
    uvicorn.run("api.index:app", host="127.0.0.1", port=8000, reload=True)
