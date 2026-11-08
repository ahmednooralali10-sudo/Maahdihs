
import requests
import telebot
import json
import os
import time
import threading

from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


# ==============================
# CONFIGURATION
# ==============================

TOKEN = os.environ["BOT_TOKEN"]

CHANNEL_ID = "@hmzahjrjjvvhdh"

ROOT_IDS = [8987133011, 6464857808, 8930921922]
OWNER_IDS = ROOT_IDS.copy()

ADMINS_FILE = "developers.json"


# ==============================
# RENDER WEB SERVER
# ==============================

app = Flask(__name__)


@app.route("/")
def home():
    return "Telegram Bot is Running! OK", 200


@app.route("/health")
def health():
    return "ONLINE", 200


def run_web_server():
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


def keep_alive():
    while True:
        try:
            time.sleep(300)

            response = requests.get(
                "https://maahdihs.onrender.com",
                timeout=30
            )

            print("KEEP ALIVE:", response.status_code)

        except Exception as e:
            print("KEEP ALIVE ERROR:", repr(e))


# ==============================
# DEVELOPERS
# ==============================

def load_developers():
    global OWNER_IDS

    OWNER_IDS = ROOT_IDS.copy()

    try:
        with open(ADMINS_FILE, "r") as f:
            saved_ids = json.load(f)

        for user_id in saved_ids:
            user_id = int(user_id)
            if user_id not in OWNER_IDS:
                OWNER_IDS.append(user_id)

    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass


def save_developers():
    extra_ids = [uid for uid in OWNER_IDS if uid not in ROOT_IDS]

    with open(ADMINS_FILE, "w") as f:
        json.dump(extra_ids, f)


def is_root(user_id):
    return user_id in ROOT_IDS


load_developers()


LIKE_API = "https://liketi-iota.vercel.app/like"

VIDEO_MAIN = "vd.mp4"
VIDEO_PRIVATE = "vgh.mp4"
VIDEO_ERROR = "vod.mp4"
VIDEO_LIKE_ERROR = "vhd.mp4"
VIDEO_LIKE_SUCCESS = "vp.mp4"

GROUPS_FILE = "active_groups.json"
DAILY_FILE = "daily_limits.json"
GLOBAL_FILE = "global_status.json"
AUTOLIKE_FILE = "autolike.json"


# ==============================
# AUTOLIKE DATA
# ==============================

