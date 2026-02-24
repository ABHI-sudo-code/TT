import os
import re
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ───────────────────────── CONFIG ─────────────────────────

TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable not set.")

EXCEL_FILE = "TimeTable.xlsx"

# ───────────────────────── LOAD TIMETABLE ─────────────────────────

def load_timetable():
    df = pd.read_excel(EXCEL_FILE, header=None)
    df = df.fillna("")
    return df

timetable_df = load_timetable()

# ───────────────────────── SCHEDULE LOGIC ─────────────────────────

def get_schedule_by_date(target_date, section):
    df = timetable_df

    # Match exact date in column 1
    row = df[df[1] == pd.Timestamp(target_date.date())]

    if row.empty:
        return None, None

    row = row.iloc[0]
    day_name = row[2]

    slots = [row[3], row[4], row[5], row[6]]

    result = []

    for idx, slot in enumerate(slots, 1):
        if not slot:
            result.append(f"Slot {idx}: Free")
            continue

        subjects = []
        entries = str(slot).split("/")

        for entry in entries:
            entry = entry.strip()
            if f"S{section}" in entry:
                subject = entry.split("(")[0]
                subjects.append(subject)

        if subjects:
            result.append(f"Slot {idx}: {' / '.join(subjects)}")
        else:
            result.append(f"Slot {idx}: Free")

    return day_name, result

# ───────────────────────── COMMANDS ─────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Timetable Bot\n\n"
        "Use:\n"
        "today s3\n"
        "tomorrow s2"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Format:\n"
        "today s1\n"
        "tomorrow s4\n\n"
        "Sections: s1 to s6"
    )

# ───────────────────────── MESSAGE HANDLER ─────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    words = text.split()

    if len(words) != 2:
        await update.message.reply_text("Use format: today s3 or tomorrow s2")
        return

    day_keyword, section_text = words

    if day_keyword not in ["today", "tomorrow"]:
        await update.message.reply_text("Use 'today' or 'tomorrow'")
        return

    match = re.search(r"s(\d)", section_text)
    if not match:
        await update.message.reply_text("Invalid section. Use s1–s6")
        return

    section = match.group(1)

    if day_keyword == "today":
        target_date = datetime.today()
    else:
        target_date = datetime.today() + timedelta(days=1)

    day_name, schedule = get_schedule_by_date(target_date, section)

    if not schedule:
        await update.message.reply_text("No timetable found for that date.")
        return

    response = (
        f"{target_date.strftime('%d %B %Y')} – {day_name}\n"
        f"Section S{section}\n\n"
        + "\n".join(schedule)
    )

    await update.message.reply_text(response)

# ───────────────────────── MAIN (WEBHOOK FOR RENDER) ─────────────────────────

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Timetable bot is running...")

    PORT = int(os.environ["PORT"])

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://tt-0u6y.onrender.com/{TOKEN}"
    )

if __name__ == "__main__":
    main()
