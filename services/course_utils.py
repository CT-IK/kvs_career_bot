COURSE_LEVELS = [
    ("bachelor", "Бакалавриат", (1, 2, 3, 4), 0),
    ("master", "Магистратура", (1, 2), 4),
    ("postgraduate", "Аспирантура", (1, 2), 6),
]


def build_course_value(level: str, year: int) -> int:
    for level_key, _title, _years, offset in COURSE_LEVELS:
        if level_key == level:
            return offset + year
    raise ValueError(f"Unknown course level: {level}")


def parse_course_callback(data: str, prefix: str) -> tuple[str, int, int]:
    parts = data.split("_")
    expected_prefix = prefix.split("_")

    if parts[:len(expected_prefix)] != expected_prefix or len(parts) != len(expected_prefix) + 2:
        raise ValueError(f"Unexpected callback data: {data}")

    level = parts[-2]
    year = int(parts[-1])
    return level, year, build_course_value(level, year)


def format_course_label(course: int) -> str:
    for _level, title, years, offset in COURSE_LEVELS:
        for year in years:
            if offset + year == course:
                return f"{title}, {year} курс"
    return str(course)
