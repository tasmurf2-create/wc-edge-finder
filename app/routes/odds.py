from collections import defaultdict

from flask import Blueprint, render_template, request
from sqlalchemy import func

from app.models import Event, OddsSnapshot
from app.services.calculations import calculate_overround, decimal_odds_to_implied_probability

bp = Blueprint("odds", __name__, url_prefix="/odds")


@bp.route("/")
def compare():
    latest = latest_snapshots()
    filters = {
        "event": request.args.get("event", ""),
        "market": request.args.get("market", ""),
        "bookmaker": request.args.get("bookmaker", ""),
        "outcome": request.args.get("outcome", ""),
    }
    rows = []
    events = {event.provider_event_id: event for event in Event.query.all()}
    for snapshot in latest:
        if filters["event"] and snapshot.provider_event_id != filters["event"]:
            continue
        if filters["market"] and snapshot.market_name != filters["market"]:
            continue
        if filters["bookmaker"] and snapshot.bookmaker != filters["bookmaker"]:
            continue
        if filters["outcome"] and filters["outcome"].lower() not in snapshot.outcome_name.lower():
            continue
        rows.append({"snapshot": snapshot, "event": events.get(snapshot.provider_event_id), "implied": decimal_odds_to_implied_probability(snapshot.decimal_odds)})

    best_keys = find_best_keys(rows)
    overrounds = compute_overrounds(rows)
    options = {
        "events": Event.query.order_by(Event.event_start_time.asc().nullslast()).all(),
        "markets": sorted({row["snapshot"].market_name for row in rows}),
        "bookmakers": sorted({row["snapshot"].bookmaker for row in rows}),
    }
    return render_template("odds.html", rows=rows, filters=filters, best_keys=best_keys, overrounds=overrounds, options=options)


def latest_snapshots():
    latest_ids = (
        OddsSnapshot.query.with_entities(func.max(OddsSnapshot.id))
        .group_by(OddsSnapshot.provider_event_id, OddsSnapshot.bookmaker, OddsSnapshot.market_name, OddsSnapshot.outcome_name)
        .all()
    )
    ids = [row[0] for row in latest_ids]
    return OddsSnapshot.query.filter(OddsSnapshot.id.in_(ids)).order_by(OddsSnapshot.provider_event_id, OddsSnapshot.market_name, OddsSnapshot.outcome_name).all() if ids else []


def find_best_keys(rows):
    grouped = defaultdict(list)
    for row in rows:
        s = row["snapshot"]
        grouped[(s.provider_event_id, s.market_name, s.outcome_name)].append(s)
    return {(key, max(items, key=lambda item: item.decimal_odds).bookmaker) for key, items in grouped.items()}


def compute_overrounds(rows):
    grouped = defaultdict(dict)
    for row in rows:
        s = row["snapshot"]
        grouped[(s.provider_event_id, s.market_name, s.bookmaker)][s.outcome_name] = s.decimal_odds
    result = {}
    for key, outcome_odds in grouped.items():
        if len(outcome_odds) >= 2:
            probabilities = [decimal_odds_to_implied_probability(odds) for odds in outcome_odds.values()]
            result[key] = calculate_overround(probabilities)
    return result
