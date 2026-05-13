import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

HORIZON_DB = Path(os.getenv("HORIZON_DB_PATH", BASE_DIR / "horizon.db"))
SMART_MONEY_DB = Path(os.getenv("SMART_MONEY_DB_PATH", BASE_DIR.parent / "smart_money" / "data" / "smart_money.db"))
SMART_MONEY_DIR = Path(os.getenv("SMART_MONEY_DIR", BASE_DIR.parent / "smart_money"))

PORT = int(os.getenv("PORT", "5001"))