def load_autolike():
    try:
        with open(AUTOLIKE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


AUTOLIKE_DATA = load_autolike()


def save_autolike():
    with open(AUTOLIKE_FILE, "w") as f:
        json.dump(AUTOLIKE_DATA, f)


bot = telebot.TeleBot(TOKEN, parse_mode="HTML")


# ==============================
# GROUPS
# ==============================

def load_groups():
    try:
        with open(GROUPS_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()


ACTIVE_GROUPS = load_groups()


# ==============================
# DAILY LIMITS
# ==============================

def load_daily_limits():
    try:
        with open(DAILY_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


DAILY_LIMITS = load_daily_limits()


# ==============================
# GLOBAL STATUS
# ==============================

def load_global_status():
    try:
        with open(GLOBAL_FILE, "r") as f:
            return json.load(f).get("enabled", True)
    except:
        return True


BOT_ENABLED = load_global_status()


def save_global_status():
    with open(GLOBAL_FILE, "w") as f:
        json.dump({"enabled": BOT_ENABLED}, f)


def save_daily_limits():
    with open(DAILY_FILE, "w") as f:
        json.dump(DAILY_LIMITS, f)


def get_user_attempts(user_id):
    now = time.time()
    user_id = str(user_id)

    attempts = DAILY_LIMITS.get(user_id, [])

    attempts = [
        t for t in attempts
        if now - t < 86400
    ]

    DAILY_LIMITS[user_id] = attempts
    save_daily_limits()

    return attempts


def add_user_attempt(user_id):
    user_id = str(user_id)

    attempts = get_user_attempts(user_id)
    attempts.append(time.time())

    DAILY_LIMITS[user_id] = attempts
    save_daily_limits()


def save_groups():
    with open(GROUPS_FILE, "w") as f:
        json.dump(list(ACTIVE_GROUPS), f)


def is_developer(user_id):
    return user_id in OWNER_IDS


# ==============================
# ADD DEVELOPER
# ==============================

@bot.message_handler(commands=["admin"])
def add_developer(message):
    if not is_root(message.from_user.id):
        return

    try:
        args = message.text.split()

        if len(args) != 2:
            bot.reply_to(message, "<b>الاستخدام الصحيح:\n/admin ID</b>")
            return

        user_id = int(args[1])

        if user_id <= 0:
            bot.reply_to(message, "<b>❌ الآيدي غير صحيح</b>")
            return

        if user_id in OWNER_IDS:
            bot.reply_to(message, "<b> هذا الشخص موجود بالفعل ضمن المطورين 👻</b>")
            return

        OWNER_IDS.append(user_id)
        save_developers()

        try:
            user = bot.get_chat(user_id)
            name = user.username and f"@{user.username}" or user.first_name
        except Exception:
            name = str(user_id)

        text = f"""
<b>تم اضافة {name} إلى قائمة المطورين بنجاح 👻

يمكنه استخدام أوامر المطورين الآن 💯

🎗️Owner : @Hmza645🎗️</b>
"""

        send_video_message(message.chat.id, "vd.mp4", text)

    except ValueError:
        bot.reply_to(message, "<b>❌ اكتب آيدي صحيح</b>")
    except Exception as e:
        bot.reply_to(message, f"حدث خطأ: {e}")


# ==============================
# REMOVE DEVELOPER
# ==============================

@bot.message_handler(commands=["nadmin"])
def remove_developer(message):
    if not is_root(message.from_user.id):
        return

    try:
        args = message.text.split()

        if len(args) != 2:
            bot.reply_to(message, "<b>الاستخدام الصحيح:\n/nadmin ID</b>")
            return

        user_id = int(args[1])

        if user_id in ROOT_IDS:
            bot.reply_to(message, "❌ لا يمكن حذف المطور الأساسي.")
            return

        if user_id not in OWNER_IDS:
            bot.reply_to(message, "<b>هذا الشخص ليس ضمن قائمة المطورين</b>")
            return

        OWNER_IDS.remove(user_id)
        save_developers()

        try:
            user = bot.get_chat(user_id)
            name = user.username and f"@{user.username}" or user.first_name
        except Exception:
            name = str(user_id)

        text = f"""
<b>تم نزل {name} من قائمة المطورين بنجاح ✅

غير قادر الآن هو على استخدام الاوامر 👾

🎗️Owner : @Hmza645🎗️</b>
"""

        send_video_message(message.chat.id, "vod.mp4", text)

    except ValueError:
        bot.reply_to(message, "<b>❌ اكتب آيدي صحيح</b>")
    except Exception as e:
        bot.reply_to(message, f"<b>حدث خطأ: {e}</b>")


# ==============================
# ACCESS CONTROL
# ==============================

def is_private(message):
    return message.chat.type == "private"


def access_allowed(message):

    user_id = message.from_user.id

    if is_private(message):
        return is_developer(user_id)

    if not BOT_ENABLED:

        send_video_message(
            message.chat.id,
            VIDEO_MAIN,
            """
<b>عذرا 👀

البوت حاليا مطفي من قبل المطور لدى جميع المجموعات 😐

🎗️Owner : @Hmza645🎗️</b>
"""
        )

        return False

    if message.chat.id not in ACTIVE_GROUPS:

        send_video_message(
            message.chat.id,
            VIDEO_ERROR,
            """
<b>عذرا يا صديقي 🫣❌

تم اطفاء البوت في هذه المجموعة 🙈

الرجاء الاتصال مع المطور 🗿 :

🎗️Owner : @Hmza645🎗️</b>
"""
        )

        return False

    return True


# ==============================
# SUBSCRIPTION
# ==============================

def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status != "left"
    except Exception as e:
        print("SUBSCRIPTION ERROR:", repr(e))
        return False


def sub_buttons():
    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "تم الاشتراك ✅",
            callback_data="check_sub"
        )
    )

    return markup


# ==============================
# REPLY CONTEXT
# ==============================

REPLY_CONTEXT = threading.local()


def set_reply(message):
    REPLY_CONTEXT.chat_id = message.chat.id
    REPLY_CONTEXT.message_id = message.message_id


# ==============================
# VIDEO MESSAGES
# ==============================

def send_video_message(chat_id, video_file, text, reply_to_message_id=None):

    if reply_to_message_id is None:
        if getattr(REPLY_CONTEXT, "chat_id", None) == chat_id:
            reply_to_message_id = getattr(
                REPLY_CONTEXT,
                "message_id",
                None
            )

    with open(video_file, "rb") as video:
        bot.send_video(
            chat_id,
            video,
            caption=text,
            parse_mode="HTML",
            reply_to_message_id=reply_to_message_id
        )


# ==============================
# PRIVATE USERS
# ==============================

@bot.message_handler(
    func=lambda m: (
        m.chat.type == "private"
        and not is_developer(m.from_user.id)
        and not (
            (m.text or "").split()
            and (m.text or "").split()[0].split("@")[0].lower()
            in ["/xgurb", "/xn", "/xf"]
        )
    ),
    content_types=[
        "text",
        "photo",
        "video",
        "document",
        "audio",
        "voice",
        "sticker",
        "animation",
        "contact",
        "location"
    ]
)
def private_users(message):

    send_video_message(
        message.chat.id,
        VIDEO_PRIVATE,
        """
<b>عذرا يا صديقي 🗿💔

البوت يشتغل فقط في المجموعة :

https://t.me/hmzahjrjjvvhdh

🎗️Owner : @Hmza645🎗️</b>
"""
    )


# ==============================
# LOADING
# ==============================

def show_loading(chat_id):
    reply_id = None

    if getattr(REPLY_CONTEXT, "chat_id", None) == chat_id:
        reply_id = getattr(REPLY_CONTEXT, "message_id", None)

    return bot.send_message(
        chat_id,
        "🔹💠🔷",
        reply_to_message_id=reply_id
    )


def send_text_reply(chat_id, text, **kwargs):
    reply_id = None

    if getattr(REPLY_CONTEXT, "chat_id", None) == chat_id:
        reply_id = getattr(REPLY_CONTEXT, "message_id", None)

    return bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_to_message_id=reply_id,
        **kwargs
    )


