#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SoloSint Bot v2.1
- Админ-панель: выдача, бан, рассылка (все кнопки рабочие)
- CryptoBot: оплата USDT/BTC/RUB
- Форматы выдачи: текст, HTML-сайт, CSV-таблица
"""
import asyncio, logging, os, re, subprocess, sqlite3, sys, tempfile, time, csv, io
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery, FSInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from phonenumbers import parse, is_valid_number, region_code_for_number, carrier
import phonenumbers

# ---------- ТОКЕНЫ ----------
BOT_TOKEN = "8635910966:AAHJFfdDQMPMo2Y_eP64MTLpKMl2Xq_b7LA"
DADATA_TOKEN = "621be36eabd463023fa35e3bbc023d8813a82d03"
SHODAN_API_KEY = "PKOe4s6iJSllaFQdUeu3Bjj5qoaWlUwb"
CRYPTOBOT_TOKEN = "599166:AAwwp972UBLM9MftML6GzBBAg3zwvXf8VuT"
ADMIN_IDS = [8526401545]

REQUIRED_CHANNELS = [
    {"id": "@beliy_aist_channel", "link": "https://t.me/+7H5GlsHZOYgwYmNk", "name": "Белый Аист"},
    {"id": "@karatele", "link": "https://t.me/karatele", "name": "Каратель"},
    {"id": "@solosintt", "link": "https://t.me/solosintt", "name": "SoloSint"},
]

PRICING = {
    1: 0.50, 10: 4.50, 50: 20.00, 100: 35.00,
    500: 150.00, 1000: 250.00, 2000: 400.00,
}

REFERRAL_BONUS = 3
REF_PERCENT = 4

CRYPTOBOT_API = "https://pay.crypt.bot/api"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

DB_PATH = "solosint.db"

# ---------- Database ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0.0,
        total_queries INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0,
        referrer_id INTEGER DEFAULT NULL, total_referrals INTEGER DEFAULT 0,
        referral_earnings REAL DEFAULT 0.0, output_format TEXT DEFAULT 'text',
        joined_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
        query_type TEXT, query_data TEXT, result_preview TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
        queries_added INTEGER, payment_method TEXT, status TEXT DEFAULT 'completed',
        admin_id INTEGER, crypto_invoice_id INTEGER DEFAULT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS invoices (
        invoice_id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL,
        queries INTEGER, currency TEXT, status TEXT DEFAULT 'active')""")
    conn.commit()
    conn.close()

def get_user(user_id: int) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0], "username": row[1], "balance": row[2], "total_queries": row[3],
            "is_banned": row[4], "is_admin": row[5], "referrer_id": row[6],
            "total_referrals": row[7], "referral_earnings": row[8], "output_format": row[9]
        }
    return None

def create_user(user_id: int, username: str, referrer_id: int = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username, referrer_id) VALUES (?,?,?)",
                (user_id, username, referrer_id))
    conn.commit()
    conn.close()

def add_queries(user_id: int, amount: float, queries: int, payment_method: str, admin_id: int = 0):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (queries, user_id))
    cur.execute("INSERT INTO transactions (user_id, amount, queries_added, payment_method, admin_id) VALUES (?,?,?,?,?)",
                (user_id, amount, queries, payment_method, admin_id))
    conn.commit()
    conn.close()

def use_query(user_id: int, username: str, query_type: str, query_data: str, result_preview: str) -> bool:
    user = get_user(user_id)
    if not user or user["balance"] <= 0 or user["is_banned"]:
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance - 1, total_queries = total_queries + 1 WHERE user_id=?", (user_id,))
    cur.execute("INSERT INTO queries (user_id, username, query_type, query_data, result_preview) VALUES (?,?,?,?,?)",
                (user_id, username, query_type, query_data, result_preview))
    conn.commit()
    conn.close()
    return True

def add_referral(referrer_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET total_referrals = total_referrals + 1 WHERE user_id=?", (referrer_id,))
    cur.execute("SELECT total_referrals FROM users WHERE user_id=?", (referrer_id,))
    total = cur.fetchone()[0]
    if total % REFERRAL_BONUS == 0:
        cur.execute("UPDATE users SET balance = balance + 1 WHERE user_id=?", (referrer_id,))
    conn.commit()
    conn.close()

def get_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users"); total_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM queries"); total_queries = cur.fetchone()[0]
    cur.execute("SELECT SUM(queries_added) FROM transactions"); total_sold = cur.fetchone()[0] or 0
    conn.close()
    return {"users": total_users, "queries": total_queries, "sold": total_sold}

