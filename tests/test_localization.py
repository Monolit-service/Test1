"""Offline localization checks: python -m unittest discover -s tests -v."""
import ast
import asyncio
import importlib.util
from pathlib import Path
import sqlite3
from string import Formatter
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('i18n', ROOT / 'app/services/i18n.py')
i18n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i18n)


class LocalizationTests(unittest.TestCase):
    def test_catalog_placeholders(self):
        fields = lambda text: {field for _, field, _, _ in Formatter().parse(text) if field is not None}
        for ru, en in i18n.TRANSLATIONS.items():
            with self.subTest(text=ru):
                self.assertEqual(fields(ru), fields(en))
                values = {field: 'VALUE' for field in fields(ru)}
                self.assertEqual(i18n.t(ru, language='en', **values), en.format(**values) if values else en)

    def test_defaults_and_literal_braces(self):
        self.assertEqual(i18n.t('🌐 Сменить язык'), '🌐 Сменить язык')
        self.assertEqual(i18n.t('🌐 Сменить язык', language='en'), '🌐 Change language')
        self.assertEqual(i18n.t('🌐 Сменить язык', language='xx'), '🌐 Сменить язык')
        self.assertEqual(i18n.t('Custom {text}', language='en'), 'Custom {text}')

    def test_async_language_isolation(self):
        async def render(lang):
            with i18n.language_context(lang):
                await asyncio.sleep(0)
                return i18n.t('🌐 Сменить язык')
        async def run():
            return await asyncio.gather(render('en'), render('ru'))
        self.assertEqual(asyncio.run(run()), ['🌐 Change language', '🌐 Сменить язык'])
        self.assertEqual(i18n.t('🌐 Сменить язык'), '🌐 Сменить язык')

    def test_existing_sqlite_migration_is_idempotent(self):
        database = sqlite3.connect(':memory:')
        database.execute('CREATE TABLE payments (id INTEGER PRIMARY KEY)')
        database.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id BIGINT)')
        database.execute('INSERT INTO users VALUES (1, 42)')
        class Connection:
            dialect = type('Dialect', (), {'name': 'sqlite'})()
            async def execute(self, sql):
                return database.execute(sql)
        class Begin:
            async def __aenter__(self): return Connection()
            async def __aexit__(self, *args): database.commit()
        class Engine:
            def begin(self): return Begin()
        tree = ast.parse((ROOT / 'app/bot.py').read_text())
        method = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'ensure_schema')
        namespace = {'engine': Engine(), 'text': str}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'ensure_schema', 'exec'), namespace)
        asyncio.run(namespace['ensure_schema']())
        asyncio.run(namespace['ensure_schema']())
        self.assertEqual(database.execute('SELECT telegram_id, language FROM users').fetchone(), (42, 'ru'))
        database.execute("UPDATE users SET language='en' WHERE id=1")
        database.commit()
        asyncio.run(namespace['ensure_schema']())
        self.assertEqual(database.execute('SELECT language FROM users').fetchone(), ('en',))
        database.close()

    def test_python_sources_compile(self):
        for path in (ROOT / 'app').rglob('*.py'):
            with self.subTest(path=path):
                compile(path.read_text(), str(path), 'exec')


if __name__ == '__main__':
    unittest.main()
