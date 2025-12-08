"""
Скрипт для генерации тестовых вакансий и загрузки их в Google Sheets
Генерирует вакансии и записывает их напрямую в Google таблицу
"""

import csv
import random
import sys
import os
from typing import List, Dict
from pathlib import Path

# Добавляем корневую директорию в путь для импорта config
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import gspread
    from google.oauth2.service_account import Credentials
    from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SHEET_NAME
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    print("⚠️  gspread не установлен. Будут создаваться только CSV файлы.")

# Данные для генерации
ORGANIZATIONS = [
    "ООО ТехноСофт",
    "АО Банк Развития",
    "ИП Иванов И.И.",
    "ООО МаркетПлюс",
    "ГК СтройПроект",
    "ООО МедиаГрупп",
    "АО Торговый Дом",
    "ООО КонсалтСервис",
    "ИП Петрова А.С.",
    "ООО ЛогистикТранс",
    "АО ФинансГрупп",
    "ООО IT-Решения",
    "ГК ЭнергоСервис",
    "ООО Образование+",
    "АО Медицинский Центр"
]

VACANCIES = [
    "Разработчик Python",
    "Менеджер по продажам",
    "Бухгалтер",
    "Маркетолог",
    "Юрист",
    "Аналитик данных",
    "Дизайнер",
    "Контент-менеджер",
    "HR-специалист",
    "Логист",
    "Финансовый аналитик",
    "Backend разработчик",
    "Frontend разработчик",
    "Системный администратор",
    "Менеджер проектов",
    "Специалист по рекламе",
    "Копирайтер",
    "Переводчик",
    "Экономист",
    "Аудитор"
]

SPHERES = [
    "IT",
    "Финансы",
    "Маркетинг",
    "Юриспруденция",
    "Логистика",
    "Образование",
    "Медицина",
    "Строительство",
    "Торговля",
    "Консалтинг"
]

SALARIES = [
    "от 30 000 руб.",
    "от 40 000 руб.",
    "от 50 000 руб.",
    "от 60 000 руб.",
    "от 70 000 руб.",
    "от 80 000 руб.",
    "от 100 000 руб.",
    "от 120 000 руб.",
    "от 150 000 руб.",
    "по договоренности",
    "от 35 000 до 50 000 руб.",
    "от 45 000 до 70 000 руб.",
    "от 55 000 до 90 000 руб."
]

SCHEDULES = [
    "Полный день",
    "Неполный день",
    "Удаленная работа",
    "Гибкий график",
    "Сменный график",
    "Выходные дни"
]

FORMATS = [
    "Офис",
    "Удаленно",
    "Гибрид",
    "Выездной"
]

EMPLOYMENT_FORMATS = [
    "Полная занятость",
    "Частичная занятость",
    "Стажировка",
    "Проектная работа",
    "Волонтерство"
]

FEATURES = [
    "Официальное трудоустройство",
    "Оплачиваемый отпуск",
    "Больничный",
    "Премии",
    "Обучение за счет компании",
    "Карьерный рост",
    "Дружный коллектив",
    "Молодая команда",
    "Опыт не требуется",
    "Стажировка с возможностью трудоустройства",
    "Гибкий график",
    "Корпоративные мероприятия",
    "ДМС",
    "Спортивные мероприятия",
    "Бонусы за результат"
]

DESCRIPTIONS = [
    "Ищем ответственного специалиста для работы в динамично развивающейся компании.",
    "Требуется опытный профессионал для работы в команде профессионалов.",
    "Отличная возможность начать карьеру в крупной компании.",
    "Работа в стабильной компании с перспективой карьерного роста.",
    "Ищем активного и целеустремленного сотрудника для нашей команды.",
    "Предлагаем интересную работу в дружном коллективе.",
    "Возможность работать над интересными проектами и развиваться профессионально.",
    "Работа в современной компании с использованием передовых технологий.",
    "Ищем специалиста для работы в международной компании.",
    "Отличная возможность для профессионального и личностного роста."
]

FACULTIES = ["ИТиАБД", "ФинФак", "ВШУ", "НАБ", "СНиМК", "МЭО", "ФЭБ", "Юрфак"]


