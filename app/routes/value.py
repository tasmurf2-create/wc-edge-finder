from collections import defaultdict

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import func

from app.extensions import db
from app.models import Event, OddsSnapshot, WatchlistItem
from app.services.calculations import (
    calculate_expected_value,
    calculate_no_vig_probabilities,
    calculate_suggested_stake,
    decimal_odds_to_implied_probability,
    implied_probability_to_fair_odds,
    is_value_candidate,
)

bp = Blueprint("value", __name__, url_prefix="/value")


@bp.route("/", methods=["GET", "POST"])
def calculator():
    result = None
    if request.method == "POST":
        try:
            result = calculate_from_form(request.form)
        except ValueError as exc:
            flash(str(exc), "warning")
            result = None
        if request.form.get("action") == "save" and result:
            item = WatchlistItem(**result["watchlist_payload"])
            db.session.add(item)
            db.session.commit()
            flash("Watchlist item saved.", "success")
            return redirect(url_for("watchlist.list_items"))
    options = build_options()
    defaults = {
        "bankroll": current_app.config["DEFAULT_BANKROLL"],
        "max_stake": current_app.config["DEFAULT_MAX_STAKE"],
        "ev_threshold": current_app.config["DEFAULT_EV_THRESHOLD"],
        "kelly_fraction": current_app.config["DEFAULT_KELLY_FRACTION"],
    }
    return render_template("value_calculator.html", options=options, result=result, defaults=defaults)


def calculate_from_form(form):
    provider_event_id = form["event"]
    market_name = form["market"]
    outcome_name = form["outcome"]
    model_probability = parse_float(form.get("model_probability"), "Model probability")
    bankroll = parse_float(form.get("bankroll") or current_app.config["DEFAULT_BANKROLL"], "Bankroll")
    max_stake = parse_float(form.get("max_stake") or current_app.config["DEFAULT_MAX_STAKE"], "Max stake")
    threshold = parse_float(form.get("ev_threshold") or current_app.config["DEFAULT_EV_THRESHOLD"], "EV threshold")
    kelly_fraction = parse_float(form.get("kelly_fraction") or current_app.config["DEFAULT_KELLY_FRACTION"], "Kelly fraction")
    if not 0 < model_probability <= 1:
        raise ValueError("Model probability must be greater than 0 and no more than 1.")
    if bankroll < 0:
        raise ValueError("Bankroll cannot be negative.")
    if max_stake < 0:
        raise ValueError("Max stake cannot be negative.")
    if not 0 <= kelly_fraction <= 1:
        raise ValueError("Kelly fraction must be between 0 and 1.")
    best = best_price(provider_event_id, market_name, outcome_name)
    if best is None:
        flash("No stored odds matched that event, market, and outcome.", "warning")
        return None
    implied = decimal_odds_to_implied_probability(best.decimal_odds)
    ev = calculate_expected_value(model_probability, best.decimal_odds)
    suggested = calculate_suggested_stake(bankroll, best.decimal_odds, model_probability, kelly_fraction, max_stake)
    no_vig = consensus_no_vig(provider_event_id, market_name).get(outcome_name)
    event = Event.query.filter_by(provider_event_id=provider_event_id).first()
    payload = {
        "provider_event_id": provider_event_id,
        "event_name": event.event_name if event else provider_event_id,
        "market_name": market_name,
        "outcome_name": outcome_name,
        "bookmaker": best.bookmaker,
        "decimal_odds": best.decimal_odds,
        "model_probability": model_probability,
        "market_no_vig_probability": no_vig,
        "implied_probability": implied,
        "expected_value": ev,
        "suggested_stake": suggested,
        "bankroll": bankroll,
        "max_stake": max_stake,
        "kelly_fraction": kelly_fraction,
        "status": "watching",
        "notes": form.get("notes"),
    }
    return {
        "best": best,
        "implied": implied,
        "fair_odds": implied_probability_to_fair_odds(model_probability),
        "expected_value": ev,
        "suggested_stake": suggested,
        "is_candidate": is_value_candidate(ev, threshold),
        "no_vig": no_vig,
        "watchlist_payload": payload,
    }


def parse_float(value, label):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a valid number.") from None


def best_price(event_id, market, outcome):
    return (
        OddsSnapshot.query.filter_by(provider_event_id=event_id, market_name=market, outcome_name=outcome)
        .order_by(OddsSnapshot.decimal_odds.desc(), OddsSnapshot.snapshot_time.desc())
        .first()
    )


def consensus_no_vig(event_id, market):
    latest_ids = (
        OddsSnapshot.query.with_entities(func.max(OddsSnapshot.id))
        .filter_by(provider_event_id=event_id, market_name=market)
        .group_by(OddsSnapshot.bookmaker, OddsSnapshot.outcome_name)
        .all()
    )
    snapshots = OddsSnapshot.query.filter(OddsSnapshot.id.in_([row[0] for row in latest_ids])).all() if latest_ids else []
    by_bookmaker = defaultdict(dict)
    for snapshot in snapshots:
        by_bookmaker[snapshot.bookmaker][snapshot.outcome_name] = snapshot.decimal_odds
    probabilities = defaultdict(list)
    for odds_map in by_bookmaker.values():
        if len(odds_map) >= 2:
            for outcome, probability in calculate_no_vig_probabilities(odds_map).items():
                probabilities[outcome].append(probability)
    return {outcome: sum(values) / len(values) for outcome, values in probabilities.items() if values}


def build_options():
    return {
        "events": Event.query.order_by(Event.event_start_time.asc().nullslast()).all(),
        "markets": sorted({row[0] for row in OddsSnapshot.query.with_entities(OddsSnapshot.market_name).distinct()}),
        "outcomes": sorted({row[0] for row in OddsSnapshot.query.with_entities(OddsSnapshot.outcome_name).distinct()}),
    }
