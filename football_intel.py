#!/usr/bin/env python3
"""
Football intelligence layer — WC 2026 match analysis.

Two layers:
  1. weather.py logic — Open-Meteo (free, no key) real weather forecast per venue
  2. Claude analyst — form, injuries, tactics, conditions → structured recommendation

Results cached to disk so Claude is only called once per match per 12h window.
"""
import os
import json
import time
import hashlib
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import anthropic

CACHE_FILE      = Path("intel_cache.json")
TEAM_DATA_FILE  = Path("team_data.json")
CACHE_TTL       = 43200   # 12 hours — match analysis
TEAM_DATA_TTL   = 86400   # 24 hours — team form/injury snapshot
MODEL           = "claude-sonnet-4-6"

_client = None

def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        _client = anthropic.Anthropic(api_key=key)
    return _client


# ---------------------------------------------------------------------------
# WC 2026 venue registry
# lat, lon, altitude_m, timezone, city_name, notes
# ---------------------------------------------------------------------------
WC_VENUES = {
    "dallas":       (32.748, -97.093,   169,  "America/Chicago",       "Arlington/Dallas TX",    "AT&T Stadium — extreme summer heat, inland Texas"),
    "houston":      (29.685, -95.411,    15,  "America/Chicago",       "Houston TX",             "NRG Stadium — tropical humidity, very hot"),
    "miami":        (25.958, -80.239,     4,  "America/New_York",      "Miami FL",               "Hard Rock Stadium — heat and high humidity"),
    "kansas_city":  (39.049, -94.484,   270,  "America/Chicago",       "Kansas City MO",         "Arrowhead Stadium — hot, exposed, midwest heat"),
    "philadelphia": (39.901, -75.168,    9,  "America/New_York",      "Philadelphia PA",         "Lincoln Financial Field — warm, humid summers"),
    "new_york":     (40.814, -74.074,    7,  "America/New_York",      "New York/NJ",            "MetLife Stadium — moderate, Final venue"),
    "boston":       (42.091, -71.264,    7,  "America/New_York",      "Boston MA",              "Gillette Stadium — cooler New England climate"),
    "seattle":      (47.596, -122.332,   4,  "America/Los_Angeles",   "Seattle WA",             "Lumen Field — mild Pacific Northwest, often cloudy"),
    "los_angeles":  (33.954, -118.339,  27,  "America/Los_Angeles",   "Los Angeles CA",         "SoFi Stadium — mild coastal climate, indoor retractable roof"),
    "san_francisco":(37.403, -121.970,  17,  "America/Los_Angeles",   "San Francisco/Santa Clara CA","Levi's Stadium — mild bay area, can be warm"),
    "toronto":      (43.633, -79.419,   76,  "America/Toronto",       "Toronto ON, Canada",     "BMO Field — moderate, Great Lakes climate"),
    "vancouver":    (49.276, -123.112,   4,  "America/Vancouver",     "Vancouver BC, Canada",   "BC Place — mild, indoor stadium"),
    "mexico_city":  (19.303, -99.151, 2240,  "America/Mexico_City",   "Mexico City, Mexico",    "Estadio Azteca — HIGH ALTITUDE 2240m, significant factor for stamina"),
    "guadalajara":  (20.688, -103.467,1560,  "America/Mexico_City",   "Guadalajara, Mexico",    "Estadio Akron — altitude 1560m, warm daytime"),
    "monterrey":    (25.670, -100.244, 538,  "America/Monterrey",     "Monterrey, Mexico",      "Estadio BBVA — very hot in June, can exceed 38°C"),
}

