import os
import time
import sqlite3
import threading
import json
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, request, jsonify, Response
import telebot
from telebot import types
from telebot.handler_backends import BaseMiddleware, CancelUpdate
import requests

# ==================== الإعدادات ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SUPER_ADMIN_IDS = [int(x.strip()) for x in os.environ.get("SUPER_ADMIN_IDS", "").split(",") if x.strip()]
RENDER_URL = os.environ.get("RENDER_URL", "https://maahdihs.onrender.com/")
LOG_CHANNEL = os.environ.get("LOG_CHANNEL", "")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")  # اختياري لحماية اللوحة

if not BOT_TOKEN:
    print("⚠️ تحذير: BOT_TOKEN غير مضبوط!")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", "bot_data.db")

flood_data = defaultdict(list)
FLOOD_WINDOW = 10
FLOOD_LIMIT = 8

REACTION_POOL = ["👍", "❤️", "🔥", "🎉", "😂", "👏", "💯", "⚡", "🚀", "🌟", "💪", "🙏", "😎", "🤩", "💎"]

# ==================== قاعدة البيانات ====================
def db_execute(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        result = cur.fetchall() if fetch else None
        conn.commit()
        return result
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY, username TEXT, promoted_by INTEGER, promoted_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS banned (
        user_id INTEGER PRIMARY KEY, reason TEXT, banned_by INTEGER, banned_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS wars (
        id INTEGER PRIMARY KEY AUTOINCREMENT, result TEXT, registered_by INTEGER, date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        messages_count INTEGER DEFAULT 0, points INTEGER DEFAULT 0,
        joined_at TEXT, last_seen TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT)""")
    # جداول جديدة للتفاعل التلقائي
    c.execute("""CREATE TABLE IF NOT EXISTS auto_react (
        chat_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0,
        emojis TEXT, mode TEXT DEFAULT 'random', updated_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS likes_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER,
        message_id INTEGER, emoji TEXT, sent_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS chat_info (
        chat_id INTEGER PRIMARY KEY, title TEXT, type TEXT,
        added_at TEXT, likes_total INTEGER DEFAULT 0)""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_likes_chat ON likes_log(chat_id)""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_likes_date ON likes_log(sent_at)""")
    conn.commit()
    conn.close()

# ==================== إعدادات ====================
def get_setting(key, default=None):
    r = db_execute("SELECT value FROM settings WHERE key=?", (key,), fetch=True)
    return r[0]["value"] if r else default

def set_setting(key, value):
    db_execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))

# ==================== صلاحيات ====================
def is_super_admin(uid):
    return uid in SUPER_ADMIN_IDS

def is_admin(uid):
    if is_super_admin(uid):
        return True
    return bool(db_execute("SELECT 1 FROM admins WHERE user_id=?", (uid,), fetch=True))

def is_banned(uid):
    return bool(db_execute("SELECT 1 FROM banned WHERE user_id=?", (uid,), fetch=True))

def track_user_record(user):
    now = datetime.now().isoformat(timespec="seconds")
    if db_execute("SELECT 1 FROM users WHERE user_id=?", (user.id,), fetch=True):
        db_execute("UPDATE users SET username=?, first_name=?, messages_count=messages_count+1, last_seen=? WHERE user_id=?",
                   (user.username, user.first_name, now, user.id))
    else:
        db_execute("INSERT INTO users (user_id, username, first_name, messages_count, points, joined_at, last_seen) VALUES (?,?,?,?,?,?,?)",
                   (user.id, user.username, user.first_name, 1, 0, now, now))

def log_to_channel(text):
    if not LOG_CHANNEL:
        return
    try:
        bot.send_message(LOG_CHANNEL, text, parse_mode="Markdown")
    except Exception as e:
        print(f"Log error: {e}")

# ==================== نظام اللايكات (Reactions) ====================
def ensure_chat(chat):
    """تسجيل/تحديث معلومات المحادثة"""
    exists = db_execute("SELECT 1 FROM chat_info WHERE chat_id=?", (chat.id,), fetch=True)
    now = datetime.now().isoformat(timespec="seconds")
    if exists:
        db_execute("UPDATE chat_info SET title=?, type=? WHERE chat_id=?",
                   (getattr(chat, "title", None) or getattr(chat, "first_name", "Private"), chat.type, chat.id))
    else:
        db_execute("INSERT INTO chat_info (chat_id, title, type, added_at, likes_total) VALUES (?,?,?,?,0)",
                   (chat.id, getattr(chat, "title", None) or getattr(chat, "first_name", "Private"), chat.type, now))

def get_auto_react(chat_id):
    r = db_execute("SELECT * FROM auto_react WHERE chat_id=?", (chat_id,), fetch=True)
    if not r:
        return {"enabled": 0, "emojis": ",".join(REACTION_POOL[:5]), "mode": "random"}
    return {"enabled": r[0]["enabled"], "emojis": r[0]["emojis"], "mode": r[0]["mode"]}

def set_auto_react(chat_id, **kwargs):
    cur = get_auto_react(chat_id)
    cur.update({k: v for k, v in kwargs.items() if v is not None})
    db_execute("""INSERT OR REPLACE INTO auto_react
                  (chat_id, enabled, emojis, mode, updated_at) VALUES (?,?,?,?,?)""",
               (chat_id, cur["enabled"], cur["emojis"], cur["mode"],
                datetime.now().isoformat(timespec="seconds")))

def send_reaction(chat_id, message_id, emoji):
    """إرسال reaction عبر Telegram API مباشرة"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}],
        "is_big": False
    }
    try:
        r = requests.post(url, json=payload, timeout=5)
        if not r.ok:
            print(f"[React] Fail {r.status_code}: {r.text[:100]}")
            return False
        return True
    except Exception as e:
        print(f"[React] Exception: {e}")
        return False

def record_like(chat_id, message_id, emoji):
    now = datetime.now().isoformat(timespec="seconds")
    db_execute("INSERT INTO likes_log (chat_id, message_id, emoji, sent_at) VALUES (?,?,?,?)",
               (chat_id, message_id, emoji, now))
    db_execute("UPDATE chat_info SET likes_total = likes_total + 1 WHERE chat_id=?", (chat_id,))

def pick_emoji(chat_id):
    cfg = get_auto_react(chat_id)
    emojis = [e.strip() for e in cfg["emojis"].split(",") if e.strip()]
    if not emojis:
        emojis = REACTION_POOL
    if cfg["mode"] == "cycle":
        # تدوير بين الإيموجيات
        count = db_execute("SELECT COUNT(*) as c FROM likes_log WHERE chat_id=?", (chat_id,), fetch=True)[0]["c"]
        return emojis[count % len(emojis)]
    import random
    return random.choice(emojis)

# ==================== Middleware ====================
class AccessMiddleware(BaseMiddleware):
    def __init__(self):
        self.update_types = ['message', 'callback_query']

    def pre_process(self, message, data):
        try:
            user = getattr(message, "from_user", None)
            if user is None:
                return
            chat = getattr(message, "chat", None)
            if chat and chat.type in ("group", "supergroup", "channel"):
                try:
                    ensure_chat(chat)
                except Exception as e:
                    print(f"Chat ensure error: {e}")
            if isinstance(message, telebot.types.Message):
                try:
                    track_user_record(user)
                except Exception:
                    pass
            if is_super_admin(user.id):
                return
            if is_banned(user.id):
                try:
                    bot.send_message(user.id, "🚫 أنت محظور من استخدام البوت.")
                except Exception:
                    pass
                return CancelUpdate()
            if get_setting("maintenance", "off") == "on":
                try:
                    bot.send_message(user.id, "🛠 البوت في وضع الصيانة. حاول لاحقاً.")
                except Exception:
                    pass
                return CancelUpdate()
        except Exception as e:
            print(f"Middleware error: {e}")

    def post_process(self, message, data, exception):
        if exception:
            print(f"Handler exception: {exception}")

# ==================== Auto-React Handler ====================
@bot.message_handler(
    func=lambda m: m.chat.type in ("group", "supergroup", "channel")
                   and get_auto_react(m.chat.id)["enabled"] == 1,
    content_types=['text', 'photo', 'video', 'animation', 'document', 'voice', 'audio', 'sticker']
)
def auto_react_handler(message):
    try:
        user = getattr(message, "from_user", None)
        if user and user.is_bot:
            return  # لا تتفاعل مع رسائل البوتات
        emoji = pick_emoji(message.chat.id)
        if send_reaction(message.chat.id, message.message_id, emoji):
            record_like(message.chat.id, message.message_id, emoji)
    except Exception as e:
        print(f"[AutoReact] {e}")

# ==================== أوامر التفاعل ====================
@bot.message_handler(commands=['autoreact'])
def cmd_autoreact(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 2 or args[1] not in ("on", "off"):
        cfg = get_auto_react(message.chat.id)
        status = "✅ مفعّل" if cfg["enabled"] else "❌ معطّل"
        bot.reply_to(message, f"ℹ️ الحالة الحالية: {status}\n\nالاستخدام: `/autoreact on|off`",
                     parse_mode="Markdown")
        return
    enabled = 1 if args[1] == "on" else 0
    set_auto_react(message.chat.id, enabled=enabled)
    bot.reply_to(message, f"✅ التفاعل التلقائي: *{args[1]}*", parse_mode="Markdown")

@bot.message_handler(commands=['setreact'])
def cmd_setreact(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "❗ الاستخدام: `/setreact ❤️,🔥,👍`", parse_mode="Markdown")
        return
    emojis = ",".join([e.strip() for e in args[1].replace("،", ",").split(",") if e.strip()])
    if not emojis:
        bot.reply_to(message, "❗ لم يتم التعرف على أي إيموجي.")
        return
    set_auto_react(message.chat.id, emojis=emojis)
    bot.reply_to(message, f"✅ تم ضبط الإيموجيات: {emojis}")

@bot.message_handler(commands=['reactmode'])
def cmd_reactmode(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 2 or args[1] not in ("random", "cycle"):
        bot.reply_to(message, "❗ الاستخدام: `/reactmode random|cycle`\n"
                              "• `random` = عشوائي\n• `cycle` = تدوير", parse_mode="Markdown")
        return
    set_auto_react(message.chat.id, mode=args[1])
    bot.reply_to(message, f"✅ الوضع: `{args[1]}`", parse_mode="Markdown")

@bot.message_handler(commands=['likes'])
def cmd_likes(message):
    chat_id = message.chat.id
    total = db_execute("SELECT COUNT(*) as c FROM likes_log WHERE chat_id=?", (chat_id,), fetch=True)[0]["c"]
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = db_execute("SELECT COUNT(*) as c FROM likes_log WHERE chat_id=? AND sent_at LIKE ?",
                             (chat_id, f"{today}%"), fetch=True)[0]["c"]
    week_ago = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    week_count = db_execute("SELECT COUNT(*) as c FROM likes_log WHERE chat_id=? AND sent_at >= ?",
                            (chat_id, week_ago), fetch=True)[0]["c"]
    emojis = db_execute(
        "SELECT emoji, COUNT(*) as c FROM likes_log WHERE chat_id=? GROUP BY emoji ORDER BY c DESC LIMIT 5",
        (chat_id,), fetch=True
    )
    emoji_text = ""
    for r in emojis:
        emoji_text += f"  {r['emoji']} — *{r['c']}* مرة\n"
    text = (
        f"❤️ *إحصائيات التفاعل في هذه المجموعة:*\n\n"
        f"📊 الإجمالي: *{total}*\n"
        f"📅 اليوم: *{today_count}*\n"
        f"📆 آخر 7 أيام: *{week_count}*\n\n"
        f"*أكثر الإيموجيات:*\n{emoji_text or '  —'}"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['toplikes'])
def cmd_toplikes(message):
    rows = db_execute("""SELECT c.title, c.chat_id, c.likes_total,
                         (SELECT COUNT(*) FROM likes_log l WHERE l.chat_id=c.chat_id
                          AND l.sent_at >= ?) as week
                         FROM chat_info c
                         ORDER BY c.likes_total DESC LIMIT 10""",
                     ((datetime.now() - timedelta(days=7)).isoformat(timespec="seconds"),),
                     fetch=True)
    if not rows:
        bot.reply_to(message, "📭 لا توجد بيانات بعد.")
        return
    text = "🏆 *أفضل 10 مجموعات بالتفاعل:*\n\n"
    for i, r in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        text += f"{medal} {r['title'] or r['chat_id']}\n   إجمالي: *{r['likes_total']}* — هذا الأسبوع: *{r['week']}*\n"
    bot.reply_to(message, text, parse_mode="Markdown")

# ==================== أوامر عامة ====================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("📊 الإحصائيات"),
        types.KeyboardButton("📖 المساعدة"),
        types.KeyboardButton("👤 ملفي"),
        types.KeyboardButton("🏆 المتصدرون"),
        types.KeyboardButton("❤️ التفاعل"),
    )
    text = (
        f"👋 أهلاً *{message.from_user.first_name}*!\n\n"
        "أنا بوت إدارة الحروب والمشرفين والتفاعل التلقائي.\n"
        "استخدم /help لرؤية كل الأوامر."
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    text = (
        "📖 *قائمة الأوامر:*\n\n"
        "👤 *عامة:*\n"
        "`/start` `/help` `/about` `/myid`\n"
        "`/profile [id]` `/stats` `/leaderboard` `/wars`\n\n"
        "❤️ *التفاعل التلقائي:*\n"
        "`/autoreact on|off` - تشغيل/إيقاف\n"
        "`/setreact ❤️,🔥,👍` - ضبط الإيموجيات\n"
        "`/reactmode random|cycle` - نمط الاختيار\n"
        "`/likes` - إحصائيات هذه المجموعة\n"
        "`/toplikes` - أفضل المجموعات\n\n"
        "🛡 *المشرفين:*\n"
        "`/admin <id>` `/demote <id>` `/admins`\n"
        "`/ban <id> [سبب]` `/unban <id>` `/banned`\n"
        "`/addwar win|loss|draw` `/deletewar <id>`\n"
        "`/addpoints <id> <n>` `/removepoints <id> <n>`\n"
        "`/userstats <id>`\n\n"
        "👑 *سوبر أدمن:*\n"
        "`/broadcast <msg>` `/resetstats` `/maintenance on|off` `/backup`\n\n"
        "👥 *إدارة المجموعة:*\n"
        "`/kick` `/mute [دقائق]` `/unmute` `/pin` `/count`\n\n"
        "⚙️ *الترحيب:*\n"
        "`/setwelcome <نص>` `/welcome on|off` `/resetwelcome`"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['about'])
def cmd_about(message):
    total_users = db_execute("SELECT COUNT(*) as c FROM users", fetch=True)[0]["c"]
    total_likes = db_execute("SELECT COUNT(*) as c FROM likes_log", fetch=True)[0]["c"]
    total_chats = db_execute("SELECT COUNT(*) as c FROM chat_info", fetch=True)[0]["c"]
    text = (
        "🤖 *بوت تيليجرام الشامل v3.0*\n\n"
        f"👥 المستخدمون: *{total_users}*\n"
        f"💬 المجموعات: *{total_chats}*\n"
        f"❤️ إجمالي التفاعلات: *{total_likes}*\n"
        f"👑 سوبر أدمن: *{len(SUPER_ADMIN_IDS)}*\n"
        "⚡ يعمل 24/7 على Render\n"
        "🌐 لوحة التحكم: /"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['myid'])
def cmd_myid(message):
    bot.reply_to(message, f"🆔 معرفك: `{message.from_user.id}`", parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    rows = db_execute("SELECT result, COUNT(*) as c FROM wars GROUP BY result", fetch=True)
    data = {"win": 0, "loss": 0, "draw": 0}
    for r in rows:
        if r["result"] in data:
            data[r["result"]] = r["c"]
    total = sum(data.values())
    bot.reply_to(message,
        f"📊 *إحصائيات الحروب:*\n\n⚔️ الإجمالي: *{total}*\n"
        f"✅ انتصارات: *{data['win']}*\n❌ خسائر: *{data['loss']}*\n🤝 تعادلات: *{data['draw']}*",
        parse_mode="Markdown")

@bot.message_handler(commands=['leaderboard'])
def cmd_leaderboard(message):
    rows = db_execute("SELECT first_name, user_id, points FROM users ORDER BY points DESC LIMIT 10", fetch=True)
    if not rows:
        bot.reply_to(message, "📭 لا يوجد مستخدمون.")
        return
    text = "🏆 *أفضل 10 مستخدمين:*\n\n"
    for i, r in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        text += f"{medal} {r['first_name'] or 'مجهول'} — `{r['user_id']}` — *{r['points']}*\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['wars'])
def cmd_wars(message):
    rows = db_execute("SELECT * FROM wars ORDER BY id DESC LIMIT 10", fetch=True)
    if not rows:
        bot.reply_to(message, "📭 لا توجد حروب.")
        return
    text = "⚔️ *آخر 10 حروب:*\n\n"
    for r in rows:
        e = {"win": "✅", "loss": "❌", "draw": "🤝"}.get(r["result"], "❔")
        text += f"{e} `#{r['id']}` — {r['result']} — {r['date']}\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    args = message.text.split()
    tid = int(args[1]) if len(args) >= 2 and args[1].lstrip("-").isdigit() else message.from_user.id
    r = db_execute("SELECT * FROM users WHERE user_id=?", (tid,), fetch=True)
    if not r:
        bot.reply_to(message, "❌ غير موجود.")
        return
    u = r[0]
    role = "👑 سوبر" if is_super_admin(tid) else ("🛡 مشرف" if is_admin(tid) else "👤 عضو")
    bot.reply_to(message,
        f"👤 *الملف:*\n\n🆔 `{u['user_id']}`\n📛 {u['first_name'] or '—'}\n"
        f"🔗 @{u['username'] or '—'}\n🎖 {role}\n"
        f"💬 {u['messages_count']} رسالة\n⭐ {u['points']} نقطة\n📅 {u['joined_at']}",
        parse_mode="Markdown")

# ==================== أوامر الإدارة ====================
@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 2 or not args[1].lstrip("-").isdigit():
        bot.reply_to(message, "❗ الاستخدام: `/admin <user_id>`", parse_mode="Markdown")
        return
    tid = int(args[1])
    if is_admin(tid):
        bot.reply_to(message, "ℹ️ مشرف مسبقاً.")
        return
    now = datetime.now().isoformat(timespec="seconds")
    db_execute("INSERT OR REPLACE INTO admins (user_id, username, promoted_by, promoted_at) VALUES (?,?,?,?)",
               (tid, None, message.from_user.id, now))
    bot.reply_to(message, f"✅ تم رفع `{tid}` إلى مشرف.", parse_mode="Markdown")
    log_to_channel(f"🛡 رفع مشرف: `{tid}` بواسطة `{message.from_user.id}`")
    try:
        bot.send_message(tid, "🎉 تم رفعك إلى مشرف في البوت.")
    except Exception:
        pass

@bot.message_handler(commands=['demote'])
def cmd_demote(message):
    if not is_super_admin(message.from_user.id):
        bot.reply_to(message, "⛔ للسوبر فقط.")
        return
    args = message.text.split()
    if len(args) != 2 or not args[1].lstrip("-").isdigit():
        bot.reply_to(message, "❗ `/demote <id>`", parse_mode="Markdown")
        return
    tid = int(args[1])
    if is_super_admin(tid):
        bot.reply_to(message, "⛔ لا يمكن تنزيل سوبر أدمن.")
        return
    db_execute("DELETE FROM admins WHERE user_id=?", (tid,))
    bot.reply_to(message, f"✅ تم تنزيل `{tid}`.", parse_mode="Markdown")

@bot.message_handler(commands=['admins'])
def cmd_admins(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    text = "👑 *المشرفون:*\n\n*السوبر:*\n"
    for a in SUPER_ADMIN_IDS:
        text += f"• `{a}`\n"
    rows = db_execute("SELECT user_id FROM admins", fetch=True)
    if rows:
        text += "\n*المرفوعون:*\n"
        for r in rows:
            text += f"• `{r['user_id']}`\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['ban'])
def cmd_ban(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        bot.reply_to(message, "❗ `/ban <id> [سبب]`", parse_mode="Markdown")
        return
    tid = int(args[1])
    reason = args[2] if len(args) > 2 else "بدون سبب"
    if is_super_admin(tid):
        bot.reply_to(message, "⛔ لا يمكن حظر سوبر أدمن.")
        return
    now = datetime.now().isoformat(timespec="seconds")
    db_execute("INSERT OR REPLACE INTO banned (user_id, reason, banned_by, banned_at) VALUES (?,?,?,?)",
               (tid, reason, message.from_user.id, now))
    bot.reply_to(message, f"✅ تم حظر `{tid}`.\nالسبب: {reason}", parse_mode="Markdown")

@bot.message_handler(commands=['unban'])
def cmd_unban(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 2 or not args[1].lstrip("-").isdigit():
        bot.reply_to(message, "❗ `/unban <id>`", parse_mode="Markdown")
        return
    db_execute("DELETE FROM banned WHERE user_id=?", (int(args[1]),))
    bot.reply_to(message, f"✅ تم رفع الحظر عن `{args[1]}`.", parse_mode="Markdown")

@bot.message_handler(commands=['banned'])
def cmd_banned(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    rows = db_execute("SELECT * FROM banned", fetch=True)
    if not rows:
        bot.reply_to(message, "📭 لا يوجد محظورون.")
        return
    text = "🚫 *المحظورون:*\n\n"
    for r in rows:
        text += f"• `{r['user_id']}` — {r['reason']}\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if not is_super_admin(message.from_user.id):
        bot.reply_to(message, "⛔ للسوبر فقط.")
        return
    text = message.text.split(maxsplit=1)
    if len(text) < 2:
        bot.reply_to(message, "❗ `/broadcast <msg>`", parse_mode="Markdown")
        return
    rows = db_execute("SELECT user_id FROM users", fetch=True)
    if not rows:
        bot.reply_to(message, "📭 لا يوجد مستخدمون.")
        return
    sent, failed = 0, 0
    status = bot.reply_to(message, "📤 جاري الإرسال...")
    for r in rows:
        try:
            bot.send_message(r["user_id"], f"📢 *إعلان:*\n\n{text[1]}", parse_mode="Markdown")
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
    bot.edit_message_text(f"✅ نجح: *{sent}*\n❌ فشل: *{failed}*",
                          message.chat.id, status.message_id, parse_mode="Markdown")

@bot.message_handler(commands=['addwar'])
def cmd_addwar(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 2 or args[1].lower() not in ("win", "loss", "draw"):
        bot.reply_to(message, "❗ `/addwar win|loss|draw`", parse_mode="Markdown")
        return
    now = datetime.now().isoformat(timespec="seconds")
    db_execute("INSERT INTO wars (result, registered_by, date) VALUES (?,?,?)",
               (args[1].lower(), message.from_user.id, now))
    e = {"win": "✅", "loss": "❌", "draw": "🤝"}[args[1].lower()]
    bot.reply_to(message, f"{e} تم تسجيل `{args[1].lower()}`.", parse_mode="Markdown")

@bot.message_handler(commands=['deletewar'])
def cmd_deletewar(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        bot.reply_to(message, "❗ `/deletewar <id>`", parse_mode="Markdown")
        return
    db_execute("DELETE FROM wars WHERE id=?", (int(args[1]),))
    bot.reply_to(message, f"✅ تم حذف الحرب `{args[1]}`.", parse_mode="Markdown")

@bot.message_handler(commands=['resetstats'])
def cmd_resetstats(message):
    if not is_super_admin(message.from_user.id):
        bot.reply_to(message, "⛔ للسوبر فقط.")
        return
    db_execute("DELETE FROM wars")
    bot.reply_to(message, "✅ تم تصفير الحروب.")

@bot.message_handler(commands=['addpoints'])
def cmd_addpoints(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 3 or not args[1].lstrip("-").isdigit() or not args[2].isdigit():
        bot.reply_to(message, "❗ `/addpoints <id> <n>`", parse_mode="Markdown")
        return
    db_execute("UPDATE users SET points=points+? WHERE user_id=?", (int(args[2]), int(args[1])))
    bot.reply_to(message, f"✅ +{args[2]} لـ `{args[1]}`.", parse_mode="Markdown")

@bot.message_handler(commands=['removepoints'])
def cmd_removepoints(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 3 or not args[1].lstrip("-").isdigit() or not args[2].isdigit():
        bot.reply_to(message, "❗ `/removepoints <id> <n>`", parse_mode="Markdown")
        return
    db_execute("UPDATE users SET points=MAX(0, points-?) WHERE user_id=?", (int(args[2]), int(args[1])))
    bot.reply_to(message, f"✅ -{args[2]} من `{args[1]}`.", parse_mode="Markdown")

@bot.message_handler(commands=['userstats'])
def cmd_userstats(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 2 or not args[1].lstrip("-").isdigit():
        bot.reply_to(message, "❗ `/userstats <id>`", parse_mode="Markdown")
        return
    r = db_execute("SELECT * FROM users WHERE user_id=?", (int(args[1]),), fetch=True)
    if not r:
        bot.reply_to(message, "❌ غير موجود.")
        return
    u = r[0]
    bot.reply_to(message,
        f"📊 `{u['user_id']}`\n📛 {u['first_name'] or '—'}\n💬 {u['messages_count']}\n⭐ {u['points']}\n📅 {u['joined_at']}",
        parse_mode="Markdown")

# ==================== إدارة المجموعة ====================
@bot.message_handler(commands=['kick'])
def cmd_kick(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "❗ يجب الرد على رسالة المستخدم.")
        return
    try:
        bot.kick_chat_member(message.chat.id, message.reply_to_message.from_user.id)
        bot.reply_to(message, "👢 تم الطرد.")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")

@bot.message_handler(commands=['mute'])
def cmd_mute(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "❗ يجب الرد على المستخدم.")
        return
    args = message.text.split()
    mins = int(args[1]) if len(args) > 1 and args[1].isdigit() else 60
    try:
        bot.restrict_chat_member(message.chat.id, message.reply_to_message.from_user.id,
                                 types.ChatPermissions(can_send_messages=False),
                                 until_date=int(time.time()) + mins * 60)
        bot.reply_to(message, f"🔇 كتم {mins} دقيقة.")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")

@bot.message_handler(commands=['unmute'])
def cmd_unmute(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "❗ يجب الرد على المستخدم.")
        return
    try:
        bot.restrict_chat_member(message.chat.id, message.reply_to_message.from_user.id,
                                 types.ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                                       can_send_other_messages=True, can_add_web_page_previews=True))
        bot.reply_to(message, "🔊 تم إلغاء الكتم.")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")

@bot.message_handler(commands=['pin'])
def cmd_pin(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "❗ رد على الرسالة.")
        return
    try:
        bot.pin_chat_message(message.chat.id, message.reply_to_message.message_id)
        bot.reply_to(message, "📌 تم التثبيت.")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")

@bot.message_handler(commands=['count'])
def cmd_count(message):
    try:
        bot.reply_to(message, f"👥 {bot.get_chat_member_count(message.chat.id)}")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")

# ==================== الترحيب ====================
@bot.message_handler(commands=['setwelcome'])
def cmd_setwelcome(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    t = message.text.split(maxsplit=1)
    if len(t) < 2:
        bot.reply_to(message, "❗ `/setwelcome <نص>` — استخدم `{name}`", parse_mode="Markdown")
        return
    set_setting("welcome_message", t[1])
    bot.reply_to(message, "✅ تم الحفظ.")

@bot.message_handler(commands=['welcome'])
def cmd_welcome(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    args = message.text.split()
    if len(args) != 2 or args[1] not in ("on", "off"):
        bot.reply_to(message, "❗ `/welcome on|off`", parse_mode="Markdown")
        return
    set_setting("welcome_enabled", args[1])
    bot.reply_to(message, f"✅ {args[1]}", parse_mode="Markdown")

@bot.message_handler(commands=['resetwelcome'])
def cmd_resetwelcome(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ ليس لديك صلاحية.")
        return
    set_setting("welcome_message", "👋 أهلاً {name}!")
    bot.reply_to(message, "✅ تم.")

@bot.message_handler(commands=['maintenance'])
def cmd_maintenance(message):
    if not is_super_admin(message.from_user.id):
        bot.reply_to(message, "⛔ للسوبر فقط.")
        return
    args = message.text.split()
    if len(args) != 2 or args[1] not in ("on", "off"):
        bot.reply_to(message, "❗ `/maintenance on|off`", parse_mode="Markdown")
        return
    set_setting("maintenance", args[1])
    bot.reply_to(message, f"✅ الصيانة: `{args[1]}`", parse_mode="Markdown")

@bot.message_handler(commands=['backup'])
def cmd_backup(message):
    if not is_super_admin(message.from_user.id):
        bot.reply_to(message, "⛔ للسوبر فقط.")
        return
    try:
        with open(DB_PATH, "rb") as f:
            bot.send_document(message.chat.id, f, caption="📦 نسخة احتياطية")
    except Exception as e:
        bot.reply_to(message, f"❌ {e}")

@bot.message_handler(content_types=['new_chat_members'])
def welcome_new(message):
    if get_setting("welcome_enabled", "off") != "on":
        return
    template = get_setting("welcome_message", "👋 أهلاً {name}!")
    for m in message.new_chat_members:
        if m.is_bot:
            continue
        try:
            bot.send_message(message.chat.id, template.format(name=m.first_name))
        except Exception:
            pass

# ==================== أزرار القائمة ====================
@bot.message_handler(func=lambda m: m.text == "📊 الإحصائيات")
def btn_stats(m): cmd_stats(m)

@bot.message_handler(func=lambda m: m.text == "📖 المساعدة")
def btn_help(m): cmd_help(m)

@bot.message_handler(func=lambda m: m.text == "👤 ملفي")
def btn_profile(m): cmd_profile(m)

@bot.message_handler(func=lambda m: m.text == "🏆 المتصدرون")
def btn_top(m): cmd_leaderboard(m)

@bot.message_handler(func=lambda m: m.text == "❤️ التفاعل")
def btn_likes(m): cmd_likes(m)

# ==================== مكافحة السبام ====================
def check_flood(message):
    u = message.from_user
    if is_super_admin(u.id) or is_admin(u.id):
        return False
    if message.chat.type == "private":
        return False
    now = time.time()
    flood_data[u.id] = [t for t in flood_data[u.id] if now - t < FLOOD_WINDOW]
    flood_data[u.id].append(now)
    return len(flood_data[u.id]) > FLOOD_LIMIT

@bot.message_handler(func=lambda m: m.chat.type in ("group", "supergroup"), content_types=['text'])
def flood_guard(message):
    if not check_flood(message):
        return
    try:
        bot.restrict_chat_member(message.chat.id, message.from_user.id,
                                 types.ChatPermissions(can_send_messages=False),
                                 until_date=int(time.time()) + 60)
        bot.send_message(message.chat.id, f"🔇 كتم `{message.from_user.id}` 60 ثانية (سبام).",
                         parse_mode="Markdown")
    except Exception:
        pass
    flood_data[message.from_user.id] = []

# ==================== Keep Alive ====================
def ping_service():
    while True:
        try:
            r = requests.get(RENDER_URL, timeout=15)
            print(f"[KeepAlive] {r.status_code} @ {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[KeepAlive] {e}")
        time.sleep(5 * 60)

def start_keep_alive():
    threading.Thread(target=ping_service, daemon=True).start()
    print("[KeepAlive] Started")

# ==================== لوحة التحكم (Dashboard) ====================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🤖 لوحة تحكم البوت</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Segoe UI', Tahoma, sans-serif;
  background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
  min-height: 100vh; color: #e0e0e0; padding: 20px;
  overflow-x: hidden;
}
body::before {
  content: ''; position: fixed; top: -50%; left: -50%;
  width: 200%; height: 200%;
  background: radial-gradient(circle, rgba(120,80,255,0.15) 0%, transparent 40%);
  animation: rotate 20s linear infinite; z-index: 0;
}
@keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.container { max-width: 1400px; margin: 0 auto; position: relative; z-index: 1; }
header { text-align: center; margin-bottom: 30px; animation: fadeIn 1s; }
header h1 {
  font-size: 3em; margin-bottom: 10px;
  background: linear-gradient(90deg, #00d4ff, #b24dff, #ff4d94, #00d4ff);
  background-size: 300% 100%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shine 3s linear infinite;
}
@keyframes shine { 0% { background-position: 0% 50%; } 100% { background-position: 300% 50%; } }
header p { color: #aaa; font-size: 1.1em; }
.status-badge {
  display: inline-block; padding: 6px 16px; border-radius: 20px;
  background: rgba(0,255,100,0.15); color: #00ff88;
  border: 1px solid rgba(0,255,100,0.3); margin-top: 10px;
  font-size: 0.9em; animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }
.stats-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 20px; margin-bottom: 30px;
}
.stat-card {
  background: rgba(255,255,255,0.05);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px; padding: 25px;
  position: relative; overflow: hidden;
  transition: transform 0.3s, box-shadow 0.3s;
  animation: fadeIn 0.8s backwards;
}
.stat-card:nth-child(1) { animation-delay: 0.1s; }
.stat-card:nth-child(2) { animation-delay: 0.2s; }
.stat-card:nth-child(3) { animation-delay: 0.3s; }
.stat-card:nth-child(4) { animation-delay: 0.4s; }
.stat-card:nth-child(5) { animation-delay: 0.5s; }
.stat-card:nth-child(6) { animation-delay: 0.6s; }
.stat-card:hover { transform: translateY(-5px); box-shadow: 0 10px 40px rgba(120,80,255,0.3); }
.stat-card::before {
  content: ''; position: absolute; top: 0; left: 0;
  width: 100%; height: 4px;
  background: linear-gradient(90deg, #00d4ff, #b24dff);
}
.stat-icon { font-size: 2.5em; margin-bottom: 10px; }
.stat-value {
  font-size: 2.5em; font-weight: bold;
  background: linear-gradient(90deg, #fff, #b24dff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.stat-label { color: #999; font-size: 0.95em; margin-top: 5px; }
.charts-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 20px; margin-bottom: 30px;
}
.chart-card {
  background: rgba(255,255,255,0.05); backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px; padding: 25px;
  animation: fadeIn 1s;
}
.chart-card h3 { margin-bottom: 20px; color: #b24dff; }
.chart-container { height: 300px; position: relative; }
.table-card {
  background: rgba(255,255,255,0.05); backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px; padding: 25px; animation: fadeIn 1.2s;
}
.table-card h3 { margin-bottom: 20px; color: #00d4ff; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 12px; text-align: right; border-bottom: 1px solid rgba(255,255,255,0.1); }
th { color: #b24dff; font-weight: 600; }
tr:hover { background: rgba(255,255,255,0.03); }
.medal { font-size: 1.3em; }
.refresh-btn {
  position: fixed; bottom: 30px; left: 30px;
  background: linear-gradient(135deg, #00d4ff, #b24dff);
  border: none; color: white; padding: 15px 25px;
  border-radius: 50px; cursor: pointer; font-size: 1em;
  font-weight: bold; box-shadow: 0 5px 20px rgba(120,80,255,0.4);
  transition: all 0.3s; z-index: 10;
}
.refresh-btn:hover { transform: scale(1.05); box-shadow: 0 8px 30px rgba(120,80,255,0.6); }
@keyframes fadeIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
.loading { text-align: center; padding: 40px; color: #999; }
@media (max-width: 768px) {
  header h1 { font-size: 2em; }
  .charts-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🤖 لوحة تحكم البوت</h1>
    <p>إحصائيات حية ومباشرة</p>
    <span class="status-badge" id="status">● متصل</span>
  </header>

  <div class="stats-grid" id="statsGrid">
    <div class="stat-card"><div class="stat-icon">👥</div><div class="stat-value" id="totalUsers">—</div><div class="stat-label">إجمالي المستخدمين</div></div>
    <div class="stat-card"><div class="stat-icon">💬</div><div class="stat-value" id="totalChats">—</div><div class="stat-label">المجموعات</div></div>
    <div class="stat-card"><div class="stat-icon">❤️</div><div class="stat-value" id="totalLikes">—</div><div class="stat-label">إجمالي التفاعلات</div></div>
    <div class="stat-card"><div class="stat-icon">📅</div><div class="stat-value" id="todayLikes">—</div><div class="stat-label">تفاعلات اليوم</div></div>
    <div class="stat-card"><div class="stat-icon">⚔️</div><div class="stat-value" id="totalWars">—</div><div class="stat-label">إجمالي الحروب</div></div>
    <div class="stat-card"><div class="stat-icon">🛡</div><div class="stat-value" id="totalAdmins">—</div><div class="stat-label">المشرفون</div></div>
  </div>

  <div class="charts-grid">
    <div class="chart-card">
      <h3>📈 التفاعلات - آخر 7 أيام</h3>
      <div class="chart-container"><canvas id="weeklyChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>🎯 أكثر الإيموجيات</h3>
      <div class="chart-container"><canvas id="emojiChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>🥇 نتائج الحروب</h3>
      <div class="chart-container"><canvas id="warsChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>📊 التفاعلات - آخر 24 ساعة</h3>
      <div class="chart-container"><canvas id="hourlyChart"></canvas></div>
    </div>
  </div>

  <div class="table-card" style="margin-bottom:30px">
    <h3>🏆 أكثر 10 مجموعات تفاعلاً</h3>
    <table>
      <thead><tr><th>#</th><th>المجموعة</th><th>الإجمالي</th><th>هذا الأسبوع</th></tr></thead>
      <tbody id="topChatsTable"><tr><td colspan="4" class="loading">جاري التحميل...</td></tr></tbody>
    </table>
  </div>
</div>

<button class="refresh-btn" onclick="loadData()">🔄 تحديث</button>

<script>
let weeklyChart, emojiChart, warsChart, hourlyChart;

async function loadData() {
  try {
    document.getElementById('status').textContent = '● متصل';
    const res = await fetch('/api/stats');
    const data = await res.json();
    if (!data.ok) throw new Error('Failed');

    document.getElementById('totalUsers').textContent = data.total_users.toLocaleString('ar-EG');
    document.getElementById('totalChats').textContent = data.total_chats.toLocaleString('ar-EG');
    document.getElementById('totalLikes').textContent = data.total_likes.toLocaleString('ar-EG');
    document.getElementById('todayLikes').textContent = data.today_likes.toLocaleString('ar-EG');
    document.getElementById('totalWars').textContent = data.total_wars.toLocaleString('ar-EG');
    document.getElementById('totalAdmins').textContent = data.total_admins.toLocaleString('ar-EG');

    renderWeeklyChart(data.weekly);
    renderEmojiChart(data.top_emojis);
    renderWarsChart(data.wars_breakdown);
    renderHourlyChart(data.hourly);
    renderTopChats(data.top_chats);
  } catch (e) {
    document.getElementById('status').textContent = '● خطأ';
    console.error(e);
  }
}

function renderWeeklyChart(weekly) {
  const ctx = document.getElementById('weeklyChart').getContext('2d');
  if (weeklyChart) weeklyChart.destroy();
  weeklyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: weekly.map(w => w.day),
      datasets: [{
        label: 'التفاعلات',
        data: weekly.map(w => w.count),
        borderColor: '#00d4ff',
        backgroundColor: 'rgba(0,212,255,0.15)',
        tension: 0.4, fill: true, borderWidth: 3,
        pointBackgroundColor: '#b24dff',
        pointBorderColor: '#fff', pointRadius: 6,
      }]
    },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#e0e0e0' } } },
      scales: {
        x: { ticks: { color: '#999' }, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { ticks: { color: '#999' }, grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true }
      }
    }
  });
}

function renderEmojiChart(emojis) {
  const ctx = document.getElementById('emojiChart').getContext('2d');
  if (emojiChart) emojiChart.destroy();
  const colors = ['#b24dff','#00d4ff','#ff4d94','#00ff88','#ffaa00','#ff6666','#66ddff'];
  emojiChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: emojis.map(e => e.emoji),
      datasets: [{
        data: emojis.map(e => e.count),
        backgroundColor: colors.slice(0, emojis.length),
        borderColor: 'rgba(0,0,0,0.3)', borderWidth: 3,
      }]
    },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#e0e0e0', font: { size: 16 } } } }
    }
  });
}

function renderWarsChart(wars) {
  const ctx = document.getElementById('warsChart').getContext('2d');
  if (warsChart) warsChart.destroy();
  warsChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ['✅ فوز', '❌ خسارة', '🤝 تعادل'],
      datasets: [{
        data: [wars.win, wars.loss, wars.draw],
        backgroundColor: ['rgba(0,255,136,0.7)', 'rgba(255,77,77,0.7)', 'rgba(255,170,0,0.7)'],
        borderColor: ['#00ff88', '#ff4d4d', '#ffaa00'],
        borderWidth: 2, borderRadius: 10,
      }]
    },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#e0e0e0', font: { size: 14 } }, grid: { display: false } },
        y: { ticks: { color: '#999' }, grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true }
      }
    }
  });
}

function renderHourlyChart(hourly) {
  const ctx = document.getElementById('hourlyChart').getContext('2d');
  if (hourlyChart) hourlyChart.destroy();
  hourlyChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: hourly.map(h => h.hour + ':00'),
      datasets: [{
        label: 'التفاعلات',
        data: hourly.map(h => h.count),
        backgroundColor: 'rgba(178,77,255,0.7)',
        borderColor: '#b24dff', borderWidth: 2, borderRadius: 8,
      }]
    },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#e0e0e0' } } },
      scales: {
        x: { ticks: { color: '#999' }, grid: { display: false } },
        y: { ticks: { color: '#999' }, grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true }
      }
    }
  });
}

function renderTopChats(chats) {
  const tbody = document.getElementById('topChatsTable');
  if (!chats || chats.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" class="loading">لا توجد بيانات</td></tr>';
    return;
  }
  const medals = ['🥇', '🥈', '🥉'];
  tbody.innerHTML = chats.map((c, i) =>
    `<tr>
      <td><span class="medal">${medals[i] || (i + 1)}</span></td>
      <td>${c.title || c.chat_id}</td>
      <td><strong style="color:#b24dff">${c.likes_total.toLocaleString('ar-EG')}</strong></td>
      <td><strong style="color:#00d4ff">${c.week.toLocaleString('ar-EG')}</strong></td>
    </tr>`
  ).join('');
}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""

@app.route('/')
def index():
    return Response(DASHBOARD_HTML, mimetype='text/html')

@app.route('/healthcheck')
def healthcheck():
    return "OK", 200

@app.route('/api/stats')
def api_stats():
    try:
        total_users = db_execute("SELECT COUNT(*) as c FROM users", fetch=True)[0]["c"]
        total_chats = db_execute("SELECT COUNT(*) as c FROM chat_info", fetch=True)[0]["c"]
        total_likes = db_execute("SELECT COUNT(*) as c FROM likes_log", fetch=True)[0]["c"]
        today = datetime.now().strftime("%Y-%m-%d")
        today_likes = db_execute("SELECT COUNT(*) as c FROM likes_log WHERE sent_at LIKE ?",
                                 (f"{today}%",), fetch=True)[0]["c"]
        total_wars = db_execute("SELECT COUNT(*) as c FROM wars", fetch=True)[0]["c"]
        total_admins = db_execute("SELECT COUNT(*) as c FROM admins", fetch=True)[0]["c"]

        # آخر 7 أيام
        weekly = []
        for i in range(6, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            count = db_execute("SELECT COUNT(*) as c FROM likes_log WHERE sent_at LIKE ?",
                              (f"{d}%",), fetch=True)[0]["c"]
            day_name = ["الأحد","الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت"][
                (datetime.now() - timedelta(days=i)).weekday()]
            weekly.append({"day": day_name, "count": count})

        # آخر 24 ساعة
        hourly = []
        now = datetime.now()
        for i in range(23, -1, -1):
            h = (now - timedelta(hours=i)).strftime("%Y-%m-%d %H")
            count = db_execute("SELECT COUNT(*) as c FROM likes_log WHERE sent_at LIKE ?",
                              (f"{h}%",), fetch=True)[0]["c"]
            hourly.append({"hour": (now - timedelta(hours=i)).hour, "count": count})

        top_emojis = [{"emoji": r["emoji"], "count": r["c"]} for r in
                      db_execute("SELECT emoji, COUNT(*) as c FROM likes_log GROUP BY emoji ORDER BY c DESC LIMIT 7", fetch=True)]

        wars_rows = db_execute("SELECT result, COUNT(*) as c FROM wars GROUP BY result", fetch=True)
        wars_breakdown = {"win": 0, "loss": 0, "draw": 0}
        for r in wars_rows:
            if r["result"] in wars_breakdown:
                wars_breakdown[r["result"]] = r["c"]

        week_ago = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
        top_chats = [
            {"title": r["title"], "chat_id": r["chat_id"],
             "likes_total": r["likes_total"], "week": r["week"]}
            for r in db_execute(
                """SELECT c.title, c.chat_id, c.likes_total,
                    (SELECT COUNT(*) FROM likes_log l WHERE l.chat_id=c.chat_id AND l.sent_at >= ?) as week
                    FROM chat_info c ORDER BY c.likes_total DESC LIMIT 10""",
                (week_ago,), fetch=True)
        ]

        return jsonify({
            "ok": True,
            "total_users": total_users,
            "total_chats": total_chats,
            "total_likes": total_likes,
            "today_likes": today_likes,
            "total_wars": total_wars,
            "total_admins": total_admins + len(SUPER_ADMIN_IDS),
            "weekly": weekly,
            "hourly": hourly,
            "top_emojis": top_emojis,
            "wars_breakdown": wars_breakdown,
            "top_chats": top_chats,
        })
    except Exception as e:
        print(f"API error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
            bot.process_new_updates([update])
            return '', 200
        except Exception as e:
            print(f"Webhook error: {e}")
            return '', 200
    return '', 403

# ==================== التشغيل ====================
def run_bot():
    bot.remove_webhook()
    time.sleep(1)
    webhook_url = os.environ.get("WEBHOOK_URL", RENDER_URL.rstrip("/") + "/webhook")
    bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    print(f"[Bot] Webhook: {webhook_url}")

init_db()
bot.setup_middleware(AccessMiddleware())

if __name__ == "__main__":
    start_keep_alive()
    try:
        run_bot()
    except Exception as e:
        print(f"[Bot] Webhook setup: {e}")
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