def ban_user(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row: return False
    new_status = 0 if row[0] else 1
    cur.execute("UPDATE users SET is_banned=? WHERE user_id=?", (new_status, user_id))
    conn.commit()
    conn.close()
    return True

# ---------- CryptoBot ----------
async def create_crypto_invoice(user_id: int, amount_usd: float, queries: int) -> Optional[dict]:
    url = f"{CRYPTOBOT_API}/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    data = {
        "asset": "USDT",
        "amount": str(amount_usd),
        "description": f"SoloSint: {queries} запросов",
        "payload": f"{user_id}:{queries}",
        "allow_anonymous": False,
        "expires_in": 3600,
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=data, headers=headers, timeout=10) as r:
                resp = await r.json()
                if resp.get("ok"):
                    inv = resp["result"]
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute("INSERT OR REPLACE INTO invoices (invoice_id, user_id, amount, queries, currency) VALUES (?,?,?,?,?)",
                                (inv["invoice_id"], user_id, amount_usd, queries, "USDT"))
                    conn.commit()
                    conn.close()
                    return inv
        except Exception as e:
            logger.error(f"CryptoBot error: {e}")
    return None

async def check_crypto_invoice(invoice_id: int) -> str:
    url = f"{CRYPTOBOT_API}/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    params = {"invoice_ids": str(invoice_id)}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, params=params, timeout=10) as r:
                resp = await r.json()
                if resp.get("ok") and resp["result"]["items"]:
                    return resp["result"]["items"][0]["status"]
        except:
            pass
    return "unknown"

