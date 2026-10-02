"""RU/EN interface translations; language is scoped to each update/task."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path

TRANSLATIONS = json.loads(Path(__file__).with_name('translations.json').read_text(encoding='utf-8'))
_current_language: ContextVar[str] = ContextVar('user_language', default='ru')


def normalize_language(language: str | None) -> str:
    return language if language in ('ru', 'en') else 'ru'


@contextmanager
def language_context(language: str | None):
    token = _current_language.set(normalize_language(language))
    try:
        yield
    finally:
        _current_language.reset(token)


def t(text: str, *, language: str | None = None, **values) -> str:
    selected = normalize_language(language) if language is not None else _current_language.get()
    translated = TRANSLATIONS.get(text, text) if selected == 'en' else text
    return translated.format(**values) if values else translated
