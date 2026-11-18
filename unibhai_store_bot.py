"""UNIBHAI STORE - safe Telegram catalogue/request bot starter.

This starter is for lawful, ordinary digital products/services. It deliberately
has no game-cheat, anti-cheat-bypass, exploit, credential, payment-collection,
or automatic key-delivery functionality.

Requirements: Python 3.10+ and python-telegram-bot 21.x
Install: pip install "python-telegram-bot>=21,<22"
Run (macOS/Linux): export BOT_TOKEN='...'; export ADMIN_IDS='123456789'; python unibhai_store_bot.py
Run (Windows PowerShell): $env:BOT_TOKEN='...'; $env:ADMIN_IDS='123456789'; python unibhai_store_bot.py
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB_PATH = os.getenv("DB_PATH", "unibhai_store.db")
SHOP_NAME = "UNIBHAI STORE"
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            price REAL NOT NULL CHECK(price >= 0),
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            package_id INTEGER NOT NULL REFERENCES packages(id),
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL
        );
        """)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Browse catalogue", callback_data="categories")],
        [InlineKeyboardButton("📦 My requests", callback_data="myrequests")],
        [InlineKeyboardButton("ℹ️ Help / Support", callback_data="help")],
    ])


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Your Telegram numeric ID: {update.effective_user.id}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    with db() as c:
        c.execute(
            "INSERT INTO users(telegram_id, username, first_name, joined_at) VALUES(?,?,?,?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
            (u.id, u.username, u.first_name, datetime.now(timezone.utc).isoformat()),
        )
    await update.message.reply_text(
        f"Welcome to {SHOP_NAME}!\nChoose an option below.",
        reply_markup=home_keyboard(),
    )


