import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
from i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language, t

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID_RAW = os.getenv("ADMIN_CHAT_ID", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not ADMIN_CHAT_ID_RAW:
    raise RuntimeError("ADMIN_CHAT_ID is not set")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW)
except ValueError as exc:
    raise RuntimeError("ADMIN_CHAT_ID must be an integer Telegram chat ID") from exc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("support-bot")

LANG_CALLBACK_PREFIX = "setlang:"


def language_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(t("language_button_ru", None), callback_data=f"{LANG_CALLBACK_PREFIX}ru"),
        InlineKeyboardButton(t("language_button_tk", None), callback_data=f"{LANG_CALLBACK_PREFIX}tk"),
    ]
    return InlineKeyboardMarkup([buttons])


async def get_lang_for_chat(chat_id: int) -> str:
    lang = await db.get_user_language(chat_id)
    return normalize_language(lang)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or update.effective_chat is None:
        return

    if update.effective_chat.type != ChatType.PRIVATE:
        return

    chat = update.effective_chat
    user = update.effective_user

    await db.upsert_user(
        chat_id=chat.id,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
    )

    existing_lang = await db.get_user_language(chat.id)

    if existing_lang is None:
        # Prefill with Telegram's reported language, but still ask explicitly.
        await update.effective_message.reply_text(
            t("language_prompt", None),
            reply_markup=language_keyboard(),
        )
        return

    lang = normalize_language(existing_lang)
    if chat.id == ADMIN_CHAT_ID:
        await update.effective_message.reply_text(t("start_admin", lang))
    else:
        await update.effective_message.reply_text(t("start_user", lang))


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or update.effective_chat is None:
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    await update.effective_message.reply_text(
        t("language_prompt", None),
        reply_markup=language_keyboard(),
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or update.effective_chat is None:
        return

    await query.answer()

    if not query.data.startswith(LANG_CALLBACK_PREFIX):
        return

    lang_code = query.data[len(LANG_CALLBACK_PREFIX):]
    if lang_code not in SUPPORTED_LANGUAGES:
        lang_code = DEFAULT_LANGUAGE

    chat_id = update.effective_chat.id
    await db.set_user_language(chat_id, lang_code)

    await query.edit_message_text(t("language_set", lang_code))

    if chat_id == ADMIN_CHAT_ID:
        await context.bot.send_message(chat_id=chat_id, text=t("start_admin", lang_code))
    else:
        await context.bot.send_message(chat_id=chat_id, text=t("start_user", lang_code))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or update.effective_chat is None:
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    chat_id = update.effective_chat.id
    lang = await get_lang_for_chat(chat_id)

    if chat_id == ADMIN_CHAT_ID:
        await update.effective_message.reply_text(t("help_admin", lang))
    else:
        await update.effective_message.reply_text(t("help_user", lang))


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or update.effective_chat is None:
        return
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return

    lang = await get_lang_for_chat(update.effective_chat.id)
    stats = await db.get_user_stats()
    await update.effective_message.reply_text(t("stats_message", lang, **stats))


def _user_display_name(update: Update) -> str:
    user = update.effective_user
    if user is None:
        return "unknown"
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    lang = await get_lang_for_chat(chat_id)

    user = update.effective_user
    await db.upsert_user(
        chat_id=chat_id,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=t("new_ticket_notification", await get_lang_for_chat(ADMIN_CHAT_ID), user_display=_user_display_name(update)),
        )
        forwarded = await context.bot.forward_message(
            chat_id=ADMIN_CHAT_ID,
            from_chat_id=chat_id,
            message_id=message.message_id,
        )
        await db.save_message_mapping(forwarded.message_id, chat_id, message.message_id)
        await message.reply_text(t("message_forwarded_to_support", lang))
    except TelegramError:
        logger.exception("Failed to forward user message to admin")
        await message.reply_text(t("message_forward_failed", lang))


async def send_admin_reply_to_user(context: ContextTypes.DEFAULT_TYPE, user_chat_id: int, reply: Update) -> bool:
    """Returns True if the message type was recognized and sent, False otherwise."""
    message = reply.effective_message
    if message is None:
        return False

    bot = context.bot

    if message.text:
        await bot.send_message(
            chat_id=user_chat_id,
            text=message.text,
            entities=message.entities,
        )
        return True

    if message.photo:
        await bot.send_photo(
            chat_id=user_chat_id,
            photo=message.photo[-1].file_id,
            caption=message.caption,
            caption_entities=message.caption_entities,
        )
        return True

    if message.video:
        await bot.send_video(
            chat_id=user_chat_id,
            video=message.video.file_id,
            caption=message.caption,
            caption_entities=message.caption_entities,
        )
        return True

    if message.document:
        await bot.send_document(
            chat_id=user_chat_id,
            document=message.document.file_id,
            caption=message.caption,
            caption_entities=message.caption_entities,
        )
        return True

    if message.audio:
        await bot.send_audio(
            chat_id=user_chat_id,
            audio=message.audio.file_id,
            caption=message.caption,
            caption_entities=message.caption_entities,
        )
        return True

    if message.voice:
        await bot.send_voice(
            chat_id=user_chat_id,
            voice=message.voice.file_id,
            caption=message.caption,
            caption_entities=message.caption_entities,
        )
        return True

    if message.animation:
        await bot.send_animation(
            chat_id=user_chat_id,
            animation=message.animation.file_id,
            caption=message.caption,
            caption_entities=message.caption_entities,
        )
        return True

    if message.video_note:
        await bot.send_video_note(
            chat_id=user_chat_id,
            video_note=message.video_note.file_id,
        )
        return True

    if message.sticker:
        await bot.send_sticker(
            chat_id=user_chat_id,
            sticker=message.sticker.file_id,
        )
        return True

    if message.contact:
        await bot.send_contact(
            chat_id=user_chat_id,
            phone_number=message.contact.phone_number,
            first_name=message.contact.first_name,
            last_name=message.contact.last_name,
            vcard=message.contact.vcard,
        )
        return True

    if message.location:
        await bot.send_location(
            chat_id=user_chat_id,
            latitude=message.location.latitude,
            longitude=message.location.longitude,
            horizontal_accuracy=message.location.horizontal_accuracy,
            live_period=message.location.live_period,
            heading=message.location.heading,
            proximity_alert_radius=message.location.proximity_alert_radius,
        )
        return True

    if message.venue:
        await bot.send_venue(
            chat_id=user_chat_id,
            latitude=message.venue.location.latitude,
            longitude=message.venue.location.longitude,
            title=message.venue.title,
            address=message.venue.address,
            foursquare_id=message.venue.foursquare_id,
            foursquare_type=message.venue.foursquare_type,
            google_place_id=message.venue.google_place_id,
            google_place_type=message.venue.google_place_type,
        )
        return True

    if message.poll:
        poll = message.poll
        await bot.send_poll(
            chat_id=user_chat_id,
            question=poll.question,
            options=[option.text for option in poll.options],
            is_anonymous=poll.is_anonymous,
            allows_multiple_answers=poll.allows_multiple_answers,
            type=poll.type,
            explanation=poll.explanation,
            correct_option_id=poll.correct_option_id,
        )
        return True

    return False


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    admin_lang = await get_lang_for_chat(ADMIN_CHAT_ID)

    if not message.reply_to_message:
        if message.text and message.text.startswith("/"):
            return
        await message.reply_text(t("admin_reply_no_target", admin_lang))
        return

    replied_to = message.reply_to_message
    mapping = await db.get_message_mapping(replied_to.message_id)
    if mapping is None:
        await message.reply_text(t("admin_mapping_not_found", admin_lang))
        return

    user_chat_id, _ = mapping
    user_lang = await get_lang_for_chat(user_chat_id)

    try:
        handled = await send_admin_reply_to_user(context, user_chat_id, update)
        if handled:
            await message.reply_text(t("admin_reply_sent", admin_lang))
        else:
            await context.bot.send_message(chat_id=user_chat_id, text=t("unsupported_message_type", user_lang))
            await message.reply_text(t("admin_unsupported_message_type", admin_lang))
    except TelegramError:
        logger.exception("Failed to send admin reply to user")
        await message.reply_text(t("admin_reply_failed", admin_lang))


async def private_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or chat.type != ChatType.PRIVATE:
        return

    if chat.id == ADMIN_CHAT_ID:
        await handle_admin_message(update, context)
    else:
        await handle_user_message(update, context)


async def post_init(application) -> None:
    await db.init_pool(DATABASE_URL)
    logger.info("Bot initialized, supported languages: %s", SUPPORTED_LANGUAGES)


async def post_shutdown(application) -> None:
    await db.close_pool()


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(language_callback, pattern=f"^{LANG_CALLBACK_PREFIX}"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.ALL, private_router))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
