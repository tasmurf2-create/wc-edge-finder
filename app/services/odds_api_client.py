from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import current_app


class OddsAPIError(RuntimeError):
    pass


class OddsAPIClient:
    def __init__(self, api_key=None, base_url=None, timeout=20):
        self.api_key = api_key if api_key is not None else current_app.config.get("ODDS_API_KEY", "")
        self.base_url = (base_url or current_app.config.get("ODDS_API_BASE_URL", "")).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.request_count = 0

    def get_events(self, sport="football", limit=None):
        params = {"sport": sport}
        if limit:
            params["limit"] = limit
        data = self._request("/v3/events", params=params)
        return self._as_list(data, keys=("events", "data", "results"))

    def get_odds(self, event_id, bookmakers=None, markets=None):
        params = {"event_id": event_id}
        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)
        if markets:
            params["markets"] = ",".join(markets)
        data = self._request("/v3/odds", params=params)
        return self._as_list(data, keys=("odds", "data", "results", "markets"))

    def test_connection(self):
        if not self.api_key:
            return {"success": False, "message": "No API key configured."}
        try:
            self.get_events(limit=1)
            return {"success": True, "message": "Connection succeeded."}
        except OddsAPIError as exc:
            return {"success": False, "message": str(exc)}

    def _request(self, path, params=None):
        if not self.api_key:
            raise OddsAPIError("No Odds-API.io key configured. Add ODDS_API_KEY to .env.")
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.api_key}"}
        params = dict(params or {})
        params.setdefault("apiKey", self.api_key)
        self.request_count += 1

        try:
            response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise OddsAPIError(f"API request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise OddsAPIError("Odds-API.io authentication failed. Check your API key.")
        if response.status_code == 429:
            raise OddsAPIError("Odds-API.io rate limit reached.")
        if 500 <= response.status_code:
            raise OddsAPIError(f"Odds-API.io server error: HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise OddsAPIError(f"Odds-API.io request failed: HTTP {response.status_code}.")

        try:
            data = response.json()
        except ValueError as exc:
            raise OddsAPIError("Odds-API.io returned invalid JSON.") from exc

        self._save_raw_response(path, data)
        return data

    def _save_raw_response(self, path, data):
        if not current_app.config.get("DEBUG_RAW_RESPONSES"):
            return
        directory: Path = current_app.config["RAW_RESPONSE_DIR"]
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        safe_path = path.strip("/").replace("/", "_")
        with (directory / f"{stamp}_{safe_path}.json").open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, default=str)

    @staticmethod
    def _as_list(data, keys):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return [data]
        return []


MARKET_ALIASES = {
    "ml": "Match Winner / 1X2",
    "moneyline": "Match Winner / 1X2",
    "match winner": "Match Winner / 1X2",
    "1x2": "Match Winner / 1X2",
    "h2h": "Match Winner / 1X2",
    "totals": "Over/Under Goals",
    "total": "Over/Under Goals",
    "over/under": "Over/Under Goals",
    "over under": "Over/Under Goals",
    "btts": "Both Teams To Score",
    "both teams to score": "Both Teams To Score",
    "draw no bet": "Draw No Bet",
    "dnb": "Draw No Bet",
    "double chance": "Double Chance",
    "spreads": "Asian Handicap",
    "asian handicap": "Asian Handicap",
    "correct score": "Correct Score",
    "outrights": "Outright Winner",
    "outright": "Outright Winner",
}


def normalise_market_name(raw_name):
    if raw_name is None:
        return "Unknown"
    key = str(raw_name).strip().lower().replace("_", " ")
    return MARKET_ALIASES.get(key, str(raw_name).strip())


def normalise_decimal_odds(value):
    if value is None:
        return None
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    return odds if odds > 1 else None


def extract_event_id(raw):
    for key in ("id", "event_id", "provider_event_id", "fixture_id"):
        if raw.get(key):
            return str(raw[key])
    return None


def normalise_event(raw, sport="football"):
    home = raw.get("home_team") or raw.get("home") or raw.get("team_home")
    away = raw.get("away_team") or raw.get("away") or raw.get("team_away")
    name = raw.get("event_name") or raw.get("name") or raw.get("title")
    if not name and home and away:
        name = f"{home} vs {away}"
    return {
        "provider_event_id": extract_event_id(raw),
        "sport": raw.get("sport") or sport,
        "league_name": raw.get("league_name") or raw.get("league") or raw.get("competition"),
        "league_slug": raw.get("league_slug") or raw.get("league_key") or raw.get("slug"),
        "competition_name": raw.get("competition_name") or raw.get("competition") or raw.get("tournament"),
        "home_team": home,
        "away_team": away,
        "event_name": name or "Unnamed event",
        "event_start_time": parse_datetime(raw.get("event_start_time") or raw.get("start_time") or raw.get("commence_time")),
        "status": raw.get("status") or "scheduled",
        "raw_json": raw,
    }


def normalise_odds_records(provider_event_id, payload):
    records = []
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        bookmakers = item.get("bookmakers") if isinstance(item, dict) else None
        if isinstance(bookmakers, list):
            for bookmaker in bookmakers:
                records.extend(_records_from_bookmaker(provider_event_id, bookmaker))
        elif isinstance(item, dict):
            records.extend(_records_from_bookmaker(provider_event_id, item))
    return records


def _records_from_bookmaker(provider_event_id, bookmaker):
    bookmaker_name = bookmaker.get("bookmaker") or bookmaker.get("bookmaker_name") or bookmaker.get("title") or bookmaker.get("key")
    markets = bookmaker.get("markets") or bookmaker.get("odds") or []
    if isinstance(markets, dict):
        markets = [{"name": key, "outcomes": value} for key, value in markets.items()]
    records = []
    for market in markets:
        raw_market = market.get("name") or market.get("key") or market.get("market_name")
        outcomes = market.get("outcomes") or market.get("prices") or market.get("runners") or []
        if isinstance(outcomes, dict):
            outcomes = [{"name": key, "odds": value} for key, value in outcomes.items()]
        for outcome in outcomes:
            odds = normalise_decimal_odds(outcome.get("decimal_odds") or outcome.get("odds") or outcome.get("price"))
            if odds is None:
                continue
            records.append(
                {
                    "provider_event_id": provider_event_id,
                    "bookmaker": bookmaker_name or "Unknown",
                    "market_name": normalise_market_name(raw_market),
                    "outcome_name": outcome.get("name") or outcome.get("outcome") or outcome.get("selection") or "Unknown",
                    "decimal_odds": odds,
                    "handicap_or_line": outcome.get("handicap") or outcome.get("line"),
                    "point_total": _float_or_none(outcome.get("point") or outcome.get("total")),
                    "raw_market_name": raw_market,
                    "raw_outcome_name": outcome.get("name") or outcome.get("outcome"),
                    "raw_json": outcome,
                }
            )
    return records


def _float_or_none(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
