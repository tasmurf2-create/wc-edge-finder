from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import Event, OddsSnapshot


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


def test_database_can_store_event_and_snapshot():
    app = create_app(TestConfig)
    with app.app_context():
        db.session.add(Event(provider_event_id="abc", event_name="A vs B", sport="football"))
        db.session.add(
            OddsSnapshot(
                provider_event_id="abc",
                bookmaker="Bet365",
                market_name="Match Winner / 1X2",
                outcome_name="A",
                decimal_odds=2.0,
            )
        )
        db.session.commit()
        assert Event.query.count() == 1
        assert OddsSnapshot.query.count() == 1