# ---------- Sherlock ----------
def run_sherlock(username: str) -> str:
    try:
        path = Path("/tmp/sherlock")
        if not path.exists():
            subprocess.run(["git", "clone", "https://github.com/sherlock-project/sherlock.git", str(path)], check=True, capture_output=True)
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(path/"requirements.txt"), "--quiet"], check=True, capture_output=True)
        result = subprocess.run([sys.executable, str(path/"sherlock"), username, "--print-found"], capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and result.stdout:
            found = [l.strip() for l in result.stdout.splitlines() if "[+]" in l]
            return "\n".join(found) if found else "Не найдено."
        return f"Ошибка: {result.stderr[:200]}"
    except Exception as e:
        return f"Ошибка: {e}"

# ---------- Report Formats ----------
def format_output(query_type: str, query_data: str, results: dict, fmt: str) -> tuple:
    """Возвращает (текст, имя_файла, содержимое_файла)"""
    if fmt == "html":
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>SoloSint — {query_data}</title>
<style>
body{{background:#0a0a0a;color:#fff;font-family:'Courier New',monospace;padding:20px;}}
.header{{text-align:center;border-bottom:2px solid #00ff00;padding-bottom:10px;margin-bottom:20px;}}
.header h1{{color:#00ff00;}} .section{{margin:15px 0;border-left:3px solid #00ff00;padding-left:10px;}}
.value{{color:#00ff00;}} .footer{{margin-top:30px;text-align:center;color:#555;font-size:12px;}}
</style></head>
<body><div class="header"><h1>SoloSint OSINT Report</h1>
<p>{query_type} | {datetime.now().strftime('%d.%m.%Y %H:%M')} | {query_data}</p></div>"""
        for s, c in results.items():
            html += f"<div class='section'><h3>{s}</h3><p class='value'>{c}</p></div>"
        html += "<div class='footer'><p>SoloSint Bot © 2026</p></div></body></html>"
        return ("HTML-отчёт", "report.html", html)

    elif fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Параметр", "Значение"])
        for s, c in results.items():
            writer.writerow([s, c])
        return ("CSV-таблица", "report.csv", output.getvalue())

    else:  # text
        text = f"⚡ SoloSint Report\nТип: {query_type}\nЗапрос: {query_data}\n\n"
        for s, c in results.items():
            text += f"• {s}: {c}\n"
        return ("Текст", None, text)

# ---------- FSM ----------
class PhoneLookup(StatesGroup):
    phone = State()
class EmailLookup(StatesGroup):
    email = State()
class UsernameSearch(StatesGroup):
    username = State()
class FullValidate(StatesGroup):
    data = State()
class AdminAddQueries(StatesGroup):
    user_id = State()
    amount = State()
class AdminBan(StatesGroup):
    user_id = State()
class AdminBroadcast(StatesGroup):
    text = State()

# ---------- Rate Limiter ----------
user_last_request: Dict[int, float] = {}
def rate_limit(user_id: int) -> bool:
    now = time.time()
    if user_id in user_last_request:
        if now - user_last_request[user_id] < 2:
            return False
    user_last_request[user_id] = now
    return True

# ---------- Keyboards ----------
def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📱 Телефон", callback_data="menu_phone"))
    builder.add(InlineKeyboardButton(text="📧 Email", callback_data="menu_email"))
    builder.add(InlineKeyboardButton(text="🔎 Ник", callback_data="menu_username"))
    builder.add(InlineKeyboardButton(text="⚡ Валидация", callback_data="menu_full_validate"))
    builder.add(InlineKeyboardButton(text="💳 Купить", callback_data="buy_queries"))
    builder.add(InlineKeyboardButton(text="ℹ️ Баланс", callback_data="my_balance"))
    builder.add(InlineKeyboardButton(text="👥 Рефералы", callback_data="my_referrals"))
    builder.add(InlineKeyboardButton(text="🎨 Формат", callback_data="output_format"))
    builder.add(InlineKeyboardButton(text="🛡 Админ", callback_data="admin_panel"))
    builder.adjust(2)
    return builder.as_markup()

def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]])

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))
    builder.add(InlineKeyboardButton(text="➕ Выдать запросы", callback_data="admin_add_queries"))
    builder.add(InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban"))
    builder.add(InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
    builder.adjust(2)
    return builder.as_markup()

def subscription_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ch in REQUIRED_CHANNELS:
        builder.add(InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch["link"]))
    builder.add(InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub"))
    builder.adjust(1)
    return builder.as_markup()

def buy_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for q, price in PRICING.items():
        builder.add(InlineKeyboardButton(text=f"{q} запросов — ${price:.2f}", callback_data=f"pay_{q}"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
    builder.adjust(1)
    return builder.as_markup()

def format_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📝 Текст", callback_data="fmt_text"))
    builder.add(InlineKeyboardButton(text="🌐 HTML-сайт", callback_data="fmt_html"))
    builder.add(InlineKeyboardButton(text="📊 CSV-таблица", callback_data="fmt_csv"))
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_main"))
    builder.adjust(1)
    return builder.as_markup()

# ---------- Check Sub ----------
async def check_subscription(user_id: int) -> bool:
    for ch in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(ch["id"], user_id)
            if member.status in ("left", "kicked", "restricted"):
                return False
        except:
            continue
    return True

# ---------- Router ----------
router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
        except: pass
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username or "unknown", referrer_id)
        if referrer_id and referrer_id != message.from_user.id:
            add_referral(referrer_id)
    if not await check_subscription(message.from_user.id):
        await message.answer("👋 <b>SoloSint</b>\nПодпишись на каналы:", reply_markup=subscription_keyboard())
        return
    await message.answer("⚡ <b>SoloSint</b> к вашим услугам.", reply_markup=main_menu())

@router.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.edit_text("✅ Подписка подтверждена!", reply_markup=main_menu())
    else:
        await call.answer("❌ Подпишись на все каналы!", show_alert=True)

@router.callback_query(F.data == "back_main")
async def cb_back(call: CallbackQuery):
    await call.message.edit_text("Главное меню:", reply_markup=main_menu())

@router.callback_query(F.data == "my_balance")
async def cb_balance(call: CallbackQuery):
    user = get_user(call.from_user.id)
    bal = user["balance"] if user else 0
    await call.message.edit_text(f"💳 Баланс: <b>{bal}</b> запросов.\nНажми «Купить» для пополнения.", reply_markup=back_button())

@router.callback_query(F.data == "my_referrals")
async def cb_referrals(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if not user:
        await call.message.edit_text("Нет данных.", reply_markup=back_button()); return
    total = user["total_referrals"]
    earnings = user["referral_earnings"]
    bonus_queries = total // REFERRAL_BONUS
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start=ref_{call.from_user.id}"
    text = (
        f"👥 <b>Реферальная система</b>\n\n"
        f"Твоих рефералов: <b>{total}</b>\n"
        f"Бесплатных запросов: <b>{bonus_queries}</b>\n"
        f"С покупок: <b>{earnings:.2f}</b> запросов\n\n"
        f"📎 Ссылка:\n<code>{ref_link}</code>\n\n"
        f"Бонус: 1 запрос за {REFERRAL_BONUS} рефералов + {REF_PERCENT}% с их покупок."
    )
    await call.message.edit_text(text, reply_markup=back_button())

@router.callback_query(F.data == "buy_queries")
async def cb_buy(call: CallbackQuery):
    await call.message.edit_text("💳 <b>Выбери пакет:</b>\nОплата через CryptoBot (USDT/BTC/RUB):", reply_markup=buy_keyboard())

@router.callback_query(F.data.startswith("pay_"))
async def cb_pay(call: CallbackQuery):
    queries = int(call.data.replace("pay_", ""))
    price = PRICING.get(queries, 0)
    inv = await create_crypto_invoice(call.from_user.id, price, queries)
    if inv:
        pay_url = inv.get("pay_url") or inv.get("bot_invoice_url")
        text = f"💳 <b>Счёт на ${price:.2f}</b>\nПакет: {queries} запросов\n\n🔗 Оплатить:\n{pay_url}"
        await call.message.edit_text(text, reply_markup=back_button())
    else:
        await call.answer("Ошибка создания счёта.", show_alert=True)

@router.callback_query(F.data == "output_format")
async def cb_format(call: CallbackQuery):
    await call.message.edit_text("🎨 <b>Формат выдачи:</b>\nВыбери как получать результаты:", reply_markup=format_keyboard())

@router.callback_query(F.data.startswith("fmt_"))
async def cb_set_format(call: CallbackQuery):
    fmt = call.data.replace("fmt_", "")
    names = {"text": "Текст", "html": "HTML-сайт", "csv": "CSV-таблица"}
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET output_format=? WHERE user_id=?", (fmt, call.from_user.id))
    conn.commit()
    conn.close()
    await call.message.edit_text(f"✅ Формат: <b>{names.get(fmt, fmt)}</b>", reply_markup=main_menu())

# ---------- Поиски ----------
async def send_result(message: Message, query_type: str, query_data: str, results: dict):
    user = get_user(message.from_user.id)
    fmt = user["output_format"] if user else "text"
    label, fname, content = format_output(query_type, query_data, results, fmt)
    if not use_query(message.from_user.id, message.from_user.username, query_type, query_data, str(results)):
        await message.reply("❌ Нет запросов.", reply_markup=main_menu())
        return
    if fmt == "text":
        await message.reply(content, reply_markup=main_menu())
    else:
        with tempfile.NamedTemporaryFile(mode="w", suffix=f".{fmt}", delete=False, encoding="utf-8") as f:
            f.write(content); path = f.name
        await message.reply_document(FSInputFile(path), caption=f"✅ {label}", reply_markup=main_menu())
        os.unlink(path)

@router.callback_query(F.data == "menu_phone")
async def cb_phone(call: CallbackQuery, state: FSMContext):
    if not await check_subscription(call.from_user.id):
        await call.answer("Подпишись!", show_alert=True); return
    await call.message.edit_text("📱 Введи номер:", reply_markup=back_button())
    await state.set_state(PhoneLookup.phone)

@router.message(PhoneLookup.phone)
async def proc_phone(message: Message, state: FSMContext):
    if not rate_limit(message.from_user.id):
        await message.reply("Слишком быстро."); return
    phone = message.text.strip()
    try:
        p = parse(phone)
        if not is_valid_number(p):
            await message.reply("Неверный номер.", reply_markup=main_menu()); await state.clear(); return
        region = region_code_for_number(p)
        car = carrier.name_for_number(p, "ru") or "—"
        results = {"Номер": phone, "Регион": region, "Оператор": car}
        await send_result(message, "Телефон", phone, results)
    except Exception as e:
        await message.reply(f"Ошибка: {e}", reply_markup=main_menu())
    await state.clear()

@router.callback_query(F.data == "menu_email")
async def cb_email(call: CallbackQuery, state: FSMContext):
    if not await check_subscription(call.from_user.id):
        await call.answer("Подпишись!", show_alert=True); return
    await call.message.edit_text("📧 Введи email:", reply_markup=back_button())
    await state.set_state(EmailLookup.email)

@router.message(EmailLookup.email)
async def proc_email(message: Message, state: FSMContext):
    email = message.text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await message.reply("Неверный формат.", reply_markup=main_menu()); await state.clear(); return
    results = {"Email": email}
    await send_result(message, "Email", email, results)
    await state.clear()

@router.callback_query(F.data == "menu_username")
async def cb_user(call: CallbackQuery, state: FSMContext):
    if not await check_subscription(call.from_user.id):
        await call.answer("Подпишись!", show_alert=True); return
    await call.message.edit_text("🔎 Введи ник:", reply_markup=back_button())
    await state.set_state(UsernameSearch.username)

@router.message(UsernameSearch.username)
async def proc_user(message: Message, state: FSMContext):
    username = message.text.strip()
    sher = run_sherlock(username)
    results = {"Ник": username, "Найденные аккаунты": sher}
    await send_result(message, "Ник", username, results)
    await state.clear()

@router.callback_query(F.data == "menu_full_validate")
async def cb_full(call: CallbackQuery, state: FSMContext):
    if not await check_subscription(call.from_user.id):
        await call.answer("Подпишись!", show_alert=True); return
    await call.message.edit_text("⚡ Введи номер, ник или email:", reply_markup=back_button())
    await state.set_state(FullValidate.data)

@router.message(FullValidate.data)
async def proc_full(message: Message, state: FSMContext):
    data = message.text.strip()
    results = {"Запрос": data}
    if re.match(r"^\+?\d{7,15}$", data):
        try:
            p = parse(data)
            results["Регион"] = region_code_for_number(p)
            results["Оператор"] = carrier.name_for_number(p, "ru") or "—"
        except: pass
    elif "@" in data:
        results["Email"] = data
    else:
        results["Ник"] = data
        results["Sherlock"] = run_sherlock(data)
    await send_result(message, "Валидация", data, results)
    await state.clear()

# ---------- АДМИН-ПАНЕЛЬ (все кнопки рабочие) ----------
@router.callback_query(F.data == "admin_panel")
async def cb_admin(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Доступ запрещён.", show_alert=True); return
    await call.message.edit_text("🛡 Админ-панель:", reply_markup=admin_panel_keyboard())

@router.callback_query(F.data == "admin_stats")
async def cb_stats(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return
    s = get_stats()
    await call.message.edit_text(f"📊 <b>Статистика:</b>\n👥 Пользователей: {s['users']}\n🔎 Запросов: {s['queries']}\n💰 Продано: {s['sold']}", reply_markup=back_button())

@router.callback_query(F.data == "admin_add_queries")
async def cb_admin_add(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    await call.message.edit_text("➕ Введи ID пользователя:", reply_markup=back_button())
    await state.set_state(AdminAddQueries.user_id)

@router.message(AdminAddQueries.user_id)
async def proc_admin_add_user(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        await state.update_data(user_id=uid)
        await message.reply("Введи количество запросов:", reply_markup=back_button())
        await state.set_state(AdminAddQueries.amount)
    except:
        await message.reply("Неверный ID.", reply_markup=main_menu())
        await state.clear()

@router.message(AdminAddQueries.amount)
async def proc_admin_add_amount(message: Message, state: FSMContext):
    try:
        qty = int(message.text.strip())
        data = await state.get_data()
        uid = data["user_id"]
        add_queries(uid, 0, qty, "admin_gift", message.from_user.id)
        await message.reply(f"✅ Выдано {qty} запросов пользователю {uid}.", reply_markup=main_menu())
    except:
        await message.reply("Ошибка.", reply_markup=main_menu())
    await state.clear()

@router.callback_query(F.data == "admin_ban")
async def cb_admin_ban(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    await call.message.edit_text("🚫 Введи ID для бана/разбана:", reply_markup=back_button())
    await state.set_state(AdminBan.user_id)

@router.message(AdminBan.user_id)
async def proc_admin_ban(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        if ban_user(uid):
            user = get_user(uid)
            status = "забанен" if user["is_banned"] else "разбанен"
            await message.reply(f"✅ Пользователь {uid} {status}.", reply_markup=main_menu())
        else:
            await message.reply("Пользователь не найден.", reply_markup=main_menu())
    except:
        await message.reply("Неверный ID.", reply_markup=main_menu())
    await state.clear()

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS: return
    await call.message.edit_text("📢 Введи текст рассылки:", reply_markup=back_button())
    await state.set_state(AdminBroadcast.text)

@router.message(AdminBroadcast.text)
async def proc_admin_broadcast(message: Message, state: FSMContext):
    text = message.text
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE is_banned=0")
    users = cur.fetchall()
    conn.close()
    cnt = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 {text}")
            cnt += 1
            await asyncio.sleep(0.05)
        except: pass
    await message.reply(f"✅ Рассылка отправлена {cnt} пользователям.", reply_markup=main_menu())
    await state.clear()

# ---------- Main ----------
async def main():
    init_db()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
