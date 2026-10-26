import os
import sys
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv

from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN not found in .env file.")
    sys.exit(1)

DEFAULT_TZ_NAME = "Asia/Colombo"

# --- Keep-Alive HTTP Server for Render ---
async def health_check(request):
    now_str = datetime.now(ZoneInfo(DEFAULT_TZ_NAME)).strftime("%Y-%m-%d %I:%M:%S %p")
    print(f"[{now_str}] [Keep-Alive Ping] Received request from {request.remote}", flush=True)
    return web.Response(status=204)

async def start_web_server():
    server = web.Application()
    server.router.add_get("/", health_check)
    server.router.add_get("/health", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server listening on port {port} for keep-alive pings...", flush=True)

# --- Helper Functions ---
def get_user_tz(context: ContextTypes.DEFAULT_TYPE) -> ZoneInfo:
    tz_name = context.user_data.get("tz", DEFAULT_TZ_NAME)
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ_NAME)

def stop_chat_alarms(chat_id, context: ContextTypes.DEFAULT_TYPE) -> bool:
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

# --- Keyboards ---
def get_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏰ Set Alarm", callback_data="nav_alarm"),
            InlineKeyboardButton("🌍 Timezone", callback_data="nav_tz"),
        ],
        [
            InlineKeyboardButton("ℹ️ About", callback_data="nav_about"),
            InlineKeyboardButton("🛑 Stop Alarms", callback_data="stop"),
        ],
    ])

def get_alarm_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("30 Mins (:00, :30)", callback_data="clock_1800"),
            InlineKeyboardButton("1 Hour (:00)", callback_data="clock_3600"),
        ],
        [
            InlineKeyboardButton("3 Secs (Test)", callback_data="test_3s"),
            InlineKeyboardButton("🛑 Stop Alarms", callback_data="stop"),
        ],
        [
            InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main"),
        ]
    ])

def get_tz_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇱🇰 Sri Lanka (UTC+5:30)", callback_data="settz_Asia/Colombo"),
            InlineKeyboardButton("🌐 UTC / GMT", callback_data="settz_UTC"),
        ],
        [
            InlineKeyboardButton("🇦🇪 Dubai (UTC+4)", callback_data="settz_Asia/Dubai"),
            InlineKeyboardButton("🇬🇧 London (GMT/BST)", callback_data="settz_Europe/London"),
        ],
        [
            InlineKeyboardButton("🇺🇸 New York (ET)", callback_data="settz_America/New_York"),
            InlineKeyboardButton("🇸🇬 Singapore (SGT)", callback_data="settz_Asia/Singapore"),
        ],
        [
            InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main"),
        ]
    ])

# --- Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tz = context.user_data.get("tz", DEFAULT_TZ_NAME)
    text = (
        "👋 **Welcome to Classroom Reminder Bot!**\n\n"
        f"📍 Current Timezone: `{user_tz}`\n\n"
        "Choose an option below:"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

async def alarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_tz = get_user_tz(context)
    now_str = datetime.now(user_tz).strftime("%I:%M %p")
    text = (
        f"⏰ **Set Alarm Interval**\n"
        f"Current Time: **{now_str}**\n\n"
        "Select a clock-aligned interval or type custom minutes (e.g. '45'):"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_alarm_menu_keyboard())
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_alarm_menu_keyboard())

async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_tz = context.user_data.get("tz", DEFAULT_TZ_NAME)
    text = (
        "🌍 **Select Your Timezone**\n\n"
        f"Current: `{current_tz}`\n\n"
        "Pick a preset below or type an IANA timezone name (e.g., `Asia/Kolkata`, `Australia/Sydney`):"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_tz_menu_keyboard())
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_tz_menu_keyboard())

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ **About This Bot**\n\n"
        "Designed for classroom/silent settings so you don't need to constantly check your phone.\n\n"
        "• **Clock-Synced**: 30-min and 1-hour alarms align with the wall clock (e.g. 1:00, 1:30, 2:00).\n"
        "• **Custom Minutes**: Send any whole number to get periodic reminders.\n"
        "• **Commands**:\n"
        "  /start - Main menu\n"
        "  /alarm - Interval options\n"
        "  /timezone - Adjust your time zone\n"
        "  /test - 3-second quick ping\n"
        "  /stop - Disable active reminders"
    )
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main")]])
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=back_kb)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb)

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    context.job_queue.run_once(test_callback, when=3, chat_id=chat_id)
    await update.message.reply_text("Test started! Notification arriving in 3 seconds...")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if stop_chat_alarms(chat_id, context):
        await update.message.reply_text("🛑 Repeating alarms stopped.")
    else:
        await update.message.reply_text("No active alarms were running.")

