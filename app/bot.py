from __future__ import annotations

from app.services.i18n import t, language_context

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal, engine
from app.handlers.language import router as language_router
from app.services.user_service import get_or_create_user
from app.handlers.admin import router as admin_router
from app.handlers.payments import router as payments_router
from app.handlers.polls import router as polls_router
from app.handlers.start import router as start_router
from app.handlers.subscriptions import router as subscriptions_router
from app.models import Base, Payment, PaymentMethod, PaymentStatus
from app.seed import seed_plans
from app.services.order_service import fulfill_subscription_payment
from app.services.payment_service import sync_crypto_payment_status
from app.services.subscription_service import expire_due_subscriptions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

settings = get_settings()


def register_routers(dp: Dispatcher) -> None:
    dp.include_router(language_router)
    dp.include_router(start_router)
    dp.include_router(admin_router)
    dp.include_router(payments_router)
    dp.include_router(polls_router)
    dp.include_router(subscriptions_router)


async def ensure_schema() -> None:
    async with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect == "sqlite":
            rows = await conn.execute(text("PRAGMA table_info(payments)"))
            columns = {row[1] for row in rows.fetchall()}
        else:
            rows = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'payments'"
                )
            )
            columns = {row[0] for row in rows.fetchall()}

        if "payment_method" not in columns:
            await conn.execute(
                text("ALTER TABLE payments ADD COLUMN payment_method VARCHAR(50) DEFAULT 'stars' NOT NULL")
            )

        if dialect == "sqlite":
            rows = await conn.execute(text("PRAGMA table_info(users)"))
            user_columns = {row[1] for row in rows.fetchall()}
        else:
            rows = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'users' AND table_schema = current_schema()"
            ))
            user_columns = {row[0] for row in rows.fetchall()}
        if "language" not in user_columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN language VARCHAR(2) DEFAULT 'ru' NOT NULL"))


async def create_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await ensure_schema()

    async with SessionLocal() as session:
        await seed_plans(session)


async def expired_subscriptions_job(bot: Bot) -> None:
    async with SessionLocal() as session:
        expired_count = await expire_due_subscriptions(session, bot)
        if expired_count:
            logging.info("Expired subscriptions processed: %s", expired_count)


async def pending_crypto_payments_job(bot: Bot) -> None:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(Payment).where(
                Payment.status == PaymentStatus.PENDING,
                Payment.payment_method == PaymentMethod.CRYPTOBOT,
                Payment.provider_payment_charge_id.is_not(None),
            )
        )
        payments = list(rows)

        for payment in payments:
            try:
                payment, is_new = await sync_crypto_payment_status(session, payment)
                if payment is None or not is_new:
                    continue
                user, plan, subscription, access_links = await fulfill_subscription_payment(session, bot, payment)
                if user is None or plan is None or subscription is None:
                    continue
                with language_context(user.language):
                    links_text = "\n".join(access_links)
                    ends_at_text = subscription.ends_at.strftime("%Y-%m-%d %H:%M UTC")
                    access_label = t('Ссылка для входа') if len(access_links) == 1 else t('Ссылки для входа')
                    access_note = t('Ссылка одноразовая и ограничена по времени.') if len(access_links) == 1 else t('Каждая ссылка одноразовая и ограничена по времени.')
                    await bot.send_message(
                        user.telegram_id,
                        t('Оплата через CryptoBot подтверждена ✅\n\nТариф: {p0}\nПодписка активна до: {p1}\n\n{p2}:\n{p3}\n\n{p4}', p0=f'{t(plan.title)}', p1=f'{ends_at_text}', p2=f'{access_label}', p3=f'{links_text}', p4=f'{access_note}'),
                    )
            except Exception:
                logging.exception("Failed to process pending crypto payment id=%s", payment.id)


async def session_middleware(handler, event, data):
    async with SessionLocal() as session:
        data["session"] = session
        telegram_user = data.get("event_from_user")
        language = "ru"
        if telegram_user is not None:
            user = await get_or_create_user(session, telegram_user.id, telegram_user.username, telegram_user.full_name)
            language = user.language
        with language_context(language):
            return await handler(event, data)


async def main() -> None:
    await create_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(session_middleware)
    register_routers(dp)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        expired_subscriptions_job,
        trigger="interval",
        minutes=settings.check_expired_every_minutes,
        kwargs={"bot": bot},
    )
    if settings.crypto_pay_enabled:
        scheduler.add_job(
            pending_crypto_payments_job,
            trigger="interval",
            minutes=settings.check_pending_crypto_every_minutes,
            kwargs={"bot": bot},
        )
    scheduler.start()

    logging.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
