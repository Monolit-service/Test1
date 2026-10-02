from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.keyboards import main_menu
from app.services.admin_service import is_admin_user
from app.services.i18n import language_context
from app.services.user_service import get_or_create_user
from app.utils.text import format_welcome_text

router = Router()


def language_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text='🇷🇺 Русский', callback_data='language:ru')
    builder.button(text='🇬🇧 English', callback_data='language:en')
    builder.button(text='🏠 Меню / Menu', callback_data='menu')
    builder.adjust(2, 1)
    return builder.as_markup()


@router.message(Command('language', 'lang'))
async def language_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer('🌐 Выберите язык / Choose language:', reply_markup=language_keyboard())


@router.callback_query(F.data == 'change_language')
async def choose_language(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text('🌐 Выберите язык / Choose language:', reply_markup=language_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith('language:'))
async def set_language(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    language = callback.data.split(':', 1)[1]
    if language not in ('ru', 'en'):
        await callback.answer('Unknown language', show_alert=True)
        return
    user = await get_or_create_user(session, callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    user.language = language
    await session.commit()
    await state.clear()
    settings = get_settings()
    with language_context(language):
        await callback.message.edit_text(
            format_welcome_text(settings.channel_1_name, settings.channel_2_name),
            reply_markup=main_menu(is_admin=is_admin_user(callback.from_user.id)),
        )
    await callback.answer('🇬🇧 Language changed to English.' if language == 'en' else '🇷🇺 Язык изменён на русский.')
