from pathlib import Path

BASE_DIR = Path(__file__).parent
HORIZON_DB = BASE_DIR / "horizon.db"
SMART_MONEY_DB = BASE_DIR.parent / "smart_money" / "data" / "smart_money.db"
PORT = 5001
