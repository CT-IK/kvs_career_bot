from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress
from pathlib import Path

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

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from config import BOT_TOKEN
from database.db import get_session
from database.models import MiniappEvent
from services.admins import is_admin

from .services.telegram_auth import extract_user_id, verify_init_data
from .services.vacancy_sheet import (
    VacancySheetError,
    build_categories,
    filter_vacancies,
    load_vacancies_from_google_sheet,
    run_daily_vacancy_refresh_scheduler,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ASSETS_DIR = BASE_DIR.parent / "assets"

app = FastAPI(title="KVS Job Miniapp")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.on_event("startup")
async def _ensure_db_ready() -> None:
    # main.py's bot startup already calls this before launching the miniapp
    # server task, but init_db() is idempotent (CREATE TABLE IF NOT EXISTS)
    # — calling it here too means the miniapp also works if it's ever run
    # standalone (as in local testing), without depending on that ordering.
    #
    # Vacancies/profile don't need a database at all (they read Google Sheets
    # directly) — only the admin events feature does. A missing/unreachable
    # Postgres shouldn't take down the whole miniapp on startup; it should
    # just mean the events endpoints fail when actually called.
    from database.db import init_db

    try:
        await init_db()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Database unavailable at startup (%s) — vacancies/profile will still work, "
            "but admin events management needs a reachable database.",
            exc,
        )


@app.on_event("startup")
async def _start_vacancy_refresh_scheduler() -> None:
    app.state.vacancy_refresh_task = asyncio.create_task(
        run_daily_vacancy_refresh_scheduler(),
        name="miniapp-vacancy-refresh",
    )


