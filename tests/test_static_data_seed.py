from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import Country, Fixture, FixtureTeam, Team, Venue
from app.services.static_data_seed import seed_static_worldcup_data


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


def test_static_seed_populates_normalized_worldcup_tables():
    app = create_app(TestConfig)
    with app.app_context():
        summary = seed_static_worldcup_data()
        assert summary["countries"] >= 48
        assert Team.query.count() == 48
        assert Venue.query.count() == 16
        assert Fixture.query.count() == 104
        assert FixtureTeam.query.count() == 144
        assert Country.query.filter_by(name="Mexico").one().fifa_code == "MEX"
        assert Fixture.query.filter_by(match_number=1).one().venue.name == "Estadio Azteca"
