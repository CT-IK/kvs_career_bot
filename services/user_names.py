def normalize_name_part(value: str) -> str:
    return value.strip().replace("–", "-").replace("—", "-")


def validate_name_part(value: str, field_name: str, allow_none_literal: bool = False) -> tuple[bool, str | None, str | None]:
    normalized = normalize_name_part(value)

    if allow_none_literal and normalized.casefold() == "нет":
        return True, None, None

    if len(normalized) < 2:
        return False, None, f"❌ {field_name} должно быть длиной минимум 2 символа."

    if normalized.startswith("-") or normalized.endswith("-") or "--" in normalized:
        return False, None, f"❌ {field_name} может содержать дефис только внутри слова."

    if not any(char.isalpha() for char in normalized):
        return False, None, f"❌ {field_name} должно содержать буквы."

    for char in normalized:
        if char.isalpha() or char == "-":
            continue
        return False, None, f"❌ {field_name} должно содержать только буквы и дефис."

    return True, normalized, None


def format_full_name(first_name: str, last_name: str, patronymic: str | None = None) -> str:
    parts = [first_name, last_name]
    if patronymic:
        parts.append(patronymic)
    return " ".join(part for part in parts if part)
