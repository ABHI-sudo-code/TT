# timetable_bot.py
import os
import re
from datetime import datetime, timedelta
import pandas as pd
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ──────────────────────────────── CONFIG ─────────────────────────────────────
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_FILE = os.path.join(BASE_DIR, "TimeTable.xlsx")

# ──────────────────────────────── DATE → WEEK MAPPING ────────────────────────
# Week numbers are negative in your file → WEEK -6, -7, ..., -11
WEEK_START_DATES = {
    -6: datetime(2026, 2, 16),
    -7: datetime(2026, 2, 23),
    -8: datetime(2026, 3, 2),
    -9: datetime(2026, 3, 9),
    -10: datetime(2026, 3, 16),
    -11: datetime(2026, 3, 23),
}

FIRST_DATE = min(WEEK_START_DATES.values())
LAST_DATE = max(WEEK_START_DATES.values()) + timedelta(days=6)  # Sunday of week -11

# ──────────────────────────────── LOAD TIMETABLE ─────────────────────────────
def load_timetable():
    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name=0, header=None)
        df = df.fillna("")
        timetable = {}
        current_week = None

        for i in range(len(df)):
            row = [str(df.iloc[i, j]).strip() for j in range(10)]

            # Detect week header
            if row[0].startswith("WEEK"):
                current_week = row[0]
                timetable[current_week] = {}
                continue

            # Skip invalid rows
            if len(row) < 3 or not row[2]:
                continue

            day = row[2].capitalize()
            if not current_week or day not in [
                "Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"
            ]:
                continue

            slots = row[3:7]  # columns D-G (0-based 3-6)
            day_data = timetable[current_week].setdefault(day, {})

            # Check for holiday/special
            special = ""
            for s in slots:
                s_clean = s.upper().strip()
                if s_clean in ["HOLI", "ID-UL-FITR", "END TERM EXAM"]:
                    special = s.strip()
                    break
            if special:
                day_data["special"] = special
                continue

            # Parse normal slots
            for slot_idx, content in enumerate(slots, 1):
                if not content.strip():
                    continue
                entries = [e.strip() for e in re.split(r'\s*/\s*', content) if e.strip()]
                for entry in entries:
                    m = re.match(r'^([A-Z]+)\(S?(\d+)\)$', entry)
                    if m:
                        subj = m.group(1)
                        sec = m.group(2)
                        if sec in ["1","2","3","4","5","6"]:
                            sec_dict = day_data.setdefault(sec, {})
                            sec_dict.setdefault(slot_idx, []).append(subj)

        return timetable

    except Exception as e:
        print("Failed to load timetable:", e)
        return {}

timetable_data = load_timetable()

# Slot times per group
SLOT_TIMES = {
    "A": {  # S1,3,5
        1: "10:30 – 12:00 hrs",
        2: "12:15 – 13:45 hrs",
        3: "14:45 – 16:15 hrs",
        4: "16:30 – 18:00 hrs",  # sometimes used
    },
    "B": {  # S2,4,6
        1: "10:00 – 11:30 hrs",
        2: "11:45 – 13:15 hrs",
        3: "14:15 – 15:45 hrs",
        4: "16:30 – 18:00 hrs",
    }
}

VENUES = {
    "1": "Room-101",
    "2": "Room-102",
    "3": "Room-103",
    "4": "Room-G07",
    "5": "Room-201",
    "6": "Room-G02"
}

# ──────────────────────────────── HELPERS ────────────────────────────────────
def get_week_key_for_date(target: datetime) -> str | None:
    target_date = target.date()
    for w_num, start in WEEK_START_DATES.items():
        end = (start + timedelta(days=6)).date()
        if start.date() <= target_date <= end:
            return f"WEEK -{abs(w_num)}"
    return None

def parse_date_input(text: str, now: datetime) -> datetime | None:
    text = text.lower().strip()
    if "today" in text:
        return now
    if "tomorrow" in text:
        return now + timedelta(days=1)
    if "yesterday" in text:
        return now - timedelta(days=1)

    # Try YYYY-MM-DD
    m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except:
            pass

    return None

def parse_section(text: str) -> str | None:
    m = re.search(r'(?:s|sec|section)\s*(\d)', text, re.I)
    if m:
        sec = m.group(1)
        if sec in "123456":
            return sec
    return None

