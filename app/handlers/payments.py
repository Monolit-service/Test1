from __future__ import annotations

from app.services.i18n import t, language_context

from decimal import Decimal, InvalidOperation
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import (
    after_purchase_keyboard,
    crypto_donation_keyboard,
    crypto_invoice_keyboard,
    donation_input_keyboard,
)
from app.config import get_settings
from app.models import PaymentMethod
from app.services.order_service import fulfill_subscription_payment
from app.services.payment_service import (
    approve_pre_checkout,
    create_crypto_donation_invoice,
    create_crypto_invoice_for_payment,
    create_pending_payment,
    get_payment_by_id,
    mark_payment_paid,
    send_donation_invoice,
    send_plan_invoice,
    sync_crypto_payment_status,
)
from app.services.plan_service import get_plan_by_id
from app.services.user_service import get_or_create_user

router = Router()
settings = get_settings()


class DonationStates(StatesGroup):
    waiting_stars_amount = State()
    waiting_crypto_amount = State()


async def _send_access_message(message: Message, session: AsyncSession, payment) -> None:
    user, plan, subscription, access_links = await fulfill_subscription_payment(session, message.bot, payment)
    if user is None or plan is None or subscription is None:
        await message.answer(t('Не удалось активировать подписку. Напиши администратору.'))
        return

    links_text = "\n".join(access_links)
    ends_at_text = subscription.ends_at.strftime("%Y-%m-%d %H:%M UTC")
    access_label = t('Ссылка для входа') if len(access_links) == 1 else t('Ссылки для входа')
    access_note = t('Ссылка одноразовая и ограничена по времени.') if len(access_links) == 1 else t('Каждая ссылка одноразовая и ограничена по времени.')
    if not access_links:
        links_text = t('Не удалось автоматически создать ссылку. Напиши администратору.')
        access_label = t('Доступ')
        access_note = ""

    text = (
        t('Оплата прошла успешно ✅\n\nТариф: {p0}\nПодписка активна до: {p1}\n\n{p2}:\n{p3}', p0=f'{t(plan.title)}', p1=f'{ends_at_text}', p2=f'{access_label}', p3=f'{links_text}')
    )
    if access_note:
        text += f"\n\n{access_note}"

    await message.answer(text, reply_markup=after_purchase_keyboard())


def _test_payments_allowed(telegram_id: int | None) -> bool:
    return settings.is_test_payments_enabled_for(telegram_id)


async def _simulate_successful_subscription_payment(message: Message, session: AsyncSession, payment, method_label: str) -> None:
    payment, is_new = await mark_payment_paid(
        session=session,
        payload=payment.payload,
        telegram_payment_charge_id=f"test-{method_label.lower()}-{payment.id}",
        provider_payment_charge_id=f"test-{method_label.lower()}-{payment.id}",
    )
    if payment is None:
        await message.answer(t('Не удалось найти тестовый платёж.'))
        return
    if not is_new:
        await message.answer(t('Этот тестовый платёж уже был обработан.'))
        return
    await message.answer(t('🧪 Тестовая оплата {p0} подтверждена.', p0=f'{escape(method_label)}'))
    await _send_access_message(message, session, payment)