# --- Alarm Logic ---
async def alarm_callback(context: ContextTypes.DEFAULT_TYPE):
    tz = get_user_tz(context)
    now_str = datetime.now(tz).strftime("%I:%M %p")
    keyboard = [[InlineKeyboardButton("🛑 Stop Alarms", callback_data="stop")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"⏰ Time check: {now_str}",
        reply_markup=reply_markup,
    )

async def test_callback(context: ContextTypes.DEFAULT_TYPE):
    tz = get_user_tz(context)
    now_str = datetime.now(tz).strftime("%I:%M:%S %p")
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"🔔 Test notification! Current time: {now_str}",
    )

def set_clock_aligned_job(chat_id, interval_seconds, context: ContextTypes.DEFAULT_TYPE):
    stop_chat_alarms(chat_id, context)
    user_tz = get_user_tz(context)
    now = datetime.now(user_tz)

    if interval_seconds == 3600:
        seconds_passed = (now.minute * 60) + now.second
        first_delay = 3600 - seconds_passed
    elif interval_seconds == 1800:
        seconds_passed = ((now.minute % 30) * 60) + now.second
        first_delay = 1800 - seconds_passed
    else:
        first_delay = interval_seconds

    if first_delay <= 0:
        first_delay = interval_seconds

    context.job_queue.run_repeating(
        alarm_callback,
        interval=interval_seconds,
        first=first_delay,
        chat_id=chat_id,
        name=str(chat_id),
    )
    return first_delay

# --- Callback and Text Handlers ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # Navigation routing
    if data == "nav_main":
        await start_command(update, context)
        return
    elif data == "nav_alarm":
        await alarm_command(update, context)
        return
    elif data == "nav_tz":
        await timezone_command(update, context)
        return
    elif data == "nav_about":
        await about_command(update, context)
        return

    # Alarm controls
    if data == "stop":
        stop_chat_alarms(chat_id, context)
        await query.edit_message_text(
            "🛑 Repeating alarms stopped.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏰ Set New Alarm", callback_data="nav_alarm")]])
        )
        return

    if data == "test_3s":
        context.job_queue.run_once(test_callback, when=3, chat_id=chat_id)
        await query.edit_message_text("Test triggered! Notification arriving in 3 seconds...")
        return

    if data.startswith("settz_"):
        chosen_tz = data.split("_", 1)[1]
        context.user_data["tz"] = chosen_tz
        now_str = datetime.now(ZoneInfo(chosen_tz)).strftime("%I:%M %p")
        await query.edit_message_text(
            f"✅ Timezone updated to `{chosen_tz}`!\nCurrent time: **{now_str}**",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏰ Set Alarm Now", callback_data="nav_alarm")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="nav_main")],
            ])
        )
        return

    if data.startswith("clock_"):
        seconds = int(data.split("_")[1])
        first_delay = set_clock_aligned_job(chat_id, seconds, context)
        wait_mins = round(first_delay / 60)
        mode = "every 30 mins (:00, :30)" if seconds == 1800 else "every hour (:00)"
        user_tz = context.user_data.get("tz", DEFAULT_TZ_NAME)
        await query.edit_message_text(
            f"✅ Alarm synced to clock {mode}!\n"
            f"Timezone: `{user_tz}`\n"
            f"Next notification in ~{wait_mins} minute(s).",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Alarms", callback_data="stop")]])
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Case 1: User typed an interval in minutes
    if text.isdigit():
        mins = int(text)
        if mins <= 0:
            await update.message.reply_text("Please enter a number greater than 0.")
            return

        seconds = mins * 60
        stop_chat_alarms(update.message.chat_id, context)
        context.job_queue.run_repeating(
            alarm_callback,
            interval=seconds,
            first=seconds,
            chat_id=update.message.chat_id,
            name=str(update.message.chat_id),
        )
        await update.message.reply_text(
            f"Repeating alarm set! You will be pinged every {mins} minute(s) from now.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Alarms", callback_data="stop")]])
        )
        return

    # Case 2: Check if user typed an IANA timezone name (e.g., "Asia/Tokyo")
    try:
        ZoneInfo(text)
        context.user_data["tz"] = text
        now_str = datetime.now(ZoneInfo(text)).strftime("%I:%M %p")
        await update.message.reply_text(
            f"✅ Timezone set to `{text}`!\nCurrent time: **{now_str}**",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏰ Set Alarm", callback_data="nav_alarm")]])
        )
        return
    except (ZoneInfoNotFoundError, ValueError):
        pass

    await update.message.reply_text(
        "Unrecognized input. Send a number for minutes (e.g., `45`), an IANA timezone (e.g., `Asia/Colombo`), or use /start.",
        parse_mode="Markdown"
    )

async def post_init(application):
    await start_web_server()

if __name__ == "__main__":
    request_config = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .request(request_config)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("alarm", alarm_command))
    app.add_handler(CommandHandler("timezone", timezone_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot is running...")
    app.run_polling(bootstrap_retries=-1, timeout=30)