import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def resolve_database_url(value):
    value = value or "sqlite:///instance/worldcup_odds.db"
    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value
    db_path = value.removeprefix(prefix)
    if db_path == ":memory:" or Path(db_path).is_absolute():
        return value
    absolute_path = BASE_DIR / db_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{absolute_path.as_posix()}"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = resolve_database_url(os.getenv("DATABASE_URL", "sqlite:///instance/worldcup_odds.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
    ODDS_API_BASE_URL = os.getenv("ODDS_API_BASE_URL", "https://api.odds-api.io")
    DEBUG_RAW_RESPONSES = os.getenv("DEBUG_RAW_RESPONSES", "false").lower() == "true"

    DEFAULT_SPORT = os.getenv("DEFAULT_SPORT", "football")
    DEFAULT_COMPETITION_FILTER = os.getenv("DEFAULT_COMPETITION_FILTER", "World Cup")
    DEFAULT_BANKROLL = float(os.getenv("DEFAULT_BANKROLL", "1000"))
    DEFAULT_MAX_STAKE = float(os.getenv("DEFAULT_MAX_STAKE", "50"))
    DEFAULT_EV_THRESHOLD = float(os.getenv("DEFAULT_EV_THRESHOLD", "0.05"))
    DEFAULT_KELLY_FRACTION = float(os.getenv("DEFAULT_KELLY_FRACTION", "0.25"))

    DEFAULT_BOOKMAKERS = [
        "Bet365",
        "Betfair",
        "PaddyPower",
        "WilliamHill",
        "Unibet",
        "Ladbrokes",
        "SkyBet",
    ]
    DEFAULT_MARKETS = [
        "Match Winner / 1X2",
        "Over/Under Goals",
        "Both Teams To Score",
        "Draw No Bet",
        "Double Chance",
        "Asian Handicap",
        "Correct Score",
        "Outright Winner",
    ]

    LOG_DIR = BASE_DIR / "logs"
    RAW_RESPONSE_DIR = LOG_DIR / "raw_responses"