@app.on_event("shutdown")
async def _stop_vacancy_refresh_scheduler() -> None:
    task = getattr(app.state, "vacancy_refresh_task", None)
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def require_admin(x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data")) -> int:
    """Verify the caller is an admin via signed Telegram WebApp initData.

    The miniapp previously "checked" admin status entirely client-side (an
    email string compared in the browser) — anyone could call an admin
    endpoint directly with no credentials at all. This verifies the Telegram
    HMAC signature server-side and checks the same admin list/flag the bot
    itself uses (config.ADMIN_IDS / User.is_admin via services.admins).
    """
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Bot token is not configured")

    parsed = verify_init_data(x_telegram_init_data, BOT_TOKEN)
    if not parsed:
        raise HTTPException(status_code=401, detail="Invalid or missing Telegram auth")

    user_id = extract_user_id(parsed)
    if not user_id or not await is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin access required")

    return user_id


class EventPayload(BaseModel):
    category: str = "Другое"
    format: str = "Офлайн"
    image: str = ""
    lead: str = ""
    title: str
    date: str = ""
    place: str = ""
    description: str = ""
    deadline: str = ""
    url: str = ""
    isActive: bool = True


def _event_to_frontend(event: MiniappEvent) -> dict:
    return {
        "id": str(event.id),
        "category": event.category,
        "format": event.format,
        "image": event.image_url or "",
        "lead": event.lead or "",
        "title": event.title,
        "date": event.date_text or "",
        "place": event.place or "",
        "description": event.description or "",
        "deadline": event.deadline_text or "",
        "url": event.external_url or "",
        "isActive": event.is_active,
    }


def _apply_event_payload(event: MiniappEvent, payload: EventPayload) -> None:
    event.category = payload.category.strip() or "Другое"
    event.format = payload.format.strip() or "Офлайн"
    event.image_url = payload.image.strip()
    event.lead = payload.lead.strip()
    event.title = payload.title.strip()
    event.date_text = payload.date.strip()
    event.place = payload.place.strip()
    event.description = payload.description.strip()
    event.deadline_text = payload.deadline.strip()
    event.external_url = payload.url.strip()
    event.is_active = payload.isActive


@app.middleware("http")
async def disable_static_cache(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/miniapp"} or request.url.path.startswith("/static/src/"):
        response.headers["Cache-Control"] = "no-store"
    return response

DEFAULT_PROFILE = {
    "name": "Профиль студента",
    "username": "@kvs_user",
    "universityShort": "Финансовый ун-т",
    "headline": "Студент Финансового университета",
    "location": "Москва",
    "relocation": "не указано",
    "status": "Открыт к предложениям",
    "target": "Стажировка / junior",
    "salary": "По договоренности",
    "email": "student@edu.fa.ru",
    "phone": "Не указан",
    "about": (
        "Профиль пока заполнен базовыми данными. После подключения авторизации Telegram "
        "миниапп сможет подставлять данные конкретного пользователя."
    ),
    "education": {
        "university": "Финансовый университет при Правительстве РФ",
        "program": "Направление и курс будут синхронизированы с профилем бота",
        "period": "Текущий учебный год",
    },
    "skills": ["Excel", "Коммуникация", "Аналитика", "Работа в команде"],
    "experience": [],
    "draft": {
        "step": 1,
        "totalSteps": 5,
        "university": "Финансовый университет при Правительстве РФ",
        "course": "",
        "specialty": "",
    },
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
        "entities": ["User", "Vacancy", "Company", "CareerEvent", "Application", "Favorite", "Profile"],
        "frontend": "static-esm",
        "vacancySource": "GOOGLE_SHEETS_URL",
    }


@app.get("/api/v1/profile")
async def get_profile():
    """Return a temporary profile contract until Telegram auth is connected."""
    return DEFAULT_PROFILE


@app.get("/api/v1/events")
async def list_events(
    category: str = Query(default="Все", max_length=120),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MiniappEvent)
        .where(MiniappEvent.is_active.is_(True))
        .order_by(MiniappEvent.created_at.desc())
    )
    all_items = [_event_to_frontend(event) for event in result.scalars().all()]
    categories = ["Все", *sorted({item["category"] for item in all_items if item["category"]})]
    items = all_items if category in ("", "Все") else [item for item in all_items if item["category"] == category]

    return {
        "source": "database",
        "categories": categories,
        "items": items,
        "total": len(items),
    }


@app.get("/api/v1/admin/events")
async def admin_list_events(
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Full event list for the admin panel, including inactive/hidden events."""
    result = await session.execute(select(MiniappEvent).order_by(MiniappEvent.created_at.desc()))
    return {"items": [_event_to_frontend(event) for event in result.scalars().all()]}


@app.post("/api/v1/admin/events", status_code=201)
async def admin_create_event(
    payload: EventPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")

    event = MiniappEvent()
    _apply_event_payload(event, payload)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return _event_to_frontend(event)


@app.put("/api/v1/admin/events/{event_id}")
async def admin_update_event(
    event_id: int,
    payload: EventPayload,
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(MiniappEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")

    _apply_event_payload(event, payload)
    await session.commit()
    await session.refresh(event)
    return _event_to_frontend(event)


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
):
    try:
        items, loaded_at = await run_in_threadpool(load_vacancies_from_google_sheet, refresh)
    except VacancySheetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Failed to load vacancies from Google Sheets") from exc

    filtered = filter_vacancies(items, query=q, category=category)
    return {
        "source": "google_sheets",
        "loadedAt": loaded_at,
        "categories": build_categories(items),
        "items": filtered[offset : offset + limit],
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/v1/vacancies/{vacancy_id}")
async def get_vacancy(vacancy_id: str, refresh: bool = Query(default=False)):
    try:
        items, loaded_at = await run_in_threadpool(load_vacancies_from_google_sheet, refresh)
    except VacancySheetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Failed to load vacancy from Google Sheets") from exc

    for item in items:
        if item["id"] == vacancy_id:
            return {**item, "source": "google_sheets", "loadedAt": loaded_at}
    raise HTTPException(status_code=404, detail="Vacancy not found")
