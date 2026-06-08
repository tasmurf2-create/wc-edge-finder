from datetime import datetime, timezone

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    provider_event_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    sport = db.Column(db.String(80))
    league_name = db.Column(db.String(160))
    league_slug = db.Column(db.String(160))
    competition_name = db.Column(db.String(160))
    home_team = db.Column(db.String(160))
    away_team = db.Column(db.String(160))
    event_name = db.Column(db.String(255))
    event_start_time = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(80), default="scheduled")
    raw_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OddsSnapshot(db.Model):
    __tablename__ = "odds_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    provider_event_id = db.Column(db.String(128), nullable=False, index=True)
    snapshot_time = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    bookmaker = db.Column(db.String(120), index=True)
    market_name = db.Column(db.String(120), index=True)
    outcome_name = db.Column(db.String(160), index=True)
    decimal_odds = db.Column(db.Float)
    handicap_or_line = db.Column(db.String(80))
    point_total = db.Column(db.Float)
    raw_market_name = db.Column(db.String(160))
    raw_outcome_name = db.Column(db.String(160))
    raw_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)


class UserProbability(db.Model):
    __tablename__ = "user_probabilities"

    id = db.Column(db.Integer, primary_key=True)
    provider_event_id = db.Column(db.String(128), nullable=False, index=True)
    market_name = db.Column(db.String(120), nullable=False)
    outcome_name = db.Column(db.String(160), nullable=False)
    user_probability = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WatchlistItem(db.Model):
    __tablename__ = "watchlist_items"

    id = db.Column(db.Integer, primary_key=True)
    provider_event_id = db.Column(db.String(128), nullable=False, index=True)
    event_name = db.Column(db.String(255))
    market_name = db.Column(db.String(120))
    outcome_name = db.Column(db.String(160))
    bookmaker = db.Column(db.String(120))
    decimal_odds = db.Column(db.Float)
    model_probability = db.Column(db.Float)
    market_no_vig_probability = db.Column(db.Float)
    implied_probability = db.Column(db.Float)
    expected_value = db.Column(db.Float)
    suggested_stake = db.Column(db.Float)
    bankroll = db.Column(db.Float)
    max_stake = db.Column(db.Float)
    kelly_fraction = db.Column(db.Float)
    status = db.Column(db.String(30), default="watching")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RefreshLog(db.Model):
    __tablename__ = "refresh_logs"

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    finished_at = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(40), default="running")
    events_fetched = db.Column(db.Integer, default=0)
    odds_snapshots_saved = db.Column(db.Integer, default=0)
    request_count = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorldCupTeam(db.Model):
    __tablename__ = "worldcup_teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    fifa_code = db.Column(db.String(8))
    group_name = db.Column(db.String(20))
    country_average_temp_c = db.Column(db.Float)
    country_average_altitude_m = db.Column(db.Float)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorldCupVenue(db.Model):
    __tablename__ = "worldcup_venues"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    city = db.Column(db.String(120))
    country = db.Column(db.String(80))
    timezone = db.Column(db.String(80))
    altitude_m = db.Column(db.Float)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorldCupFixture(db.Model):
    __tablename__ = "worldcup_fixtures"

    id = db.Column(db.Integer, primary_key=True)
    match_number = db.Column(db.Integer, unique=True, nullable=False)
    stage = db.Column(db.String(80))
    group_name = db.Column(db.String(20))
    home_team = db.Column(db.String(120))
    away_team = db.Column(db.String(120))
    venue_name = db.Column(db.String(160))
    kickoff_utc = db.Column(db.DateTime(timezone=True))
    source_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SquadPlayer(db.Model):
    __tablename__ = "squad_players"

    id = db.Column(db.Integer, primary_key=True)
    team_name = db.Column(db.String(120), index=True, nullable=False)
    shirt_number = db.Column(db.Integer)
    position = db.Column(db.String(20))
    name_on_shirt = db.Column(db.String(120), nullable=False)
    club = db.Column(db.String(160))
    source_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Country(db.Model):
    __tablename__ = "countries"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    fifa_code = db.Column(db.String(8), unique=True)
    average_temp_c = db.Column(db.Float)
    average_altitude_m = db.Column(db.Float)
    climate_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    teams = db.relationship("Team", back_populates="country")