async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    with db() as c:
        rows = c.execute("SELECT id,name FROM categories ORDER BY name").fetchall()
    if not rows:
        await q.edit_message_text("Catalogue is being prepared. Please check back later.", reply_markup=home_keyboard())
        return
    kb = [[InlineKeyboardButton(r['name'], callback_data=f"cat:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton("⬅️ Home", callback_data="home")])
    await q.edit_message_text("Choose a category:", reply_markup=InlineKeyboardMarkup(kb))


async def show_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    cat_id = int(q.data.split(":", 1)[1])
    with db() as c:
        cat = c.execute("SELECT name FROM categories WHERE id=?", (cat_id,)).fetchone()
        rows = c.execute("SELECT id,name FROM products WHERE category_id=? AND active=1 ORDER BY name", (cat_id,)).fetchall()
    if not cat:
        await q.edit_message_text("Category not found.", reply_markup=home_keyboard())
        return
    kb = [[InlineKeyboardButton(r['name'], callback_data=f"prod:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton("⬅️ Categories", callback_data="categories")])
    await q.edit_message_text(f"{cat['name']}\nChoose a product:", reply_markup=InlineKeyboardMarkup(kb))


async def show_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    product_id = int(q.data.split(":", 1)[1])
    with db() as c:
        p = c.execute("SELECT name,description,category_id FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
        packs = c.execute("SELECT id,label,price FROM packages WHERE product_id=? AND active=1 ORDER BY price", (product_id,)).fetchall()
    if not p:
        await q.edit_message_text("Product not found.", reply_markup=home_keyboard())
        return
    kb = [[InlineKeyboardButton(f"{x['label']} — {x['price']:.2f}", callback_data=f"pack:{x['id']}")] for x in packs]
    kb.append([InlineKeyboardButton("⬅️ Products", callback_data=f"cat:{p['category_id']}")])
    desc = f"\n{p['description']}" if p['description'] else ""
    await q.edit_message_text(f"{p['name']}{desc}\n\nChoose a package:", reply_markup=InlineKeyboardMarkup(kb))


async def create_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    package_id = int(q.data.split(":", 1)[1])
    with db() as c:
        pack = c.execute(
            "SELECT packages.label,packages.price,products.name FROM packages "
            "JOIN products ON products.id=packages.product_id WHERE packages.id=? AND packages.active=1 AND products.active=1",
            (package_id,),
        ).fetchone()
        if not pack:
            await q.edit_message_text("This package is currently unavailable.", reply_markup=home_keyboard())
            return
        cur = c.execute(
            "INSERT INTO requests(telegram_id,package_id,created_at) VALUES(?,?,?)",
            (q.from_user.id, package_id, datetime.now(timezone.utc).isoformat()),
        )
        request_id = cur.lastrowid
    await q.edit_message_text(
        f"Request #{request_id} submitted.\n{pack['name']} — {pack['label']}\n"
        f"Listed price: {pack['price']:.2f}\n\nAn admin will contact you. No payment has been taken.",
        reply_markup=home_keyboard(),
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"New catalogue request #{request_id}\nUser: {q.from_user.id}\n"
                f"Item: {pack['name']} / {pack['label']}\nListed price: {pack['price']:.2f}",
            )
        except Exception:
            log.exception("Could not notify admin %s", admin_id)


async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    with db() as c:
        rows = c.execute(
            "SELECT r.id,p.name,pk.label,r.status FROM requests r "
            "JOIN packages pk ON pk.id=r.package_id JOIN products p ON p.id=pk.product_id "
            "WHERE r.telegram_id=? ORDER BY r.id DESC LIMIT 10", (q.from_user.id,)
        ).fetchall()
    if not rows:
        msg = "You have no requests yet."
    else:
        msg = "Your latest requests:\n" + "\n".join(
            f"#{r['id']} — {r['name']} / {r['label']} — {r['status']}" for r in rows
        )
    await q.edit_message_text(msg, reply_markup=home_keyboard())


async def help_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("For help, contact the store administrator. Never share passwords, OTPs, or private account credentials.", reply_markup=home_keyboard())


async def home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(f"Welcome to {SHOP_NAME}!", reply_markup=home_keyboard())


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "Admin commands:\n"
        "/addcategory Name\n"
        "/addproduct CATEGORY_ID | Product name | Description\n"
        "/addpackage PRODUCT_ID | Package label | Price\n"
        "/requests — latest requests\n"
        "/setstatus REQUEST_ID | status"
    )


async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id): return
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Usage: /addcategory Category name"); return
    try:
        with db() as c: c.execute("INSERT INTO categories(name) VALUES(?)", (name,))
        await update.message.reply_text("Category added.")
    except sqlite3.IntegrityError:
        await update.message.reply_text("That category already exists.")


async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id): return
    raw = update.message.text.partition(" ")[2]
    parts = [x.strip() for x in raw.split("|", 2)]
    if len(parts) < 2:
        await update.message.reply_text("Usage: /addproduct CATEGORY_ID | Product name | Description"); return
    try:
        with db() as c:
            c.execute("INSERT INTO products(category_id,name,description) VALUES(?,?,?)",
                      (int(parts[0]), parts[1], parts[2] if len(parts) > 2 else ""))
        await update.message.reply_text("Product added.")
    except (ValueError, sqlite3.IntegrityError):
        await update.message.reply_text("Invalid category ID. Add the category first.")


async def add_package(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id): return
    raw = update.message.text.partition(" ")[2]
    parts = [x.strip() for x in raw.split("|", 2)]
    if len(parts) != 3:
        await update.message.reply_text("Usage: /addpackage PRODUCT_ID | Package label | Price"); return
    try:
        with db() as c:
            c.execute("INSERT INTO packages(product_id,label,price) VALUES(?,?,?)",
                      (int(parts[0]), parts[1], float(parts[2])))
        await update.message.reply_text("Package added.")
    except (ValueError, sqlite3.IntegrityError):
        await update.message.reply_text("Invalid product ID or price.")


async def list_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id): return
    with db() as c:
        rows = c.execute("SELECT id,telegram_id,package_id,status FROM requests ORDER BY id DESC LIMIT 20").fetchall()
    if not rows:
        await update.message.reply_text("No requests yet."); return
    await update.message.reply_text("Latest requests:\n" + "\n".join(
        f"#{r['id']} user={r['telegram_id']} package={r['package_id']} status={r['status']}" for r in rows
    ))


async def set_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id): return
    raw = update.message.text.partition(" ")[2]
    parts = [x.strip() for x in raw.split("|", 1)]
    allowed = {"new", "contacted", "fulfilled", "cancelled"}
    if len(parts) != 2 or parts[1] not in allowed:
        await update.message.reply_text("Usage: /setstatus REQUEST_ID | new/contacted/fulfilled/cancelled"); return
    try:
        with db() as c:
            cur = c.execute("UPDATE requests SET status=? WHERE id=?", (parts[1], int(parts[0])))
        await update.message.reply_text("Status updated." if cur.rowcount else "Request not found.")
    except ValueError:
        await update.message.reply_text("Invalid request ID.")


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /start to open the store menu.")


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN as an environment variable. Do not paste it into this file or a chat.")
    if not ADMIN_IDS:
        raise SystemExit("Set ADMIN_IDS to your numeric Telegram user ID (comma-separated for multiple admins).")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("addcategory", add_category))
    app.add_handler(CommandHandler("addproduct", add_product))
    app.add_handler(CommandHandler("addpackage", add_package))
    app.add_handler(CommandHandler("requests", list_requests))
    app.add_handler(CommandHandler("setstatus", set_status))
    app.add_handler(CallbackQueryHandler(categories, pattern="^categories$"))
    app.add_handler(CallbackQueryHandler(show_category, pattern="^cat:\\d+$"))
    app.add_handler(CallbackQueryHandler(show_product, pattern="^prod:\\d+$"))
    app.add_handler(CallbackQueryHandler(create_request, pattern="^pack:\\d+$"))
    app.add_handler(CallbackQueryHandler(my_requests, pattern="^myrequests$"))
    app.add_handler(CallbackQueryHandler(help_page, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(home, pattern="^home$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))
    log.info("Starting %s", SHOP_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
