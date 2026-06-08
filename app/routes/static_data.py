import csv
from io import TextIOWrapper
from zoneinfo import ZoneInfo

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.models import Country, Fixture, Player, SquadMembership, Team, Venue
from app.services.static_data_seed import import_squad_rows, seed_static_worldcup_data

bp = Blueprint("static_data", __name__, url_prefix="/world-cup")


@bp.route("/")
def index():
    fixtures = Fixture.query.order_by(Fixture.match_number).all()
    return render_template(
        "static_data.html",
        countries=Country.query.order_by(Country.name).all(),
        teams=Team.query.join(Country).order_by(Team.group_name, Team.display_name).all(),
        venues=Venue.query.order_by(Venue.city).all(),
        fixtures=fixtures,
        squad_memberships=(
            SquadMembership.query.join(Team)
            .join(Player)
            .order_by(Team.display_name, SquadMembership.shirt_number, Player.full_name)
            .all()
        ),
        local_time=local_time,
    )


@bp.post("/seed")
def seed():
    summary = seed_static_worldcup_data()
    flash(
        f"Seeded normalized data: {summary['countries']} countries, {summary['teams']} teams, "
        f"{summary['venues']} venues, {summary['fixtures']} fixtures.",
        "success",
    )
    return redirect(url_for("static_data.index"))


@bp.post("/squads/import")
def import_squads():
    upload = request.files.get("squad_csv")
    if not upload:
        flash("Choose a CSV file first.", "warning")
        return redirect(url_for("static_data.index"))
    rows = csv.DictReader(TextIOWrapper(upload.stream, encoding="utf-8-sig"))
    count = import_squad_rows(rows)
    flash(f"Imported {count} squad player rows.", "success")
    return redirect(url_for("static_data.index"))


def local_time(fixture):
    if not fixture.kickoff_utc or not fixture.venue or not fixture.venue.timezone:
        return ""
    return fixture.kickoff_utc.astimezone(ZoneInfo(fixture.venue.timezone)).strftime("%Y-%m-%d %H:%M")
