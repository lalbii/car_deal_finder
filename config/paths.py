from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
DB_PATH = DATA_DIR / "listings.db"
SEARCH_CONFIG_PATH = PROJECT_ROOT / "config" / "searches.yaml"
VALUATION_VOCABULARY_PATH = PROJECT_ROOT / "config" / "valuation_vocabulary.yaml"
RUN_LOCK_PATH = PROJECT_ROOT / ".car_deal_finder.lock"
