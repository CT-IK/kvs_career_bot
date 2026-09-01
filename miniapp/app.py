from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import sys
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

# This package is imported two different ways depending on how the server is
# launched: with kvs_career_bot/ itself as the working directory (main.py's
# own uvicorn.Config("miniapp.app:app", ...), and this repo's Bash-tested
# invocations), or from the project's parent directory via the top-level
# miniapp/app.py shim (`from kvs_career_bot.miniapp.app import app`). Only the
# first puts kvs_career_bot/ on sys.path automatically, so `config`,
# `database`, `services` (all top-level modules *inside* kvs_career_bot/)
# fail to resolve under the second. Adding it explicitly here makes both work.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import (
    MAX_BOT_TOKEN,
    MINIAPP_DEV_ADMIN_ENABLED,
    MINIAPP_PUBLIC_URL,
)
from database.db import get_session
from database.models import (
    Company,
    Division,
    MiniappAction,
    MiniappEvent,
    MiniappEventRegistration,
    Vacancy,
    VacancySyncState,
)
from services.admins import is_max_admin
from services.max_bot import MaxApiError, max_bot
from services.partner_defaults import KEPT_PARTNER
from services.vacancy_scheduler import run_daily_vacancy_sync_scheduler

from .services.max_auth import extract_user_id, verify_init_data
from .services.analytics import build_metrics_dashboard, export_metrics_csv
from .services.vacancy_sheet import (
    build_categories,
    filter_vacancies,
    vacancy_from_db,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ASSETS_DIR = BASE_DIR.parent / "assets"
EVENT_UPLOAD_DIR = STATIC_DIR / "uploads" / "events"
EVENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="KVS Job Miniapp")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(OSError)
async def database_error_handler(request, exc: Exception):
    logging.getLogger(__name__).warning("Database request failed for %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database is temporarily unavailable"},
    )


@app.on_event("startup")
async def _ensure_db_ready() -> None:
    # main.py's bot startup already calls this before launching the miniapp
    # server task, but init_db() is idempotent (CREATE TABLE IF NOT EXISTS)
    # — calling it here too means the miniapp also works if it's ever run
    # standalone (as in local testing), without depending on that ordering.
    #
    # The sync itself is deliberately not part of startup. It runs in a
    # background task below so a slow Google request cannot delay the UI.
    from database.db import init_db

    try:
        await init_db()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Database unavailable at startup (%s); database-backed sections "
            "will return a temporary-service response.",
            exc,
        )


@app.on_event("startup")
async def _start_vacancy_refresh_scheduler() -> None:
    app.state.vacancy_refresh_task = asyncio.create_task(
        run_daily_vacancy_sync_scheduler(),
        name="vacancy-db-sync",
    )


@app.on_event("shutdown")
async def _stop_vacancy_refresh_scheduler() -> None:
    task = getattr(app.state, "vacancy_refresh_task", None)
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _is_local_request(request: Request) -> bool:
    hostname = request.url.hostname or ""
    client_host = request.client.host if request.client else ""
    try:
        client_is_loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        client_is_loopback = client_host == "localhost"
    return client_is_loopback and hostname in {"localhost", "127.0.0.1", "::1"}


async def require_admin(
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
) -> int:
    """Verify MAX initData and the server-side MAX administrator list."""
    if MINIAPP_DEV_ADMIN_ENABLED and not x_max_init_data and _is_local_request(request):
        return 0

    if not MAX_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="MAX bot token is not configured")

    parsed = verify_init_data(x_max_init_data, MAX_BOT_TOKEN)
    if not parsed:
        raise HTTPException(status_code=401, detail="Invalid or missing MAX auth")

    user_id = extract_user_id(parsed)
    if not user_id or not await is_max_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin access required")

    return user_id


def _resolve_miniapp_user(request: Request, init_data: str) -> int | None:
    if MAX_BOT_TOKEN and init_data:
        parsed = verify_init_data(init_data, MAX_BOT_TOKEN)
        user_id = extract_user_id(parsed) if parsed else None
        if user_id:
            return user_id
    if MINIAPP_DEV_ADMIN_ENABLED and not init_data and _is_local_request(request):
        return 0
    return None


