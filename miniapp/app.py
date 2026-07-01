from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .services.vacancy_sheet import (
    VacancySheetError,
    build_categories,
    filter_vacancies,
    load_vacancies_from_google_sheet,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ASSETS_DIR = BASE_DIR.parent / "assets"

app = FastAPI(title="KVS Job Miniapp")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


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

EVENT_CATEGORIES = ["Все", "Хакатоны", "Воркшопы", "Дни карьеры"]
DEFAULT_EVENTS = [
    {
        "id": "career-day",
        "category": "Дни карьеры",
        "format": "Офлайн",
        "image": "/assets/images/menu_picture.jpg",
        "lead": "Встреть работодателей вживую",
        "title": "День карьеры Финансового университета",
        "date": "Дата уточняется",
        "place": "Финансовый университет",
        "description": "Компании-партнеры, карьерные консультации и встречи со студентами.",
        "deadline": "Регистрация будет открыта позже",
        "url": "",
    },
    {
        "id": "resume-workshop",
        "category": "Воркшопы",
        "format": "Онлайн",
        "image": "/assets/images/fin-career-hero.jpg",
        "lead": "Разбор резюме и карьерного трека",
        "title": "Воркшоп по резюме",
        "date": "Дата уточняется",
        "place": "Онлайн",
        "description": "Практическая встреча по подготовке резюме для стажировок и junior-позиций.",
        "deadline": "Регистрация будет открыта позже",
        "url": "",
    },
]


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
async def list_events(category: str = Query(default="Все", max_length=120)):
    items = DEFAULT_EVENTS if category == "Все" else [item for item in DEFAULT_EVENTS if item["category"] == category]
    return {
        "source": "mock",
        "categories": EVENT_CATEGORIES,
        "items": items,
        "total": len(items),
    }


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
