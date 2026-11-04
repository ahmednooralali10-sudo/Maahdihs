# By : xct TEAM
# By : @Hmza645

import requests
import telebot
import json
import os
import threading
import time
from datetime import datetime, timedelta

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# =================== التوكن من متغيرات راندر ===================
TOKEN = os.environ.get("BOT_TOKEN")

if not TOKEN:
    print("❌ ERROR: BOT_TOKEN غير موجود في متغيرات البيئة (Environment Variables)")
    exit(1)

CHANNEL_ID = os.environ.get("CHANNEL_ID", "@hmzahjrjjvvhdh")
OWNER_IDS = [8987133011, 6464857808, 8930921922]

LIKE_API = "https://liketi-iota.vercel.app/like"

VIDEO_MAIN = "vd.mp4"
VIDEO_ERROR = "vod.mp4"
VIDEO_LIKE_ERROR = "vhd.mp4"
VIDEO_LIKE_SUCCESS = "vp.mp4"

GROUPS_FILE = "active_groups.json"
AUTO_FILE = "auto_likes.json"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

def load_groups():
    try:
        with open(GROUPS_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

ACTIVE_GROUPS = load_groups()

def save_groups():
    with open(GROUPS_FILE, "w") as f:
        json.dump(list(ACTIVE_GROUPS), f)

def load_auto():
    try:
        with open(AUTO_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_auto(data):
    with open(AUTO_FILE, "w") as f:
        json.dump(data, f, indent=2)

def hide_uid(uid):
    uid = str(uid)
    if len(uid) <= 4:
        return uid[0] + "****"
    return uid[:3] + "****" + uid[-2:]

def is_developer(user_id):
    return user_id in OWNER_IDS

def is_private(message):
    return message.chat.type == "private"

def access_allowed(message):
    user_id = message.from_user.id
    if is_private(message):
        return is_developer(user_id)
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

def send_video_message(chat_id, video_file, text):
    with open(video_file, "rb") as video:
        bot.send_video(
            chat_id,
            video,
            caption=text,
            parse_mode="HTML"
        )

def show_loading(chat_id):
    return bot.send_message(chat_id, "🔹💠🔷")

def delete_loading(chat_id, msg_id):
    try:
        bot.delete_message(chat_id, msg_id)
    except:
        pass

def owner_help():
    return """
<b>✳️ Welcome the Owner to like Bot ✳️

✨ الاوامر :

<code>/like uid</code>
- لإرسال اللايكات إلى اللاعب !

<code>/auto uid days</code>
- اوتو لايك كل 24 ساعة ⏰

<code>/autolist</code>
- عرض الاوتو

<code>/autostop uid</code>
- ايقاف الاوتو

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

# =================== AUTO SYSTEM ===================

def send_auto_channel_report(uid, player_name, likes_today, likes_now, days_left, days_total):
    try:
        hidden = hide_uid(uid)
        text = f"""
<b>⏰ Auto Like Report ⏰

❤️ الايكات المرسلة اليوم : {likes_today}

👤 الاسم : {player_name}
🆔 الايدي : {hidden}

📅 عدد الايام المتبقية : {days_left} / {days_total}
💙 عدد الايكات حاليا : {likes_now}

🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}

🎗️ By xct TEAM</b>
"""
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("المطور", url="https://t.me/Hmza645"),
            InlineKeyboardButton("البوت", url="https://t.me/Hhmzjb356bot")
        )
        
        if os.path.exists(VIDEO_LIKE_SUCCESS):
            with open(VIDEO_LIKE_SUCCESS, "rb") as v:
                bot.send_video(CHANNEL_ID, v, caption=text, parse_mode="HTML", reply_markup=markup)
        else:
            bot.send_message(CHANNEL_ID, text, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        print("AUTO CHANNEL ERROR:", e)

def do_like_request(uid):
    try:
        url = LIKE_API + "?uid=" + str(uid)
        res = requests.get(url, timeout=60)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print("LIKE API ERROR:", e)
        return None

def auto_worker():
    print("Auto Worker Started...")
    while True:
        try:
            auto_data = load_auto()
            changed = False
            for uid in list(auto_data.keys()):
                info = auto_data[uid]
                if info.get("days_left", 0) <= 0:
                    continue
                
                last_run_str = info.get("last_run")
                last_run = datetime.fromisoformat(last_run_str) if last_run_str else datetime.now() - timedelta(days=2)
                
                if datetime.now() - last_run >= timedelta(hours=24):
                    data = do_like_request(uid)
                    if data:
                        likes_given = int(float(data.get("LikesGivenByAPI", data.get("LikesGiven", data.get("LikesAdded", 0)))))
                        likes_after = data.get("LikesafterCommand", data.get("LikesAfter", 0))
                        player = data.get("PlayerNickname", "Unknown")
                        
                        if likes_given > 0:
                            auto_data[uid]["days_left"] -= 1
                        auto_data[uid]["last_run"] = datetime.now().isoformat()
                        
                        send_auto_channel_report(
                            uid, player, likes_given, likes_after,
                            auto_data[uid]["days_left"], auto_data[uid]["days_total"]
                        )
                        changed = True
                    else:
                        auto_data[uid]["last_run"] = (datetime.now() - timedelta(hours=23)).isoformat()
                        changed = True
            
            if changed:
                save_auto(auto_data)
        except Exception as e:
            print("AUTO LOOP ERROR:", e)
        time.sleep(3600)

threading.Thread(target=auto_worker, daemon=True).start()

@bot.message_handler(commands=["auto"])
def auto_command(message):
    if not is_developer(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3 or not args[1].isdigit() or not args[2].isdigit():
        bot.send_message(message.chat.id, "<b>❌ الاستخدام: <code>/auto uid days</code>\nمثال: <code>/auto 12345678 30</code></b>")
        return
    
    uid = args[1]
    days = int(args[2])
    
    auto_data = load_auto()
    auto_data[uid] = {
        "days_total": days,
        "days_left": days,
        "start_date": datetime.now().isoformat(),
        "last_run": (datetime.now() - timedelta(days=1, minutes=2)).isoformat(),
    }
    save_auto(auto_data)
    
    bot.send_message(message.chat.id, f"<b>✅ تم تفعيل الأوتو ⏰\n\n🆔 الايدي : {hide_uid(uid)}\n📅 المدة : {days} يوم\nسيتم الإرسال كل 24 ساعة في {CHANNEL_ID}</b>")
    
    # ارسال أول واحد فورا
    data = do_like_request(uid)
    if data:
        likes_given = int(float(data.get("LikesGivenByAPI", 0)))
        likes_after = data.get("LikesafterCommand", 0)
        player = data.get("PlayerNickname", "Unknown")
        send_auto_channel_report(uid, player, likes_given, likes_after, days-1, days)
        auto_data[uid]["last_run"] = datetime.now().isoformat()
        auto_data[uid]["days_left"] = days - 1
        save_auto(auto_data)

@bot.message_handler(commands=["autolist"])
def autolist_command(message):
    if not is_developer(message.from_user.id):
        return
    auto_data = load_auto()
    if not auto_data:
        bot.send_message(message.chat.id, "<b>لا يوجد اوتو حاليا</b>")
        return
    txt = "<b>📋 Auto List:\n\n</b>"
    for uid, info in auto_data.items():
        txt += f"• {hide_uid(uid)} | متبقي {info['days_left']}/{info['days_total']} يوم\n"
    bot.send_message(message.chat.id, txt)

@bot.message_handler(commands=["autostop"])
def autostop_command(message):
    if not is_developer(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 2:
        bot.send_message(message.chat.id, "<b>استخدم: <code>/autostop uid</code></b>")
        return
    uid = args[1]
    auto_data = load_auto()
    if uid in auto_data:
        del auto_data[uid]
        save_auto(auto_data)
        bot.send_message(message.chat.id, f"<b>✅ تم ايقاف {hide_uid(uid)}</b>")
    else:
        bot.send_message(message.chat.id, "<b>❌ غير موجود</b>")

# =================== اوامر المجموعات الاصلية ===================

@bot.message_handler(commands=["on"])
def turn_on(message):
    if is_private(message):
        if is_developer(message.from_user.id):
            bot.send_message(message.chat.id, "هذا الأمر يعمل داخل المجموعات فقط.")
        return
    if not is_developer(message.from_user.id):
        return
    if message.chat.id in ACTIVE_GROUPS:
        send_video_message(message.chat.id, VIDEO_ERROR, "<b>البوت مفعل بالمجموعة بالفعل 🗿</b>")
        return
    ACTIVE_GROUPS.add(message.chat.id)
    save_groups()
    send_video_message(message.chat.id, VIDEO_LIKE_SUCCESS, "<b>تم تشغيل البوت في هذه المجموعة بنجاح ✅</b>")

@bot.message_handler(commands=["off"])
def turn_off(message):
    if is_private(message):
        if is_developer(message.from_user.id):
            bot.send_message(message.chat.id, "هذا الأمر يعمل داخل المجموعات فقط.")
        return
    if not is_developer(message.from_user.id):
        return
    if message.chat.id not in ACTIVE_GROUPS:
        bot.send_message(message.chat.id, "<b>البوت ملغي في هذه المجموعة بالفعل 😶\n\n🎗️Owner : @Hmza645🎗️</b>")
        return
    ACTIVE_GROUPS.discard(message.chat.id)
    save_groups()
    bot.send_message(message.chat.id, "<b>تم إطفاء البوت في هذه المجموعة بنجاح 🙈\n\n🎗️Owner : @Hmza645🎗️</b>")

@bot.message_handler(commands=["sid"])
def sid_command(message):
    if is_private(message):
        if is_developer(message.from_user.id):
            bot.send_message(message.chat.id, "هذا الأمر يعمل داخل المجموعات فقط.")
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

@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def check_sub(c):
    if not is_developer(c.from_user.id):
        if c.message.chat.type == "private":
            return
        if c.message.chat.id not in ACTIVE_GROUPS:
            return
    if not check_subscription(c.from_user.id):
        bot.answer_callback_query(c.id, "❌ لم يتم العثور على اشتراكك", show_alert=True)
        return
    bot.answer_callback_query(c.id, "✅ تم التحقق من الاشتراك")
    text = owner_help() if is_developer(c.from_user.id) else user_help()
    send_video_message(c.message.chat.id, VIDEO_MAIN, text)

@bot.message_handler(commands=["start", "help", "hi"])
def start(message):
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
    send_video_message(message.chat.id, VIDEO_MAIN, text)
    delete_loading(message.chat.id, loading.message_id)

@bot.message_handler(commands=["like"])
def like_player(message):
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
    loading = show_loading(message.chat.id)
    try:
        url = LIKE_API + "?uid=" + str(uid)
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()
        delete_loading(message.chat.id, loading.message_id)
        PlayerNickname = data.get("PlayerNickname", "Unknown")
        LikesGivenByAPI = int(float(data.get("LikesGivenByAPI", data.get("LikesGiven", 0))))
        LikesBefore = data.get("LikesbeforeCommand", data.get("LikesBefore", 0))
        LikesAfter = data.get("LikesafterCommand", data.get("LikesAfter", 0))
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
        delete_loading(message.chat.id, loading.message_id)
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

print("Like Bot Started...")
bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
