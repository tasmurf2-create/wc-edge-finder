import json

import plotly
import plotly.graph_objects as go
from flask import Blueprint, render_template, request

from app.models import Event, OddsSnapshot

bp = Blueprint("movement", __name__, url_prefix="/movement")


@bp.route("/")
def movement():
    filters = {key: request.args.get(key, "") for key in ("event", "market", "outcome", "bookmaker")}
    query = OddsSnapshot.query
    if filters["event"]:
        query = query.filter_by(provider_event_id=filters["event"])
    if filters["market"]:
        query = query.filter_by(market_name=filters["market"])
    if filters["outcome"]:
        query = query.filter_by(outcome_name=filters["outcome"])
    if filters["bookmaker"]:
        query = query.filter_by(bookmaker=filters["bookmaker"])
    snapshots = query.order_by(OddsSnapshot.snapshot_time.asc()).all()
    current = snapshots[-1] if snapshots else None
    previous = snapshots[-2] if len(snapshots) > 1 else None
    chart_json = make_chart(snapshots)
    options = {
        "events": Event.query.order_by(Event.event_start_time.asc().nullslast()).all(),
        "markets": sorted({row[0] for row in OddsSnapshot.query.with_entities(OddsSnapshot.market_name).distinct()}),
        "outcomes": sorted({row[0] for row in OddsSnapshot.query.with_entities(OddsSnapshot.outcome_name).distinct()}),
        "bookmakers": sorted({row[0] for row in OddsSnapshot.query.with_entities(OddsSnapshot.bookmaker).distinct()}),
    }
    return render_template("movement.html", filters=filters, snapshots=snapshots, current=current, previous=previous, chart_json=chart_json, options=options)


def make_chart(snapshots):
    fig = go.Figure()
    if snapshots:
        fig.add_trace(go.Scatter(x=[s.snapshot_time for s in snapshots], y=[s.decimal_odds for s in snapshots], mode="lines+markers", name="Decimal odds"))
    fig.update_layout(template="plotly_white", height=420, margin={"l": 40, "r": 20, "t": 30, "b": 40}, yaxis_title="Decimal odds")
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