def delete_loading(chat_id, msg_id):

    try:
        bot.delete_message(chat_id, msg_id)
    except:
        pass


# ==============================
# HELP
# ==============================

def owner_help():

    return """
<b>✳️ Welcome the Owner to like Bot ✳️

✨ الاوامر :

<code>/like uid</code>

- لإرسال اللايكات إلى اللاعب !

🎗️Owner : @Hmza645🎗️</b>
"""


def user_help():

    return """
<b>✳️ Welcome to the like Bot ✳️

✨ الاوامر :

<code>/like uid</code>

- لإرسال اللايكات إلى اللاعب !

🎗️Owner : @Hmza645🎗️</b>
"""


# ==============================
# TURN ON GROUP
# ==============================

@bot.message_handler(commands=["on"])
def turn_on(message):

    if is_private(message):
        if is_developer(message.from_user.id):
            bot.send_message(
                message.chat.id,
                "هذا الأمر يعمل داخل المجموعات فقط."
            )
        return

    if not is_developer(message.from_user.id):
        return

    if message.chat.id in ACTIVE_GROUPS:
        send_video_message(
            message.chat.id,
            VIDEO_ERROR,
            "<b>البوت مفعل بالمجموعة بالفعل 🗿</b>"
        )
        return

    ACTIVE_GROUPS.add(message.chat.id)
    save_groups()

    send_video_message(
        message.chat.id,
        VIDEO_LIKE_SUCCESS,
        "<b>تم تشغيل البوت في هذه المجموعة بنجاح ✅</b>"
    )


# ==============================
# TURN OFF GROUP
# ==============================

@bot.message_handler(commands=["off"])
def turn_off(message):

    if is_private(message):
        if is_developer(message.from_user.id):
            bot.send_message(
                message.chat.id,
                "هذا الأمر يعمل داخل المجموعات فقط."
            )
        return

    if not is_developer(message.from_user.id):
        return

    if message.chat.id not in ACTIVE_GROUPS:
        bot.send_message(
            message.chat.id,
            "<b>البوت ملغي في هذه المجموعة بالفعل 😶\n\n🎗️Owner : @Hmza645🎗️</b>"
        )
        return

    ACTIVE_GROUPS.discard(message.chat.id)
    save_groups()

    send_text_reply(
        message.chat.id,
        "<b>تم إطفاء البوت في هذه المجموعة بنجاح 🙈</b>"
    )


# ==============================
# SID COMMAND
# ==============================

