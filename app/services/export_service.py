from __future__ import annotations

import pandas as pd
from flask import Response

from app.models import Event, OddsSnapshot, WatchlistItem


def dataframe_response(df, filename):
    csv_data = df.to_csv(index=False)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def export_latest_odds():
    rows = latest_odds_rows()
    return dataframe_response(pd.DataFrame(rows), "latest_odds.csv")


def export_movement():
    query = OddsSnapshot.query.order_by(OddsSnapshot.provider_event_id, OddsSnapshot.market_name, OddsSnapshot.outcome_name, OddsSnapshot.snapshot_time)
    rows = [snapshot_to_dict(row) for row in query]
    return dataframe_response(pd.DataFrame(rows), "odds_movement.csv")


def export_watchlist():
    rows = [
        {
            "event": item.event_name,
            "market": item.market_name,
            "outcome": item.outcome_name,
            "bookmaker": item.bookmaker,
            "decimal_odds": item.decimal_odds,
            "model_probability": item.model_probability,
            "expected_value": item.expected_value,
            "suggested_stake": item.suggested_stake,
            "status": item.status,
            "notes": item.notes,
        }
        for item in WatchlistItem.query.order_by(WatchlistItem.created_at.desc())
    ]
    return dataframe_response(pd.DataFrame(rows), "watchlist.csv")


def export_value_candidates():
    rows = [
        {
            "event": item.event_name,
            "market": item.market_name,
            "outcome": item.outcome_name,
            "bookmaker": item.bookmaker,
            "decimal_odds": item.decimal_odds,
            "expected_value": item.expected_value,
            "suggested_stake": item.suggested_stake,
            "status": item.status,
        }
        for item in WatchlistItem.query.filter(WatchlistItem.expected_value > 0).order_by(WatchlistItem.expected_value.desc())
    ]
    return dataframe_response(pd.DataFrame(rows), "value_candidates.csv")


def latest_odds_rows():
    latest_ids = (
        OddsSnapshot.query.with_entities(
            OddsSnapshot.provider_event_id,
            OddsSnapshot.bookmaker,
            OddsSnapshot.market_name,
            OddsSnapshot.outcome_name,
            db_max_snapshot_id(),
        )
        .group_by(OddsSnapshot.provider_event_id, OddsSnapshot.bookmaker, OddsSnapshot.market_name, OddsSnapshot.outcome_name)
        .all()
    )
    snapshots = OddsSnapshot.query.filter(OddsSnapshot.id.in_([row[-1] for row in latest_ids])).all() if latest_ids else []
    events = {event.provider_event_id: event for event in Event.query.all()}
    return [snapshot_to_dict(snapshot, events.get(snapshot.provider_event_id)) for snapshot in snapshots]


def db_max_snapshot_id():
    from sqlalchemy import func

    return func.max(OddsSnapshot.id).label("latest_id")


def snapshot_to_dict(snapshot, event=None):
    return {
        "event": event.event_name if event else snapshot.provider_event_id,
        "competition": event.competition_name if event else None,
        "bookmaker": snapshot.bookmaker,
        "market": snapshot.market_name,
        "outcome": snapshot.outcome_name,
        "decimal_odds": snapshot.decimal_odds,
        "snapshot_time": snapshot.snapshot_time,
    }
