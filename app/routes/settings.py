from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import AppSetting
from app.services.export_service import export_latest_odds, export_movement, export_value_candidates
from app.services.odds_api_client import OddsAPIClient
from app.services.odds_refresh_service import refresh_worldcup_odds

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for key in ("competition_filter", "default_bookmakers", "default_markets", "default_bankroll", "default_max_stake", "default_ev_threshold"):
            save_setting(key, request.form.get(key, ""))
        flash("Settings saved locally.", "success")
        return redirect(url_for("settings.settings"))
    settings_map = {item.key: item.value for item in AppSetting.query.all()}
    return render_template("settings.html", settings=settings_map, api_key_present=bool(current_app.config.get("ODDS_API_KEY")))


@bp.post("/refresh")
def refresh():
    summary = refresh_worldcup_odds()
    flash("Manual refresh finished." if summary["success"] else f"Refresh failed: {summary['error_message']}", "success" if summary["success"] else "warning")
    return redirect(url_for("settings.settings"))


@bp.post("/test-connection")
def test_connection():
    result = OddsAPIClient().test_connection()
    flash(result["message"], "success" if result["success"] else "warning")
    return redirect(url_for("settings.settings"))


@bp.route("/export/latest-odds.csv")
def latest_odds_csv():
    return export_latest_odds()


@bp.route("/export/movement.csv")
def movement_csv():
    return export_movement()


@bp.route("/export/value-candidates.csv")
def value_candidates_csv():
    return export_value_candidates()


def save_setting(key, value):
    setting = AppSetting.query.filter_by(key=key).first()
    if setting is None:
        setting = AppSetting(key=key)
        db.session.add(setting)
    setting.value = value
    db.session.commit()
