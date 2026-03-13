import os
import sys
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SHEET_NAME, GOOGLE_SHEETS_URL
from database.models import Vacancy, Company, Division
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from datetime import datetime


def _safe_print(message: str) -> None:
    """Print logs without crashing on consoles that cannot encode emoji."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sanitized = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(sanitized)


async def _sync_companies_and_divisions(session: AsyncSession, vacancies_data: list[dict]) -> tuple[int, int]:
    """Backfill companies and divisions from synced vacancies without touching descriptions."""
    organizations = sorted({item["organization"] for item in vacancies_data if item.get("organization")})
    if not organizations:
        return 0, 0

    existing_companies_result = await session.execute(
        select(Company).where(Company.name.in_(organizations))
    )
    companies_by_name = {company.name: company for company in existing_companies_result.scalars().all()}

    created_companies = 0
    for organization in organizations:
        if organization not in companies_by_name:
            company = Company(name=organization, description=None)
            session.add(company)
            companies_by_name[organization] = company
            created_companies += 1

    if created_companies:
        await session.flush()

    company_ids = [company.id for company in companies_by_name.values() if company.id is not None]
    if not company_ids:
        return created_companies, 0

    existing_divisions_result = await session.execute(
        select(Division).where(Division.company_id.in_(company_ids))
    )
    existing_divisions = {
        (division.company_id, division.name)
        for division in existing_divisions_result.scalars().all()
    }

    created_divisions = 0
    division_pairs = sorted(
        {
            (item["organization"], item["division"])
            for item in vacancies_data
            if item.get("organization") and item.get("division")
        }
    )
    for organization, division_name in division_pairs:
        company = companies_by_name.get(organization)
        if not company or company.id is None:
            continue
        division_key = (company.id, division_name)
        if division_key in existing_divisions:
            continue
        session.add(Division(company_id=company.id, name=division_name, description=None))
        existing_divisions.add(division_key)
        created_divisions += 1

    return created_companies, created_divisions


def get_google_sheet():
    """Подключение к Google Sheets - тот же метод что в генераторе"""
    _safe_print("🔗 Подключение к Google Sheets...")
    
    # Проверяем наличие credentials
    if not GOOGLE_CREDENTIALS_FILE:
        _safe_print("❌ GOOGLE_CREDENTIALS_FILE не указан")
        return None
    
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        _safe_print(f"❌ Файл {GOOGLE_CREDENTIALS_FILE} не найден")
        return None
    
    try:
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=scopes
        )
        client = gspread.authorize(creds)
        
        # Пробуем разные способы открытия таблицы
        spreadsheet = None
        if GOOGLE_SHEETS_URL:
            _safe_print(f"📎 Открываю по URL: {GOOGLE_SHEETS_URL[:60]}...")
            spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
        elif GOOGLE_SHEET_NAME:
            _safe_print(f"📎 Открываю по имени: {GOOGLE_SHEET_NAME}")
            spreadsheet = client.open(GOOGLE_SHEET_NAME)
        else:
            _safe_print("❌ Не указаны GOOGLE_SHEETS_URL или GOOGLE_SHEET_NAME")
            return None
        
        sheet = spreadsheet.sheet1
        _safe_print(f"✅ Подключено к таблице: {spreadsheet.title}")
        return sheet
        
    except Exception as e:
        _safe_print(f"❌ Ошибка подключения: {e}")
        import traceback
        traceback.print_exc()
        return None


def parse_vacancies_from_sheet(sheet) -> list[dict]:
    """Парсинг вакансий из Google таблицы"""
    try:
        # Получаем заголовки из 2 строки (у пользователя такая структура)
        headers = sheet.row_values(2)
        _safe_print(f"📋 Заголовки ({len(headers)}): {headers[:5]}...")
        
        if not headers or len(headers) < 5:
            _safe_print("❌ Заголовки не найдены или их слишком мало")
            return []
        
        # Получаем все данные
        all_values = sheet.get_all_values()
        _safe_print(f"📊 Всего строк в таблице: {len(all_values)}")
        
        # Данные начинаются с 3 строки (индекс 2)
        data_rows = all_values[2:] if len(all_values) > 2 else []
        _safe_print(f"📊 Строк с данными: {len(data_rows)}")
        
        if not data_rows:
            _safe_print("⚠️ Нет данных для парсинга (строки 3+)")
            return []
        
        vacancies = []
        for row_idx, row in enumerate(data_rows):
            # Пропускаем пустые строки
            if not row or not row[0] or not row[0].strip():
                continue
            
            # Создаем словарь из строки
            vacancy_data = {}
            for i, header in enumerate(headers):
                if i < len(row):
                    vacancy_data[header] = row[i]
                else:
                    vacancy_data[header] = ""
            
            # Преобразуем в структуру для БД
            vacancy = {
                "organization": vacancy_data.get("Организация", "").strip(),
                "division": vacancy_data.get("Подразделение", "").strip(),
                "position": vacancy_data.get("Вакансия", "").strip(),
                "sphere": vacancy_data.get("Сфера", "").strip(),
                "salary": vacancy_data.get("ЗП", "").strip(),
                "schedule": vacancy_data.get("График", "").strip(),
                "work_format": vacancy_data.get("Формат", "").strip(),
                "description": vacancy_data.get("Описание", "").strip(),
                "employment_format": vacancy_data.get("Формат трудоустройства", "").strip(),
                "feature1": vacancy_data.get("Особенность 1", "").strip(),
                "feature2": vacancy_data.get("Особенность 2", "").strip(),
                "feature3": vacancy_data.get("Особенность 3", "").strip(),
                "itiabd": _parse_faculty_field(vacancy_data.get("ИТиАБД", "")),
                "finfak": _parse_faculty_field(vacancy_data.get("ФинФак", "")),
                "vshu": _parse_faculty_field(vacancy_data.get("ВШУ", "")),
                "nab": _parse_faculty_field(vacancy_data.get("НАБ", "")),
                "snimk": _parse_faculty_field(vacancy_data.get("СНиМК", "")),
                "meo": _parse_faculty_field(vacancy_data.get("МЭО", "")),
                "feb": _parse_faculty_field(vacancy_data.get("ФЭБ", "")),
                "yurfak": _parse_faculty_field(vacancy_data.get("Юрфак", "")),
            }
            
            # Пропускаем вакансии без организации или позиции
            if vacancy["organization"] and vacancy["position"]:
                vacancies.append(vacancy)
        
        _safe_print(f"✅ Распознано вакансий: {len(vacancies)}")
        return vacancies
        
    except Exception as e:
        _safe_print(f"❌ Ошибка парсинга: {e}")
        import traceback
        traceback.print_exc()
        return []


def _parse_faculty_field(value: str) -> bool:
    """Парсинг поля факультета"""
    if not value:
        return False
    value_lower = str(value).lower().strip()
    return value_lower in ['да', 'yes', '1', 'x', '✓', 'true', 'т', '+']


# Класс для обратной совместимости
class GoogleSheetsParser:
    def __init__(self):
        self.sheet = None
        
    def connect(self):
        self.sheet = get_google_sheet()
        return self.sheet is not None
    
    def parse_vacancies(self) -> list[dict]:
        if not self.sheet:
            if not self.connect():
                return []
        return parse_vacancies_from_sheet(self.sheet)


async def sync_vacancies_to_db(session: AsyncSession, clear_existing: bool = True):
    """Синхронизация вакансий из Google Sheets в БД"""
    _safe_print("\n" + "="*50)
    _safe_print("🔄 СИНХРОНИЗАЦИЯ ВАКАНСИЙ")
    _safe_print("="*50)
    
    # Подключаемся к Google Sheets
    sheet = get_google_sheet()
    if not sheet:
        _safe_print("❌ Не удалось подключиться к Google Sheets")
        return 0
    
    # Парсим вакансии
    vacancies_data = parse_vacancies_from_sheet(sheet)
    
    if not vacancies_data:
        _safe_print("⚠️ Нет вакансий для синхронизации")
        return 0
    
    # Очищаем существующие вакансии
    if clear_existing:
        await session.execute(delete(Vacancy))
        _safe_print("🗑️ Старые вакансии удалены")
    
    # Добавляем новые
    synced_count = 0
    for vac_data in vacancies_data:
        new_vacancy = Vacancy(**vac_data)
        session.add(new_vacancy)
        synced_count += 1

    created_companies, created_divisions = await _sync_companies_and_divisions(session, vacancies_data)
    
    await session.commit()
    
    _safe_print("="*50)
    _safe_print(f"✅ СИНХРОНИЗИРОВАНО: {synced_count} вакансий")
    _safe_print(f"🏢 СОЗДАНО КОМПАНИЙ: {created_companies}")
    _safe_print(f"🏛️ СОЗДАНО ПОДРАЗДЕЛЕНИЙ: {created_divisions}")
    _safe_print("="*50 + "\n")
    
    return synced_count


async def ensure_vacancies_seeded(session: AsyncSession) -> int:
    """Load vacancies from Google Sheets once when the database is empty."""
    existing_count = (await session.execute(select(func.count(Vacancy.id)))).scalar() or 0
    if existing_count > 0:
        _safe_print(f"ℹ️ Вакансии уже загружены: {existing_count}")
        return existing_count

    _safe_print("ℹ️ База вакансий пуста, запускаю начальную синхронизацию из Google Sheets")
    return await sync_vacancies_to_db(session, clear_existing=False)
