"""Integration checks with installed requirements; no Telegram/API calls."""
import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

# Use an isolated database and dummy credentials; never read the project's .env.
os.environ.update(BOT_TOKEN='123456:TEST_TOKEN', BOT_USERNAME='test_bot', CHANNEL_1_ID='-1001', DATABASE_URL='sqlite+aiosqlite:///:memory:', CRYPTO_PAY_TOKEN='', ADMIN_IDS='')
with patch('dotenv.load_dotenv'):
    from aiogram import Dispatcher
    from sqlalchemy import select
    from app.bot import create_db, register_routers, session_middleware
    from app.db import SessionLocal, engine
    from app.handlers.language import set_language
    from app.keyboards import main_menu, crypto_invoice_keyboard, plans_keyboard
    from app.models import User, Plan
    from app.services.i18n import language_context, t
    from app.services.payment_service import send_plan_invoice, send_donation_invoice
    from app.services.user_service import get_or_create_user
    from app.utils.text import format_welcome_text, format_profile_text


class BotLanguageTests(unittest.TestCase):
    def test_language_switch_and_persistence(self):
        async def run():
            await create_db()
            state = SimpleNamespace(clear=AsyncMock())
            callback = SimpleNamespace(data='language:en', from_user=SimpleNamespace(id=987, username='tester', full_name='Tester'), message=SimpleNamespace(edit_text=AsyncMock()), answer=AsyncMock())
            async with SessionLocal() as session:
                await set_language(callback, session, state)
            self.assertIn('Glad', callback.message.edit_text.call_args.args[0])
            async with SessionLocal() as session:
                user = await get_or_create_user(session, 987, 'tester', 'Tester')
                self.assertEqual(user.language, 'en')
                plans = list(await session.scalars(select(Plan)))
                with language_context(user.language):
                    self.assertIn('Glad', format_welcome_text('', ''))
                    self.assertIn('My profile', format_profile_text(user, []))
                    self.assertTrue(any(button.text == '🌐 Change language' for row in main_menu().inline_keyboard for button in row))
                    self.assertIn('Private', plans_keyboard(plans).inline_keyboard[0][0].text)
                    self.assertEqual(crypto_invoice_keyboard('https://example.com/pay', 1).inline_keyboard[1][0].text, '✅ Check payment')
                    message = SimpleNamespace(answer_invoice=AsyncMock(), from_user=SimpleNamespace(id=987))
                    await send_plan_invoice(message, SimpleNamespace(payload='test'), plans[0])
                    self.assertIn('Private', message.answer_invoice.call_args.kwargs['title'])
                    self.assertIn('Access', message.answer_invoice.call_args.kwargs['description'])
                    await send_donation_invoice(message, 250)
                    self.assertEqual(message.answer_invoice.call_args.kwargs['title'], 'Support the project')
            async def handler(event, data):
                self.assertEqual(t('🌐 Сменить язык'), '🌐 Change language')
                return 'ok'
            self.assertEqual(await session_middleware(handler, None, {'event_from_user': callback.from_user}), 'ok')
            self.assertEqual(t('🌐 Сменить язык'), '🌐 Сменить язык')
            # Invalid callback must not overwrite a saved preference.
            callback.data = 'language:fr'
            async with SessionLocal() as session:
                await set_language(callback, session, state)
                user = await session.scalar(select(User).where(User.telegram_id == 987))
                self.assertEqual(user.language, 'en')
            callback.data = 'language:ru'
            async with SessionLocal() as session:
                await set_language(callback, session, state)
            self.assertIn('Привет', callback.message.edit_text.call_args.args[0])
            dispatcher = Dispatcher()
            register_routers(dispatcher)
            self.assertEqual(dispatcher.sub_routers[0].name, __import__('app.handlers.language', fromlist=['router']).router.name)
            await engine.dispose()
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
