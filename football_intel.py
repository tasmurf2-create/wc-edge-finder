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

CACHE_FILE = Path("intel_cache.json")
CACHE_TTL  = 43200   # 12 hours
MODEL      = "claude-sonnet-4-6"

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
    return f"""Analyse this World Cup 2026 group-stage match as a professional betting researcher.

MATCH: {home} vs {away}
KICK-OFF (UTC): {commence}

VENUE CONDITIONS (June climate data + altitude):
{weather_str}

PRICE SIGNAL FROM MARKET:
{price_notes}

IMPORTANT CONTEXT:
- Your knowledge cutoff is August 2025. The WC 2026 starts 11 June 2026.
- You will not have final squad lists, pre-tournament form from early 2026, or late injuries.
- Clearly flag what you do not know. Do not invent injury news.
- The heat/altitude data above is real and should heavily influence your assessment.
  Teams from cool climates (Northern Europe, UK, South America) will be significantly
  affected by 35°C+ Texas heat or 2200m Mexico City altitude. Teams from hot regions
  (North Africa, Middle East, Central America) will have a natural advantage.

Produce ONLY a JSON object with EXACTLY this structure:

{{
  "home_form": "Specific: last known results, quality of opposition, goal record, defensive solidity. Note if this is pre-2026 data.",
  "away_form": "Same for {away}.",
  "home_strengths": ["up to 3 specific strengths relevant to this fixture"],
  "away_strengths": ["up to 3 specific strengths relevant to this fixture"],
  "key_absences": "Known or expected absences — injuries, suspensions, ageing key players. Be honest about what you don't know.",
  "conditions_impact": "How will the specific temperature, humidity, altitude, and local kick-off time impact each team? Which team benefits? Be explicit about cool-climate vs hot-climate squads.",
  "tactical_matchup": "Specific: pressing vs deep-block, set-piece threat, pace on the counter, width play. Who does the style matchup favour?",
  "goals_assessment": "Expected scoring range, likelihood of BTTS, over/under 2.5 reasoning. Which defence is more suspect?",
  "market_read": "Is the bookmaker pricing fair, too short on the favourite, or too generous on the underdog/draw? What might the market be missing?",
  "recommendation": {{
    "outcome": "one of: home_win, draw, away_win, over_2.5, under_2.5, no_clear_edge",
    "reasoning": "2-3 sentences — specific football and conditions reasons, not just price.",
    "strength": "one of: strong, moderate, lean",
    "watch_out": "The single biggest risk that could make this recommendation wrong."
  }},
  "overall_summary": "4-5 sentences. Plain English match preview a punter can read in 20 seconds. Include conditions impact prominently.",
  "intel_confidence": "one of: high, medium, low",
  "knowledge_caveat": "What specific information you're missing that would change your assessment."
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
            messages   = [{"role": "user",
                           "content": _build_prompt(home, away, commence, price_notes, cond_str)}],
        )
        raw = resp.content[0].text.strip()
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
    Caps fresh API calls at max_calls to control cost.
    """
    results = {}
    calls   = 0
    cache   = _load_cache()

    for m in match_list:
        home, away = m["home"], m["away"]
        ck    = _cache_key(home, away)
        entry = cache.get(ck)

        if entry and (time.time() - entry.get("cached_at", 0)) < CACHE_TTL:
            results[ck] = entry["intel"]
            continue

        if calls >= max_calls:
            continue

        intel = get_match_intel(home, away, m.get("commence",""), m.get("price_notes",""))
        if intel:
            results[ck] = intel
            calls += 1

    print(f"[intel] {len(results)} matches served ({calls} fresh Claude calls)")
    return results
