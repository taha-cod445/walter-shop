#!/usr/bin/env python3
# Walter Telegram Bot — standalone version with Telegram Bot API colored buttons
# Requirements: pip install pyTelegramBotAPI python-dotenv
# Keep your existing .env and walter.db. This script adds its own tables and does not delete existing data.

import os
import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

import telebot
from telebot import types
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
CHANNEL = os.getenv("CHANNEL_USERNAME", "@WalterTM").strip()
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/WalterTM").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip()
PAYMENT_TEXT = os.getenv(
    "PAYMENT_TEXT",
    "لطفاً برای روش پرداخت و هماهنگی، پس از ثبت سفارش با پشتیبانی تماس بگیر."
).strip()

if not BOT_TOKEN:
    raise SystemExit("خطا: BOT_TOKEN در فایل .env پیدا نشد.")
try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    raise SystemExit("خطا: ADMIN_ID در فایل .env باید شناسه عددی مدیر باشد.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("walter")
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True)

DB_PATH = BASE_DIR / "walter.db"
DATA_PATH = BASE_DIR / "walter_data.json"

DEFAULT_DATA = {
    "prices": {
        "stars_unit": 0,
        "premium_3": 0,
        "premium_6": 0,
        "premium_12": 0
    },
    "services": [
        {"id": "design", "name": "طراحی و ساخت محتوای تلگرام", "price": 0, "active": True},
        {"id": "setup", "name": "راه‌اندازی و تنظیم ربات", "price": 0, "active": True},
        {"id": "channel_setup", "name": "ساخت و تنظیم کانال", "price": 0, "active": True},
        {"id": "consult", "name": "مشاوره و پشتیبانی تلگرام", "price": 0, "active": True}
    ]
}
# Per-user temporary conversation state; persistent orders are stored in SQLite.
user_state = {}

def load_data():
    data = {}
    if DATA_PATH.exists():
        try:
            data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            logger.exception("Could not parse walter_data.json; using defaults in memory.")
            data = {}
    # Preserve unrelated existing keys.
    changed = False
    for key, value in DEFAULT_DATA.items():
        if key not in data or not isinstance(data[key], type(value)):
            data[key] = value.copy() if isinstance(value, (dict, list)) else value
            changed = True
    for k, v in DEFAULT_DATA["prices"].items():
        if k not in data["prices"]:
            data["prices"][k] = v
            changed = True
    if not isinstance(data.get("services"), list):
        data["services"] = DEFAULT_DATA["services"].copy()
        changed = True
    if changed or not DATA_PATH.exists():
        save_data(data)
    return data

def save_data(data=None):
    if data is None:
        data = app_data
    tmp = DATA_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA_PATH)

