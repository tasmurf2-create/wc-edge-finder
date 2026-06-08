import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models import AppSetting


DEFAULT_SETTINGS = {
    "competition_filter": "World Cup",
    "default_bookmakers": "Bet365, Betfair, PaddyPower, WilliamHill, Unibet, Ladbrokes, SkyBet",
    "default_markets": "Match Winner / 1X2, Over/Under Goals, Both Teams To Score, Draw No Bet, Double Chance, Asian Handicap, Correct Score, Outright Winner",
    "default_bankroll": "1000",
    "default_max_stake": "50",
    "default_ev_threshold": "0.05",
}


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        for key, value in DEFAULT_SETTINGS.items():
            if AppSetting.query.filter_by(key=key).first() is None:
                db.session.add(AppSetting(key=key, value=value))
        db.session.commit()
    print("Database initialized and default settings seeded.")


if __name__ == "__main__":
    main()
