import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SHEET_NAME
from database.models import Vacancy
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime


class GoogleSheetsParser:
    def __init__(self):
        self.client = None
        self.sheet = None
        
    def connect(self):
        """Подключение к Google Sheets"""
        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE,
                scopes=scopes
            )
            self.client = gspread.authorize(creds)
            spreadsheet = self.client.open(GOOGLE_SHEET_NAME)
            # Используем первый лист, если название не указано
            self.sheet = spreadsheet.sheet1
            return True
        except Exception as e:
            print(f"Ошибка подключения к Google Sheets: {e}")
            return False
    
    def parse_vacancies(self) -> list[dict]:
        """Парсинг вакансий из Google таблицы"""
        if not self.sheet:
            if not self.connect():
                return []
        
        try:
            # Получаем заголовки из 3 строки (индекс 2)
            headers = self.sheet.row_values(3)
            
            # Получаем все данные начиная с 4 строки (индекс 3)
            all_values = self.sheet.get_all_values()
            data_rows = all_values[3:]  # Пропускаем первые 3 строки
            
            vacancies = []
            for row in data_rows:
                if not row or not row[0]:  # Пропускаем пустые строки
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
                    "organization": vacancy_data.get("Организация", ""),
                    "position": vacancy_data.get("Вакансия", ""),
                    "sphere": vacancy_data.get("Сфера", ""),
                    "salary": vacancy_data.get("ЗП", ""),
                    "schedule": vacancy_data.get("График", ""),
                    "work_format": vacancy_data.get("Формат", ""),
                    "description": vacancy_data.get("Описание", ""),
                    "employment_format": vacancy_data.get("Формат трудоустройства", ""),
                    "feature1": vacancy_data.get("Особенность 1", ""),
                    "feature2": vacancy_data.get("Особенность 2", ""),
                    "feature3": vacancy_data.get("Особенность 3", ""),
                    "itiabd": self._parse_faculty_field(vacancy_data.get("ИТиАБД", "")),
                    "finfak": self._parse_faculty_field(vacancy_data.get("ФинФак", "")),
                    "vshu": self._parse_faculty_field(vacancy_data.get("ВШУ", "")),
                    "nab": self._parse_faculty_field(vacancy_data.get("НАБ", "")),
                    "snimk": self._parse_faculty_field(vacancy_data.get("СНиМК", "")),
                    "meo": self._parse_faculty_field(vacancy_data.get("МЭО", "")),
                    "feb": self._parse_faculty_field(vacancy_data.get("ФЭБ", "")),
                    "yurfak": self._parse_faculty_field(vacancy_data.get("Юрфак", "")),
                }
                
                vacancies.append(vacancy)
            
            return vacancies
        except Exception as e:
            print(f"Ошибка при парсинге вакансий: {e}")
            return []
    
    def _parse_faculty_field(self, value: str) -> bool:
        """Парсинг поля факультета (может быть 'да', '1', 'x' и т.д.)"""
        if not value:
            return False
        value_lower = str(value).lower().strip()
        return value_lower in ['да', 'yes', '1', 'x', '✓', 'true', 'т']


async def sync_vacancies_to_db(session: AsyncSession):
    """Синхронизация вакансий из Google Sheets в БД"""
    parser = GoogleSheetsParser()
    vacancies_data = parser.parse_vacancies()
    
    if not vacancies_data:
        return 0
    
    from database.models import Vacancy
    
    synced_count = 0
    for vac_data in vacancies_data:
        # Проверяем, существует ли уже такая вакансия
        result = await session.execute(
            select(Vacancy).where(
                Vacancy.organization == vac_data["organization"],
                Vacancy.position == vac_data["position"]
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Обновляем существующую вакансию
            for key, value in vac_data.items():
                setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            # Создаем новую вакансию
            new_vacancy = Vacancy(**vac_data)
            session.add(new_vacancy)
        
        synced_count += 1
    
    await session.commit()
    return synced_count

