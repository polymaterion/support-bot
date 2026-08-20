"""
Простая, но полноценная система локализации.

- Переводы хранятся в locales/<lang>.json
- Ключи не найденные в выбранном языке -> fallback на DEFAULT_LANGUAGE
- Поддержка форматирования через {placeholder}
- Добавление нового языка = просто положить новый locales/<code>.json,
  никакие изменения в коде не требуются.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("support-bot.i18n")

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LANGUAGE = "ru"

SUPPORTED_LANGUAGES: list[str] = []
_translations: dict[str, dict[str, str]] = {}


def _load_translations() -> None:
    global SUPPORTED_LANGUAGES
    if not LOCALES_DIR.exists():
        raise RuntimeError(f"Locales directory not found: {LOCALES_DIR}")

    for path in sorted(LOCALES_DIR.glob("*.json")):
        lang_code = path.stem
        with path.open("r", encoding="utf-8") as f:
            _translations[lang_code] = json.load(f)
        logger.info("Loaded locale '%s' with %d keys", lang_code, len(_translations[lang_code]))

    SUPPORTED_LANGUAGES = sorted(_translations.keys())

    if DEFAULT_LANGUAGE not in _translations:
        raise RuntimeError(f"Default language '{DEFAULT_LANGUAGE}' locale file is missing")

    # Audit: warn about missing keys across locales so nothing silently falls back.
    all_keys = set()
    for keys in _translations.values():
        all_keys.update(keys.keys())
    for lang_code, keys in _translations.items():
        missing = all_keys - keys.keys()
        if missing:
            logger.warning("Locale '%s' is missing keys: %s", lang_code, sorted(missing))


_load_translations()


def is_supported(lang_code: str | None) -> bool:
    return lang_code in _translations


def normalize_language(lang_code: str | None) -> str:
    """Map an arbitrary/telegram language code to one of our supported languages."""
    if not lang_code:
        return DEFAULT_LANGUAGE
    lang_code = lang_code.lower()
    if lang_code in _translations:
        return lang_code
    # Telegram sends things like 'ru-RU'; try the primary subtag.
    primary = lang_code.split("-")[0]
    if primary in _translations:
        return primary
    return DEFAULT_LANGUAGE


def t(key: str, lang: str | None, **kwargs: Any) -> str:
    """Translate `key` into `lang`, falling back to DEFAULT_LANGUAGE, then to the key itself."""
    lang = normalize_language(lang)
    translations = _translations.get(lang, {})
    template = translations.get(key)

    if template is None:
        fallback = _translations.get(DEFAULT_LANGUAGE, {})
        template = fallback.get(key)
        if template is None:
            logger.warning("Missing translation key '%s' in all locales", key)
            return key

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            logger.exception("Failed to format translation key '%s'", key)
            return template

    return template