@router.callback_query(F.data.startswith("buy_stars:"))
async def buy_stars_handler(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    plan_id = int(callback.data.split(":", maxsplit=1)[1])
    plan = await get_plan_by_id(session, plan_id)
    if plan is None or not plan.is_active:
        await callback.answer(t('Тариф не найден или отключён'), show_alert=True)
        return

    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    payment = await create_pending_payment(session, user, plan, payment_method=PaymentMethod.STARS)
    await send_plan_invoice(callback.message, payment, plan)
    await callback.answer()


@router.callback_query(F.data.startswith("buy_crypto:"))
async def buy_crypto_handler(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    plan_id = int(callback.data.split(":", maxsplit=1)[1])
    plan = await get_plan_by_id(session, plan_id)
    if plan is None or not plan.is_active:
        await callback.answer(t('Тариф не найден или отключён'), show_alert=True)
        return

    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    payment = await create_pending_payment(session, user, plan, payment_method=PaymentMethod.CRYPTOBOT)

    try:
        pay_url = await create_crypto_invoice_for_payment(session, payment, plan)
    except Exception as exc:
        await callback.answer(t('Не удалось создать счёт в CryptoBot'), show_alert=True)
        await callback.message.answer(t('Ошибка: <code>{p0}</code>', p0=f'{exc}'))
        return

    await callback.message.edit_text(
        t('Счёт создан. Оплати его в CryptoBot, затем нажми «Проверить оплату».\nЕсли оплата уже прошла, доступ выдастся автоматически или после ручной проверки.'),
        reply_markup=crypto_invoice_keyboard(pay_url, payment.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("check_crypto:"))
async def check_crypto_handler(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    payment_id = int(callback.data.split(":", maxsplit=1)[1])
    payment = await get_payment_by_id(session, payment_id)
    if payment is None or payment.payment_method != PaymentMethod.CRYPTOBOT:
        await callback.answer(t('Платёж не найден'), show_alert=True)
        return

    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    if payment.user_id != user.id:
        await callback.answer(t('Это не ваш платёж'), show_alert=True)
        return

    payment, is_new = await sync_crypto_payment_status(session, payment)
    if payment is None:
        await callback.answer(t('Платёж не найден'), show_alert=True)
        return

    if not is_new and payment.status != "paid":
        await callback.answer(t('Оплата ещё не подтверждена'), show_alert=True)
        return

    if is_new:
        await callback.message.edit_text(t('Оплата подтверждена, выдаю доступ…'))
        await _send_access_message(callback.message, session, payment)
    else:
        await callback.answer(t('Этот платёж уже был обработан'))

    await callback.answer()


@router.callback_query(F.data.startswith("test_pay:"))
async def test_payment_handler(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    if not _test_payments_allowed(callback.from_user.id if callback.from_user else None):
        await callback.answer(t('Тестовый режим оплаты выключен'), show_alert=True)
        return

    _, method, plan_id_raw = callback.data.split(":", maxsplit=2)
    plan_id = int(plan_id_raw)
    plan = await get_plan_by_id(session, plan_id)
    if plan is None or not plan.is_active:
        await callback.answer(t('Тариф не найден или отключён'), show_alert=True)
        return

    user = await get_or_create_user(
        session=session,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )

    payment_method = PaymentMethod.STARS if method == "stars" else PaymentMethod.CRYPTOBOT
    method_label = "Stars" if method == "stars" else "CryptoBot"
    payment = await create_pending_payment(session, user, plan, payment_method=payment_method)
    await _simulate_successful_subscription_payment(callback.message, session, payment, method_label)
    await callback.answer(t('Тестовая оплата обработана'))


@router.callback_query(F.data == "test_donate:stars")
async def test_donate_stars_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if not _test_payments_allowed(callback.from_user.id if callback.from_user else None):
        await callback.answer(t('Тестовый режим оплаты выключен'), show_alert=True)
        return

    await callback.message.edit_text(
        t('🧪 Тест доната Stars прошёл успешно.\n\nОу, это было красиво. Спасибо за донат! ⚡️\nОбожаю такую взаимность. Обещаю пустить эти ресурсы на создание еще более горячего контента для тебя💎'),
        reply_markup=after_purchase_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "test_donate:crypto")
async def test_donate_crypto_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if not _test_payments_allowed(callback.from_user.id if callback.from_user else None):
        await callback.answer(t('Тестовый режим оплаты выключен'), show_alert=True)
        return

    await callback.message.edit_text(
        t('🧪 Тест доната CryptoBot прошёл успешно.\n\nОу, это было красиво. Спасибо за донат! ⚡️\nОбожаю такую взаимность. Обещаю пустить эти ресурсы на создание еще более горячего контента для тебя💎'),
        reply_markup=after_purchase_keyboard(),
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery) -> None:
    await approve_pre_checkout(pre_checkout_query)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    successful_payment = message.successful_payment
    payload = successful_payment.invoice_payload

    if payload.startswith("donate:stars:"):
        parts = payload.split(":")
        amount = parts[3] if len(parts) > 3 else ""
        thanks_text = (
            t('Оу, это было красиво. Спасибо за донат! ⚡️\nОбожаю такую взаимность. Обещаю пустить эти ресурсы на создание еще более горячего контента для тебя💎')
        )
        if amount:
            thanks_text = (
                t('Оу, это было красиво. Спасибо за донат на {p0} ⭐! ⚡️\nОбожаю такую взаимность. Обещаю пустить эти ресурсы на создание еще более горячего контента для тебя💎', p0=f'{amount}')
            )
        await message.answer(thanks_text, reply_markup=after_purchase_keyboard())
        return

    payment, is_new = await mark_payment_paid(
        session=session,
        payload=payload,
        telegram_payment_charge_id=successful_payment.telegram_payment_charge_id,
        provider_payment_charge_id=successful_payment.provider_payment_charge_id,
    )

    if payment is None:
        await message.answer(t('Не удалось найти оплату. Напиши администратору.'))
        return

    if not is_new:
        await message.answer(t('Этот платёж уже был обработан ранее.'))
        return

    await _send_access_message(message, session, payment)


@router.callback_query(F.data == "donate:stars")
async def donate_stars_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DonationStates.waiting_stars_amount)
    await callback.message.edit_text(
        t('Введи сумму доната в звёздах одним сообщением.\n\nНапример: <code>250</code>'),
        reply_markup=donation_input_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "donate:crypto")
async def donate_crypto_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DonationStates.waiting_crypto_amount)
    await callback.message.edit_text(
        t('Введи сумму доната через CryptoBot одним сообщением.\n\nНапример: <code>5</code> или <code>12.5</code>.'),
        reply_markup=donation_input_keyboard(),
    )
    await callback.answer()


@router.message(DonationStates.waiting_stars_amount)
async def donate_stars_amount_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() in {"отмена", "/cancel", "cancel"}:
        await state.clear()
        await message.answer(t('Донат отменён.'))
        return

    if not text.isdigit():
        await message.answer(t('Введи целое число звёзд, например: <code>250</code>.'))
        return

    amount = int(text)
    if amount <= 0:
        await message.answer(t('Сумма должна быть больше нуля.'))
        return
    if amount > 250000:
        await message.answer(t('Слишком большая сумма. Введи сумму поменьше.'))
        return

    await state.clear()
    await send_donation_invoice(message, amount)


@router.message(DonationStates.waiting_crypto_amount)
async def donate_crypto_amount_handler(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().replace(",", ".")
    if text.lower() in {"отмена", "/cancel", "cancel"}:
        await state.clear()
        await message.answer(t('Донат отменён.'))
        return

    try:
        amount = Decimal(text)
    except InvalidOperation:
        await message.answer(t('Введи сумму числом, например: <code>5</code> или <code>12.5</code>.'))
        return

    if amount <= 0:
        await message.answer(t('Сумма должна быть больше нуля.'))
        return
    if amount > Decimal("100000"):
        await message.answer(t('Слишком большая сумма. Введи сумму поменьше.'))
        return

    amount_str = format(amount.normalize(), "f") if amount == amount.normalize() else format(amount, "f")
    await state.clear()

    try:
        pay_url = await create_crypto_donation_invoice(amount_str)
    except Exception as exc:
        await message.answer(t('Не удалось создать донат-счёт: <code>{p0}</code>', p0=f'{exc}'))
        return

    await message.answer(
        t('Спасибо за поддержку ❤️\nОткрой счёт в CryptoBot и отправь донат.'),
        reply_markup=crypto_donation_keyboard(pay_url),
    )