@bot.message_handler(commands=["sid"])
def sid_command(message):

    if is_private(message):
        if is_developer(message.from_user.id):
            bot.send_message(
                message.chat.id,
                "هذا الأمر يعمل داخل المجموعات فقط."
            )
        return

    if not is_developer(message.from_user.id):
        return

    ACTIVE_GROUPS.add(message.chat.id)
    save_groups()

    send_video_message(
        message.chat.id,
        VIDEO_LIKE_SUCCESS,
        """
<b>تم تشغيل البوت في هذه المجموعة بنجاح ✅

يمكنكم استخدام البوت الآن 🦋

ارسل /help ~ لاظهار الاوامر 📍

🎗️Owner : @Hmza645🎗️</b>
"""
    )


# ==============================
# GLOBAL GROUP CONTROL
# ==============================

def admin_only_message(message):

    send_video_message(
        message.chat.id,
        VIDEO_ERROR,
        """
<b>عذرا هذا الأمر يخص الادمن فقط 😑

تواصل مع الادمن لكي يمكنك عمل هذا الأمر 🚀

🎗️Owner : @Hmza645🎗️</b>
"""
    )


@bot.message_handler(commands=["xn"])
def turn_on_all(message):

    set_reply(message)

    global BOT_ENABLED

    if not is_developer(message.from_user.id):
        admin_only_message(message)
        return

    BOT_ENABLED = True
    save_global_status()

    send_video_message(
        message.chat.id,
        VIDEO_LIKE_SUCCESS,
        """
<b>تم تشغيل البوت في كل المجموعات المفعلة بنجاح 😼

🎗️Owner : @Hmza645🎗️</b>
"""
    )


@bot.message_handler(commands=["xf"])
def turn_off_all(message):

    set_reply(message)

    global BOT_ENABLED

    if not is_developer(message.from_user.id):
        admin_only_message(message)
        return

    BOT_ENABLED = False
    save_global_status()

    send_video_message(
        message.chat.id,
        VIDEO_LIKE_ERROR,
        """
<b>تم اطفاء البوت في جميع الكروبات بنجاح 🌸

🎗️Owner : @Hmza645🎗️</b>
"""
    )


@bot.message_handler(commands=["xgurb"])
def groups_status(message):

    set_reply(message)

    if not is_developer(message.from_user.id):
        return

    groups = sorted(ACTIVE_GROUPS)

    text = f"""<b>☣️ عدد المجموعات التي تم تشغيل البوت بها :

~ {len(groups)}

☣️ روابط المجموعات المفعلة بيها البوت ؛

"""

    for index, group_id in enumerate(groups, start=1):
        try:
            chat = bot.get_chat(group_id)

            if chat.username:
                group_link = f"https://t.me/{chat.username}"
            elif getattr(chat, "invite_link", None):
                group_link = chat.invite_link
            else:
                group_link = "الرابط غير متاح حالياً"

        except Exception as e:
            print("GROUP LINK ERROR:", group_id, repr(e))
            group_link = "الرابط غير متاح حالياً"

        text += f"""كروب رقم : {index}

~ {group_link}

"""

    text += """|~ لايقاف البوت في كل الكروبات ارسل :

/xf

|~ لتشغيل البوت في جميع الكروبات ارسل :

/xn

🎗️Owner : @Hmza645🎗️</b>"""

    header = f"""<b>☣️ عدد المجموعات المفعلة : {len(groups)} ☣️

☣️ روابط المجموعات المفعلة :▪️ تحت هذه الرسالة ▪️ ☣️</b>"""

    send_video_message(
        message.chat.id,
        VIDEO_PRIVATE,
        header
    )

    for start in range(0, len(text), 3500):
        bot.send_message(
            message.chat.id,
            text[start:start + 3500],
            parse_mode="HTML",
            reply_to_message_id=message.message_id
        )


# ==============================
# SUBSCRIPTION CALLBACK
# ==============================

@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def check_sub(c):

    if not is_developer(c.from_user.id):

        if c.message.chat.type == "private":
            return

        if c.message.chat.id not in ACTIVE_GROUPS:
            return

    if not check_subscription(c.from_user.id):

        bot.answer_callback_query(
            c.id,
            "❌ لم يتم العثور على اشتراكك",
            show_alert=True
        )

        return

    bot.answer_callback_query(
        c.id,
        "✅ تم التحقق من الاشتراك"
    )

    text = owner_help() if is_developer(c.from_user.id) else user_help()

    send_video_message(
        c.message.chat.id,
        VIDEO_MAIN,
        text
    )


# ==============================
# START / HELP
# ==============================

