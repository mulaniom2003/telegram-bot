"""
Telegram Bot - Full Featured Broadcaster
=========================================
Sends text, media, documents, and audio to groups/channels.
Supports admin-only access, captions, multi-chat broadcasting,
scheduled messages, and selective chat targeting.

Usage:
    python bot.py
"""

import os
import json
import logging
import asyncio
import functools
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ─────────────────────────────────────────────
# 1. LOAD ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set. Check your .env file.")

ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [
    int(uid.strip()) for uid in ADMIN_IDS_RAW.split(",") if uid.strip().isdigit()
]

# ─────────────────────────────────────────────
# 2. LOGGING SETUP
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 3. CONFIG — TARGET GROUPS / CHANNELS
# ─────────────────────────────────────────────
CONFIG_FILE = Path("config.json")
SCHEDULES_FILE = Path("schedules.json")

def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "target_chats": [],
        "description": "Add chat IDs (negative for groups, e.g. -1001234567890)"
    }

def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

def load_schedules() -> list:
    if SCHEDULES_FILE.exists():
        with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_schedules(schedules: list) -> None:
    with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
        json.dump(schedules, f, indent=2)

# ─────────────────────────────────────────────
# 4. ADMIN GUARD DECORATOR
# ─────────────────────────────────────────────
def admin_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if ADMIN_IDS and user.id not in ADMIN_IDS:
            logger.warning(f"Unauthorized access by user {user.id} (@{user.username})")
            await update.message.reply_text(
                "❌ *Access Denied.* You are not authorized to use this bot.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        return await func(update, context)
    return wrapper

# ─────────────────────────────────────────────
# 5. BROADCAST HELPER
# ─────────────────────────────────────────────
async def broadcast(context: ContextTypes.DEFAULT_TYPE, send_fn, chat_ids: list) -> tuple[int, int]:
    """
    Send a message to multiple chats using send_fn.
    Includes a small delay between sends to respect Telegram rate limits.
    Returns (success_count, fail_count).
    """
    success, fail = 0, 0
    for chat_id in chat_ids:
        try:
            await send_fn(chat_id)
            success += 1
            logger.info(f"Sent to chat {chat_id}")
        except Exception as e:
            fail += 1
            logger.error(f"Failed to send to {chat_id}: {e}")
        await asyncio.sleep(0.05)  # Respect Telegram rate limits
    return success, fail

# ─────────────────────────────────────────────
# 6. RESOLVE TARGET CHATS HELPER
# ─────────────────────────────────────────────
def resolve_target_chats(args: list, all_chats: list) -> tuple[list, str]:
    """
    Parse optional --chats flag from command args.

    Usage in commands:
      /sendtext Hello everyone           → sends to ALL configured chats
      /sendtext --chats -100123,-100456 Hello  → sends to SELECTED chats only

    Returns (chat_ids_to_use, remaining_text_args_as_string)
    """
    if "--chats" not in args:
        return all_chats, " ".join(args)

    idx = args.index("--chats")
    # The value right after --chats is a comma-separated list of chat IDs
    if idx + 1 >= len(args):
        return all_chats, " ".join(args)

    raw_ids = args[idx + 1].split(",")
    selected = []
    for raw in raw_ids:
        try:
            selected.append(int(raw.strip()))
        except ValueError:
            pass

    # Remove --chats and the ID list from the remaining args
    remaining = args[:idx] + args[idx + 2:]
    return selected, " ".join(remaining)

# ─────────────────────────────────────────────
# 7. COMMAND HANDLERS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = (
        f"👋 Hello, *{user.first_name}*!\n\n"
        "I'm a Telegram broadcaster bot. Here's what I can do:\n\n"
        "📨 *Broadcast Commands:*\n"
        "`/sendtext` — Send plain or formatted text\n"
        "`/sendphoto` — Send an image with caption\n"
        "`/sendvideo` — Send a video with caption\n"
        "`/sendfile` — Send a document/file\n"
        "`/sendaudio` — Send an audio file\n"
        "`/sendsticker` — Send a sticker\n\n"
        "🕐 *Scheduled Messages:*\n"
        "`/schedule` — Schedule a text message\n"
        "`/listschedules` — View all scheduled messages\n"
        "`/cancelschedule` — Cancel a scheduled message\n\n"
        "🎯 *Selective Targeting:*\n"
        "Add `--chats id1,id2` to any send command to target specific chats.\n"
        "Example: `/sendtext --chats -1001234,-1005678 Hello!`\n\n"
        "⚙️ *Config Commands:*\n"
        "`/addchat <chat_id>` — Add a target chat\n"
        "`/removechat <chat_id>` — Remove a target chat\n"
        "`/listchats` — List all target chats\n"
        "`/myid` — Get your user ID\n"
        "`/chatid` — Get current chat ID\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"👤 Your Telegram User ID: `{user.id}`\n"
        f"Username: @{user.username or 'N/A'}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    await update.message.reply_text(
        f"💬 This Chat ID: `{chat.id}`\n"
        f"Type: `{chat.type}`\n"
        f"Title: `{chat.title or 'Private Chat'}`",
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def listchats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = load_config()
    chats = config.get("target_chats", [])
    if not chats:
        await update.message.reply_text(
            "📋 No target chats configured yet.\n"
            "Use `/addchat <chat_id>` to add one.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    lines = [f"• `{cid}`" for cid in chats]
    await update.message.reply_text(
        f"📋 *Target Chats ({len(chats)}):*\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def addchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: `/addchat <chat_id>`\nExample: `/addchat -1001234567890`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid chat ID. Must be a number.")
        return

    config = load_config()
    if chat_id in config["target_chats"]:
        await update.message.reply_text(f"⚠️ Chat `{chat_id}` is already in the list.", parse_mode=ParseMode.MARKDOWN)
        return

    config["target_chats"].append(chat_id)
    save_config(config)
    await update.message.reply_text(f"✅ Chat `{chat_id}` added successfully!", parse_mode=ParseMode.MARKDOWN)


@admin_only
async def removechat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: `/removechat <chat_id>`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid chat ID.")
        return

    config = load_config()
    if chat_id not in config["target_chats"]:
        await update.message.reply_text(f"⚠️ Chat `{chat_id}` not found in list.", parse_mode=ParseMode.MARKDOWN)
        return

    config["target_chats"].remove(chat_id)
    save_config(config)
    await update.message.reply_text(f"✅ Chat `{chat_id}` removed.", parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────
# 8. SEND COMMANDS (with Selective Targeting)
# ─────────────────────────────────────────────

@admin_only
async def sendtext(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /sendtext <message>
    /sendtext --chats -100123,-100456 <message>   ← selective targeting

    Supports HTML: <b>bold</b> <i>italic</i> <a href="url">link</a>
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: `/sendtext <your message>`\n"
            "Selective: `/sendtext --chats id1,id2 <message>`\n\n"
            "Supports HTML: `<b>bold</b>` `<i>italic</i>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    config = load_config()
    all_chats = config.get("target_chats", [])
    chat_ids, message_text = resolve_target_chats(context.args, all_chats)

    if not message_text.strip():
        await update.message.reply_text("❌ No message text provided.")
        return
    if not chat_ids:
        await update.message.reply_text("⚠️ No target chats. Use `/addchat` or provide `--chats`.", parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text(f"📤 Broadcasting to {len(chat_ids)} chat(s)...")

    async def send(chat_id):
        await context.bot.send_message(chat_id=chat_id, text=message_text, parse_mode=ParseMode.HTML)

    success, fail = await broadcast(context, send, chat_ids)
    await update.message.reply_text(f"✅ Done! Sent: {success} | Failed: {fail}")


@admin_only
async def sendphoto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /sendphoto [--chats id1,id2] [caption]
    Send photo to all or selected chats. Reply to a photo or send one with this as caption.
    """
    replied = update.message.reply_to_message
    photo = None
    args = context.args or []

    config = load_config()
    all_chats = config.get("target_chats", [])
    chat_ids, caption_text = resolve_target_chats(args, all_chats)
    caption = caption_text.strip() or None

    if replied and replied.photo:
        photo = replied.photo[-1].file_id
    elif update.message.photo:
        photo = update.message.photo[-1].file_id
    else:
        await update.message.reply_text(
            "📸 Send a photo with caption `/sendphoto [--chats id1,id2] caption`\n"
            "Or reply to a photo with `/sendphoto`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not chat_ids:
        await update.message.reply_text("⚠️ No target chats configured.")
        return

    await update.message.reply_text(f"📤 Broadcasting photo to {len(chat_ids)} chat(s)...")

    async def send(chat_id):
        await context.bot.send_photo(
            chat_id=chat_id, photo=photo, caption=caption,
            parse_mode=ParseMode.HTML if caption else None,
        )

    success, fail = await broadcast(context, send, chat_ids)
    await update.message.reply_text(f"✅ Done! Sent: {success} | Failed: {fail}")


@admin_only
async def sendvideo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    replied = update.message.reply_to_message
    video = None
    args = context.args or []

    config = load_config()
    all_chats = config.get("target_chats", [])
    chat_ids, caption_text = resolve_target_chats(args, all_chats)
    caption = caption_text.strip() or None

    if replied and replied.video:
        video = replied.video.file_id
    elif update.message.video:
        video = update.message.video.file_id
    else:
        await update.message.reply_text(
            "🎬 Send a video with caption `/sendvideo [--chats id1,id2] caption`\n"
            "Or reply to a video with `/sendvideo`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not chat_ids:
        await update.message.reply_text("⚠️ No target chats configured.")
        return

    await update.message.reply_text(f"📤 Broadcasting video to {len(chat_ids)} chat(s)...")

    async def send(chat_id):
        await context.bot.send_video(
            chat_id=chat_id, video=video, caption=caption,
            parse_mode=ParseMode.HTML if caption else None,
        )

    success, fail = await broadcast(context, send, chat_ids)
    await update.message.reply_text(f"✅ Done! Sent: {success} | Failed: {fail}")


@admin_only
async def sendfile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    replied = update.message.reply_to_message
    document = None
    args = context.args or []

    config = load_config()
    all_chats = config.get("target_chats", [])
    chat_ids, caption_text = resolve_target_chats(args, all_chats)
    caption = caption_text.strip() or None

    if replied and replied.document:
        document = replied.document.file_id
    elif update.message.document:
        document = update.message.document.file_id
    else:
        await update.message.reply_text(
            "📁 Send a file with caption `/sendfile [--chats id1,id2] caption`\n"
            "Or reply to a file with `/sendfile`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not chat_ids:
        await update.message.reply_text("⚠️ No target chats configured.")
        return

    await update.message.reply_text(f"📤 Broadcasting file to {len(chat_ids)} chat(s)...")

    async def send(chat_id):
        await context.bot.send_document(
            chat_id=chat_id, document=document, caption=caption,
            parse_mode=ParseMode.HTML if caption else None,
        )

    success, fail = await broadcast(context, send, chat_ids)
    await update.message.reply_text(f"✅ Done! Sent: {success} | Failed: {fail}")


@admin_only
async def sendaudio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    replied = update.message.reply_to_message
    audio = None
    args = context.args or []

    config = load_config()
    all_chats = config.get("target_chats", [])
    chat_ids, caption_text = resolve_target_chats(args, all_chats)
    caption = caption_text.strip() or None

    if replied and replied.audio:
        audio = replied.audio.file_id
    elif replied and replied.voice:
        audio = replied.voice.file_id
    elif update.message.audio:
        audio = update.message.audio.file_id
    else:
        await update.message.reply_text(
            "🎵 Send an audio with caption `/sendaudio [--chats id1,id2] caption`\n"
            "Or reply to an audio with `/sendaudio`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not chat_ids:
        await update.message.reply_text("⚠️ No target chats configured.")
        return

    await update.message.reply_text(f"📤 Broadcasting audio to {len(chat_ids)} chat(s)...")

    async def send(chat_id):
        await context.bot.send_audio(
            chat_id=chat_id, audio=audio, caption=caption,
            parse_mode=ParseMode.HTML if caption else None,
        )

    success, fail = await broadcast(context, send, chat_ids)
    await update.message.reply_text(f"✅ Done! Sent: {success} | Failed: {fail}")


@admin_only
async def sendsticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    replied = update.message.reply_to_message
    sticker = None
    args = context.args or []

    config = load_config()
    all_chats = config.get("target_chats", [])
    chat_ids, _ = resolve_target_chats(args, all_chats)

    if replied and replied.sticker:
        sticker = replied.sticker.file_id
    elif update.message.sticker:
        sticker = update.message.sticker.file_id
    else:
        await update.message.reply_text(
            "🎭 Reply to a sticker with `/sendsticker [--chats id1,id2]`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not chat_ids:
        await update.message.reply_text("⚠️ No target chats configured.")
        return

    await update.message.reply_text(f"📤 Broadcasting sticker to {len(chat_ids)} chat(s)...")

    async def send(chat_id):
        await context.bot.send_sticker(chat_id=chat_id, sticker=sticker)

    success, fail = await broadcast(context, send, chat_ids)
    await update.message.reply_text(f"✅ Done! Sent: {success} | Failed: {fail}")


# ─────────────────────────────────────────────
# 9. SCHEDULED MESSAGES
# ─────────────────────────────────────────────

@admin_only
async def schedule_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Schedule a text message for a future time.

    Usage:
      /schedule <YYYY-MM-DD HH:MM> <message>
      /schedule <YYYY-MM-DD HH:MM> --chats id1,id2 <message>

    Times are in UTC. Examples:
      /schedule 2025-12-25 09:00 Merry Christmas everyone!
      /schedule 2025-06-01 14:30 --chats -1001234,-1005678 Hello selected chats!
    """
    if len(context.args) < 3:
        await update.message.reply_text(
            "📅 *Schedule a message:*\n\n"
            "`/schedule YYYY-MM-DD HH:MM <message>`\n\n"
            "*With selective chats:*\n"
            "`/schedule YYYY-MM-DD HH:MM --chats id1,id2 <message>`\n\n"
            "*Examples:*\n"
            "`/schedule 2025-12-25 09:00 Merry Christmas!`\n"
            "`/schedule 2025-06-01 14:30 --chats -100123 Hello!`\n\n"
            "⏰ All times are in UTC.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Parse date + time (first two args)
    date_str = context.args[0]
    time_str = context.args[1]
    remaining_args = list(context.args[2:])

    try:
        send_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        send_at = send_at.replace(tzinfo=timezone.utc)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid date/time format. Use `YYYY-MM-DD HH:MM`\n"
            "Example: `2025-12-25 09:00`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    now = datetime.now(timezone.utc)
    if send_at <= now:
        await update.message.reply_text("❌ Scheduled time must be in the future.")
        return

    config = load_config()
    all_chats = config.get("target_chats", [])
    chat_ids, message_text = resolve_target_chats(remaining_args, all_chats)

    if not message_text.strip():
        await update.message.reply_text("❌ No message text provided.")
        return
    if not chat_ids:
        await update.message.reply_text("⚠️ No target chats. Use `/addchat` or `--chats`.", parse_mode=ParseMode.MARKDOWN)
        return

    # Save the schedule
    schedules = load_schedules()
    schedule_id = int(now.timestamp() * 1000)  # Unique ms-based ID
    entry = {
        "id": schedule_id,
        "send_at": send_at.isoformat(),
        "message": message_text.strip(),
        "chat_ids": chat_ids,
        "created_by": update.effective_user.id,
        "sent": False,
    }
    schedules.append(entry)
    save_schedules(schedules)

    delay_secs = (send_at - now).total_seconds()
    hours = int(delay_secs // 3600)
    minutes = int((delay_secs % 3600) // 60)

    await update.message.reply_text(
        f"✅ *Message Scheduled!*\n\n"
        f"🆔 ID: `{schedule_id}`\n"
        f"📅 Send at: `{send_at.strftime('%Y-%m-%d %H:%M UTC')}`\n"
        f"⏳ In: {hours}h {minutes}m\n"
        f"💬 Chats: {len(chat_ids)}\n"
        f"📝 Message: _{message_text.strip()[:80]}{'...' if len(message_text) > 80 else ''}_\n\n"
        f"Use `/cancelschedule {schedule_id}` to cancel.",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Register the job with PTB's JobQueue
    context.job_queue.run_once(
        _send_scheduled,
        when=delay_secs,
        data=entry,
        name=str(schedule_id),
    )
    logger.info(f"Scheduled message {schedule_id} for {send_at.isoformat()}")


async def _send_scheduled(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Internal job callback: fires when a scheduled message is due."""
    entry = context.job.data
    schedule_id = entry["id"]
    message_text = entry["message"]
    chat_ids = entry["chat_ids"]

    logger.info(f"Firing scheduled message {schedule_id} to {len(chat_ids)} chats")

    async def send(chat_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=ParseMode.HTML,
        )

    success, fail = await broadcast(context, send, chat_ids)

    # Mark as sent in schedules.json
    schedules = load_schedules()
    for s in schedules:
        if s["id"] == schedule_id:
            s["sent"] = True
            s["sent_at"] = datetime.now(timezone.utc).isoformat()
            break
    save_schedules(schedules)

    # Notify admins
    report = (
        f"🕐 *Scheduled message sent!*\n"
        f"🆔 ID: `{schedule_id}`\n"
        f"✅ Sent: {success} | ❌ Failed: {fail}\n"
        f"📝 _{message_text[:80]}{'...' if len(message_text) > 80 else ''}_"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=report, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass


@admin_only
async def list_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listschedules — Show all pending scheduled messages."""
    schedules = load_schedules()
    pending = [s for s in schedules if not s.get("sent")]

    if not pending:
        await update.message.reply_text("📅 No pending scheduled messages.")
        return

    lines = []
    for s in pending:
        send_at = datetime.fromisoformat(s["send_at"]).strftime("%Y-%m-%d %H:%M UTC")
        preview = s["message"][:50] + ("..." if len(s["message"]) > 50 else "")
        lines.append(
            f"🆔 `{s['id']}`\n"
            f"📅 {send_at}\n"
            f"💬 {len(s['chat_ids'])} chat(s)\n"
            f"📝 _{preview}_"
        )

    await update.message.reply_text(
        f"📅 *Pending Schedules ({len(pending)}):*\n\n" + "\n\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cancel_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cancelschedule <id> — Cancel a scheduled message."""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/cancelschedule <schedule_id>`\n"
            "Find the ID with `/listschedules`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        schedule_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    schedules = load_schedules()
    found = False
    for s in schedules:
        if s["id"] == schedule_id and not s.get("sent"):
            s["sent"] = True
            s["cancelled"] = True
            found = True
            break

    if not found:
        await update.message.reply_text(f"⚠️ Schedule `{schedule_id}` not found or already sent.", parse_mode=ParseMode.MARKDOWN)
        return

    save_schedules(schedules)

    # Remove job from PTB's JobQueue
    jobs = context.job_queue.get_jobs_by_name(str(schedule_id))
    for job in jobs:
        job.schedule_removal()

    await update.message.reply_text(f"✅ Schedule `{schedule_id}` cancelled.", parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Cancelled schedule {schedule_id}")


# ─────────────────────────────────────────────
# 10. ERROR HANDLER
# ─────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)
    error_msg = f"⚠️ *Bot Error:*\n`{type(context.error).__name__}: {context.error}`"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=error_msg, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass


# ─────────────────────────────────────────────
# 11. RESTORE PENDING SCHEDULES ON STARTUP
# ─────────────────────────────────────────────
async def restore_schedules(app: Application) -> None:
    """
    On bot startup, reload any pending schedules from schedules.json
    and re-register them with the JobQueue so they survive restarts.
    """
    schedules = load_schedules()
    now = datetime.now(timezone.utc)
    restored = 0

    for entry in schedules:
        if entry.get("sent") or entry.get("cancelled"):
            continue
        send_at = datetime.fromisoformat(entry["send_at"])
        delay = (send_at - now).total_seconds()

        if delay <= 0:
            # Missed while bot was offline — send immediately
            logger.warning(f"Schedule {entry['id']} was missed, sending now.")
            delay = 1

        app.job_queue.run_once(
            _send_scheduled,
            when=delay,
            data=entry,
            name=str(entry["id"]),
        )
        restored += 1

    if restored:
        logger.info(f"Restored {restored} pending schedule(s) from schedules.json")


# ─────────────────────────────────────────────
# 12. BOT STARTUP
# ─────────────────────────────────────────────
def main() -> None:
    logger.info("Starting Telegram Broadcaster Bot...")

    if not CONFIG_FILE.exists():
        save_config({"target_chats": [], "description": "Add chat IDs here"})
        logger.info("Created default config.json")

    if not SCHEDULES_FILE.exists():
        save_schedules([])
        logger.info("Created default schedules.json")

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Register command handlers ──────────────────
    app.add_handler(CommandHandler("start",           start))
    app.add_handler(CommandHandler("help",            start))
    app.add_handler(CommandHandler("myid",            myid))
    app.add_handler(CommandHandler("chatid",          chatid))
    app.add_handler(CommandHandler("listchats",       listchats))
    app.add_handler(CommandHandler("addchat",         addchat))
    app.add_handler(CommandHandler("removechat",      removechat))
    app.add_handler(CommandHandler("sendtext",        sendtext))
    app.add_handler(CommandHandler("sendphoto",       sendphoto))
    app.add_handler(CommandHandler("sendvideo",       sendvideo))
    app.add_handler(CommandHandler("sendfile",        sendfile))
    app.add_handler(CommandHandler("sendaudio",       sendaudio))
    app.add_handler(CommandHandler("sendsticker",     sendsticker))
    app.add_handler(CommandHandler("schedule",        schedule_message))
    app.add_handler(CommandHandler("listschedules",   list_schedules))
    app.add_handler(CommandHandler("cancelschedule",  cancel_schedule))

    # ── Handle media sent directly with caption commands ──
    app.add_handler(MessageHandler(filters.PHOTO & filters.Caption(["/sendphoto"]),      sendphoto))
    app.add_handler(MessageHandler(filters.VIDEO & filters.Caption(["/sendvideo"]),      sendvideo))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.Caption(["/sendfile"]), sendfile))
    app.add_handler(MessageHandler(filters.AUDIO & filters.Caption(["/sendaudio"]),      sendaudio))

    # ── Error handler ──────────────────────────────
    app.add_error_handler(error_handler)

    # ── Restore pending schedules on startup ──────
    app.post_init = restore_schedules

    logger.info("Bot is running. Press Ctrl+C to stop.")
    logger.info(f"Admin IDs: {ADMIN_IDS if ADMIN_IDS else 'None set (open access)'}")

    # Python 3.12+ no longer auto-creates an event loop; set one explicitly.
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