# Best-effort group stage venue assignments based on confirmed WC 2026 schedule.
# frozenset of (home, away) lower-case → venue key
# Covers the fixtures most likely to have heat/altitude relevance.
MATCH_VENUES = {
    # Mexico host city — Azteca
    frozenset(["mexico", "south africa"]):        "mexico_city",
    frozenset(["mexico", "south korea"]):         "dallas",
    frozenset(["mexico", "czech republic"]):      "dallas",
    # USA host city
    frozenset(["united states", "paraguay"]):     "kansas_city",
    frozenset(["united states", "australia"]):    "los_angeles",
    frozenset(["united states", "turkey"]):       "los_angeles",
    frozenset(["turkey", "usa"]):                 "los_angeles",
    frozenset(["usa", "australia"]):              "los_angeles",
    frozenset(["usa", "paraguay"]):               "kansas_city",
    # Canada
    frozenset(["canada", "bosnia & herzegovina"]):  "toronto",
    frozenset(["canada", "qatar"]):               "toronto",
    frozenset(["switzerland", "canada"]):         "toronto",
    # Known hot-venue matches
    frozenset(["brazil", "morocco"]):             "dallas",
    frozenset(["brazil", "haiti"]):               "dallas",
    frozenset(["scotland", "brazil"]):            "houston",
    frozenset(["scotland", "morocco"]):           "houston",
    frozenset(["morocco", "haiti"]):              "houston",
    frozenset(["spain", "cape verde"]):           "miami",
    frozenset(["spain", "saudi arabia"]):         "miami",
    frozenset(["uruguay", "spain"]):              "miami",
    frozenset(["uruguay", "cape verde"]):         "miami",
    frozenset(["new zealand", "egypt"]):          "miami",
    frozenset(["new zealand", "belgium"]):        "miami",
    frozenset(["egypt", "iran"]):                 "miami",
    frozenset(["france", "senegal"]):             "philadelphia",
    frozenset(["france", "iraq"]):                "philadelphia",
    frozenset(["norway", "senegal"]):             "philadelphia",
    frozenset(["norway", "france"]):              "philadelphia",
    frozenset(["senegal", "iraq"]):               "philadelphia",
    frozenset(["argentina", "algeria"]):          "san_francisco",
    frozenset(["argentina", "austria"]):          "san_francisco",
    frozenset(["jordan", "algeria"]):             "san_francisco",
    frozenset(["jordan", "argentina"]):           "san_francisco",
    frozenset(["algeria", "austria"]):            "san_francisco",
    frozenset(["germany", "curacao"]):            "boston",
    frozenset(["germany", "ivory coast"]):        "boston",
    frozenset(["ecuador", "germany"]):            "boston",
    frozenset(["ecuador", "curacao"]):            "seattle",
    frozenset(["ivory coast", "ecuador"]):        "boston",
    frozenset(["curacao", "ivory coast"]):        "seattle",
    frozenset(["netherlands", "japan"]):          "new_york",
    frozenset(["netherlands", "sweden"]):         "new_york",
    frozenset(["tunisia", "netherlands"]):        "new_york",
    frozenset(["japan", "sweden"]):               "new_york",
    frozenset(["tunisia", "japan"]):              "new_york",
    frozenset(["sweden", "tunisia"]):             "new_york",
    frozenset(["england", "croatia"]):            "los_angeles",
    frozenset(["england", "ghana"]):              "los_angeles",
    frozenset(["panama", "england"]):             "los_angeles",
    frozenset(["panama", "croatia"]):             "los_angeles",
    frozenset(["croatia", "ghana"]):              "los_angeles",
    frozenset(["ghana", "panama"]):               "los_angeles",
    frozenset(["belgium", "egypt"]):              "kansas_city",
    frozenset(["belgium", "iran"]):               "kansas_city",
    frozenset(["new zealand", "belgium"]):        "kansas_city",
    frozenset(["saudi arabia", "uruguay"]):       "dallas",
    frozenset(["iran", "new zealand"]):           "kansas_city",
    frozenset(["portugal", "dr congo"]):          "guadalajara",
    frozenset(["portugal", "uzbekistan"]):        "guadalajara",
    frozenset(["colombia", "portugal"]):          "guadalajara",
    frozenset(["colombia", "dr congo"]):          "guadalajara",
    frozenset(["dr congo", "uzbekistan"]):        "guadalajara",
    frozenset(["uzbekistan", "colombia"]):        "guadalajara",
    frozenset(["qatar", "switzerland"]):          "monterrey",
    frozenset(["south korea", "czech republic"]): "monterrey",
    frozenset(["south africa", "south korea"]):   "monterrey",
    frozenset(["czech republic", "south africa"]):"monterrey",
    frozenset(["bosnia & herzegovina", "qatar"]): "monterrey",
    frozenset(["switzerland", "bosnia & herzegovina"]): "monterrey",
    frozenset(["iraq", "norway"]):                "toronto",
    frozenset(["haiti", "scotland"]):             "vancouver",
    frozenset(["australia", "turkey"]):           "vancouver",
    frozenset(["paraguay", "australia"]):         "vancouver",
    frozenset(["turkey", "paraguay"]):            "vancouver",
    frozenset(["austria", "jordan"]):             "seattle",
    frozenset(["panama", "croatia"]):             "los_angeles",
}


