from pathlib import Path

import pytest

from app import create_app
from app.routes.value import parse_float


class TestConfig:
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ODDS_API_KEY = ""
    ODDS_API_BASE_URL = "https://api.odds-api.io"
    DEBUG_RAW_RESPONSES = False
    DEFAULT_SPORT = "football"
    DEFAULT_COMPETITION_FILTER = "World Cup"
    DEFAULT_BANKROLL = 1000
    DEFAULT_MAX_STAKE = 50
    DEFAULT_EV_THRESHOLD = 0.05
    DEFAULT_KELLY_FRACTION = 0.25
    DEFAULT_BOOKMAKERS = ["Bet365"]
    DEFAULT_MARKETS = ["Match Winner / 1X2"]
    LOG_DIR = Path("logs")
    RAW_RESPONSE_DIR = Path("logs/raw_responses")


def test_parse_float_rejects_bad_values():
    app = create_app(TestConfig)
    with app.app_context():
        with pytest.raises(ValueError, match="Model probability"):
            parse_float("nope", "Model probability")