app_data = load_data()

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS walter_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            item_type TEXT NOT NULL,
            item_name TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            details TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ثبت شده',
            created_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS walter_support (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'باز'
        )""")
init_db()

def is_admin(user_id):
    return int(user_id) == ADMIN_ID

def joined(user_id):
    try:
        member = bot.get_chat_member(CHANNEL, user_id)
        return member.status in ("creator", "administrator", "member")
    except Exception as e:
        logger.warning("Membership check failed: %s", e)
        return False

def join_markup():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_URL, style="primary"))
    m.add(types.InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join", style="success"))
    return m

def gate_message(chat_id):
    bot.send_message(
        chat_id,
        "برای استفاده از ربات، ابتدا در کانال زیر عضو شو و بعد «بررسی عضویت» را بزن.",
        reply_markup=join_markup()
    )

def main_markup(user_id):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("⭐ خرید استارز", callback_data="buy_stars", style="primary"),
        types.InlineKeyboardButton("💎 تلگرام پریمیوم", callback_data="premium", style="primary")
    )
    m.add(
        types.InlineKeyboardButton("🧰 خدمات", callback_data="services", style="primary"),
        types.InlineKeyboardButton("📦 سفارش‌های من", callback_data="my_orders", style="success")
    )
    m.add(
        types.InlineKeyboardButton("💱 نرخ‌ها", callback_data="rates", style="primary"),
        types.InlineKeyboardButton("🆘 پشتیبانی", callback_data="support", style="success")
    )
    if is_admin(user_id):
        m.add(types.InlineKeyboardButton("🔐 ورود به پنل مدیریت", callback_data="admin", style="primary"))
    return m

def admin_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("💰 قیمت استارز", callback_data="adm_price_stars", style="primary"),
        types.InlineKeyboardButton("💎 قیمت پریمیوم", callback_data="adm_price_premium", style="primary")
    )
    m.add(
        types.InlineKeyboardButton("🧰 مدیریت خدمات", callback_data="adm_services", style="primary"),
        types.InlineKeyboardButton("📋 سفارش‌ها", callback_data="adm_orders", style="success")
    )
    m.add(
        types.InlineKeyboardButton("📨 پیام‌های پشتیبانی", callback_data="adm_support", style="success"),
        types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="home", style="danger")
    )
    return m

def send_or_edit(call, text, markup=None):
    try:
        bot.edit_message_text(
            text, call.message.chat.id, call.message.message_id,
            reply_markup=markup, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

def money(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)

def user_label(user):
    return f"@{user.username}" if user.username else str(user.id)

def create_order(user, item_type, item_name, price, details=""):
    with db() as con:
        cur = con.execute(
            """INSERT INTO walter_orders
            (user_id, username, item_type, item_name, price, details, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'ثبت شده', ?)""",
            (user.id, user.username or "", item_type, item_name, int(price), details,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        return cur.lastrowid

def notify_admin(text):
    try:
        bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception:
        logger.exception("Could not notify admin")

def home_message(chat_id, user_id, edit_call=None):
    text = "سلام 👋 به ربات Walter خوش اومدی.\nاز منوی زیر یکی از گزینه‌ها رو انتخاب کن."
    if edit_call:
        send_or_edit(edit_call, text, main_markup(user_id))
    else:
        bot.send_message(chat_id, text, reply_markup=main_markup(user_id))

@bot.message_handler(commands=["start", "menu"])
def start(message):
    user_state.pop(message.from_user.id, None)
    if not joined(message.from_user.id):
        gate_message(message.chat.id)
        return
    home_message(message.chat.id, message.from_user.id)

@bot.message_handler(commands=["admin"])
def admin_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ دسترسی ندارید.")
        return
    bot.send_message(message.chat.id, "🔐 پنل مدیریت Walter", reply_markup=admin_markup())

@bot.callback_query_handler(func=lambda c: True)
def callbacks(call):
    uid = call.from_user.id
    data = call.data or ""

    if data == "check_join":
        if joined(uid):
            bot.answer_callback_query(call.id, "عضویت تأیید شد ✅")
            home_message(call.message.chat.id, uid, call)
        else:
            bot.answer_callback_query(call.id, "هنوز عضویت تأیید نشده است.", show_alert=True)
        return

    if not joined(uid):
        bot.answer_callback_query(call.id)
        gate_message(call.message.chat.id)
        return

    if data == "home":
        bot.answer_callback_query(call.id)
        user_state.pop(uid, None)
        home_message(call.message.chat.id, uid, call)
        return

    if data == "admin":
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_or_edit(call, "🔐 <b>پنل مدیریت Walter</b>\nیکی از گزینه‌ها را انتخاب کن.", admin_markup())
        return

    if data.startswith("adm_") and not is_admin(uid):
        bot.answer_callback_query(call.id, "دسترسی ندارید.", show_alert=True)
        return

    if data == "buy_stars":
        price = int(app_data["prices"].get("stars_unit", 0) or 0)
        m = types.InlineKeyboardMarkup()
        for amount in (50, 100, 250, 500, 1000):
            total = amount * price
            m.add(types.InlineKeyboardButton(
                f"{amount} استارز — {money(total)} تومان",
                callback_data=f"stars_amount:{amount}", style="success"
            ))
        m.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="home", style="danger"))
        send_or_edit(call, f"⭐ خرید استارز\nقیمت هر استارز: {money(price)} تومان\nتعداد موردنظر را انتخاب کن:", m)
        return

    if data.startswith("stars_amount:"):
        amount = int(data.split(":", 1)[1])
        unit = int(app_data["prices"].get("stars_unit", 0) or 0)
        total = amount * unit
        order_id = create_order(call.from_user, "استارز", f"{amount} استارز", total)
        notify_admin(
            f"🆕 سفارش جدید #{order_id}\n"
            f"کاربر: {user_label(call.from_user)} (<code>{uid}</code>)\n"
            f"محصول: {amount} استارز\nقیمت: {money(total)} تومان"
        )
        m = types.InlineKeyboardMarkup()
        if SUPPORT_USERNAME:
            m.add(types.InlineKeyboardButton("🆘 هماهنگی پرداخت", url="https://t.me/" + SUPPORT_USERNAME.lstrip("@")))
        m.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="home", style="danger"))
        send_or_edit(call, f"✅ سفارش #{order_id} ثبت شد.\nمحصول: {amount} استارز\nمبلغ ثبت‌شده: {money(total)} تومان\n\n{PAYMENT_TEXT}", m)
        return

    if data == "premium":
        prices = app_data["prices"]
        m = types.InlineKeyboardMarkup()
        for months in (3, 6, 12):
            price = int(prices.get(f"premium_{months}", 0) or 0)
            m.add(types.InlineKeyboardButton(
                f"💎 پریمیوم {months} ماهه — {money(price)} تومان",
                callback_data=f"premium_months:{months}", style="primary"
            ))
        m.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="home", style="danger"))
        send_or_edit(call, "مدت اشتراک پریمیوم را انتخاب کن:", m)
        return

    if data.startswith("premium_months:"):
        months = int(data.split(":", 1)[1])
        price = int(app_data["prices"].get(f"premium_{months}", 0) or 0)
        user_state[uid] = {"mode": "premium_username", "months": months, "price": price}
        send_or_edit(call, f"💎 پریمیوم {months} ماهه\nقیمت: {money(price)} تومان\n\nحالا آیدی تلگرام گیرنده را بفرست (مثلاً <code>@username</code>).")
        return

    if data == "services":
        m = types.InlineKeyboardMarkup()
        active = [x for x in app_data["services"] if x.get("active", True)]
        for service in active:
            m.add(types.InlineKeyboardButton(
                f"{service['name']} — {money(service.get('price', 0))} تومان",
                callback_data=f"service:{service['id']}", style="primary"
            ))
        m.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="home", style="danger"))
        send_or_edit(call, "🧰 خدمات موجود:", m)
        return

    if data.startswith("service:"):
        service_id = data.split(":", 1)[1]
        service = next((x for x in app_data["services"] if x.get("id") == service_id and x.get("active", True)), None)
        if not service:
            bot.answer_callback_query(call.id, "این خدمت فعلاً موجود نیست.", show_alert=True)
            return
        user_state[uid] = {"mode": "service_details", "service": service}
        send_or_edit(call, f"خدمت: <b>{service['name']}</b>\nقیمت: {money(service.get('price', 0))} تومان\n\nجزئیات موردنیازت رو در یک پیام بفرست تا سفارش ثبت بشه.")
        return

    if data == "rates":
        p = app_data["prices"]
        text = (
            "💱 <b>نرخ‌های فعلی</b>\n"
            f"هر استارز: {money(p.get('stars_unit', 0))} تومان\n"
            f"پریمیوم ۳ ماهه: {money(p.get('premium_3', 0))} تومان\n"
            f"پریمیوم ۶ ماهه: {money(p.get('premium_6', 0))} تومان\n"
            f"پریمیوم ۱۲ ماهه: {money(p.get('premium_12', 0))} تومان"
        )
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="home", style="danger"))
        send_or_edit(call, text, m)
        return

    if data == "my_orders":
        with db() as con:
            rows = con.execute(
                "SELECT id,item_name,price,status,created_at FROM walter_orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
                (uid,)
            ).fetchall()
        if not rows:
            text = "هنوز سفارشی ثبت نکردی."
        else:
            text = "📦 <b>آخرین سفارش‌های تو</b>\n\n" + "\n".join(
                f"#{r['id']} — {r['item_name']} — {money(r['price'])} تومان\nوضعیت: {r['status']} | {r['created_at']}"
                for r in rows
            )
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="home", style="danger"))
        send_or_edit(call, text, m)
        return

    if data == "support":
        user_state[uid] = {"mode": "support"}
        send_or_edit(call, "پیام یا سؤال خودت رو در یک پیام بفرست؛ برای پشتیبانی ارسال می‌شه.")
        return

    if data == "adm_price_stars":
        user_state[uid] = {"mode": "set_price", "key": "stars_unit"}
        send_or_edit(call, "قیمت هر استارز را به تومان و فقط به‌صورت عدد بفرست (مثلاً 1200).")
        return

    if data == "adm_price_premium":
        m = types.InlineKeyboardMarkup()
        for months in (3, 6, 12):
            m.add(types.InlineKeyboardButton(f"پریمیوم {months} ماهه", callback_data=f"adm_premium_price:{months}", style="primary"))
        m.add(types.InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin", style="danger"))
        send_or_edit(call, "مدت پریمیوم را برای تغییر قیمت انتخاب کن:", m)
        return

    if data.startswith("adm_premium_price:"):
        months = int(data.split(":", 1)[1])
        user_state[uid] = {"mode": "set_price", "key": f"premium_{months}"}
        send_or_edit(call, f"قیمت پریمیوم {months} ماهه را به تومان و فقط به‌صورت عدد بفرست.")
        return

    if data == "adm_services":
        m = types.InlineKeyboardMarkup()
        for service in app_data["services"]:
            status = "فعال" if service.get("active", True) else "غیرفعال"
            m.add(types.InlineKeyboardButton(
                f"{service['name']} ({status})",
                callback_data=f"adm_service:{service.get('id')}", style="primary"
            ))
        m.add(types.InlineKeyboardButton("➕ افزودن خدمت", callback_data="adm_add_service", style="success"))
        m.add(types.InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin", style="danger"))
        send_or_edit(call, "🧰 مدیریت خدمات:", m)
        return

    if data == "adm_add_service":
        user_state[uid] = {"mode": "add_service_name"}
        send_or_edit(call, "نام خدمت جدید را بفرست. فقط خدمات قانونی و شفاف اضافه کن.")
        return

    if data.startswith("adm_service:"):
        service_id = data.split(":", 1)[1]
        service = next((x for x in app_data["services"] if x.get("id") == service_id), None)
        if not service:
            bot.answer_callback_query(call.id, "خدمت پیدا نشد.", show_alert=True)
            return
        m = types.InlineKeyboardMarkup(row_width=2)
        m.add(
            types.InlineKeyboardButton("💰 تغییر قیمت", callback_data=f"adm_service_price:{service_id}"),
            types.InlineKeyboardButton("فعال/غیرفعال", callback_data=f"adm_service_toggle:{service_id}")
        )
        m.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="adm_services"))
        send_or_edit(call, f"<b>{service['name']}</b>\nقیمت: {money(service.get('price', 0))} تومان\nوضعیت: {'فعال' if service.get('active', True) else 'غیرفعال'}", m)
        return

    if data.startswith("adm_service_price:"):
        service_id = data.split(":", 1)[1]
        user_state[uid] = {"mode": "set_service_price", "service_id": service_id}
        send_or_edit(call, "قیمت جدید را به تومان و فقط به‌صورت عدد بفرست.")
        return

    if data.startswith("adm_service_toggle:"):
        service_id = data.split(":", 1)[1]
        service = next((x for x in app_data["services"] if x.get("id") == service_id), None)
        if service:
            service["active"] = not service.get("active", True)
            save_data()
            bot.answer_callback_query(call.id, "وضعیت خدمت ذخیره شد.")
            m = types.InlineKeyboardMarkup()
            m.add(types.InlineKeyboardButton("⬅️ مدیریت خدمات", callback_data="adm_services", style="danger"))
            send_or_edit(call, f"{service['name']}: {'فعال' if service['active'] else 'غیرفعال'}", m)
        return

    if data == "adm_orders":
        with db() as con:
            rows = con.execute(
                "SELECT id,user_id,username,item_name,price,status,created_at FROM walter_orders ORDER BY id DESC LIMIT 15"
            ).fetchall()
        if not rows:
            text = "هنوز سفارشی ثبت نشده."
            m = types.InlineKeyboardMarkup()
        else:
            lines = []
            m = types.InlineKeyboardMarkup()
            for r in rows:
                lines.append(f"#{r['id']} | {r['item_name']} | {money(r['price'])} تومان | {r['status']} | user <code>{r['user_id']}</code>")
                m.add(types.InlineKeyboardButton(f"#{r['id']} — تغییر وضعیت", callback_data=f"adm_order:{r['id']}", style="success"))
            text = "📋 <b>آخرین سفارش‌ها</b>\n" + "\n".join(lines)
        m.add(types.InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin", style="danger"))
        send_or_edit(call, text, m)
        return

    if data.startswith("adm_order:"):
        order_id = int(data.split(":", 1)[1])
        m = types.InlineKeyboardMarkup(row_width=2)
        for status in ("در انتظار پرداخت", "در حال انجام", "تکمیل شد", "لغو شد"):
            m.add(types.InlineKeyboardButton(status, callback_data=f"adm_order_status:{order_id}:{status}", style=("success" if status == "تکمیل شد" else "danger" if status == "لغو شد" else "primary")))
        m.add(types.InlineKeyboardButton("⬅️ سفارش‌ها", callback_data="adm_orders"))
        send_or_edit(call, f"برای سفارش #{order_id} وضعیت جدید را انتخاب کن:", m)
        return

    if data.startswith("adm_order_status:"):
        _, _, order_id, status = data.split(":", 3)
        order_id = int(order_id)
        with db() as con:
            row = con.execute("SELECT user_id FROM walter_orders WHERE id=?", (order_id,)).fetchone()
            con.execute("UPDATE walter_orders SET status=? WHERE id=?", (status, order_id))
        if row:
            try:
                bot.send_message(row["user_id"], f"وضعیت سفارش #{order_id} تغییر کرد: <b>{status}</b>")
            except Exception:
                pass
        bot.answer_callback_query(call.id, "وضعیت ذخیره شد.")
        send_or_edit(call, f"وضعیت سفارش #{order_id} شد: {status}", admin_markup())
        return

    if data == "adm_support":
        with db() as con:
            rows = con.execute("SELECT id,user_id,username,message,created_at FROM walter_support ORDER BY id DESC LIMIT 10").fetchall()
        if not rows:
            text = "پیام پشتیبانی جدیدی وجود ندارد."
        else:
            text = "📨 <b>پیام‌های اخیر پشتیبانی</b>\n\n" + "\n\n".join(
                f"#{r['id']} از <code>{r['user_id']}</code> (@{r['username'] or 'بدون‌نام'})\n{r['message'][:700]}\n{r['created_at']}"
                for r in rows
            )
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin", style="danger"))
        send_or_edit(call, text, m)
        return

    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=["text"])
def text_messages(message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    if text.startswith("/"):
        return
    if not joined(uid):
        gate_message(message.chat.id)
        return

    state = user_state.get(uid)
    if not state:
        home_message(message.chat.id, uid)
        return

    mode = state.get("mode")

    if mode == "premium_username":
        username = text.lstrip("@")
        if not username or " " in username or len(username) > 64:
            bot.reply_to(message, "آیدی معتبر بفرست، مثل <code>@username</code>.")
            return
        months = int(state["months"])
        price = int(state["price"])
        order_id = create_order(message.from_user, "پریمیوم", f"پریمیوم {months} ماهه برای @{username}", price, f"recipient=@{username}")
        user_state.pop(uid, None)
        notify_admin(
            f"🆕 سفارش جدید #{order_id}\nکاربر: {user_label(message.from_user)} (<code>{uid}</code>)\n"
            f"محصول: پریمیوم {months} ماهه\nگیرنده: @{username}\nمبلغ: {money(price)} تومان"
        )
        m = types.InlineKeyboardMarkup()
        if SUPPORT_USERNAME:
            m.add(types.InlineKeyboardButton("🆘 هماهنگی پرداخت", url="https://t.me/" + SUPPORT_USERNAME.lstrip("@")))
        m.add(types.InlineKeyboardButton("🏠 منوی اصلی", callback_data="home", style="danger"))
        bot.send_message(message.chat.id, f"✅ سفارش #{order_id} ثبت شد.\n{PAYMENT_TEXT}", reply_markup=m)
        return

    if mode == "service_details":
        service = state["service"]
        order_id = create_order(message.from_user, "خدمت", service["name"], int(service.get("price", 0)), text[:1500])
        user_state.pop(uid, None)
        notify_admin(
            f"🆕 سفارش خدمت #{order_id}\nکاربر: {user_label(message.from_user)} (<code>{uid}</code>)\n"
            f"خدمت: {service['name']}\nقیمت: {money(service.get('price', 0))} تومان\n"
            f"جزئیات: {text[:1200]}"
        )
        bot.send_message(message.chat.id, f"✅ سفارش #{order_id} ثبت شد.\n{PAYMENT_TEXT}", reply_markup=main_markup(uid))
        return

    if mode == "support":
        with db() as con:
            cur = con.execute(
                "INSERT INTO walter_support (user_id,username,message,created_at) VALUES (?,?,?,?)",
                (uid, message.from_user.username or "", text[:3000], datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            ticket_id = cur.lastrowid
        user_state.pop(uid, None)
        notify_admin(f"📨 پیام پشتیبانی #{ticket_id}\nاز: {user_label(message.from_user)} (<code>{uid}</code>)\n\n{text[:2500]}")
        bot.reply_to(message, f"پیامت ثبت شد. شماره پیگیری: #{ticket_id}")
        return

    if mode == "set_price":
        if not is_admin(uid):
            user_state.pop(uid, None)
            bot.reply_to(message, "دسترسی ندارید.")
            return
        try:
            value = int(text.replace(",", "").replace("٬", ""))
            if value < 0:
                raise ValueError
        except ValueError:
            bot.reply_to(message, "فقط یک عدد صفر یا بزرگ‌تر بفرست.")
            return
        key = state["key"]
        app_data["prices"][key] = value
        save_data()
        user_state.pop(uid, None)
        bot.reply_to(message, f"✅ قیمت ذخیره شد: {money(value)} تومان", reply_markup=admin_markup())
        return

    if mode == "set_service_price":
        if not is_admin(uid):
            user_state.pop(uid, None)
            bot.reply_to(message, "دسترسی ندارید.")
            return
        try:
            value = int(text.replace(",", "").replace("٬", ""))
            if value < 0:
                raise ValueError
        except ValueError:
            bot.reply_to(message, "فقط یک عدد صفر یا بزرگ‌تر بفرست.")
            return
        service = next((x for x in app_data["services"] if x.get("id") == state["service_id"]), None)
        if not service:
            user_state.pop(uid, None)
            bot.reply_to(message, "خدمت پیدا نشد.")
            return
        service["price"] = value
        save_data()
        user_state.pop(uid, None)
        bot.reply_to(message, f"✅ قیمت «{service['name']}» ذخیره شد: {money(value)} تومان", reply_markup=admin_markup())
        return

    if mode == "add_service_name":
        if not is_admin(uid):
            user_state.pop(uid, None)
            bot.reply_to(message, "دسترسی ندارید.")
            return
        if len(text) < 2 or len(text) > 80:
            bot.reply_to(message, "نام خدمت باید بین ۲ تا ۸۰ نویسه باشد.")
            return
        user_state[uid] = {"mode": "add_service_price", "name": text}
        bot.reply_to(message, "قیمت خدمت را به تومان و فقط به‌صورت عدد بفرست.")
        return

    if mode == "add_service_price":
        if not is_admin(uid):
            user_state.pop(uid, None)
            bot.reply_to(message, "دسترسی ندارید.")
            return
        try:
            price = int(text.replace(",", "").replace("٬", ""))
            if price < 0:
                raise ValueError
        except ValueError:
            bot.reply_to(message, "فقط یک عدد صفر یا بزرگ‌تر بفرست.")
            return
        name = state["name"]
        service_id = "svc_" + str(int(datetime.now().timestamp()))
        app_data["services"].append({"id": service_id, "name": name, "price": price, "active": True})
        save_data()
        user_state.pop(uid, None)
        bot.reply_to(message, f"✅ خدمت «{name}» اضافه شد.", reply_markup=admin_markup())
        return

@bot.message_handler(content_types=["photo"])
def photos(message):
    uid = message.from_user.id
    if not joined(uid):
        gate_message(message.chat.id)
        return
    # Receipts are forwarded for manual review; this does not automatically confirm payment.
    caption = f"🧾 تصویر ارسالی از {user_label(message.from_user)} (ID <code>{uid}</code>)"
    try:
        bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, parse_mode="HTML")
        bot.reply_to(message, "تصویر به مدیر ارسال شد تا دستی بررسی شود.")
    except Exception:
        logger.exception("Could not forward photo")
        bot.reply_to(message, "ارسال تصویر ناموفق بود؛ کمی بعد دوباره امتحان کن.")

def main():
    logger.info("Walter bot starting. Mandatory channel: %s", CHANNEL)
    try:
        bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
    except KeyboardInterrupt:
        logger.info("Stopped by keyboard interrupt.")

if __name__ == "__main__":
    main()