def generate_vacancy() -> Dict[str, str]:
    """Генерирует одну вакансию"""
    # Выбираем случайные значения
    organization = random.choice(ORGANIZATIONS)
    vacancy = random.choice(VACANCIES)
    sphere = random.choice(SPHERES)
    salary = random.choice(SALARIES)
    schedule = random.choice(SCHEDULES)
    work_format = random.choice(FORMATS)
    description = random.choice(DESCRIPTIONS)
    employment_format = random.choice(EMPLOYMENT_FORMATS)
    
    # Особенности (может быть 1-3)
    num_features = random.randint(1, 3)
    features = random.sample(FEATURES, num_features)
    feature1 = features[0] if len(features) > 0 else ""
    feature2 = features[1] if len(features) > 1 else ""
    feature3 = features[2] if len(features) > 2 else ""
    
    # Генерируем факультеты (случайно выбираем 2-5 факультетов, которым подходит вакансия)
    suitable_faculties = random.sample(FACULTIES, random.randint(2, 5))
    
    vacancy_data = {
        "Организация": organization,
        "Вакансия": vacancy,
        "Сфера": sphere,
        "ЗП": salary,
        "График": schedule,
        "Формат": work_format,
        "Описание": description,
        "Формат трудоустройства": employment_format,
        "Особенность 1": feature1,
        "Особенность 2": feature2,
        "Особенность 3": feature3,
        "ИТиАБД": "Да" if "ИТиАБД" in suitable_faculties else "Нет",
        "ФинФак": "Да" if "ФинФак" in suitable_faculties else "Нет",
        "ВШУ": "Да" if "ВШУ" in suitable_faculties else "Нет",
        "НАБ": "Да" if "НАБ" in suitable_faculties else "Нет",
        "СНиМК": "Да" if "СНиМК" in suitable_faculties else "Нет",
        "МЭО": "Да" if "МЭО" in suitable_faculties else "Нет",
        "ФЭБ": "Да" if "ФЭБ" in suitable_faculties else "Нет",
        "Юрфак": "Да" if "Юрфак" in suitable_faculties else "Нет",
    }
    
    return vacancy_data


def get_headers():
    """Возвращает список заголовков"""
    return [
        "Организация",
        "Вакансия",
        "Сфера",
        "ЗП",
        "График",
        "Формат",
        "Описание",
        "Формат трудоустройства",
        "Особенность 1",
        "Особенность 2",
        "Особенность 3",
        "ИТиАБД",
        "ФинФак",
        "ВШУ",
        "НАБ",
        "СНиМК",
        "МЭО",
        "ФЭБ",
        "Юрфак"
    ]