@bot.message_handler(commands=["start", "help", "hi"])
def start(message):

    set_reply(message)

    if not access_allowed(message):
        return

    if not check_subscription(message.from_user.id):

        bot.send_message(
            message.chat.id,
            """<b>عذراً 🫣

يجب عليك الدخول أولاً إلى القناة الخاصة بنا !

رابط القناة :
https://t.me/hmzahjrjjvvhdh</b>""",
            reply_markup=sub_buttons()
        )

        return

    loading = show_loading(message.chat.id)

    text = owner_help() if is_developer(message.from_user.id) else user_help()

    send_video_message(
        message.chat.id,
        VIDEO_MAIN,
        text
    )

    delete_loading(
        message.chat.id,
        loading.message_id
    )


# ==============================
# AUTOLIKE EXECUTION
# ==============================

def execute_autolike(uid, chat_id):

    try:
        response = requests.get(
            LIKE_API,
            params={"uid": uid},
            timeout=60
        )

        response.raise_for_status()
        data = response.json()

        PlayerNickname = data.get("PlayerNickname", "Unknown")
        LikesGivenByAPI = int(data.get("LikesGivenByAPI", 0))
        LikesBefore = data.get("LikesBefore", 0)
        LikesAfter = data.get("LikesAfter", 0)

        if LikesGivenByAPI <= 0:
            send_video_message(
                chat_id,
                VIDEO_LIKE_ERROR,
                f"""<b>🚀 أوتو لايك 🚀

عذرا يا صديقي 🫣❌

تم زيادة اللايكات اليوم 🫠

غدا تلقائيا سوف يتم زيادة لايكاتك الرسالة النتيجة هنا 😼
🎗️Owner : @Hmza645🎗️</b>"""
            )
            return

        send_video_message(
            chat_id,
            VIDEO_LIKE_SUCCESS,
            f"""<b>🚀 أوتو لايك 🚀

تم الارسال بنجاح 😶‍🌫️

✨ اسم الحساب :
{PlayerNickname}

✨ عدد اللايكات قبل الزيادة :
{LikesBefore}

✨ عدد اللايكات بعد الزيادة :
{LikesAfter}

✨ عدد اللايكات المضافة :
{LikesGivenByAPI}

🦋 سوف يتم زيادة اللايكات كل 25 ساعة سيظهر النتائج هنا 🦋

🎗️Owner : @Hmza645🎗️</b>"""
        )

    except Exception as e:
        print("AUTOLIKE ERROR:", repr(e))

        send_video_message(
            chat_id,
            VIDEO_ERROR,
            """<b>🚀 أوتو لايك 🚀

عذراً يا صديقي 🫠❌

فشل الاتصــال بالــ Api
الرجاء المحاولة فيما بعد 😶‍🌫️

~ لكن تم اضافتك ضمن أوتو لايك 🗿

🎗️Owner : @Hmza645🎗️</b>"""
        )


# ==============================
# AUTOLIKE COMMAND
# ==============================

@bot.message_handler(commands=["autolike"])
def autolike_command(message):

    if not is_developer(message.from_user.id):
        admin_only_message(message)
        return

    args = message.text.split()

    if len(args) != 2 or not args[1].isdigit():

        send_video_message(
            message.chat.id,
            VIDEO_LIKE_ERROR,
            """<b>🚀 أوتو لايك 🚀

عذرا 🫣❌

الرجاء إدخال الاوامر بشكل صحيح :

/autolike uid

🌑example :

/autolike 12345678

🎗️Owner : @Hmza645🎗️</b>"""
        )
        return

    uid = args[1]

    AUTOLIKE_DATA.update({
        "uid": uid,
        "chat_id": message.chat.id,
        "next_run": time.time() + (25 * 60 * 60)
    })

    save_autolike()

    execute_autolike(uid, message.chat.id)


# ==============================
# AUTOLIKE SCHEDULER
# ==============================

def autolike_scheduler():

    while True:

        try:
            if AUTOLIKE_DATA:
                next_run = AUTOLIKE_DATA.get("next_run", 0)

                if time.time() >= next_run:

                    uid = AUTOLIKE_DATA.get("uid")
                    chat_id = AUTOLIKE_DATA.get("chat_id")

                    if uid and chat_id:

                        AUTOLIKE_DATA["next_run"] = (
                            time.time() + (25 * 60 * 60)
                        )

                        save_autolike()

                        execute_autolike(uid, chat_id)

        except Exception as e:
            print("AUTOLIKE SCHEDULER ERROR:", repr(e))

        time.sleep(30)


