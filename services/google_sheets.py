import os
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SHEET_NAME, GOOGLE_SHEETS_URL
from database.models import Vacancy
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime


def get_google_sheet():
    """Подключение к Google Sheets - тот же метод что в генераторе"""
    print("🔗 Подключение к Google Sheets...")
    
    # Проверяем наличие credentials
    if not GOOGLE_CREDENTIALS_FILE:
        print("❌ GOOGLE_CREDENTIALS_FILE не указан")
        return None
    
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"❌ Файл {GOOGLE_CREDENTIALS_FILE} не найден")
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
            print(f"📎 Открываю по URL: {GOOGLE_SHEETS_URL[:60]}...")
            spreadsheet = client.open_by_url(GOOGLE_SHEETS_URL)
        elif GOOGLE_SHEET_NAME:
            print(f"📎 Открываю по имени: {GOOGLE_SHEET_NAME}")
            spreadsheet = client.open(GOOGLE_SHEET_NAME)
        else:
            print("❌ Не указаны GOOGLE_SHEETS_URL или GOOGLE_SHEET_NAME")
            return None
        
        sheet = spreadsheet.sheet1
        print(f"✅ Подключено к таблице: {spreadsheet.title}")
        return sheet
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        import traceback
        traceback.print_exc()
        return None


def parse_vacancies_from_sheet(sheet) -> list[dict]:
    """Парсинг вакансий из Google таблицы"""
    try:
        # Получаем заголовки из 3 строки
        headers = sheet.row_values(3)
        print(f"📋 Заголовки ({len(headers)}): {headers[:5]}...")
        
        if not headers or len(headers) < 5:
            print("❌ Заголовки не найдены или их слишком мало")
            return []
        
        # Получаем все данные
        all_values = sheet.get_all_values()
        print(f"📊 Всего строк в таблице: {len(all_values)}")
        
        # Данные начинаются с 4 строки (индекс 3)
        data_rows = all_values[3:] if len(all_values) > 3 else []
        print(f"📊 Строк с данными: {len(data_rows)}")
        
        if not data_rows:
            print("⚠️ Нет данных для парсинга (строки 4+)")
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
        
        print(f"✅ Распознано вакансий: {len(vacancies)}")
        return vacancies
        
    except Exception as e:
        print(f"❌ Ошибка парсинга: {e}")
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
    print("\n" + "="*50)
    print("🔄 СИНХРОНИЗАЦИЯ ВАКАНСИЙ")
    print("="*50)
    
    # Подключаемся к Google Sheets
    sheet = get_google_sheet()
    if not sheet:
        print("❌ Не удалось подключиться к Google Sheets")
        return 0
    
    # Парсим вакансии
    vacancies_data = parse_vacancies_from_sheet(sheet)
    
    if not vacancies_data:
        print("⚠️ Нет вакансий для синхронизации")
        return 0
    
    # Очищаем существующие вакансии
    if clear_existing:
        await session.execute(delete(Vacancy))
        print("🗑️ Старые вакансии удалены")
    
    # Добавляем новые
    synced_count = 0
    for vac_data in vacancies_data:
        new_vacancy = Vacancy(**vac_data)
        session.add(new_vacancy)
        synced_count += 1
    
    await session.commit()
    
    print("="*50)
    print(f"✅ СИНХРОНИЗИРОВАНО: {synced_count} вакансий")
    print("="*50 + "\n")
    
    return synced_count
