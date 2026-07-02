from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

# Telegram invalidates initData server-side checks after this long — treat an
# older auth_date as a replay rather than trust it indefinitely.
MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60


def verify_init_data(init_data: str, bot_token: str) -> dict | None:
    """Verify a Telegram WebApp initData string against the bot token.

    Implements Telegram's documented check: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    Returns the parsed key/value pairs (with `hash` removed) if the signature
    and age are valid, otherwise None.
    """
    if not init_data or not bot_token:
        return None

    try:
        pairs = parse_qsl(init_data, strict_parsing=True)
    except ValueError:
        return None

    parsed = dict(pairs)
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = parsed.get("auth_date")
    if not auth_date or not auth_date.isdigit():
        return None
    if time.time() - int(auth_date) > MAX_INIT_DATA_AGE_SECONDS:
        return None

    return parsed


def extract_user_id(parsed_init_data: dict) -> int | None:
    """Pull the Telegram numeric user id out of initData's `user` JSON field."""
    raw_user = parsed_init_data.get("user")
    if not raw_user:
        return None
    try:
        user = json.loads(raw_user)
    except (json.JSONDecodeError, TypeError):
        return None
    user_id = user.get("id")
    return int(user_id) if isinstance(user_id, (int, float)) or (isinstance(user_id, str) and user_id.isdigit()) else None
