from flask import Blueprint, render_template, request
from sqlalchemy import func

from app.extensions import db
from app.models import Event, OddsSnapshot

bp = Blueprint("events", __name__, url_prefix="/events")


@bp.route("/")
def list_events():
    query = Event.query
    if request.args.get("team"):
        team = f"%{request.args['team']}%"
        query = query.filter((Event.home_team.ilike(team)) | (Event.away_team.ilike(team)) | (Event.event_name.ilike(team)))
    if request.args.get("competition"):
        query = query.filter(Event.competition_name.ilike(f"%{request.args['competition']}%"))
    if request.args.get("status"):
        query = query.filter(Event.status == request.args["status"])
    if request.args.get("date"):
        query = query.filter(func.date(Event.event_start_time) == request.args["date"])

    events = query.order_by(Event.event_start_time.asc().nullslast()).all()
    stats = event_stats([event.provider_event_id for event in events])
    return render_template("events.html", events=events, stats=stats)


def event_stats(event_ids):
    if not event_ids:
        return {}
    rows = (
        db.session.query(
            OddsSnapshot.provider_event_id,
            func.count(func.distinct(OddsSnapshot.bookmaker)),
            func.count(func.distinct(OddsSnapshot.market_name)),
            func.max(OddsSnapshot.snapshot_time),
        )
        .filter(OddsSnapshot.provider_event_id.in_(event_ids))
        .group_by(OddsSnapshot.provider_event_id)
        .all()
    )
    return {row[0]: {"bookmakers": row[1], "markets": row[2], "latest": row[3]} for row in rows}
