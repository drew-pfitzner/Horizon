import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("SMART_MONEY_DATA_DIR") or os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.environ.get("SMART_MONEY_DB_PATH") or os.path.join(DATA_DIR, "smart_money.db")
GURU_LIST_PATH = os.path.join(DATA_DIR, "guru_list.csv")

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".smart_money")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

FETCH_DELAY = 0.15  # seconds between guru fetches (SEC rate limit safety)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH_SIZE = 10  # items per request (free tier limit without API key)


def load_settings() -> dict:
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    return {}


def save_settings(settings: dict) -> None:
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def get_sec_identity() -> str | None:
    """Get the SEC identity email from settings. Returns None if not configured."""
    return load_settings().get("sec_identity")


def set_sec_identity(email: str) -> None:
    """Save the SEC identity email to settings."""
    settings = load_settings()
    settings["sec_identity"] = email
    save_settings(settings)


def require_sec_identity() -> str:
    """Get SEC identity, prompting interactively if not set (CLI use only)."""
    identity = get_sec_identity()
    if identity:
        return identity
    print("SEC EDGAR requires an email for their fair access policy.")
    email = input("Enter your email: ").strip()
    if not email or "@" not in email:
        raise SystemExit("A valid email is required to access SEC EDGAR.")
    set_sec_identity(email)
    return email