def write_to_google_sheets(vacancies: List[Dict], clear_existing: bool = False):
    """Записывает вакансии в Google Sheets"""
    if not GSPREAD_AVAILABLE:
        print("❌ gspread не доступен. Используйте CSV режим.")
        return False
    
    if not GOOGLE_CREDENTIALS_FILE or not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"❌ Файл credentials.json не найден: {GOOGLE_CREDENTIALS_FILE}")
        return False
    
    if not GOOGLE_SHEET_NAME:
        print("❌ GOOGLE_SHEET_NAME не указан в .env файле")
        return False
    
    try:
        # Подключаемся к Google Sheets
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=scopes
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open(GOOGLE_SHEET_NAME)
        sheet = spreadsheet.sheet1
        
        headers = get_headers()
        
        # Проверяем и добавляем заголовки в 3-ю строку
        existing_headers = sheet.row_values(3)
        if not existing_headers or existing_headers[0] != headers[0]:
            print("📝 Добавляю заголовки в 3-ю строку...")
            sheet.update(values=[headers], range_name='A3')
        
        # Определяем, с какой строки начинать запись
        all_values = sheet.get_all_values()
        
        if clear_existing:
            # Очищаем данные начиная с 4-й строки
            if len(all_values) > 3:
                # Удаляем все строки начиная с 4-й
                end_row = len(all_values)
                if end_row >= 4:
                    sheet.delete_rows(4, end_row)
            start_row = 4
        else:
            # Находим первую пустую строку после заголовков
            start_row = 4
            for i in range(3, len(all_values)):
                if not all_values[i] or not all_values[i][0] or all_values[i][0].strip() == "":
                    start_row = i + 1
                    break
            else:
                # Если все строки заполнены, добавляем в конец
                start_row = len(all_values) + 1
        
        # Подготавливаем данные для записи
        rows_to_write = []
        for vacancy in vacancies:
            row = [
                vacancy["Организация"],
                vacancy["Вакансия"],
                vacancy["Сфера"],
                vacancy["ЗП"],
                vacancy["График"],
                vacancy["Формат"],
                vacancy["Описание"],
                vacancy["Формат трудоустройства"],
                vacancy["Особенность 1"],
                vacancy["Особенность 2"],
                vacancy["Особенность 3"],
                vacancy["ИТиАБД"],
                vacancy["ФинФак"],
                vacancy["ВШУ"],
                vacancy["НАБ"],
                vacancy["СНиМК"],
                vacancy["МЭО"],
                vacancy["ФЭБ"],
                vacancy["Юрфак"]
            ]
            rows_to_write.append(row)
        
        # Записываем данные начиная с нужной строки
        range_name = f'A{start_row}:S{start_row + len(rows_to_write) - 1}'
        sheet.update(values=rows_to_write, range_name=range_name)
        
        print(f"✅ Записано {len(vacancies)} вакансий в Google Sheets, начиная со строки {start_row}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при записи в Google Sheets: {e}")
        return False


def generate_csv_file(num_vacancies: int = 50, filename: str = "vacancies.csv", write_to_sheets: bool = True, clear_existing: bool = False):
    """Генерирует CSV файл с вакансиями и опционально записывает в Google Sheets"""
    
    headers = get_headers()
    
    # Генерируем вакансии
    vacancies = []
    for i in range(num_vacancies):
        vacancy = generate_vacancy()
        vacancies.append(vacancy)
    
    # Записываем в CSV
    with open(filename, 'w', encoding='utf-8-sig', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(vacancies)
    
    print(f"✅ Сгенерировано {num_vacancies} вакансий в файл {filename}")
    
    # Записываем в Google Sheets, если доступно
    if write_to_sheets and GSPREAD_AVAILABLE:
        print("\n📤 Загрузка в Google Sheets...")
        write_to_google_sheets(vacancies, clear_existing=clear_existing)
    
    # Статистика
    print(f"\n📊 Статистика:")
    faculty_stats = {faculty: 0 for faculty in FACULTIES}
    for vacancy in vacancies:
        for faculty in FACULTIES:
            if vacancy[faculty] == "Да":
                faculty_stats[faculty] += 1
    
    for faculty, count in faculty_stats.items():
        print(f"   {faculty}: {count} вакансий")


if __name__ == "__main__":
    # Парсим аргументы
    num_vacancies = 50
    write_to_sheets = True
    clear_existing = False
    
    if len(sys.argv) > 1:
        try:
            num_vacancies = int(sys.argv[1])
        except ValueError:
            print("❌ Неверное количество вакансий. Используется значение по умолчанию: 50")
    
    if len(sys.argv) > 2:
        if sys.argv[2] == "--csv-only":
            write_to_sheets = False
        elif sys.argv[2] == "--clear":
            clear_existing = True
    
    print(f"🚀 Генерация {num_vacancies} тестовых вакансий...")
    
    if write_to_sheets and GSPREAD_AVAILABLE:
        print("📤 Данные будут загружены в Google Sheets")
        if clear_existing:
            print("⚠️  Режим очистки: существующие данные будут удалены")
    else:
        print("📄 Данные будут сохранены только в CSV файл")
    
    generate_csv_file(num_vacancies, write_to_sheets=write_to_sheets, clear_existing=clear_existing)
    
    if write_to_sheets and GSPREAD_AVAILABLE:
        print("\n✅ Готово! Вакансии загружены в Google Sheets")
    else:
        print("\n💡 Файл vacancies.csv готов для импорта в Google Sheets!")
        print("   Просто скопируйте содержимое в вашу таблицу, начиная с 4-й строки.")