class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), nullable=False, index=True)
    display_name = db.Column(db.String(120), unique=True, nullable=False)
    group_name = db.Column(db.String(20), index=True)
    confederation = db.Column(db.String(40))
    fifa_ranking = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    country = db.relationship("Country", back_populates="teams")
    squad_memberships = db.relationship("SquadMembership", back_populates="team")


class Venue(db.Model):
    __tablename__ = "venues"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    city = db.Column(db.String(120))
    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), index=True)
    timezone = db.Column(db.String(80))
    altitude_m = db.Column(db.Float)
    roof_type = db.Column(db.String(80))
    pitch_type = db.Column(db.String(80))
    capacity = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    country = db.relationship("Country")
    fixtures = db.relationship("Fixture", back_populates="venue")


class Fixture(db.Model):
    __tablename__ = "fixtures"

    id = db.Column(db.Integer, primary_key=True)
    match_number = db.Column(db.Integer, unique=True, nullable=False)
    stage = db.Column(db.String(80), index=True)
    group_name = db.Column(db.String(20), index=True)
    home_team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), index=True)
    away_team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), index=True)
    venue_id = db.Column(db.Integer, db.ForeignKey("venues.id"), index=True)
    kickoff_utc = db.Column(db.DateTime(timezone=True), index=True)
    status = db.Column(db.String(40), default="scheduled")
    source_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    home_team = db.relationship("Team", foreign_keys=[home_team_id])
    away_team = db.relationship("Team", foreign_keys=[away_team_id])
    venue = db.relationship("Venue", back_populates="fixtures")
    fixture_teams = db.relationship("FixtureTeam", back_populates="fixture")
    weather_snapshots = db.relationship("WeatherSnapshot", back_populates="fixture")


class FixtureTeam(db.Model):
    __tablename__ = "fixture_teams"

    id = db.Column(db.Integer, primary_key=True)
    fixture_id = db.Column(db.Integer, db.ForeignKey("fixtures.id"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True)
    home_away = db.Column(db.String(10))
    score = db.Column(db.Integer)
    result = db.Column(db.String(20))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    fixture = db.relationship("Fixture", back_populates="fixture_teams")
    team = db.relationship("Team")


class Player(db.Model):
    __tablename__ = "players"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False, index=True)
    date_of_birth = db.Column(db.Date)
    primary_position = db.Column(db.String(20))
    club = db.Column(db.String(160))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    squad_memberships = db.relationship("SquadMembership", back_populates="player")


class SquadMembership(db.Model):
    __tablename__ = "squad_memberships"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False, index=True)
    tournament_year = db.Column(db.Integer, default=2026, index=True)
    shirt_number = db.Column(db.Integer)
    position = db.Column(db.String(20))
    status = db.Column(db.String(40), default="squad")
    source_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    team = db.relationship("Team", back_populates="squad_memberships")
    player = db.relationship("Player", back_populates="squad_memberships")


class WeatherSnapshot(db.Model):
    __tablename__ = "weather_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    fixture_id = db.Column(db.Integer, db.ForeignKey("fixtures.id"), nullable=False, index=True)
    captured_at = db.Column(db.DateTime(timezone=True), default=utcnow, index=True)
    forecast_for = db.Column(db.DateTime(timezone=True), index=True)
    temp_c = db.Column(db.Float)
    humidity = db.Column(db.Float)
    wind_kph = db.Column(db.Float)
    precipitation_mm = db.Column(db.Float)
    source_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    fixture = db.relationship("Fixture", back_populates="weather_snapshots")


class Bookmaker(db.Model):
    __tablename__ = "bookmakers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    display_name = db.Column(db.String(120))
    country_id = db.Column(db.Integer, db.ForeignKey("countries.id"), index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Market(db.Model):
    __tablename__ = "markets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(80))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)