# ──────────────────────────────── BOT HANDLERS ───────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me something like:\n\n"
        "today s3\n"
        "tomorrow section 4\n"
        "2026-03-05 s1\n"
        "yesterday s5\n\n"
        "I'll show only the schedule for that section on that date.\n"
        "/help for more info"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Usage examples:\n\n"
        "• today s3\n"
        "• tomorrow section 2\n"
        "• 2026-02-25 s4\n"
        "• yesterday s1\n"
        "• friday s6   (will use nearest/recent Friday)\n\n"
        "I will show **only** the requested section's timetable.\n"
        "Free periods are marked clearly.\n"
        "Holidays / exams are shown when applicable.\n\n"
        "Timetable period: 16 Feb 2026 – 29 Mar 2026"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return

    now = datetime.now()
    target_date = parse_date_input(text, now)

    # Fallback: try to interpret day name as this/next week
    if not target_date:
        day_map = {
            "monday": 0, "mon": 0,
            "tuesday": 1, "tue": 1,
            "wednesday": 2, "wed": 2,
            "thursday": 3, "thu": 3, "thur": 3,
            "friday": 4, "fri": 4,
            "saturday": 5, "sat": 5,
            "sunday": 6, "sun": 6,
        }
        for name, offset in day_map.items():
            if name in text.lower():
                today_weekday = now.weekday()
                days_to_add = (offset - today_weekday) % 7
                if days_to_add == 0 and name not in ["today", "tomorrow"]:
                    days_to_add = 7  # next week
                target_date = now + timedelta(days=days_to_add)
                break

    if not target_date:
        await update.message.reply_text(
            "Couldn't understand the date.\n\n"
            "Try:\n"
            "today s3\n"
            "tomorrow section 4\n"
            "2026-03-05 s1\n"
            "friday s2"
        )
        return

    section = parse_section(text)
    if not section:
        await update.message.reply_text(
            "Which section? (s1–s6 or section 3)\n\n"
            "Example: today s3"
        )
        return

    target_date = target_date.replace(hour=now.hour, minute=now.minute, second=now.second)

    if target_date.date() < FIRST_DATE.date():
        await update.message.reply_text(
            f"Invalid date — timetable starts from {FIRST_DATE.strftime('%d %b %Y')}"
        )
        return

    if target_date.date() > LAST_DATE.date():
        await update.message.reply_text(
            f"No data — timetable ends on {LAST_DATE.strftime('%d %b %Y')}"
        )
        return

    week_key = get_week_key_for_date(target_date)
    if not week_key or week_key not in timetable_data:
        await update.message.reply_text("No timetable data for this date.")
        return

    weekday = target_date.strftime("%A")
    day_data = timetable_data[week_key].get(weekday, {})

    if "special" in day_data:
        await update.message.reply_text(
            f"📅 {target_date.strftime('%d %B %Y')} – {weekday}\n\n"
            f"**{day_data['special']}**\n"
            "No regular classes."
        )
        return

    sec_data = day_data.get(section, {})
    group = "A" if section in ["1","3","5"] else "B"
    times = SLOT_TIMES[group]

    lines = []
    has_class = False

    for slot in range(1, 5):
        time_str = times.get(slot, "??:?? – ??:??")
        subjects = sec_data.get(slot, [])
        if subjects:
            has_class = True
            subj_str = " / ".join(subjects)
            lines.append(f"{time_str}\n{subj_str}")
        else:
            lines.append(f"{time_str}\nFree")

    venue = VENUES.get(section, "—")

    if not has_class:
        msg = (
            f"📅 {target_date.strftime('%d %B %Y')} – {weekday}\n"
            f"Section {section} (Room {venue})\n\n"
            "All periods free.\n"
            "No classes scheduled for Section {section} on this day."
        )
    else:
        msg = (
            f"📅 {target_date.strftime('%d %B %Y')} – {weekday}\n"
            f"Section {section} (Room {venue})\n\n"
            + "\n\n".join(lines)
        )

    await update.message.reply_text(msg, parse_mode="Markdown")

# ──────────────────────────────── MAIN ───────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Timetable bot is running...")
    # For webhook (Render, Railway, etc.)
    PORT = int(os.environ.get("PORT", 8443))
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://tt-0u6y.onrender.com/{TOKEN}"
    )
    # For local testing uncomment:
    # app.run_polling()

if __name__ == "__main__":
    main()