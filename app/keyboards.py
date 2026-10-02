from __future__ import annotations

from app.services.i18n import t, language_context

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import get_settings
from app.models import Plan, Poll
from app.services.payment_service import crypto_price_for_plan
from app.services.poll_service import PollStats

settings = get_settings()

MAIN_MENU_TEXT = "🏠 Главное меню"
MAIN_MENU_CALLBACK = "menu"


def add_main_menu_button(builder: InlineKeyboardBuilder) -> None:
    builder.button(text=t(MAIN_MENU_TEXT), callback_data=MAIN_MENU_CALLBACK)


def main_menu(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t('🔐 Хочу в приват'), callback_data="show_plans")
    builder.button(text=t('❓ Задать смелый вопрос'), callback_data="ask_bold_question")
    builder.button(text=t('💳 Поддержка автора'), callback_data="show_donations")
    if settings.external_bot_url:
        builder.button(text="🔌 MonoliteVPN", url=settings.external_bot_url)
    if is_admin:
        builder.button(text=t('🛠 Админ-панель'), callback_data="admin_panel")
    builder.button(text=t("🌐 Сменить язык"), callback_data="change_language")
    builder.adjust(1)
    return builder.as_markup()


def plans_keyboard(plans: list[Plan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.button(
            text=f"{t(plan.title)} — {plan.price_xtr} ⭐",
            callback_data=f"plan:{plan.id}",
        )
    builder.button(text=t('👤 Мой профиль'), callback_data="my_profile")
    builder.button(text=t('💝 Донаты'), callback_data="show_donations")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def plan_payment_keyboard(plan: Plan, *, allow_test_buttons: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t('⭐ Оплатить за {p0} XTR', p0=f'{plan.price_xtr}'), callback_data=f"buy_stars:{plan.id}")
    if settings.crypto_pay_enabled:
        crypto_price = crypto_price_for_plan(plan)
        builder.button(
            text=f"🪙 CryptoBot · {crypto_price} {settings.crypto_pay_asset}",
            callback_data=f"buy_crypto:{plan.id}",
        )
    if allow_test_buttons:
        builder.button(text=t('🧪 Тест Stars'), callback_data=f"test_pay:stars:{plan.id}")
        if settings.crypto_pay_enabled:
            builder.button(text=t('🧪 Тест CryptoBot'), callback_data=f"test_pay:crypto:{plan.id}")
    builder.button(text=t('⬅️ К тарифам'), callback_data="show_plans")
    builder.button(text=t('👤 Мой профиль'), callback_data="my_profile")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def crypto_invoice_keyboard(pay_url: str, payment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t('🪙 Открыть счёт CryptoBot'), url=pay_url)
    builder.button(text=t('✅ Проверить оплату'), callback_data=f"check_crypto:{payment_id}")
    builder.button(text=t('⬅️ К тарифам'), callback_data="show_plans")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def donation_methods_keyboard(*, allow_test_buttons: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t('⭐ Донат звёздами'), callback_data="donate:stars")
    if settings.crypto_pay_enabled:
        builder.button(text=t('🪙 Донат через CryptoBot'), callback_data="donate:crypto")
    if allow_test_buttons:
        builder.button(text=t('🧪 Тест доната Stars'), callback_data="test_donate:stars")
        if settings.crypto_pay_enabled:
            builder.button(text=t('🧪 Тест доната CryptoBot'), callback_data="test_donate:crypto")
    if settings.donate_url:
        builder.button(text=t('🔗 Внешняя ссылка на донат'), url=settings.donate_url)
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def donation_input_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t('⬅️ К донатам'), callback_data="show_donations")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def ask_question_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def crypto_donation_keyboard(pay_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t('🪙 Открыть донат-счёт'), url=pay_url)
    builder.button(text=t('⬅️ К донатам'), callback_data="show_donations")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def profile_keyboard(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t('💳 Купить/продлить'), callback_data="show_plans")
    builder.button(text=t('💝 Донаты'), callback_data="show_donations")
    builder.button(text=t('🔄 Обновить профиль'), callback_data="my_profile")
    if is_admin:
        builder.button(text=t('🛠 Админ-панель'), callback_data="admin_panel")
    add_main_menu_button(builder)
    builder.button(text=t("🌐 Сменить язык"), callback_data="change_language")
    builder.adjust(1)
    return builder.as_markup()


def after_purchase_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t('👤 Мой профиль'), callback_data="my_profile")
    builder.button(text=t('💳 Купить ещё'), callback_data="show_plans")
    builder.button(text=t('💝 Донаты'), callback_data="show_donations")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def admin_poll_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="1 ответ", callback_data="poll_create:single")
    builder.button(text="Несколько ответов", callback_data="poll_create:multiple")
    builder.button(text="❌ Отмена", callback_data="poll_create:cancel")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def admin_poll_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📣 Разослать опрос", callback_data="poll_publish")
    builder.button(text="❌ Отмена", callback_data="poll_create:cancel")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def admin_poll_close_keyboard(poll_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛑 Завершить опрос", callback_data=f"poll_admin_close:{poll_id}")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def poll_voting_keyboard(
    poll: Poll,
    *,
    selected_option_ids: set[int],
    stats: PollStats,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sorted_options = sorted(poll.options, key=lambda item: item.position)
    for option in sorted_options:
        selected_prefix = "✅ " if option.id in selected_option_ids else ""
        count = stats.option_counts.get(option.id, 0)
        builder.button(
            text=f"{selected_prefix}{option.text} · {count}",
            callback_data=f"poll_vote:{poll.id}:{option.id}",
        )
    builder.button(text=t('📊 Обновить результаты'), callback_data=f"poll_refresh:{poll.id}")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()




def admin_question_reply_keyboard(question_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Ответить", callback_data=f"answer_question:{question_id}")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()


def admin_question_answer_keyboard(question_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"answer_question_cancel:{question_id}")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()

def admin_panel_keyboard(*, is_busy: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Обновить статистику", callback_data="admin_stats")
    if not is_busy:
        builder.button(text="🗄 Скачать БД", callback_data="admin_backup")
    add_main_menu_button(builder)
    builder.adjust(1)
    return builder.as_markup()
