import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from app import create_app
from app.services.odds_refresh_service import refresh_worldcup_odds


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    app = create_app()
    with app.app_context():
        summary = refresh_worldcup_odds()
    print("Odds refresh summary")
    print(f"Success: {summary['success']}")
    print(f"Events fetched: {summary['events_fetched']}")
    print(f"Odds snapshots saved: {summary['odds_snapshots_saved']}")
    print(f"Requests: {summary['request_count']}")
    if summary["error_message"]:
        print(f"Error: {summary['error_message']}")
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