async def require_miniapp_user(
    request: Request,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
) -> int:
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Откройте мини-приложение внутри MAX")
    return user_id


class EventPayload(BaseModel):
    category: str = "Другое"
    format: str = "Офлайн"
    image: str = ""
    lead: str = ""
    title: str
    date: str = ""
    startsAt: datetime | None = None
    place: str = ""
    description: str = ""
    deadline: str = ""
    url: str = ""
    capacity: int = Field(default=0, ge=0, le=100000)
    isActive: bool = True


class EventMessagePayload(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    audience: Literal["all", "confirmed", "reserve"] = "all"


class DepartmentPayload(BaseModel):
    name: str = Field(max_length=200)
    description: str = ""


class PartnerPayload(BaseModel):
    name: str = Field(max_length=200)
    logo: str = ""
    description: str = ""
    achievements: str = ""
    isActive: bool = True
    departments: list[DepartmentPayload] = Field(default_factory=list)


class MetricEventPayload(BaseModel):
    eventType: Literal["click", "page_view"]
    action: str = Field(min_length=1, max_length=100)
    route: str = Field(default="/", max_length=255)
    target: str = Field(default="", max_length=255)
    sessionId: str = Field(min_length=8, max_length=64)
    metadata: dict = Field(default_factory=dict)


def _event_to_frontend(
    event: MiniappEvent,
    *,
    registration: MiniappEventRegistration | None = None,
    reserve_position: int | None = None,
    include_admin: bool = False,
    main_count: int = 0,
    reserve_count: int = 0,
) -> dict:
    item = {
        "id": str(event.id),
        "category": event.category,
        "format": event.format,
        "image": event.image_url or "",
        "lead": event.lead or "",
        "title": event.title,
        "date": event.date_text or "",
        "startsAt": event.starts_at.isoformat() if event.starts_at else "",
        "place": event.place or "",
        "description": event.description or "",
        "deadline": event.deadline_text or "",
        "url": event.external_url or "",
        "isActive": event.is_active,
        "isRegistered": registration is not None,
        "registrationStatus": registration.status if registration else "",
        "reservePosition": reserve_position,
    }
    if include_admin:
        item.update({
            "capacity": event.capacity,
            "mainCount": main_count,
            "reserveCount": reserve_count,
        })
    return item


def _apply_event_payload(event: MiniappEvent, payload: EventPayload) -> None:
    event.category = payload.category.strip() or "Другое"
    event.format = payload.format.strip() or "Офлайн"
    event.image_url = payload.image.strip()
    event.lead = payload.lead.strip()
    event.title = payload.title.strip()
    event.date_text = payload.date.strip()
    event.starts_at = (
        payload.startsAt.replace(tzinfo=timezone.utc)
        if payload.startsAt and payload.startsAt.tzinfo is None
        else payload.startsAt
    )
    event.place = payload.place.strip()
    event.description = payload.description.strip()
    event.deadline_text = payload.deadline.strip()
    event.external_url = payload.url.strip()
    event.capacity = payload.capacity
    event.is_active = payload.isActive


def _partner_to_frontend(company: Company, *, include_departments: bool = True) -> dict:
    item = {
        "id": str(company.id),
        "name": company.name,
        "logoUrl": company.logo_url or "",
        "initial": (company.name[:1] or "К").upper(),
        "brandColor": "#c40016",
        "description": company.description or "",
        "achievements": company.achievements or "",
        "isActive": company.is_active,
        "departmentCount": len(company.divisions),
    }
    if include_departments:
        item["departments"] = [
            {
                "id": str(department.id),
                "companyId": str(company.id),
                "companyName": company.name,
                "name": department.name,
                "description": department.description or "",
            }
            for department in company.divisions
        ]
    return item


def _default_partner_to_frontend(*, include_departments: bool = True) -> dict:
    departments = [
        {
            "id": str(index),
            "companyId": "1",
            "companyName": KEPT_PARTNER["name"],
            "name": item["name"],
            "description": item["description"],
        }
        for index, item in enumerate(KEPT_PARTNER["departments"], start=1)
    ]
    partner = {
        "id": "1",
        "name": KEPT_PARTNER["name"],
        "logoUrl": KEPT_PARTNER["logo_url"],
        "initial": "K",
        "brandColor": "#c40016",
        "description": KEPT_PARTNER["description"],
        "achievements": KEPT_PARTNER["achievements"],
        "isActive": True,
        "departmentCount": len(departments),
    }
    if include_departments:
        partner["departments"] = departments
    return partner


def _apply_partner_payload(company: Company, payload: PartnerPayload) -> None:
    company.name = payload.name.strip()
    company.logo_url = payload.logo.strip()
    company.description = payload.description.strip()
    company.achievements = payload.achievements.strip()
    company.is_partner = True
    company.is_active = payload.isActive
    company.divisions.clear()
    company.divisions.extend(
        Division(name=item.name.strip(), description=item.description.strip())
        for item in payload.departments
        if item.name.strip()
    )


async def _get_partner(
    session: AsyncSession,
    partner_id: int,
    *,
    public_only: bool = False,
) -> Company | None:
    conditions = [Company.id == partner_id, Company.is_partner.is_(True)]
    if public_only:
        conditions.append(Company.is_active.is_(True))
    return (
        await session.execute(
            select(Company).options(selectinload(Company.divisions)).where(*conditions)
        )
    ).scalar_one_or_none()


@app.middleware("http")
async def disable_static_cache(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/miniapp"} or request.url.path.startswith("/static/src/"):
        response.headers["Cache-Control"] = "no-store"
    return response

DEFAULT_PROFILE = {
    "name": "Профиль студента",
    # Temporary values until the university profile service is connected.
    "faculty": "ИТиАБД",
    "course": "3 курс",
    "group": "ПИ23-1",
}

@app.get("/")
@app.get("/miniapp")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "kvs-job-miniapp"}


@app.get("/api/v1/bootstrap")
async def bootstrap():
    """Return the current miniapp backend contract."""
    return {
        "mode": "google_sheets",
        "entities": ["User", "Vacancy", "Partner", "Department", "CareerEvent", "Application", "Favorite", "Profile"],
        "frontend": "static-esm",
        "vacancySource": "GOOGLE_SHEETS_URL",
    }


@app.get("/api/v1/profile")
async def get_profile():
    """Return a temporary profile contract until the MAX profile is connected."""
    return DEFAULT_PROFILE


@app.post("/api/v1/metrics/actions", status_code=204)
async def record_miniapp_action(
    payload: MetricEventPayload,
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    max_user_id = None
    if MAX_BOT_TOKEN and x_max_init_data:
        parsed = verify_init_data(x_max_init_data, MAX_BOT_TOKEN)
        if parsed:
            max_user_id = extract_user_id(parsed)

    raw_data = json.dumps(payload.metadata, ensure_ascii=False, separators=(",", ":"))
    session.add(
        MiniappAction(
            max_user_id=max_user_id,
            session_id=payload.sessionId.strip(),
            event_type=payload.eventType,
            action=payload.action.strip(),
            route=payload.route.strip() or "/",
            target=payload.target.strip(),
            raw_data=raw_data[:4000],
        )
    )
    await session.commit()
    return Response(status_code=204)


@app.get("/api/v1/admin/metrics")
async def admin_get_metrics(
    days: int = Query(default=30, ge=7, le=90),
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await build_metrics_dashboard(session, days)


@app.get("/api/v1/admin/metrics/export")
async def admin_export_metrics(
    days: int = Query(default=30, ge=7, le=90),
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    content = await export_metrics_csv(session, days)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="kvs-metrics-{days}d.csv"'
        },
    )


@app.get("/api/v1/partners")
async def list_partners(session: AsyncSession = Depends(get_session)):
    try:
        result = await session.execute(
            select(Company)
            .options(selectinload(Company.divisions))
            .where(Company.is_partner.is_(True), Company.is_active.is_(True))
            .order_by(Company.name)
        )
    except (SQLAlchemyError, OSError) as exc:
        logging.getLogger(__name__).warning("Using default partners because the database is unavailable: %s", exc)
        item = _default_partner_to_frontend(include_departments=False)
        return {"source": "defaults", "items": [item], "total": 1}
    items = [
        _partner_to_frontend(company, include_departments=False)
        for company in result.scalars().all()
    ]
    return {"source": "database", "items": items, "total": len(items)}


@app.get("/api/v1/partners/{partner_id}")
async def get_partner(partner_id: int, session: AsyncSession = Depends(get_session)):
    try:
        company = await _get_partner(session, partner_id, public_only=True)
    except (SQLAlchemyError, OSError) as exc:
        logging.getLogger(__name__).warning("Using default partner because the database is unavailable: %s", exc)
        if partner_id == 1:
            return _default_partner_to_frontend()
        raise HTTPException(status_code=404, detail="Partner not found") from exc
    if not company:
        raise HTTPException(status_code=404, detail="Partner not found")
    return _partner_to_frontend(company)


@app.get("/api/v1/partners/{partner_id}/departments/{department_id}")
async def get_partner_department(
    partner_id: int,
    department_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        company = await _get_partner(session, partner_id, public_only=True)
    except (SQLAlchemyError, OSError) as exc:
        logging.getLogger(__name__).warning("Using default department because the database is unavailable: %s", exc)
        partner = _default_partner_to_frontend()
        department = next(
            (item for item in partner["departments"] if item["id"] == str(department_id)),
            None,
        )
        if partner_id != 1 or not department:
            raise HTTPException(status_code=404, detail="Department not found") from exc
        return {**department, "companyLogoUrl": partner["logoUrl"]}
    if not company:
        raise HTTPException(status_code=404, detail="Partner not found")
    department = next((item for item in company.divisions if item.id == department_id), None)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    return {
        "id": str(department.id),
        "companyId": str(company.id),
        "companyName": company.name,
        "companyLogoUrl": company.logo_url or "",
        "name": department.name,
        "description": department.description or "",
    }


@app.get("/api/v1/admin/partners")
async def admin_list_partners(
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Company)
        .options(selectinload(Company.divisions))
        .where(Company.is_partner.is_(True))
        .order_by(Company.name)
    )
    return {"items": [_partner_to_frontend(company) for company in result.scalars().all()]}


@app.post("/api/v1/admin/partners", status_code=201)
async def admin_create_partner(
    payload: PartnerPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")

    company = (
        await session.execute(select(Company).where(func.lower(Company.name) == name.lower()))
    ).scalar_one_or_none()
    if company and company.is_partner:
        raise HTTPException(status_code=409, detail="Partner with this name already exists")
    if company is None:
        company = Company()
        session.add(company)
    else:
        await session.refresh(company, attribute_names=["divisions"])

    _apply_partner_payload(company, payload)
    await session.commit()
    company = await _get_partner(session, company.id)
    return _partner_to_frontend(company)


@app.put("/api/v1/admin/partners/{partner_id}")
async def admin_update_partner(
    partner_id: int,
    payload: PartnerPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    company = await _get_partner(session, partner_id)
    if not company:
        raise HTTPException(status_code=404, detail="Partner not found")
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Name is required")

    duplicate = (
        await session.execute(
            select(Company.id).where(
                Company.id != partner_id,
                func.lower(Company.name) == payload.name.strip().lower(),
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="Company with this name already exists")

    _apply_partner_payload(company, payload)
    await session.commit()
    company = await _get_partner(session, partner_id)
    return _partner_to_frontend(company)


@app.delete("/api/v1/admin/partners/{partner_id}", status_code=204)
async def admin_delete_partner(
    partner_id: int,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    company = await _get_partner(session, partner_id)
    if not company:
        raise HTTPException(status_code=404, detail="Partner not found")
    company.is_partner = False
    company.is_active = False
    await session.commit()
    return None


@app.get("/api/v1/subscription")
async def get_subscription_status(user_id: int = Depends(require_miniapp_user)):
    try:
        status = await max_bot.subscription_status(user_id)
    except MaxApiError as exc:
        logging.getLogger(__name__).warning("MAX subscription check failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Не удалось проверить подписку. Убедитесь, что MAX-бот добавлен "
                "администратором обязательного канала."
            ),
        ) from exc
    return {
        "required": status.required,
        "subscribed": status.subscribed,
        "channelUrl": status.channel_url,
    }


async def _require_max_subscription(user_id: int) -> None:
    try:
        status = await max_bot.subscription_status(user_id)
    except MaxApiError as exc:
        raise HTTPException(status_code=503, detail="Не удалось проверить подписку в MAX") from exc
    if status.required and not status.subscribed:
        raise HTTPException(status_code=403, detail="Сначала подпишитесь на канал в MAX")


async def _reserve_position(
    session: AsyncSession,
    registration: MiniappEventRegistration,
) -> int | None:
    if registration.status != "reserve":
        return None
    return int(
        (
            await session.execute(
                select(func.count(MiniappEventRegistration.id)).where(
                    MiniappEventRegistration.event_id == registration.event_id,
                    MiniappEventRegistration.status == "reserve",
                    MiniappEventRegistration.id <= registration.id,
                )
            )
        ).scalar_one()
    )


def _max_event_button() -> dict | None:
    if not MINIAPP_PUBLIC_URL:
        return None
    return {
        "text": "Открыть мои мероприятия",
        "url": f"{MINIAPP_PUBLIC_URL.split('#', 1)[0]}#/notifications",
    }


async def _notify_registration(user_id: int, event: MiniappEvent, status: str) -> bool:
    if status == "confirmed":
        text = f"Вы зарегистрированы на мероприятие «{event.title}». Место подтверждено."
    else:
        text = (
            f"Вы в резерве на мероприятие «{event.title}». "
            "Как только освободится место, мы сообщим вам в MAX."
        )
    try:
        await max_bot.send_message(user_id, text, button=_max_event_button())
        return True
    except MaxApiError as exc:
        logging.getLogger(__name__).warning(
            "Cannot deliver MAX registration message to %s: %s", user_id, exc
        )
        return False


async def _notify_promotion(user_id: int, event: MiniappEvent) -> bool:
    try:
        await max_bot.send_message(
            user_id,
            f"Освободилось место на мероприятии «{event.title}». Вы перенесены из резерва в основной список.",
            button=_max_event_button(),
        )
        return True
    except MaxApiError as exc:
        logging.getLogger(__name__).warning(
            "Cannot deliver MAX promotion message to %s: %s", user_id, exc
        )
        return False


@app.get("/api/v1/events")
async def list_events(
    request: Request,
    category: str = Query(default="Все", max_length=120),
    x_max_init_data: str = Header(default="", alias="X-Max-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    user_id = _resolve_miniapp_user(request, x_max_init_data)
    result = await session.execute(
        select(MiniappEvent)
        .where(MiniappEvent.is_active.is_(True))
        .order_by(MiniappEvent.starts_at.asc().nullslast(), MiniappEvent.created_at.desc())
    )
    events = result.scalars().all()
    registrations: dict[int, MiniappEventRegistration] = {}
    if user_id is not None and events:
        rows = (
            await session.execute(
                select(MiniappEventRegistration).where(
                    MiniappEventRegistration.max_user_id == user_id,
                    MiniappEventRegistration.event_id.in_([event.id for event in events]),
                )
            )
        ).scalars().all()
        registrations = {row.event_id: row for row in rows}
    all_items = []
    for event in events:
        registration = registrations.get(event.id)
        all_items.append(
            _event_to_frontend(
                event,
                registration=registration,
                reserve_position=(await _reserve_position(session, registration)) if registration else None,
            )
        )
    categories = ["Все", *sorted({item["category"] for item in all_items if item["category"]})]
    items = all_items if category in ("", "Все") else [item for item in all_items if item["category"] == category]

    return {
        "source": "database",
        "categories": categories,
        "items": items,
        "total": len(items),
        "registeredCount": len(registrations),
    }


@app.get("/api/v1/me/events")
async def list_my_events(
    user_id: int = Depends(require_miniapp_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MiniappEvent, MiniappEventRegistration)
        .join(
            MiniappEventRegistration,
            MiniappEventRegistration.event_id == MiniappEvent.id,
        )
        .where(
            MiniappEventRegistration.max_user_id == user_id,
            MiniappEvent.is_active.is_(True),
        )
        .order_by(MiniappEvent.starts_at.asc().nullslast(), MiniappEvent.created_at.desc())
    )
    items = []
    for event, registration in result.all():
        item = _event_to_frontend(
            event,
            registration=registration,
            reserve_position=await _reserve_position(session, registration),
        )
        item["registeredAt"] = registration.created_at.isoformat() if registration.created_at else ""
        items.append(item)
    return {"items": items, "total": len(items)}


@app.post("/api/v1/events/{event_id}/register", status_code=201)
async def register_for_event(
    event_id: int,
    user_id: int = Depends(require_miniapp_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_max_subscription(user_id)
    event = (
        await session.execute(
            select(MiniappEvent).where(MiniappEvent.id == event_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not event or not event.is_active:
        raise HTTPException(status_code=404, detail="Event not found")
    if not event.starts_at:
        raise HTTPException(status_code=409, detail="Event start time is not configured")
    now = datetime.now(timezone.utc)
    starts_at = event.starts_at
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    if starts_at <= now:
        raise HTTPException(status_code=409, detail="Event has already started")

    registration = (
        await session.execute(
            select(MiniappEventRegistration).where(
                MiniappEventRegistration.event_id == event_id,
                MiniappEventRegistration.max_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if registration is None:
        main_count = int(
            (
                await session.execute(
                    select(func.count(MiniappEventRegistration.id)).where(
                        MiniappEventRegistration.event_id == event_id,
                        MiniappEventRegistration.status == "confirmed",
                    )
                )
            ).scalar_one()
        )
        status = "confirmed" if event.capacity <= 0 or main_count < event.capacity else "reserve"
        registration = MiniappEventRegistration(
            event_id=event_id,
            max_user_id=user_id,
            status=status,
        )
        session.add(registration)
        await session.commit()
        await session.refresh(registration)
        notification_sent = await _notify_registration(user_id, event, status)
    else:
        notification_sent = True
    item = _event_to_frontend(
        event,
        registration=registration,
        reserve_position=await _reserve_position(session, registration),
    )
    item["notificationSent"] = notification_sent
    return item


@app.delete("/api/v1/events/{event_id}/register", status_code=204)
async def unregister_from_event(
    event_id: int,
    user_id: int = Depends(require_miniapp_user),
    session: AsyncSession = Depends(get_session),
):
    event = (
        await session.execute(
            select(MiniappEvent).where(MiniappEvent.id == event_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    registration = (
        await session.execute(
            select(MiniappEventRegistration).where(
                MiniappEventRegistration.event_id == event_id,
                MiniappEventRegistration.max_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    promoted_user_id = None
    if registration:
        should_promote = registration.status == "confirmed"
        await session.delete(registration)
        await session.flush()
        if should_promote:
            promoted = (
                await session.execute(
                    select(MiniappEventRegistration)
                    .where(
                        MiniappEventRegistration.event_id == event_id,
                        MiniappEventRegistration.status == "reserve",
                    )
                    .order_by(MiniappEventRegistration.created_at, MiniappEventRegistration.id)
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if promoted:
                promoted.status = "confirmed"
                promoted.promoted_at = datetime.now(timezone.utc)
                promoted_user_id = promoted.max_user_id
        await session.commit()
    if promoted_user_id:
        await _notify_promotion(promoted_user_id, event)
    return Response(status_code=204)


@app.get("/api/v1/admin/events")
async def admin_list_events(
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Full event list for the admin panel, including inactive/hidden events."""
    result = await session.execute(select(MiniappEvent).order_by(MiniappEvent.created_at.desc()))
    events = result.scalars().all()
    counts = {}
    if events:
        count_rows = (
            await session.execute(
                select(
                    MiniappEventRegistration.event_id,
                    MiniappEventRegistration.status,
                    func.count(MiniappEventRegistration.id),
                )
                .where(MiniappEventRegistration.event_id.in_([event.id for event in events]))
                .group_by(MiniappEventRegistration.event_id, MiniappEventRegistration.status)
            )
        ).all()
        for event_id, status, count in count_rows:
            counts.setdefault(event_id, {})[status] = int(count)
    return {
        "items": [
            _event_to_frontend(
                event,
                include_admin=True,
                main_count=counts.get(event.id, {}).get("confirmed", 0),
                reserve_count=counts.get(event.id, {}).get("reserve", 0),
            )
            for event in events
        ]
    }


@app.post("/api/v1/admin/events/upload", status_code=201)
async def admin_upload_event_image(
    request: Request,
    admin_id: int = Depends(require_admin),
):
    content_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    extension = content_types.get(request.headers.get("content-type", "").split(";", 1)[0])
    if not extension:
        raise HTTPException(status_code=415, detail="Поддерживаются JPG, PNG, WEBP и GIF")
    data = await request.body()
    if len(data) > 6 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Изображение должно быть не больше 6 МБ")
    if not data:
        raise HTTPException(status_code=422, detail="Файл пуст")
    filename = f"{uuid.uuid4().hex}{extension}"
    (EVENT_UPLOAD_DIR / filename).write_bytes(data)
    return {"url": f"/static/uploads/events/{filename}"}


@app.post("/api/v1/admin/events", status_code=201)
async def admin_create_event(
    payload: EventPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")
    if payload.capacity < 1:
        raise HTTPException(status_code=422, detail="Укажите лимит участников")

    event = MiniappEvent()
    _apply_event_payload(event, payload)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return _event_to_frontend(event, include_admin=True)


@app.put("/api/v1/admin/events/{event_id}")
async def admin_update_event(
    event_id: int,
    payload: EventPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    event = (
        await session.execute(
            select(MiniappEvent).where(MiniappEvent.id == event_id).with_for_update()
        )
    ).scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")
    if payload.capacity < 1:
        raise HTTPException(status_code=422, detail="Укажите лимит участников")

    main_count = int(
        (
            await session.execute(
                select(func.count(MiniappEventRegistration.id)).where(
                    MiniappEventRegistration.event_id == event_id,
                    MiniappEventRegistration.status == "confirmed",
                )
            )
        ).scalar_one()
    )
    if payload.capacity < main_count:
        raise HTTPException(
            status_code=409,
            detail=f"Лимит нельзя сделать меньше основного списка ({main_count})",
        )

    _apply_event_payload(event, payload)
    promoted = []
    free_slots = payload.capacity - main_count
    if free_slots > 0:
        promoted = list(
            (
                await session.execute(
                    select(MiniappEventRegistration)
                    .where(
                        MiniappEventRegistration.event_id == event_id,
                        MiniappEventRegistration.status == "reserve",
                    )
                    .order_by(MiniappEventRegistration.created_at, MiniappEventRegistration.id)
                    .limit(free_slots)
                    .with_for_update()
                )
            ).scalars()
        )
        now = datetime.now(timezone.utc)
        for registration in promoted:
            registration.status = "confirmed"
            registration.promoted_at = now
    await session.commit()
    await session.refresh(event)
    for registration in promoted:
        if registration.max_user_id:
            await _notify_promotion(registration.max_user_id, event)
    reserve_count = int(
        (
            await session.execute(
                select(func.count(MiniappEventRegistration.id)).where(
                    MiniappEventRegistration.event_id == event_id,
                    MiniappEventRegistration.status == "reserve",
                )
            )
        ).scalar_one()
    )
    return _event_to_frontend(
        event,
        include_admin=True,
        main_count=main_count + len(promoted),
        reserve_count=reserve_count,
    )


@app.post("/api/v1/admin/events/{event_id}/message")
async def admin_message_event_participants(
    event_id: int,
    payload: EventMessagePayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(MiniappEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    conditions = [
        MiniappEventRegistration.event_id == event_id,
        MiniappEventRegistration.max_user_id.is_not(None),
    ]
    if payload.audience != "all":
        conditions.append(MiniappEventRegistration.status == payload.audience)
    recipients = list(
        (
            await session.execute(
                select(MiniappEventRegistration.max_user_id)
                .where(*conditions)
                .order_by(MiniappEventRegistration.id)
            )
        ).scalars()
    )
    sent = 0
    failed = 0
    for user_id in recipients:
        try:
            await max_bot.send_message(
                user_id,
                f"Сообщение по мероприятию «{event.title}»:\n\n{payload.text.strip()}",
                button=_max_event_button(),
            )
            sent += 1
        except MaxApiError as exc:
            failed += 1
            logging.getLogger(__name__).warning(
                "Cannot deliver admin MAX message to %s: %s", user_id, exc
            )
    return {"total": len(recipients), "sent": sent, "failed": failed}


@app.delete("/api/v1/admin/events/{event_id}", status_code=204)
async def admin_delete_event(
    event_id: int,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(MiniappEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await session.delete(event)
    await session.commit()
    return None


@app.get("/api/v1/vacancies")
async def list_vacancies(
    q: str = Query(default="", max_length=160),
    category: str = Query(default="Все", max_length=120),
    limit: int = Query(default=80, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    refresh: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    # ``refresh`` is retained for compatibility with older clients. Source
    # refreshes are centralized in the scheduler so one HTTP request can never
    # make every user wait on Google Sheets.
    del refresh
    vacancies = (
        await session.execute(select(Vacancy).order_by(Vacancy.id.desc()))
    ).scalars().all()
    state = await session.get(VacancySyncState, 1)
    items = [vacancy_from_db(vacancy) for vacancy in vacancies]
    filtered = filter_vacancies(items, query=q, category=category)
    syncing = bool(state and state.status == "syncing")
    if syncing and state.started_at:
        started_at = state.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        # Do not leave the UI in an eternal "updating" state after a hard
        # process stop. The next scheduler run will write a fresh state.
        syncing = datetime.now(timezone.utc) - started_at < timedelta(minutes=20)
    maintenance = not items
    if syncing:
        maintenance_message = "Обновляем вакансии. Обычно это занимает несколько минут."
    elif state and state.status == "failed":
        maintenance_message = "Идёт технический перерыв. Повторим загрузку автоматически."
    else:
        maintenance_message = "Вакансии подготавливаются. Попробуйте открыть раздел через несколько минут."

    loaded_at = state.completed_at if state else None
    if loaded_at is None and vacancies:
        loaded_at = max((item.updated_at or item.created_at) for item in vacancies)
    return {
        "source": "database",
        "loadedAt": loaded_at.isoformat() if loaded_at else None,
        "categories": build_categories(items),
        "items": filtered[offset : offset + limit],
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "syncing": syncing,
        "maintenance": maintenance,
        "maintenanceMessage": maintenance_message,
    }


@app.get("/api/v1/vacancies/{vacancy_id}")
async def get_vacancy(
    vacancy_id: str,
    refresh: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    del refresh
    raw_id = vacancy_id[3:] if vacancy_id.startswith("db-") else vacancy_id
    if not raw_id.isdigit():
        raise HTTPException(status_code=404, detail="Vacancy not found")
    vacancy = await session.get(Vacancy, int(raw_id))
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    state = await session.get(VacancySyncState, 1)
    loaded_at = state.completed_at if state else vacancy.updated_at
    return {
        **vacancy_from_db(vacancy),
        "source": "database",
        "loadedAt": loaded_at.isoformat() if loaded_at else None,
    }
