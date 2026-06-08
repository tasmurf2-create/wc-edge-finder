from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app

from app.extensions import db
from app.models import Event, OddsSnapshot, RefreshLog
from app.services.odds_api_client import OddsAPIClient, OddsAPIError, normalise_event, normalise_odds_records


def refresh_worldcup_odds(client=None):
    started_at = datetime.now(timezone.utc)
    log = RefreshLog(started_at=started_at, status="running")
    db.session.add(log)
    db.session.commit()

    client = client or OddsAPIClient()
    summary = {
        "success": False,
        "events_fetched": 0,
        "odds_snapshots_saved": 0,
        "request_count": 0,
        "error_message": None,
    }

    try:
        sport = current_app.config["DEFAULT_SPORT"]
        raw_events = client.get_events(sport=sport)
        worldcup_events = [
            normalise_event(raw_event, sport=sport)
            for raw_event in raw_events
            if is_worldcup_event(raw_event, current_app.config["DEFAULT_COMPETITION_FILTER"])
        ]
        worldcup_events = [event for event in worldcup_events if event["provider_event_id"]]
        summary["events_fetched"] = len(worldcup_events)

        for event_data in worldcup_events:
            upsert_event(event_data)
            raw_odds = client.get_odds(
                event_data["provider_event_id"],
                bookmakers=current_app.config["DEFAULT_BOOKMAKERS"],
                markets=current_app.config["DEFAULT_MARKETS"],
            )
            records = normalise_odds_records(event_data["provider_event_id"], raw_odds)
            saved = save_odds_records(records)
            summary["odds_snapshots_saved"] += saved

        summary["success"] = True
        log.status = "success"
    except OddsAPIError as exc:
        current_app.logger.exception("Odds refresh failed")
        summary["error_message"] = str(exc)
        log.status = "failed"
        log.error_message = str(exc)
    except Exception as exc:
        current_app.logger.exception("Unexpected odds refresh error")
        summary["error_message"] = str(exc)
        log.status = "failed"
        log.error_message = str(exc)
    finally:
        summary["request_count"] = getattr(client, "request_count", 0)
        log.finished_at = datetime.now(timezone.utc)
        log.events_fetched = summary["events_fetched"]
        log.odds_snapshots_saved = summary["odds_snapshots_saved"]
        log.request_count = summary["request_count"]
        db.session.commit()

    return summary


def is_worldcup_event(raw_event, competition_filter="World Cup"):
    needle = (competition_filter or "World Cup").lower()
    haystack = " ".join(
        str(raw_event.get(key, ""))
        for key in (
            "league_name",
            "league",
            "league_slug",
            "competition_name",
            "competition",
            "tournament",
            "name",
            "event_name",
            "sport_title",
        )
    ).lower()
    return needle in haystack


def upsert_event(event_data):
    event = Event.query.filter_by(provider_event_id=event_data["provider_event_id"]).first()
    if event is None:
        event = Event(provider_event_id=event_data["provider_event_id"])
        db.session.add(event)
    for key, value in event_data.items():
        setattr(event, key, value)
    db.session.commit()
    return event


def save_odds_records(records):
    saved = 0
    for record in records:
        if is_duplicate_latest(record):
            continue
        db.session.add(OddsSnapshot(**record))
        saved += 1
    db.session.commit()
    return saved


def is_duplicate_latest(record):
    latest = (
        OddsSnapshot.query.filter_by(
            provider_event_id=record["provider_event_id"],
            bookmaker=record["bookmaker"],
            market_name=record["market_name"],
            outcome_name=record["outcome_name"],
        )
        .order_by(OddsSnapshot.snapshot_time.desc())
        .first()
    )
    if latest is None:
        return False
    return (
        latest.decimal_odds == record["decimal_odds"]
        and latest.handicap_or_line == record.get("handicap_or_line")
        and latest.point_total == record.get("point_total")
    )
