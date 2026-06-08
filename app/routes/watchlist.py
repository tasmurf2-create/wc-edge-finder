from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import WatchlistItem
from app.services.export_service import export_watchlist

bp = Blueprint("watchlist", __name__, url_prefix="/watchlist")

VALID_STATUSES = {"watching", "placed", "passed", "expired"}


@bp.route("/")
def list_items():
    status = request.args.get("status", "")
    query = WatchlistItem.query
    if status:
        query = query.filter_by(status=status)
    items = query.order_by(WatchlistItem.created_at.desc()).all()
    return render_template("watchlist.html", items=items, status=status, statuses=sorted(VALID_STATUSES))


@bp.post("/<int:item_id>/update")
def update_item(item_id):
    item = WatchlistItem.query.get_or_404(item_id)
    if request.form.get("status") in VALID_STATUSES:
        item.status = request.form["status"]
    item.notes = request.form.get("notes")
    db.session.commit()
    flash("Watchlist item updated.", "success")
    return redirect(url_for("watchlist.list_items"))


@bp.post("/<int:item_id>/delete")
def delete_item(item_id):
    item = WatchlistItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash("Watchlist item deleted.", "success")
    return redirect(url_for("watchlist.list_items"))


@bp.route("/export.csv")
def export():
    return export_watchlist()
