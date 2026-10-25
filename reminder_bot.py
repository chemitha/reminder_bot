import os
import sys
import asyncio
from datetime import datetime
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

# --- Keep-Alive HTTP Server for Render ---
async def health_check(request):
    """Responds to external pings to keep Render awake."""
    return web.Response(text="Bot is running and awake!")

async def start_web_server():
    """Binds to the port provided by Render (default 8080)."""
    server = web.Application()
    server.router.add_get("/", health_check)
    server.router.add_get("/health", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server listening on port {port} for keep-alive pings...")

# --- Bot Handlers ---
def stop_chat_alarms(chat_id, context: ContextTypes.DEFAULT_TYPE) -> bool:
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

async def keepalive_callback(context: ContextTypes.DEFAULT_TYPE):
    """Logs to stdout every 10 minutes."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] [Keep-Alive] Bot is active. No sleep.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("30 Mins (:00, :30)", callback_data="clock_1800"),
            InlineKeyboardButton("1 Hour (:00)", callback_data="clock_3600"),
        ],
        [
            InlineKeyboardButton("3 Secs (Test)", callback_data="test_3s"),
            InlineKeyboardButton("Stop Alarms", callback_data="stop"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Select a clock-aligned reminder or type custom interval minutes (e.g. '15'):",
        reply_markup=reply_markup,
    )

async def alarm_callback(context: ContextTypes.DEFAULT_TYPE):
    now_str = datetime.now().strftime("%I:%M %p")
    keyboard = [[InlineKeyboardButton("🛑 Stop Alarms", callback_data="stop")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"⏰ Time check: {now_str}",
        reply_markup=reply_markup,
    )

async def test_callback(context: ContextTypes.DEFAULT_TYPE):
    now_str = datetime.now().strftime("%I:%M:%S %p")
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"🔔 Test notification! Current time: {now_str}",
    )

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    context.job_queue.run_once(test_callback, when=3, chat_id=chat_id)
    await update.message.reply_text("Test started! Waiting 3 seconds...")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if stop_chat_alarms(chat_id, context):
        await update.message.reply_text("🛑 Repeating alarms stopped.")
    else:
        await update.message.reply_text("No active alarms were running.")

def set_clock_aligned_job(chat_id, interval_seconds, context: ContextTypes.DEFAULT_TYPE):
    stop_chat_alarms(chat_id, context)

    now = datetime.now()
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "stop":
        stop_chat_alarms(chat_id, context)
        await query.edit_message_text("🛑 Repeating alarms stopped.")
        return

    if query.data == "test_3s":
        context.job_queue.run_once(test_callback, when=3, chat_id=chat_id)
        await query.edit_message_text("Test triggered! Notification arriving in 3 seconds...")
        return

    if query.data.startswith("clock_"):
        seconds = int(query.data.split("_")[1])
        first_delay = set_clock_aligned_job(chat_id, seconds, context)
        wait_mins = round(first_delay / 60)
        
        mode = "every 30 mins (:00, :30)" if seconds == 1800 else "every hour on the hour (:00)"
        await query.edit_message_text(
            f"✅ Alarm synced to clock {mode}!\n"
            f"Next notification will arrive in ~{wait_mins} minute(s)."
        )

async def custom_interval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Please enter a valid whole number of minutes.")
        return

    mins = int(text)
    if mins <= 0:
        await update.message.reply_text("Enter a number greater than 0.")
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
    await update.message.reply_text(f"Alarm set! You will be pinged every {mins} minute(s) from now.")

async def post_init(application):
    """Sets up the 10-minute console logging loop once the bot starts."""
    application.job_queue.run_repeating(
        keepalive_callback,
        interval=600,   # Every 10 minutes (600 seconds)
        first=10,       # First log after 10 seconds
        name="render_keepalive"
    )
    # Start the lightweight HTTP server in the same event loop
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, custom_interval_handler))

    print("Bot is starting...")
    app.run_polling(bootstrap_retries=-1, timeout=30)