def _venue_for_match(home, away):
    """Look up venue for a match, return venue_key or None."""
    key = frozenset([home.lower(), away.lower()])
    return MATCH_VENUES.get(key)


# ---------------------------------------------------------------------------
# Open-Meteo weather fetch (free, no API key)
# ---------------------------------------------------------------------------

# June climate normals per venue (avg high °C, avg humidity %, typical conditions)
# Source: historical climate data for June — more reliable than a forecast for future dates
JUNE_CLIMATE = {
    "dallas":        {"avg_high_c": 35, "feels_like_c": 39, "humidity_pct": 58, "notes": "Extreme heat. Afternoon games brutal. Evening games still 30°C+. Thunderstorm risk."},
    "houston":       {"avg_high_c": 34, "feels_like_c": 41, "humidity_pct": 72, "notes": "Tropical humidity makes 34°C feel like 41°C. One of the most demanding venues."},
    "miami":         {"avg_high_c": 31, "feels_like_c": 37, "humidity_pct": 76, "notes": "High humidity, afternoon heat, frequent storms. Evening games more manageable."},
    "kansas_city":   {"avg_high_c": 31, "feels_like_c": 34, "humidity_pct": 63, "notes": "Hot and open. Exposed stadium, no shade. Midday heat significant."},
    "philadelphia":  {"avg_high_c": 28, "feels_like_c": 30, "humidity_pct": 60, "notes": "Warm but manageable. East coast humidity present. Evening games comfortable."},
    "new_york":      {"avg_high_c": 27, "feels_like_c": 28, "humidity_pct": 60, "notes": "Warm, moderate humidity. Final venue — good playing conditions."},
    "boston":        {"avg_high_c": 25, "feels_like_c": 26, "humidity_pct": 60, "notes": "Mild New England summer. Comfortable playing conditions."},
    "seattle":       {"avg_high_c": 21, "feels_like_c": 21, "humidity_pct": 55, "notes": "Mild Pacific Northwest. Rarely hot. Cool evening temperatures — best conditions in USA."},
    "los_angeles":   {"avg_high_c": 24, "feels_like_c": 24, "humidity_pct": 60, "notes": "SoFi has a roof — weather-controlled. Mild LA coastal climate regardless."},
    "san_francisco": {"avg_high_c": 18, "feels_like_c": 17, "humidity_pct": 65, "notes": "Famous June fog. Cool afternoons. Can be cold evenings — very different to rest of tournament."},
    "toronto":       {"avg_high_c": 25, "feels_like_c": 26, "humidity_pct": 62, "notes": "Warm Canadian summer. Manageable conditions."},
    "vancouver":     {"avg_high_c": 20, "feels_like_c": 19, "humidity_pct": 65, "notes": "BC Place is indoor dome — controlled conditions. Cool and comfortable."},
    "mexico_city":   {"avg_high_c": 23, "feels_like_c": 20, "humidity_pct": 45, "notes": "ALTITUDE 2240m — the dominant factor. Stamina severely impacted for sea-level teams. Surprisingly cool temperatures but thin air is the issue."},
    "guadalajara":   {"avg_high_c": 28, "feels_like_c": 27, "humidity_pct": 40, "notes": "ALTITUDE 1560m — significant but less extreme than Mexico City. Warm and dry. Double impact: altitude + afternoon heat."},
    "monterrey":     {"avg_high_c": 37, "feels_like_c": 41, "humidity_pct": 50, "notes": "Hottest WC venue. June temperatures regularly exceed 38°C. Brutal for European sides. Evening games still 32°C+."},
}


def _local_kickoff(iso_datetime, tz):
    """Convert UTC kickoff to local time string."""
    try:
        import zoneinfo
        dt       = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
        local_tz = zoneinfo.ZoneInfo(tz)
        local_dt = dt.astimezone(local_tz)
        return local_dt.strftime("%H:%M %Z (%A)")
    except Exception:
        return "unknown"


def _fetch_weather(lat, lon, iso_datetime, tz):
    """Stub — Open-Meteo only forecasts ~16 days ahead; WC 2026 is future.
    Climate normals are used instead via JUNE_CLIMATE lookup."""
    return None


