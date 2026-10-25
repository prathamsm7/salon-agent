"""One-time browser login for the calendar test.

Run from the backend folder:

    .venv/bin/python -m app.calender_login
"""

from dotenv import load_dotenv

from app.calendar.auth import BACKEND_DIR, login

load_dotenv(BACKEND_DIR / ".env")
login()
print("Saved calendar login.")
