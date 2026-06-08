from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from sqlalchemy import distinct, func

from app.extensions import db
from app.models import Event, OddsSnapshot, RefreshLog, WatchlistItem
from app.services.odds_refresh_service import refresh_worldcup_odds

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    latest_refresh = RefreshLog.query.order_by(RefreshLog.started_at.desc()).first()
    metrics = {
        "events": Event.query.count(),
        "snapshots": OddsSnapshot.query.count(),
        "bookmakers": db.session.query(func.count(distinct(OddsSnapshot.bookmaker))).scalar() or 0,
        "markets": db.session.query(func.count(distinct(OddsSnapshot.market_name))).scalar() or 0,
        "candidates": WatchlistItem.query.filter(WatchlistItem.expected_value > current_app.config["DEFAULT_EV_THRESHOLD"]).count(),
        "latest_refresh": latest_refresh,
        "has_api_key": bool(current_app.config.get("ODDS_API_KEY")),
    }
    return render_template("dashboard.html", metrics=metrics)


@bp.post("/refresh")
def refresh():
    summary = refresh_worldcup_odds()
    if summary["success"]:
        flash(f"Refresh complete: {summary['events_fetched']} events, {summary['odds_snapshots_saved']} odds snapshots saved.", "success")
    else:
        flash(f"Refresh failed. Showing stored odds where available. {summary['error_message']}", "warning")
    return redirect(url_for("dashboard.index"))
