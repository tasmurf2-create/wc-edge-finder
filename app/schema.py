from sqlalchemy import inspect, text

from app.extensions import db


def ensure_sqlite_schema():
    if not str(db.engine.url).startswith("sqlite"):
        return
    inspector = inspect(db.engine)
    with db.engine.begin() as connection:
        add_column_if_missing(inspector, connection, "events", "fixture_id", "INTEGER")
        add_column_if_missing(inspector, connection, "odds_snapshots", "fixture_id", "INTEGER")
        add_column_if_missing(inspector, connection, "odds_snapshots", "bookmaker_id", "INTEGER")
        add_column_if_missing(inspector, connection, "odds_snapshots", "market_id", "INTEGER")


def add_column_if_missing(inspector, connection, table_name, column_name, column_type):
    if not inspector.has_table(table_name):
        return
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name not in existing_columns:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
