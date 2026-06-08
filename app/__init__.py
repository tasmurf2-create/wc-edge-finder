import logging
from pathlib import Path

from flask import Flask, render_template

from app.config import Config
from app.extensions import db


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config["LOG_DIR"].mkdir(parents=True, exist_ok=True)
    app.config["RAW_RESPONSE_DIR"].mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    register_logging(app)
    register_blueprints(app)
    register_error_handlers(app)

    with app.app_context():
        db.create_all()

    return app


def register_logging(app):
    log_path = app.config["LOG_DIR"] / "app.log"
    handler = logging.FileHandler(log_path)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    app.logger.addHandler(handler)


def register_blueprints(app):
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.events import bp as events_bp
    from app.routes.movement import bp as movement_bp
    from app.routes.odds import bp as odds_bp
    from app.routes.settings import bp as settings_bp
    from app.routes.static_data import bp as static_data_bp
    from app.routes.value import bp as value_bp
    from app.routes.watchlist import bp as watchlist_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(odds_bp)
    app.register_blueprint(movement_bp)
    app.register_blueprint(value_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(static_data_bp)


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", title="Not found", message="That page was not found."), 404

    @app.errorhandler(500)
    def server_error(error):
        app.logger.exception("Unhandled server error: %s", error)
        return render_template("error.html", title="Server error", message="Something went wrong locally."), 500