def get_conditions_for_match(home, away, commence):
    """Return conditions dict for a match using climate normals."""
    vk = _venue_for_match(home, away)
    if not vk:
        return None, None
    lat, lon, alt, tz, city, venue_notes = WC_VENUES[vk]
    climate = JUNE_CLIMATE.get(vk, {})
    local_ko = _local_kickoff(commence, tz)
    return {
        "city":          city,
        "altitude_m":    alt,
        "local_kickoff": local_ko,
        "avg_high_c":    climate.get("avg_high_c"),
        "feels_like_c":  climate.get("feels_like_c"),
        "humidity_pct":  climate.get("humidity_pct"),
        "notes":         climate.get("notes", venue_notes),
    }, vk


def _fmt_conditions(cond, vk):
    if not cond:
        return "Venue not confirmed in schedule — reason from your knowledge about likely host city."
    alt_note = f" *** ALTITUDE {cond['altitude_m']}m ***" if cond["altitude_m"] > 800 else ""
    return (
        f"Venue: {cond['city']}{alt_note}\n"
        f"Local kick-off: {cond['local_kickoff']}\n"
        f"June avg high: {cond['avg_high_c']}°C  |  Feels like: {cond['feels_like_c']}°C  |  Humidity: {cond['humidity_pct']}%\n"
        f"Assessment: {cond['notes']}"
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _cache_key(home, away):
    return hashlib.md5(f"{home.lower()}|{away.lower()}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Team data cache — web search once per team per day, store to disk
# ---------------------------------------------------------------------------

def _load_team_data():
    if TEAM_DATA_FILE.exists():
        try:
            return json.loads(TEAM_DATA_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_team_data(data):
    TEAM_DATA_FILE.write_text(json.dumps(data, indent=2))


def _team_key(team):
    return team.lower().strip()


def fetch_team_snapshot(team, force=False):
    """
    Fetch a team's current form, injuries and squad news via web search.
    Cached for 24h. Returns a plain-text summary string.
    """
    key   = _team_key(team)
    store = _load_team_data()
    entry = store.get(key)

    if not force and entry and (time.time() - entry.get("fetched_at", 0)) < TEAM_DATA_TTL:
        return entry["snapshot"]

    try:
        client = _get_client()
        resp = client.messages.create(
            model      = MODEL,
            max_tokens = 400,
            tools      = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages   = [{
                "role": "user",
                "content": (
                    f"Search for the latest news on the {team} national football team "
                    f"for the 2026 FIFA World Cup. In 4-6 bullet points cover: "
                    f"(1) manager and current squad form/results in 2026, "
                    f"(2) key players to watch, "
                    f"(3) any confirmed injuries or suspensions, "
                    f"(4) tactical setup/style. "
                    f"Be factual and concise. No waffle."
                )
            }],
        )
        # Extract text from mixed content blocks
        snapshot = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                snapshot = block.text.strip()
                break

        if snapshot:
            store[key] = {"snapshot": snapshot, "fetched_at": int(time.time()), "team": team}
            _save_team_data(store)
            print(f"[team] fetched snapshot for {team} ({len(snapshot)} chars)")
            return snapshot
    except Exception as e:
        print(f"[team] web search failed for {team}: {e}")

    # Fallback: return cached even if stale
    return entry["snapshot"] if entry else ""


def get_team_snapshots(home, away, force=False):
    """Return (home_snapshot, away_snapshot) strings, fetching if needed."""
    h = fetch_team_snapshot(home, force=force)
    a = fetch_team_snapshot(away, force=force)
    return h, a


def get_team_snapshots_cached_only(home, away):
    """Return snapshots from cache only — never triggers a web search."""
    store = _load_team_data()
    h = store.get(_team_key(home), {}).get("snapshot", "")
    a = store.get(_team_key(away), {}).get("snapshot", "")
    return h, a


def refresh_teams_for_matches(match_list, force=False):
    """Pre-fetch team snapshots for all teams in match_list. Call once per day."""
    teams = set()
    for m in match_list:
        teams.add(m["home"])
        teams.add(m["away"])
    for team in sorted(teams):
        fetch_team_snapshot(team, force=force)
    print(f"[team] snapshots ready for {len(teams)} teams")


# ---------------------------------------------------------------------------
# Claude prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior football betting analyst with 20 years of experience
specialising in international tournaments and FIFA World Cups. You combine deep tactical
knowledge with sharp commercial instincts — you understand both the football AND the markets.

Your job: analyse World Cup 2026 matches and produce structured research that a punter
can act on. Be direct, specific, and honest. If you're uncertain (e.g. injury news after
your knowledge cutoff), say so clearly. Flag where odds look sharp and where they look soft.

Always output valid JSON matching the exact schema requested — no markdown fences, no extra keys."""


def _build_prompt(home, away, commence, price_notes, weather_str):
    return f"""WC 2026 match: {home} vs {away} (kick-off UTC: {commence})

VENUE: {weather_str}

BOOKMAKER PRICE SIGNAL:
{price_notes}

Use your web search tool to look up current form, injuries and squad news for BOTH teams before analysing. Search for "{home} World Cup 2026 squad injuries form" and "{away} World Cup 2026 squad injuries form". Then output ONLY this JSON:
{{
  "home_form": "Last known form, goal record, key players. 2 sentences.",
  "away_form": "Same for {away}. 2 sentences.",
  "key_absences": "Known injuries/suspensions or 'none known'.",
  "conditions_impact": "How heat/altitude/kickoff time affects each team specifically. Which team benefits?",
  "tactical_matchup": "Style clash in 2 sentences. Who does it favour?",
  "goals_assessment": "Over/under 2.5 reasoning. BTTS likelihood.",
  "market_read": "Is the price fair, favourite too short, or underdog value?",
  "recommendation": {{
    "outcome": "home_win|draw|away_win|over_2.5|under_2.5|no_clear_edge",
    "reasoning": "2 sentences — football reasons, not just price.",
    "strength": "strong|moderate|lean",
    "watch_out": "Biggest risk to this call in 1 sentence."
  }},
  "overall_summary": "3 sentences a punter can act on. Lead with conditions.",
  "intel_confidence": "high|medium|low",
  "knowledge_caveat": "What you don't know that matters most."
}}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_match_intel(home, away, commence, price_notes="No price signal."):
    """
    Return football intelligence for a match. Cached for CACHE_TTL seconds.
    Returns None if API key missing or call fails.
    """
    cache = _load_cache()
    ck    = _cache_key(home, away)
    entry = cache.get(ck)

    if entry and (time.time() - entry.get("cached_at", 0)) < CACHE_TTL:
        return entry["intel"]

    # Get venue conditions (climate normals for June)
    cond, vk     = get_conditions_for_match(home, away, commence)
    cond_str     = _fmt_conditions(cond, vk)

    try:
        client = _get_client()
        resp   = client.messages.create(
            model      = MODEL,
            max_tokens = 2500,
            system     = SYSTEM_PROMPT,
            tools      = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages   = [{"role": "user",
                           "content": _build_prompt(home, away, commence, price_notes, cond_str)}],
        )
        # Concatenate all text blocks (web search returns many small fragments)
        full_text = "".join(
            block.text for block in resp.content
            if getattr(block, "type", None) == "text"
        )
        # Extract the JSON object from the response (ignore any prose before/after)
        start = full_text.find("{")
        end   = full_text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found in response")
        raw = full_text[start:end]
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        intel = json.loads(raw.strip())
        intel["conditions"] = cond
        intel["cached_at"]  = int(time.time())

        cache[ck] = {"intel": intel, "cached_at": int(time.time())}
        _save_cache(cache)
        return intel

    except Exception as e:
        print(f"[intel] {home} vs {away} failed: {e}")
        return None


def get_intel_batch(match_list, max_calls=15):
    """
    Fetch intel for a list of dicts with keys: home, away, commence, price_notes.
    Returns {cache_key: intel_dict}.
    Caps fresh API calls at max_calls; runs them concurrently for speed.
    """
    import concurrent.futures

    cache = _load_cache()
    results = {}
    to_fetch = []

    for m in match_list:
        ck = _cache_key(m["home"], m["away"])
        entry = cache.get(ck)
        if entry and (time.time() - entry.get("cached_at", 0)) < CACHE_TTL:
            results[ck] = entry["intel"]
        elif len(to_fetch) < max_calls:
            to_fetch.append(m)

    if not to_fetch:
        print(f"[intel] {len(results)} matches from cache, 0 fresh calls")
        return results

    # Run sequentially with a gap between calls to stay under 30k tokens/minute rate limit
    for i, m in enumerate(to_fetch):
        if i > 0:
            time.sleep(20)   # wait 20s between calls — each web-search call uses ~15k tokens
        intel = get_match_intel(m["home"], m["away"], m.get("commence",""), m.get("price_notes",""))
        if intel:
            results[_cache_key(m["home"], m["away"])] = intel

    print(f"[intel] {len(results)} matches served ({len(to_fetch)} fresh Claude calls)")
    return results