# ==============================
# LIKE COMMAND
# ==============================

@bot.message_handler(commands=["like"])
def like_player(message):

    set_reply(message)

    if not access_allowed(message):
        return

    if not check_subscription(message.from_user.id):

        bot.send_message(
            message.chat.id,
            """<b>عذراً 🫣

يجب عليك الدخول أولاً إلى القناة الخاصة بنا !

رابط القناة :
https://t.me/hmzahjrjjvvhdh</b>""",
            reply_markup=sub_buttons()
        )

        return

    args = message.text.split()

    if len(args) != 2 or not args[1].isdigit():

        send_video_message(
            message.chat.id,
            VIDEO_LIKE_ERROR,
            """
<b>عذرا 🫣❌

الرجاء إدخال الاوامر بشكل صحيح :

<code>/like uid</code>

🌑example :

<code>/like 12345678</code>

🎗️Owner : @Hmza645🎗️</b>
"""
        )

        return

    uid = args[1]

    if not is_developer(message.from_user.id):

        attempts = get_user_attempts(message.from_user.id)

        if len(attempts) >= 3:

            send_video_message(
                message.chat.id,
                VIDEO_MAIN,
                """
<b>عذراً يا صديقي ❌

يمكنك المحاولة بعد 24 ساعة 🎀

السبب : لان تم نفاذ محاولاتك اليومية لزيادة اللايكات الي تبلغ عددها 3 محاولات 👀

🎗️Owner : @Hmza645🎗️</b>
"""
            )

            return

    loading = show_loading(message.chat.id)

    try:

        response = requests.get(
            LIKE_API,
            params={"uid": uid},
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

        if not is_developer(message.from_user.id):
            add_user_attempt(message.from_user.id)

        delete_loading(
            message.chat.id,
            loading.message_id
        )

        PlayerNickname = data.get("PlayerNickname", "Unknown")

        LikesGivenByAPI = int(data.get("LikesGivenByAPI", 0))

        LikesBefore = data.get("LikesBefore", 0)

        LikesAfter = data.get("LikesAfter", 0)

        if LikesGivenByAPI <= 0:

            send_video_message(
                message.chat.id,
                VIDEO_LIKE_ERROR,
                """
<b>عذرا يا صديقي 🫣❌

الحد لزيادة اللايكات هي كل 24 ساعة 🫠

الرجاء المحاولة بعد 24 ساعة 🔥

🎗️Owner : @Hmza645🎗️</b>
"""
            )

            return

        send_video_message(
            message.chat.id,
            VIDEO_LIKE_SUCCESS,
            f"""
<b>تم الارسال بنجاح 😶‍🌫️

✨ اسم الحساب :
{PlayerNickname}

✨ عدد اللايكات قبل الزيادة :
{LikesBefore}

✨ عدد اللايكات بعد الزيادة :
{LikesAfter}

✨ عدد اللايكات المضافة :
{LikesGivenByAPI}

🎗️Owner : @Hmza645🎗️</b>
"""
        )

    except Exception as e:

        print("LIKE ERROR:", repr(e))

        delete_loading(
            message.chat.id,
            loading.message_id
        )

        send_video_message(
            message.chat.id,
            VIDEO_ERROR,
            """
<b>عذراً يا صديقي 🫠❌

فشل الاتصــال بالــ Api
الرجاء المحاولة فيما بعد 😶‍🌫️

🎗️Owner : @Hmza645🎗️</b>
"""
        )


# ==============================
# START ALL SERVICES
# ==============================

if __name__ == "__main__":

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    threading.Thread(
        target=keep_alive,
        daemon=True
    ).start()

    threading.Thread(
        target=autolike_scheduler,
        daemon=True
    ).start()

    print("Like Bot Started...")
    print("Render Web Server Started...")
    print("Keep Alive Started...")

    bot.infinity_polling(
        timeout=60,
        long_polling_timeout=60,
        skip_pending=True
    )


# فكيو 🗿🗿🗿🗿

# فكيو وش تعمل تحت يزبي 😶😶

# تع مص 😂

# برا روح شغل لا تشوف هون 🗿

# لك ايري بطيزك يا قحبة

# مهدي يحبه

# ههه

# حمزة عمك
# قحبه هي 1100 سطر ها 🙈
