"""
Telegram Broadcaster Bot
========================
- Admin: full control, manages own chats, creates ad packages, approves users/payments
- Users: manage their own chats, buy ad packages to broadcast to admin's chats
"""

import os, json, logging, asyncio
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes, MessageHandler, filters

# ─────────────────────────────────────────────
# ENV & LOGGING
# ─────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set.")

ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip().isdigit()]

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO,
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")],
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# FILE I/O
# ─────────────────────────────────────────────
CONFIG_FILE   = Path("config.json")
SCHED_FILE    = Path("schedules.json")
USERS_FILE    = Path("users.json")
PKGS_FILE     = Path("ad_packages.json")

def _rw(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f: return json.load(f)
    return default

def _save(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)

def load_config():
    d = _rw(CONFIG_FILE, {})
    d.setdefault("target_chats", []); d.setdefault("chat_info", {}); d.setdefault("removed_chats", [])
    return d
def save_config(c): _save(CONFIG_FILE, c)

def load_schedules(): return _rw(SCHED_FILE, [])
def save_schedules(s): _save(SCHED_FILE, s)

def load_users():
    d = _rw(USERS_FILE, {})
    d.setdefault("approved", []); d.setdefault("pending", []); d.setdefault("denied", [])
    return d
def save_users(u): _save(USERS_FILE, u)

def load_packages(): return _rw(PKGS_FILE, [])
def save_packages(p): _save(PKGS_FILE, p)

# ─────────────────────────────────────────────
# ACCESS HELPERS
# ─────────────────────────────────────────────
def is_admin(uid): return not ADMIN_IDS or uid in ADMIN_IDS
def is_approved(uid):
    if is_admin(uid): return True
    return any(u["id"] == uid for u in load_users()["approved"])
def is_pending(uid): return any(u["id"] == uid for u in load_users()["pending"])

def get_approved_user(uid):
    return next((u for u in load_users()["approved"] if u["id"] == uid), None)

def get_user_chats(uid) -> list:
    """All chats a user can broadcast to."""
    if is_admin(uid):
        return load_config().get("target_chats", [])
    u = get_approved_user(uid)
    if not u: return []
    own = u.get("target_chats", [])
    ad_chats = []
    pkgs = load_packages()
    for pid in u.get("ad_packages", []):
        pkg = next((p for p in pkgs if p["id"] == pid and p.get("active", True)), None)
        if pkg: ad_chats.extend(pkg.get("chat_ids", []))
    seen, result = set(), []
    for cid in own + ad_chats:
        if cid not in seen: seen.add(cid); result.append(cid)
    return result

def get_user_chat_info(uid) -> dict:
    if is_admin(uid): return load_config().get("chat_info", {})
    u = get_approved_user(uid)
    if not u: return {}
    info = dict(u.get("chat_info", {}))
    for k, v in load_config().get("chat_info", {}).items():
        info.setdefault(k, v)
    return info

# ─────────────────────────────────────────────
# BUTTON LABELS
# ─────────────────────────────────────────────
B_BROADCAST = "📢 Broadcast"
B_CHATS     = "⚙️ Manage Chats"
B_MY_CHATS  = "📁 My Chats"
B_AD_PKGS   = "📦 Ad Packages"
B_SCHEDULES = "📅 Schedules"
B_INFO      = "ℹ️ My Info"
B_USERS     = "👥 Users"
B_BACK      = "◀️ Back"
B_TEXT      = "📝 Text";  B_PHOTO   = "🖼 Photo";  B_VIDEO   = "🎬 Video"
B_FILE      = "📁 File";  B_AUDIO   = "🎵 Audio";  B_STICKER = "🎭 Sticker"
B_ADD_CHAT  = "➕ Add Chat"; B_ACTIVE = "📋 Active Chats"; B_REMOVED = "🗑 Removed Chats"
B_NEW_SCHED = "➕ New Schedule"; B_VIEW_SCHED = "📋 View Schedules"
B_ADD_USER  = "➕ Add User"; B_APPR = "✅ Approved"; B_PEND = "⏳ Pending"
B_PKGS_MGT  = "📦 Ad Packages"
B_NEW_PKG   = "➕ Create Package"; B_VIEW_PKGS = "📋 View Packages"

ALL_BTNS = {B_BROADCAST,B_CHATS,B_MY_CHATS,B_AD_PKGS,B_SCHEDULES,B_INFO,B_USERS,B_BACK,
            B_TEXT,B_PHOTO,B_VIDEO,B_FILE,B_AUDIO,B_STICKER,
            B_ADD_CHAT,B_ACTIVE,B_REMOVED,B_NEW_SCHED,B_VIEW_SCHED,
            B_ADD_USER,B_APPR,B_PEND,B_PKGS_MGT,B_NEW_PKG,B_VIEW_PKGS}

# ─────────────────────────────────────────────
# PERSISTENT KEYBOARDS
# ─────────────────────────────────────────────
def kb_main(uid=0):
    admin = is_admin(uid)
    if admin:
        rows = [[B_BROADCAST, B_CHATS],[B_SCHEDULES, B_INFO],[B_USERS]]
    else:
        rows = [[B_BROADCAST, B_MY_CHATS],[B_AD_PKGS, B_SCHEDULES],[B_INFO]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_broadcast():  return ReplyKeyboardMarkup([[B_TEXT,B_PHOTO,B_VIDEO],[B_FILE,B_AUDIO,B_STICKER],[B_BACK]], resize_keyboard=True)
def kb_chats():      return ReplyKeyboardMarkup([[B_ADD_CHAT],[B_ACTIVE,B_REMOVED],[B_BACK]], resize_keyboard=True)
def kb_schedules():  return ReplyKeyboardMarkup([[B_NEW_SCHED,B_VIEW_SCHED],[B_BACK]], resize_keyboard=True)
def kb_users():      return ReplyKeyboardMarkup([[B_ADD_USER],[B_APPR,B_PEND],[B_PKGS_MGT],[B_BACK]], resize_keyboard=True)
def kb_pkgs_mgt():   return ReplyKeyboardMarkup([[B_NEW_PKG,B_VIEW_PKGS],[B_BACK]], resize_keyboard=True)
def kb_cancel():     return ReplyKeyboardMarkup([[B_BACK]], resize_keyboard=True)

# ─────────────────────────────────────────────
# INLINE HELPERS
# ─────────────────────────────────────────────
def _label(cid, chat_info):
    info = chat_info.get(str(cid), {})
    title = info.get("title") or str(cid)
    e = {"channel":"📢","group":"👥","supergroup":"👥","private":"👤"}.get(info.get("type",""),"💬")
    return f"{e} {title}"

def inline_chats(active, removed, chat_info, tab, rm_cb, ra_cb, tab_cb_a, tab_cb_r):
    rows = [[
        InlineKeyboardButton(f"📋 Active ({len(active)}) {'✓' if tab=='active' else ''}", callback_data=tab_cb_a),
        InlineKeyboardButton(f"🗑 Removed ({len(removed)}) {'✓' if tab=='removed' else ''}", callback_data=tab_cb_r),
    ]]
    if tab == "active":
        txt = f"📋 *Active ({len(active)})*\nTap ❌ to remove:" if active else "📋 *Active*\n\nNone yet."
        for cid in active:
            rows.append([InlineKeyboardButton(_label(cid,chat_info), callback_data="noop"), InlineKeyboardButton("❌", callback_data=f"{rm_cb}:{cid}")])
    else:
        txt = f"🗑 *Removed ({len(removed)})*\nTap ♻️ to re-add:" if removed else "🗑 *Removed*\n\nNone yet."
        for e in removed:
            rows.append([InlineKeyboardButton(_label(e["id"],chat_info), callback_data="noop"), InlineKeyboardButton("♻️", callback_data=f"{ra_cb}:{e['id']}")])
    return txt, InlineKeyboardMarkup(rows)

def inline_admin_chats(config, tab):
    return inline_chats(config["target_chats"], config["removed_chats"], config["chat_info"], tab, "rm","ra","ac:active","ac:removed")

def inline_user_chats(user, tab):
    return inline_chats(user.get("target_chats",[]), user.get("removed_chats",[]), user.get("chat_info",{}), tab, "urm","ura","uc:active","uc:removed")

def inline_approved_users():
    users = load_users()["approved"]
    if not users: return "✅ *Approved Users*\n\nNone yet.", InlineKeyboardMarkup([])
    rows = []
    for u in users:
        lbl = f"👤 {u.get('name',str(u['id']))}" + (f" (@{u['username']})" if u.get("username") else "")
        rows.append([InlineKeyboardButton(lbl,callback_data="noop"), InlineKeyboardButton("🚫 Revoke",callback_data=f"revoke:{u['id']}")])
    return f"✅ *Approved Users ({len(users)})*\n\nTap 🚫 to revoke:", InlineKeyboardMarkup(rows)

def inline_pending_users():
    pending = load_users()["pending"]
    if not pending: return "⏳ *Pending*\n\nNo requests.", InlineKeyboardMarkup([])
    rows = []
    for u in pending:
        lbl = f"👤 {u.get('name',str(u['id']))}" + (f" (@{u['username']})" if u.get("username") else "")
        rows.append([InlineKeyboardButton(lbl,callback_data="noop"), InlineKeyboardButton("✅",callback_data=f"approve:{u['id']}"), InlineKeyboardButton("❌",callback_data=f"deny:{u['id']}")])
    return f"⏳ *Pending ({len(pending)})*", InlineKeyboardMarkup(rows)

def inline_pkg_chat_selector(selected_ids: list):
    """Inline keyboard for admin to select which chats go into an ad package."""
    config = load_config()
    chats  = config.get("target_chats", [])
    info   = config.get("chat_info", {})
    if not chats:
        return "⚠️ No chats in your list yet. Add chats first.", InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancel", callback_data="pkg_cancel")]])
    rows = []
    for cid in chats:
        check = "✅" if cid in selected_ids else "⬜"
        rows.append([InlineKeyboardButton(f"{check} {_label(cid, info)}", callback_data=f"pkg_sel:{cid}")])
    rows.append([InlineKeyboardButton("✅ Create Package", callback_data="pkg_done"), InlineKeyboardButton("◀️ Cancel", callback_data="pkg_cancel")])
    return f"🎯 *Select chats for this package:*\n_{len(selected_ids)} selected_", InlineKeyboardMarkup(rows)

def inline_admin_packages():
    pkgs = load_packages()
    config = load_config()
    if not pkgs:
        return "📦 *Ad Packages*\n\nNo packages yet.", InlineKeyboardMarkup([])
    rows = []
    for p in pkgs:
        status = "🟢" if p.get("active", True) else "🔴"
        rows.append([
            InlineKeyboardButton(f"{status} {p['name']} — ${p['price']} USD", callback_data="noop"),
            InlineKeyboardButton("🔴" if p.get("active",True) else "🟢", callback_data=f"pkg_toggle:{p['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"pkg_del:{p['id']}"),
        ])
    return f"📦 *Ad Packages ({len(pkgs)})*\n\n🟢=active 🔴=paused", InlineKeyboardMarkup(rows)

def inline_user_packages(uid):
    pkgs = [p for p in load_packages() if p.get("active", True)]
    u    = get_approved_user(uid) or {}
    owned = u.get("ad_packages", [])
    pending_pays = [pp["pkg_id"] for pp in u.get("pending_payments", [])]
    config = load_config()
    info   = config.get("chat_info", {})

    if not pkgs:
        return "📦 *Ad Packages*\n\nNo packages available yet.", InlineKeyboardMarkup([])

    lines, rows = [], []
    for p in pkgs:
        chat_names = ", ".join(_label(cid, info) for cid in p.get("chat_ids", []))
        if p["id"] in owned:
            status = "✅ Active"
            btn_lbl, btn_cb = "✅ Owned", "noop"
        elif p["id"] in pending_pays:
            status = "⏳ Payment pending"
            btn_lbl, btn_cb = "⏳ Pending", "noop"
        else:
            status = f"💵 ${p['price']} USD"
            btn_lbl, btn_cb = "🛒 Buy", f"pkg_buy:{p['id']}"

        lines.append(f"*{p['name']}*\n  Chats: {chat_names or 'N/A'}\n  {status}")
        rows.append([InlineKeyboardButton(f"📦 {p['name']}", callback_data="noop"), InlineKeyboardButton(btn_lbl, callback_data=btn_cb)])

    return "📦 *Available Ad Packages*\n\n" + "\n\n".join(lines), InlineKeyboardMarkup(rows)

# ─────────────────────────────────────────────
# BROADCAST HELPER
# ─────────────────────────────────────────────
async def broadcast(context, send_fn, chat_ids):
    s, f = 0, 0
    for cid in chat_ids:
        try: await send_fn(cid); s += 1
        except Exception as e: f += 1; logger.error(f"Failed {cid}: {e}")
        await asyncio.sleep(0.05)
    return s, f

# ─────────────────────────────────────────────
# SHOW HELPERS
# ─────────────────────────────────────────────
async def show_main(msg, context, uid):
    context.user_data.clear()
    chats = get_user_chats(uid)
    await msg.reply_text(
        f"🤖 *Broadcaster Bot*\n\nAvailable chats: *{len(chats)}*\nChoose an option:",
        reply_markup=kb_main(uid), parse_mode=ParseMode.MARKDOWN,
    )

async def show_schedules(msg):
    pending = [s for s in load_schedules() if not s.get("sent")]
    if not pending:
        await msg.reply_text("📅 *Schedules*\n\nNone pending.", parse_mode=ParseMode.MARKDOWN); return
    lines = [f"• `{s['id']}` — {datetime.fromisoformat(s['send_at']).strftime('%d %b %H:%M UTC')}\n  _{s['message'][:40]}_" for s in pending]
    rows  = [[InlineKeyboardButton(f"❌ Cancel #{s['id']}", callback_data=f"sched_cancel:{s['id']}")] for s in pending]
    await msg.reply_text(f"📅 *Pending ({len(pending)})*\n\n" + "\n\n".join(lines), reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user = update.effective_user; uid = user.id
    chat = update.effective_chat

    # Group/channel context → redirect to private chat
    if chat and chat.type != "private":
        await update.message.reply_text(
            "👋 *Hey there!*\n\n"
            "I'm *CS Broadcast Bot* — a tool for broadcasting content to multiple chats.\n\n"
            "📩 Open me in private to get started:\n👉 @CS\_BroadcastBot\n\n"
            "💡 *To add this group to your broadcast list* — just type `/addhere`\n\n"
            "❓ *Support:* @CheekyXD",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if is_approved(uid):
        await show_main(update.message, context, uid); return
    if is_pending(uid):
        await update.message.reply_text("⏳ *Your request is pending.* The admin will review it shortly.", parse_mode=ParseMode.MARKDOWN); return
    await update.message.reply_text(
        "👋 *Welcome to CS Broadcast Bot!*\n\n"
        "This bot lets you broadcast messages to multiple Telegram chats at once.\n\n"
        "🔒 *This bot is private.* Tap below to request access.\n\n"
        "❓ *Support:* @CheekyXD",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📨 Request Access", callback_data=f"req:{uid}")]]),
        parse_mode=ParseMode.MARKDOWN,
    )

# ─────────────────────────────────────────────
# /about
# ─────────────────────────────────────────────
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    await update.message.reply_text(
        "🤖 *CS Broadcast Bot*\n\n"
        "A private broadcasting tool for sending messages, photos, videos and more to multiple Telegram chats at once.\n\n"
        "✅ Broadcast text, photos, videos, files, audio & stickers\n"
        "📅 Schedule messages in advance\n"
        "📦 Ad packages for approved users\n"
        "🔒 Private access — invite only\n\n"
        "📩 Start in private: @CS\_BroadcastBot\n"
        "❓ *Support:* @CheekyXD",
        parse_mode=ParseMode.MARKDOWN,
    )

# ─────────────────────────────────────────────
# /addhere — used inside a group to trigger add prompt
# ─────────────────────────────────────────────
async def addhere(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    uid  = user.id
    if chat.type == "private":
        await update.message.reply_text("ℹ️ Use this command *inside the group* you want to add.", parse_mode=ParseMode.MARKDOWN)
        return
    if not (is_admin(uid) or is_approved(uid)):
        await update.message.reply_text("🔒 You don't have access to this bot.", parse_mode=ParseMode.MARKDOWN)
        return
    cid   = chat.id
    cinfo = {"title": chat.title or str(cid), "type": chat.type}
    e     = {"channel": "📢", "group": "👥", "supergroup": "👥"}.get(chat.type, "💬")

    if is_admin(uid):
        config = load_config()
        if cid in config["target_chats"]:
            await update.message.reply_text("ℹ️ This chat is already in your list.")
            return
        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, Add", callback_data=f"gadd:{uid}:{cid}"),
            InlineKeyboardButton("❌ No",       callback_data=f"gdeny:{cid}"),
        ]])
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=aid,
                    text=f"🔔 *Add this chat to your list?*\n\n{e} *{cinfo['title']}*\n`{chat.type}` | ID: `{cid}`",
                    reply_markup=confirm_kb, parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as ex: logger.error(f"addhere notify failed: {ex}")
        await update.message.reply_text("✅ Check your private chat with me to confirm!")
    else:
        users_data = load_users()
        u2 = next((x for x in users_data["approved"] if x["id"] == uid), None)
        if u2 and cid in u2.get("target_chats", []):
            await update.message.reply_text("ℹ️ Already in your list.")
            return
        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, Add", callback_data=f"ugadd:{uid}:{cid}"),
            InlineKeyboardButton("❌ No",       callback_data=f"ugdeny:{cid}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"🔔 *Add this chat to your list?*\n\n{e} *{cinfo['title']}*\n`{chat.type}` | ID: `{cid}`",
                reply_markup=confirm_kb, parse_mode=ParseMode.MARKDOWN,
            )
            await update.message.reply_text("✅ Check your private chat with me to confirm!")
        except Exception as ex:
            await update.message.reply_text("❌ Couldn't reach you in private. Start the bot first: @CS_BroadcastBot")

# ─────────────────────────────────────────────
# ADD CHAT HELPER (shared logic)
# ─────────────────────────────────────────────
async def handle_add_chat(msg, context, raw: str, uid: int):
    """Resolves raw input to a chat and adds it to the correct list (admin→config, user→profile)."""
    admin = is_admin(uid)
    config = load_config() if admin else None
    users_data = None if admin else load_users()
    user_obj   = None if admin else next((u for u in users_data["approved"] if u["id"] == uid), None)

    def already_has(cid):
        if admin: return cid in config["target_chats"]
        return user_obj and cid in user_obj.get("target_chats", [])

    def do_add(cid, cinfo):
        if admin:
            config["target_chats"].append(cid)
            config.setdefault("chat_info", {})[str(cid)] = cinfo
            save_config(config)
        else:
            user_obj.setdefault("target_chats", []).append(cid)
            user_obj.setdefault("chat_info", {})[str(cid)] = cinfo
            save_users(users_data)

    # Normalise: extract invite hash or username from various link formats
    is_invite = False
    if "t.me/+" in raw:
        # Private invite link — keep as full URL for get_chat
        is_invite = True
        raw = raw if raw.startswith("https://") else "https://t.me/+" + raw.split("t.me/+")[-1].strip("/")
    elif "t.me/" in raw:
        raw = "@" + raw.split("t.me/")[-1].strip("/")

    if raw.lstrip("-").isdigit():
        cid = int(raw)
        if already_has(cid):
            await msg.reply_text(f"⚠️ `{cid}` already in your list.", parse_mode=ParseMode.MARKDOWN); return
        do_add(cid, {})
        context.user_data.pop("state", None)
        await msg.reply_text(f"✅ Chat `{cid}` added!", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_chats())
        return

    if not raw.startswith("@") and not is_invite: raw = "@" + raw
    label = "private invite link" if is_invite else f"`{raw}`"
    searching = await msg.reply_text(f"🔍 Looking up {label}…", parse_mode=ParseMode.MARKDOWN)
    try:
        chat = await context.bot.get_chat(raw)
    except Exception as e:
        if is_invite:
            await searching.edit_text(
                "❌ *Private invite links can't be looked up* — this is a Telegram API limitation.\n\n"
                "*To add this private group:*\n"
                "➡️ Add *@CS\_BroadcastBot* to the group (member is enough)\n"
                "➡️ You'll instantly get a *Yes / No* prompt here to add it",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await searching.edit_text(f"❌ Not found: `{raw}`\n`{e}`", parse_mode=ParseMode.MARKDOWN)
        return
    cid = chat.id
    if already_has(cid):
        await searching.edit_text(f"⚠️ *{chat.title or cid}* already in your list.", parse_mode=ParseMode.MARKDOWN); return
    cinfo = {"title": chat.title or chat.username or str(cid), "type": chat.type}
    do_add(cid, cinfo)
    context.user_data.pop("state", None)
    e2 = {"channel": "📢", "group": "👥", "supergroup": "👥", "private": "👤"}.get(chat.type, "💬")
    await searching.edit_text(f"✅ *{cinfo['title']}* added!\n{e2} `{chat.type}` | ID: `{cid}`", parse_mode=ParseMode.MARKDOWN)
    await msg.reply_text("⚙️ Chats", reply_markup=kb_chats(), parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────────────────────────
# MESSAGE HANDLER
# ─────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; uid = user.id; msg = update.message
    if not is_approved(uid): await start(update, context); return

    text  = msg.text or ""
    state = context.user_data.get("state")
    admin = is_admin(uid)

    if text == B_BACK:
        context.user_data.pop("state", None); context.user_data["menu"] = "main"
        await show_main(msg, context, uid); return

    # ── Awaiting input ─────────────────────────
    if state:
        chat_ids = get_user_chats(uid)

        async def do_broadcast(send_fn, label):
            if not chat_ids:
                no_chat_kb = kb_chats() if admin else kb_chats()
                await msg.reply_text("⚠️ No chats available. Add chats first.", reply_markup=no_chat_kb)
                context.user_data.clear(); return
            context.user_data.pop("state", None)
            st = await msg.reply_text(f"📤 Broadcasting {label} to {len(chat_ids)} chat(s)…")
            s, f = await broadcast(context, send_fn, chat_ids)
            await st.edit_text(f"✅ Done!  Sent: {s}  |  Failed: {f}")
            await show_main(msg, context, uid)

        if state == "await_text":
            if not text or text in ALL_BTNS: await msg.reply_text("❌ Type your message.", reply_markup=kb_cancel()); return
            async def send(cid): await context.bot.send_message(chat_id=cid, text=text, parse_mode=ParseMode.HTML)
            await do_broadcast(send, "text")

        elif state == "await_photo":
            if not msg.photo: await msg.reply_text("❌ Send a photo.", reply_markup=kb_cancel()); return
            fid,cap = msg.photo[-1].file_id, msg.caption or None
            async def send(cid): await context.bot.send_photo(chat_id=cid,photo=fid,caption=cap,parse_mode=ParseMode.HTML if cap else None)
            await do_broadcast(send,"photo")

        elif state == "await_video":
            if not msg.video: await msg.reply_text("❌ Send a video.", reply_markup=kb_cancel()); return
            fid,cap = msg.video.file_id, msg.caption or None
            async def send(cid): await context.bot.send_video(chat_id=cid,video=fid,caption=cap,parse_mode=ParseMode.HTML if cap else None)
            await do_broadcast(send,"video")

        elif state == "await_file":
            if not msg.document: await msg.reply_text("❌ Send a file.", reply_markup=kb_cancel()); return
            fid,cap = msg.document.file_id, msg.caption or None
            async def send(cid): await context.bot.send_document(chat_id=cid,document=fid,caption=cap,parse_mode=ParseMode.HTML if cap else None)
            await do_broadcast(send,"file")

        elif state == "await_audio":
            fid = (msg.audio and msg.audio.file_id) or (msg.voice and msg.voice.file_id)
            if not fid: await msg.reply_text("❌ Send an audio file.", reply_markup=kb_cancel()); return
            cap = msg.caption or None
            async def send(cid): await context.bot.send_audio(chat_id=cid,audio=fid,caption=cap,parse_mode=ParseMode.HTML if cap else None)
            await do_broadcast(send,"audio")

        elif state == "await_sticker":
            if not msg.sticker: await msg.reply_text("❌ Send a sticker.", reply_markup=kb_cancel()); return
            fid = msg.sticker.file_id
            async def send(cid): await context.bot.send_sticker(chat_id=cid,sticker=fid)
            await do_broadcast(send,"sticker")

        elif state == "await_add_chat":
            await handle_add_chat(msg, context, text.strip(), uid)

        elif state == "await_add_user":
            await _handle_add_user(msg, context, text.strip(), uid)

        elif state == "await_pkg_name":
            if not text or text in ALL_BTNS: await msg.reply_text("❌ Enter a package name.", reply_markup=kb_cancel()); return
            context.user_data["new_pkg"] = {"name": text.strip()}
            context.user_data["state"]   = "await_pkg_price"
            await msg.reply_text("💰 Enter price in *USD* (number only):\nExample: `10` or `25.50`", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN)

        elif state == "await_pkg_price":
            val = text.strip().replace("$", "").strip()
            if not val.replace(".", "").isdigit():
                await msg.reply_text("❌ Enter a number (USD only).\nExample: `10` or `25.50`", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN); return
            context.user_data["new_pkg"]["price"]    = val
            context.user_data["new_pkg"]["currency"] = "USD"
            context.user_data["state"] = "await_pkg_payment"
            await msg.reply_text("🪙 Enter your *crypto wallet address(es):*\n\n_Examples:_\n`USDT (TRC20): TXxxx...`\n`BTC: 1Axxx...`\n`ETH: 0xabc...`\n\nYou can add multiple on separate lines.", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN)

        elif state == "await_pkg_payment":
            if not text or text in ALL_BTNS: await msg.reply_text("❌ Enter payment info.", reply_markup=kb_cancel()); return
            context.user_data["new_pkg"]["payment_info"] = text.strip()
            context.user_data["new_pkg"]["selected_chats"] = []
            context.user_data.pop("state", None)
            txt, kb = inline_pkg_chat_selector([])
            await msg.reply_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

        elif state == "await_payment_proof":
            pkg_id = context.user_data.get("pending_pkg_id")
            pkg = next((p for p in load_packages() if p["id"] == pkg_id), None) if pkg_id else None
            if not pkg:
                context.user_data.pop("state", None); context.user_data.pop("pending_pkg_id", None)
                await show_main(msg, context, uid); return
            proof_type, proof_value = None, None
            if msg.photo:
                proof_type, proof_value = "screenshot", msg.photo[-1].file_id
            elif text and text not in ALL_BTNS:
                proof_type, proof_value = "hash", text.strip()
            if not proof_type:
                await msg.reply_text("❌ Send your TX hash (text) or a screenshot (photo).", reply_markup=kb_cancel()); return
            users = load_users()
            u = next((x for x in users["approved"] if x["id"] == uid), None)
            if not u: await show_main(msg, context, uid); return
            u.setdefault("pending_payments", [])
            if any(pp["pkg_id"] == pkg_id for pp in u["pending_payments"]):
                await msg.reply_text("⏳ Payment already pending review.", reply_markup=kb_main(uid))
                context.user_data.pop("state", None); context.user_data.pop("pending_pkg_id", None); return
            u["pending_payments"].append({
                "pkg_id": pkg_id,
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "proof_type": proof_type,
                "proof_value": proof_value if proof_type == "hash" else None,
                "screenshot_id": proof_value if proof_type == "screenshot" else None,
            })
            save_users(users)
            context.user_data.pop("state", None); context.user_data.pop("pending_pkg_id", None)
            await msg.reply_text("⏳ *Proof submitted!* The admin will verify and activate your package shortly.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main(uid))
            uname_str = f" (@{msg.from_user.username})" if msg.from_user.username else ""
            caption = (
                f"💰 *Payment Received*\n\n"
                f"👤 {msg.from_user.first_name}{uname_str}\n"
                f"🆔 `{uid}`\n"
                f"📦 Package: *{pkg['name']}*\n"
                f"💵 ${pkg['price']} USD\n\n"
                + (f"🔗 *TX Hash:*\n`{proof_value}`" if proof_type == "hash" else "🖼 *Screenshot attached*")
            )
            confirm_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Confirm Payment", callback_data=f"cpay:{uid}:{pkg_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"dpay:{uid}:{pkg_id}"),
            ]])
            for aid in ADMIN_IDS:
                try:
                    if proof_type == "screenshot":
                        await context.bot.send_photo(chat_id=aid, photo=proof_value, caption=caption, reply_markup=confirm_kb, parse_mode=ParseMode.MARKDOWN)
                    else:
                        await context.bot.send_message(chat_id=aid, text=caption, reply_markup=confirm_kb, parse_mode=ParseMode.MARKDOWN)
                except Exception as e: logger.error(f"Admin notify failed {aid}: {e}")
            return

        elif state == "await_schedule":
            parts = text.strip().split()
            if len(parts) < 3: await msg.reply_text("❌ Format: `YYYY-MM-DD HH:MM Message`", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN); return
            try: send_at = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            except: await msg.reply_text("❌ Bad date. Use `YYYY-MM-DD HH:MM`", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN); return
            now = datetime.now(timezone.utc)
            if send_at <= now: await msg.reply_text("❌ Must be in the future.", reply_markup=kb_cancel()); return
            mtxt = " ".join(parts[2:])
            if not chat_ids: await msg.reply_text("⚠️ No chats.", reply_markup=kb_chats()); return
            sid   = int(now.timestamp()*1000)
            entry = {"id":sid,"send_at":send_at.isoformat(),"message":mtxt,"chat_ids":chat_ids,"created_by":uid,"sent":False}
            sch   = load_schedules(); sch.append(entry); save_schedules(sch)
            delay = (send_at - now).total_seconds()
            context.job_queue.run_once(_send_scheduled, when=delay, data=entry, name=str(sid))
            context.user_data.pop("state", None)
            h,m = int(delay//3600), int((delay%3600)//60)
            await msg.reply_text(f"✅ *Scheduled!*\n📅 `{send_at.strftime('%Y-%m-%d %H:%M UTC')}`\n⏳ In {h}h {m}m\n📝 _{mtxt[:60]}_", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_schedules())
        return

    # ── Navigation ────────────────────────────
    if   text == B_BROADCAST: await msg.reply_text(f"📢 *Broadcast*\nChats: *{len(get_user_chats(uid))}*\nSelect type:", reply_markup=kb_broadcast(), parse_mode=ParseMode.MARKDOWN)
    elif text in (B_CHATS, B_MY_CHATS): await msg.reply_text("⚙️ *Manage Chats*", reply_markup=kb_chats(), parse_mode=ParseMode.MARKDOWN)
    elif text == B_SCHEDULES: await msg.reply_text("📅 *Schedules*", reply_markup=kb_schedules(), parse_mode=ParseMode.MARKDOWN); await show_schedules(msg)
    elif text == B_INFO:
        await msg.reply_text(f"ℹ️ *Info*\n\n👤 {user.first_name}\n🆔 `{uid}`\n💬 Chat ID: `{msg.chat_id}`", reply_markup=kb_main(uid), parse_mode=ParseMode.MARKDOWN)
    elif text == B_USERS and admin: await msg.reply_text("👥 *Manage Users*", reply_markup=kb_users(), parse_mode=ParseMode.MARKDOWN)

    elif text == B_TEXT:    context.user_data["state"]="await_text";    await msg.reply_text("📝 Type your message:\n_(HTML: `<b>bold</b>` `<i>italic</i>`)_", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN)
    elif text == B_PHOTO:   context.user_data["state"]="await_photo";   await msg.reply_text("🖼 Send the photo:", reply_markup=kb_cancel())
    elif text == B_VIDEO:   context.user_data["state"]="await_video";   await msg.reply_text("🎬 Send the video:", reply_markup=kb_cancel())
    elif text == B_FILE:    context.user_data["state"]="await_file";    await msg.reply_text("📁 Send the file:", reply_markup=kb_cancel())
    elif text == B_AUDIO:   context.user_data["state"]="await_audio";   await msg.reply_text("🎵 Send the audio:", reply_markup=kb_cancel())
    elif text == B_STICKER: context.user_data["state"]="await_sticker"; await msg.reply_text("🎭 Send the sticker:", reply_markup=kb_cancel())

    elif text == B_ADD_CHAT:
        context.user_data["state"] = "await_add_chat"
        await msg.reply_text("➕ Send @username, t.me/link, or numeric ID:\n\nℹ️ For private groups — just add the bot to the group (no need to make it admin). You'll get a Yes/No prompt here automatically.", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN)
    elif text == B_ACTIVE:
        if admin:
            c = load_config(); t,k = inline_admin_chats(c,"active")
        else:
            u2 = get_approved_user(uid) or {}; t,k = inline_user_chats(u2,"active")
        await msg.reply_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)
    elif text == B_REMOVED:
        if admin:
            c = load_config(); t,k = inline_admin_chats(c,"removed")
        else:
            u2 = get_approved_user(uid) or {}; t,k = inline_user_chats(u2,"removed")
        await msg.reply_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif text == B_NEW_SCHED: context.user_data["state"]="await_schedule"; await msg.reply_text("📅 `YYYY-MM-DD HH:MM Your message`\n⏰ UTC.", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN)
    elif text == B_VIEW_SCHED: await show_schedules(msg)

    elif text == B_ADD_USER and admin: context.user_data["state"]="await_add_user"; await msg.reply_text("➕ Send @username or user ID:", reply_markup=kb_cancel())
    elif text == B_APPR and admin:
        t,k = inline_approved_users(); await msg.reply_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)
    elif text == B_PEND and admin:
        t,k = inline_pending_users(); await msg.reply_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)
    elif text == B_PKGS_MGT and admin: await msg.reply_text("📦 *Ad Packages*", reply_markup=kb_pkgs_mgt(), parse_mode=ParseMode.MARKDOWN)
    elif text == B_NEW_PKG and admin:
        context.user_data["state"] = "await_pkg_name"
        await msg.reply_text("📦 *New Ad Package*\n\nEnter a name for this package:", reply_markup=kb_cancel(), parse_mode=ParseMode.MARKDOWN)
    elif text == B_VIEW_PKGS and admin:
        t,k = inline_admin_packages(); await msg.reply_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif text == B_AD_PKGS and not admin:
        t,k = inline_user_packages(uid); await msg.reply_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    else: await show_main(msg, context, uid)

# ─────────────────────────────────────────────
# ADD USER HELPER
# ─────────────────────────────────────────────
async def _handle_add_user(msg, context, raw, admin_uid):
    users = load_users()
    async def notify_approved(new_id, name):
        try: await context.bot.send_message(chat_id=new_id, text="✅ *Access approved!*\nSend /start to begin.", parse_mode=ParseMode.MARKDOWN)
        except: pass

    if raw.lstrip("-").isdigit():
        new_id = int(raw)
        if is_admin(new_id) or any(u["id"]==new_id for u in users["approved"]):
            await msg.reply_text(f"⚠️ User `{new_id}` already has access.", parse_mode=ParseMode.MARKDOWN); return
        entry = {"id":new_id,"name":str(new_id),"username":None,"added_at":datetime.now(timezone.utc).isoformat(),"target_chats":[],"chat_info":{},"removed_chats":[],"ad_packages":[],"pending_payments":[]}
        users["approved"].append(entry); users["pending"] = [u for u in users["pending"] if u["id"]!=new_id]; save_users(users)
        context.user_data.pop("state",None)
        await msg.reply_text(f"✅ User `{new_id}` approved!", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_users())
        await notify_approved(new_id, str(new_id)); return

    if not raw.startswith("@"): raw = "@"+raw
    sr = await msg.reply_text(f"🔍 `{raw}`…", parse_mode=ParseMode.MARKDOWN)
    try: chat = await context.bot.get_chat(raw)
    except Exception as e: await sr.edit_text(f"❌ Not found: `{raw}`\n`{e}`", parse_mode=ParseMode.MARKDOWN); return
    new_id = chat.id
    if is_admin(new_id) or any(u["id"]==new_id for u in users["approved"]):
        await sr.edit_text(f"⚠️ *{chat.first_name or raw}* already has access.", parse_mode=ParseMode.MARKDOWN); return
    entry = {"id":new_id,"name":chat.first_name or str(new_id),"username":chat.username,"added_at":datetime.now(timezone.utc).isoformat(),"target_chats":[],"chat_info":{},"removed_chats":[],"ad_packages":[],"pending_payments":[]}
    users["approved"].append(entry); users["pending"] = [u for u in users["pending"] if u["id"]!=new_id]; save_users(users)
    context.user_data.pop("state",None)
    await sr.edit_text(f"✅ *{entry['name']}* approved!", parse_mode=ParseMode.MARKDOWN)
    await msg.reply_text("👥 *Users*", reply_markup=kb_users(), parse_mode=ParseMode.MARKDOWN)
    await notify_approved(new_id, entry["name"])

# ─────────────────────────────────────────────
# CALLBACK HANDLER
# ─────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; data = q.data

    # ── Bot-added-to-group confirmations (admin) ──
    if data.startswith("gadd:"):
        if not is_admin(uid): await q.answer("Not authorized.", show_alert=True); return
        _, adder_uid, cid_str = data.split(":", 2); cid = int(cid_str)
        config = load_config()
        if cid in config["target_chats"]:
            await q.answer("Already in your list.", show_alert=True)
            await q.edit_message_text("ℹ️ This chat is already in your list.", parse_mode=ParseMode.MARKDOWN); return
        try:
            chat = await context.bot.get_chat(cid)
            cinfo = {"title": chat.title or str(cid), "type": chat.type}
        except: cinfo = {}
        config["target_chats"].append(cid)
        config.setdefault("chat_info", {})[str(cid)] = cinfo
        save_config(config)
        await q.answer("Added!", show_alert=False)
        title = cinfo.get("title", str(cid))
        await q.edit_message_text(f"✅ *{title}* added to your chat list!", parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith("gdeny:"):
        if not is_admin(uid): await q.answer("Not authorized.", show_alert=True); return
        await q.answer("Skipped.", show_alert=False)
        await q.edit_message_text("❌ Not added.", parse_mode=ParseMode.MARKDOWN); return

    # ── Bot-added-to-group confirmations (approved user) ──
    if data.startswith("ugadd:"):
        _, owner_uid_str, cid_str = data.split(":", 2)
        owner_uid = int(owner_uid_str); cid = int(cid_str)
        if uid != owner_uid and not is_admin(uid): await q.answer("Not authorized.", show_alert=True); return
        if not is_approved(owner_uid): await q.answer("User not approved.", show_alert=True); return
        users_data = load_users()
        u2 = next((x for x in users_data["approved"] if x["id"] == owner_uid), None)
        if not u2: await q.answer("User not found.", show_alert=True); return
        if cid in u2.get("target_chats", []):
            await q.answer("Already in list.", show_alert=True)
            await q.edit_message_text("ℹ️ Already in your list."); return
        try:
            chat = await context.bot.get_chat(cid)
            cinfo = {"title": chat.title or str(cid), "type": chat.type}
        except: cinfo = {}
        u2.setdefault("target_chats", []).append(cid)
        u2.setdefault("chat_info", {})[str(cid)] = cinfo
        save_users(users_data)
        await q.answer("Added!", show_alert=False)
        await q.edit_message_text(f"✅ *{cinfo.get('title', cid)}* added to your chat list!", parse_mode=ParseMode.MARKDOWN)
        return

    if data.startswith("ugdeny:"):
        await q.answer("Skipped.", show_alert=False)
        await q.edit_message_text("❌ Not added."); return

    # Access request — any user
    if data.startswith("req:"):
        req_uid = int(data[4:])
        if is_approved(req_uid): await q.answer("You already have access!", show_alert=True); return
        if is_pending(req_uid):  await q.answer("Already sent. Please wait.", show_alert=True); return
        users = load_users()
        entry = {"id":req_uid,"name":q.from_user.first_name or str(req_uid),"username":q.from_user.username,"requested_at":datetime.now(timezone.utc).isoformat()}
        users["pending"].append(entry); save_users(users)
        await q.answer("Request sent! Waiting for admin approval.", show_alert=True)
        await q.edit_message_text("⏳ *Request sent.* You'll be notified once approved.", parse_mode=ParseMode.MARKDOWN)
        uname = f" (@{q.from_user.username})" if q.from_user.username else ""
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=aid,
                    text=f"🔔 *New Access Request*\n\n👤 {entry['name']}{uname}\n🆔 `{req_uid}`",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve",callback_data=f"approve:{req_uid}"),InlineKeyboardButton("❌ Deny",callback_data=f"deny:{req_uid}")]]),
                    parse_mode=ParseMode.MARKDOWN,
                )
                logger.info(f"Notified admin {aid} about request from {req_uid}")
            except Exception as e:
                logger.error(f"Failed to notify admin {aid} about request from {req_uid}: {e}")
        return

    # User: buy package
    if data.startswith("pkg_buy:") and is_approved(uid):
        pkg_id = data[8:]
        pkg = next((p for p in load_packages() if p["id"]==pkg_id), None)
        if not pkg: await q.answer("Package not found.", show_alert=True); return
        await q.answer()
        config = load_config(); info = config.get("chat_info",{})
        chat_names = "\n".join(f"  • {_label(cid,info)}" for cid in pkg.get("chat_ids",[]))
        await q.edit_message_text(
            f"📦 *{pkg['name']}*\n\n"
            f"Chats included:\n{chat_names or '  None'}\n\n"
            f"💵 Price: *${pkg['price']} USD*\n\n"
            f"🪙 *Pay with Crypto:*\n`{pkg['payment_info']}`\n\n"
            f"After paying, tap *I've Paid* — you'll be asked for your TX hash or screenshot.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I've Paid", callback_data=f"pkg_paid:{pkg_id}")],
                [InlineKeyboardButton("◀️ Back", callback_data="pkg_back")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if data.startswith("pkg_paid:") and is_approved(uid):
        pkg_id = data[9:]
        pkg = next((p for p in load_packages() if p["id"]==pkg_id), None)
        if not pkg: await q.answer("Package not found.", show_alert=True); return
        await q.answer()
        context.user_data["state"] = "await_payment_proof"
        context.user_data["pending_pkg_id"] = pkg_id
        await q.edit_message_text(
            f"📸 *Send Payment Proof*\n\n"
            f"📦 {pkg['name']} — *${pkg['price']} USD*\n\n"
            f"Please send one of the following:\n"
            f"• 📋 *Transaction Hash* — paste the TX hash as text\n"
            f"• 🖼 *Screenshot* — send a photo of your payment",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancel", callback_data="pkg_back")]]),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if data == "pkg_back" and is_approved(uid):
        await q.answer()
        context.user_data.pop("state", None); context.user_data.pop("pending_pkg_id", None)
        t,k = inline_user_packages(uid)
        await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)
        return

    # Admin-only from here
    if not is_admin(uid):
        await q.answer("❌ Not authorized.", show_alert=True); return
    await q.answer()

    users  = load_users()
    config = load_config()

    if data.startswith("approve:"):
        req_uid = int(data[8:])
        pe = next((u for u in users["pending"] if u["id"]==req_uid), {"id":req_uid,"name":str(req_uid)})
        users["pending"]  = [u for u in users["pending"]  if u["id"]!=req_uid]
        users["denied"]   = [u for u in users["denied"]   if u["id"]!=req_uid]
        if not any(u["id"]==req_uid for u in users["approved"]):
            pe.update({"added_at":datetime.now(timezone.utc).isoformat(),"target_chats":[],"chat_info":{},"removed_chats":[],"ad_packages":[],"pending_payments":[]})
            users["approved"].append(pe)
        save_users(users)
        await q.edit_message_text(f"✅ *{pe.get('name',req_uid)}* approved!", parse_mode=ParseMode.MARKDOWN)
        try: await context.bot.send_message(chat_id=req_uid, text="✅ *Access approved!*\nSend /start.", parse_mode=ParseMode.MARKDOWN)
        except: pass

    elif data.startswith("deny:"):
        req_uid = int(data[5:])
        pe = next((u for u in users["pending"] if u["id"]==req_uid), {"id":req_uid,"name":str(req_uid)})
        users["pending"] = [u for u in users["pending"] if u["id"]!=req_uid]
        if not any(u["id"]==req_uid for u in users["denied"]): users["denied"].append(pe)
        save_users(users)
        await q.edit_message_text(f"❌ *{pe.get('name',req_uid)}* denied.", parse_mode=ParseMode.MARKDOWN)
        try: await context.bot.send_message(chat_id=req_uid, text="❌ Your access request was not approved.")
        except: pass

    elif data.startswith("revoke:"):
        req_uid = int(data[7:])
        e = next((u for u in users["approved"] if u["id"]==req_uid), {"id":req_uid,"name":str(req_uid)})
        users["approved"] = [u for u in users["approved"] if u["id"]!=req_uid]; save_users(users)
        t,k = inline_approved_users()
        await q.edit_message_text(f"🚫 *{e.get('name',req_uid)}* revoked.\n\n"+t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)
        try: await context.bot.send_message(chat_id=req_uid, text="🚫 Your bot access has been revoked.")
        except: pass

    elif data.startswith("cpay:"):  # confirm payment
        _, buyer_uid, pkg_id = data.split(":", 2); buyer_uid = int(buyer_uid)
        u = next((x for x in users["approved"] if x["id"]==buyer_uid), None)
        pkg = next((p for p in load_packages() if p["id"]==pkg_id), None)
        if not u or not pkg: await q.edit_message_text("⚠️ User or package not found."); return
        u["pending_payments"] = [pp for pp in u.get("pending_payments",[]) if pp["pkg_id"]!=pkg_id]
        u.setdefault("ad_packages",[])
        if pkg_id not in u["ad_packages"]: u["ad_packages"].append(pkg_id)
        save_users(users)
        await q.edit_message_text(f"✅ Payment confirmed for *{u.get('name',buyer_uid)}*\nPackage: *{pkg['name']}* activated.", parse_mode=ParseMode.MARKDOWN)
        try: await context.bot.send_message(chat_id=buyer_uid, text=f"✅ *Payment confirmed!*\nYour *{pkg['name']}* package is now active.\nGo to 📦 Ad Packages to start broadcasting.", parse_mode=ParseMode.MARKDOWN)
        except: pass

    elif data.startswith("dpay:"):  # deny payment
        _, buyer_uid, pkg_id = data.split(":", 2); buyer_uid = int(buyer_uid)
        u = next((x for x in users["approved"] if x["id"]==buyer_uid), None)
        pkg = next((p for p in load_packages() if p["id"]==pkg_id), None)
        if u:
            u["pending_payments"] = [pp for pp in u.get("pending_payments",[]) if pp["pkg_id"]!=pkg_id]
            save_users(users)
        await q.edit_message_text(f"❌ Payment denied for `{buyer_uid}`.", parse_mode=ParseMode.MARKDOWN)
        try: await context.bot.send_message(chat_id=buyer_uid, text=f"❌ Your payment for *{pkg['name'] if pkg else pkg_id}* could not be verified. Please contact the admin.", parse_mode=ParseMode.MARKDOWN)
        except: pass

    elif data.startswith("pkg_sel:"):  # toggle chat in package selector
        cid = int(data[8:])
        np = context.user_data.get("new_pkg", {})
        sel = np.get("selected_chats", [])
        if cid in sel: sel.remove(cid)
        else: sel.append(cid)
        np["selected_chats"] = sel
        context.user_data["new_pkg"] = np
        t,k = inline_pkg_chat_selector(sel)
        await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data == "pkg_done":  # finalize package creation
        np = context.user_data.get("new_pkg", {})
        if not np.get("selected_chats"):
            await q.answer("Select at least one chat!", show_alert=True); return
        pkgs = load_packages()
        new_pkg = {
            "id":       f"pkg_{int(datetime.now().timestamp()*1000)}",
            "name":     np["name"],
            "price":    np["price"],
            "currency": np["currency"],
            "payment_info": np["payment_info"],
            "chat_ids": np["selected_chats"],
            "active":   True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        pkgs.append(new_pkg); save_packages(pkgs)
        context.user_data.pop("new_pkg", None)
        config = load_config(); info = config.get("chat_info",{})
        chat_names = ", ".join(_label(c,info) for c in new_pkg["chat_ids"])
        await q.edit_message_text(
            f"✅ *Package Created!*\n\n📦 {new_pkg['name']}\n💰 {new_pkg['price']} {new_pkg['currency']}\n📢 Chats: {chat_names}",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "pkg_cancel":
        context.user_data.pop("new_pkg", None)
        await q.edit_message_text("❌ Package creation cancelled.")

    elif data.startswith("pkg_toggle:"):  # toggle package active/inactive
        pkg_id = data[11:]; pkgs = load_packages()
        for p in pkgs:
            if p["id"]==pkg_id: p["active"] = not p.get("active",True)
        save_packages(pkgs)
        t,k = inline_admin_packages(); await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("pkg_del:"):
        pkg_id = data[8:]; pkgs = [p for p in load_packages() if p["id"]!=pkg_id]; save_packages(pkgs)
        t,k = inline_admin_packages(); await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data in ("ac:active","ac:removed"):
        t,k = inline_admin_chats(config, "active" if data=="ac:active" else "removed")
        await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data in ("uc:active","uc:removed"):
        u2 = get_approved_user(uid) or {}
        t,k = inline_user_chats(u2, "active" if data=="uc:active" else "removed")
        await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("rm:"):
        cid = int(data[3:])
        if cid in config["target_chats"]:
            config["target_chats"].remove(cid)
            e = {"id":cid,**config["chat_info"].get(str(cid),{}),"removed_at":datetime.now(timezone.utc).isoformat()}
            config["removed_chats"] = [r for r in config["removed_chats"] if r["id"]!=cid]; config["removed_chats"].append(e)
            save_config(config)
        t,k = inline_admin_chats(config,"active"); await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("ra:"):
        cid = int(data[3:])
        if cid not in config["target_chats"]:
            config["target_chats"].append(cid)
            config["removed_chats"] = [r for r in config["removed_chats"] if r["id"]!=cid]
            save_config(config)
        t,k = inline_admin_chats(config,"removed"); await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("urm:"):
        cid = int(data[4:]); users = load_users()
        u2 = next((x for x in users["approved"] if x["id"]==uid), None)
        if u2 and cid in u2.get("target_chats",[]):
            u2["target_chats"].remove(cid)
            e = {"id":cid,**u2.get("chat_info",{}).get(str(cid),{}),"removed_at":datetime.now(timezone.utc).isoformat()}
            u2.setdefault("removed_chats",[])
            u2["removed_chats"] = [r for r in u2["removed_chats"] if r["id"]!=cid]; u2["removed_chats"].append(e)
            save_users(users)
        u3 = get_approved_user(uid) or {}; t,k = inline_user_chats(u3,"active")
        await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("ura:"):
        cid = int(data[4:]); users = load_users()
        u2 = next((x for x in users["approved"] if x["id"]==uid), None)
        if u2 and cid not in u2.get("target_chats",[]):
            u2.setdefault("target_chats",[]).append(cid)
            u2.setdefault("removed_chats",[])
            u2["removed_chats"] = [r for r in u2["removed_chats"] if r["id"]!=cid]
            save_users(users)
        u3 = get_approved_user(uid) or {}; t,k = inline_user_chats(u3,"removed")
        await q.edit_message_text(t, reply_markup=k, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("sched_cancel:"):
        sid = int(data[13:]); scheds = load_schedules()
        for s in scheds:
            if s["id"]==sid and not s.get("sent"): s["sent"]=True; s["cancelled"]=True; break
        save_schedules(scheds)
        for job in context.job_queue.get_jobs_by_name(str(sid)): job.schedule_removal()
        pending = [s for s in scheds if not s.get("sent")]
        if not pending: await q.edit_message_text("📅 *Schedules*\n\nNone pending.", parse_mode=ParseMode.MARKDOWN)
        else:
            lines = [f"• `{s['id']}` — {datetime.fromisoformat(s['send_at']).strftime('%d %b %H:%M UTC')}\n  _{s['message'][:40]}_" for s in pending]
            rows  = [[InlineKeyboardButton(f"❌ Cancel #{s['id']}",callback_data=f"sched_cancel:{s['id']}")] for s in pending]
            await q.edit_message_text(f"📅 *Pending ({len(pending)})*\n\n"+"\n\n".join(lines), reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)

    elif data == "noop": pass

# ─────────────────────────────────────────────
# SCHEDULED JOB
# ─────────────────────────────────────────────
async def _send_scheduled(context: ContextTypes.DEFAULT_TYPE):
    e = context.job.data; sid,text,chat_ids = e["id"],e["message"],e["chat_ids"]
    async def send(cid): await context.bot.send_message(chat_id=cid, text=text, parse_mode=ParseMode.HTML)
    s,f = await broadcast(context, send, chat_ids)
    scheds = load_schedules()
    for sc in scheds:
        if sc["id"]==sid: sc["sent"]=True; sc["sent_at"]=datetime.now(timezone.utc).isoformat(); break
    save_schedules(scheds)
    for aid in ADMIN_IDS:
        try: await context.bot.send_message(chat_id=aid, text=f"🕐 *Scheduled sent!*\nID:`{sid}` ✅{s} ❌{f}\n_{text[:80]}_", parse_mode=ParseMode.MARKDOWN)
        except: pass

async def restore_schedules(app):
    now = datetime.now(timezone.utc); n = 0
    for e in load_schedules():
        if e.get("sent") or e.get("cancelled"): continue
        delay = max(1.0,(datetime.fromisoformat(e["send_at"])-now).total_seconds())
        app.job_queue.run_once(_send_scheduled, when=delay, data=e, name=str(e["id"])); n+=1
    if n: logger.info(f"Restored {n} schedule(s)")
    # Register bot commands in Telegram UI
    try:
        private_cmds = [
            BotCommand("start",   "Open the bot menu"),
            BotCommand("menu",    "Open the bot menu"),
            BotCommand("about",   "About this bot"),
        ]
        group_cmds = [
            BotCommand("start",   "Start / info about this bot"),
            BotCommand("about",   "About CS Broadcast Bot"),
            BotCommand("addhere", "Add this group to your broadcast list"),
        ]
        await app.bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())
        await app.bot.set_my_commands(group_cmds,   scope=BotCommandScopeAllGroupChats())
        logger.info("Bot commands registered.")
    except Exception as ex:
        logger.warning(f"Could not set commands: {ex}")

async def handle_bot_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Notify when bot is added to any group/channel — always fires for admin."""
    result = update.my_chat_member
    if not result: return
    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    if new_status not in ("member", "administrator"): return
    if old_status in ("member", "administrator"): return

    chat     = result.chat
    added_by = result.from_user
    cid      = chat.id
    title    = chat.title or str(cid)
    ctype    = chat.type
    e        = {"channel": "📢", "group": "👥", "supergroup": "👥"}.get(ctype, "💬")
    adder_uid   = added_by.id if added_by else 0
    adder_name  = (added_by.first_name or str(adder_uid)) if added_by else "Unknown"
    adder_uname = f" (@{added_by.username})" if added_by and added_by.username else ""

    # Build link line
    if chat.username:
        link_line = f"🔗 @{chat.username}  |  t.me/{chat.username}"
    else:
        # Try to get invite link if bot is admin; fallback to showing ID only
        try:
            invite = await context.bot.export_chat_invite_link(cid)
            link_line = f"🔗 {invite}"
        except:
            link_line = f"🔒 Private  |  ID: `{cid}`"

    logger.info(f"Bot added to {cid} ({title}) by {adder_uid}")

    # ── Always notify admin ──────────────────
    admin_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, Add", callback_data=f"gadd:{adder_uid}:{cid}"),
        InlineKeyboardButton("❌ No",       callback_data=f"gdeny:{cid}"),
    ]])
    admin_text = (
        f"🔔 *Bot added to a chat!*\n\n"
        f"{e} *{title}*\n"
        f"{link_line}\n"
        f"Added by: *{adder_name}*{adder_uname}\n\n"
        f"Add this to your broadcast list?"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=admin_text, reply_markup=admin_kb, parse_mode=ParseMode.MARKDOWN)
            logger.info(f"Admin {aid} notified about {cid}")
        except Exception as ex:
            logger.error(f"Failed to notify admin {aid}: {ex}")

    # ── Also notify the user who added (if approved non-admin) ──
    if adder_uid and not is_admin(adder_uid) and is_approved(adder_uid):
        user_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, Add", callback_data=f"ugadd:{adder_uid}:{cid}"),
            InlineKeyboardButton("❌ No",       callback_data=f"ugdeny:{cid}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=adder_uid,
                text=f"🔔 *Bot added to {e} {title}*\n\nAdd this to your broadcast list?",
                reply_markup=user_kb, parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as ex:
            logger.error(f"Failed to notify user {adder_uid}: {ex}")

async def error_handler(update, context):
    from telegram.error import Conflict, NetworkError, TimedOut
    err = context.error
    # Don't spam admin with polling/network noise
    if isinstance(err, (Conflict, NetworkError, TimedOut)):
        logger.warning(f"Suppressed error: {err}")
        return
    logger.error(f"Error: {err}", exc_info=True)
    for aid in ADMIN_IDS:
        try: await context.bot.send_message(chat_id=aid, text=f"⚠️ `{err}`", parse_mode=ParseMode.MARKDOWN)
        except: pass

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    logger.info("Starting bot...")
    for path, default in [(CONFIG_FILE,{"target_chats":[],"chat_info":{},"removed_chats":[]}),(SCHED_FILE,[]),(USERS_FILE,{"approved":[],"pending":[],"denied":[]}),(PKGS_FILE,[])]:
        if not path.exists(): _save(path, default)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("menu",    start))
    app.add_handler(CommandHandler("about",   about))
    app.add_handler(CommandHandler("addhere", addhere))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(ChatMemberHandler(handle_bot_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE | filters.Sticker.ALL,
        handle_message,
    ))
    app.add_error_handler(error_handler)
    app.post_init = restore_schedules
    logger.info(f"Admins: {ADMIN_IDS}")
    import asyncio; asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=0.0, timeout=30)

if __name__ == "__main__":
    main()
