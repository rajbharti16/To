import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = {
    "price_min": "0.10", "price_max": "0.50", "spam_mode": "no", "mail_mode": "yes",
    "mail_type": "any", "password_mode": "any", "session_min_hours": "20",
    "session_life_hours": "24", "countries": "", "deny_countries": "IR",
    "nsb_only": "1", "currency": "usd",
}