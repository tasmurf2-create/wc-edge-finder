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
import threading
import concurrent.futures
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import static_data

CACHE_FILE      = Path("intel_cache.json")
SEED_FILE       = Path("intel_seed.json")        # committed seed: analyst cards for a fresh deploy
INJURY_DIGEST_FILE = Path("injury_digest.json")  # ONE tournament-wide injury digest (BBC)
WEATHER_FILE    = Path("weather_cache.json")   # Open-Meteo forecasts per venue+date
CACHE_TTL       = 43200    # 12 hours — match analysis
INJURIES_TTL    = 43200    # 12 hours — injury data
# Restrict injury searches to one trusted source. One broad BBC search per refresh
# covers the newsworthy injuries tournament-wide, instead of one search per team.
INJURY_DOMAINS  = ["bbc.com"]
WEATHER_TTL     = 21600    # 6 hours — weather forecast (refreshes a few times daily)
WEATHER_HORIZON_DAYS = 15  # Open-Meteo forecasts ~16 days ahead; use live data inside this
MODEL           = "claude-sonnet-4-6"          # match analysis (reasoning)
SEARCH_MODEL    = "claude-haiku-4-5-20251001"  # web-search snapshots — cheaper +
                                               # a SEPARATE rate-limit bucket, so
                                               # token-heavy searches don't starve
                                               # the Sonnet analysis budget.
# On Tier 1 the org rate limit (30k input tokens/min) is the real bottleneck, not
# latency. The SDK auto-retries 429s with backoff respecting retry-after headers;
# give it plenty of headroom so a burst self-paces instead of failing.
MAX_RETRIES     = 8

_client = None
_search_client = None
# Guards read-modify-write of the on-disk caches when intel is fetched
# concurrently across matches/teams. Held only around the quick file I/O,
# never around the network calls.
_io_lock = threading.Lock()

def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        _client = anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES)
    return _client


def _get_search_client():
    """Separate client for web-search snapshots (Haiku, its own rate bucket)."""
    global _search_client
    if _search_client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        _search_client = anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES)
    return _search_client





# ---------------------------------------------------------------------------
# Open-Meteo weather fetch (free, no API key)
# ---------------------------------------------------------------------------



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


def _match_local_date(iso_datetime, tz):
    """The match's calendar date in the venue's local timezone (a date object)."""
    try:
        import zoneinfo
        dt_utc = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
        return dt_utc.astimezone(zoneinfo.ZoneInfo(tz)).date()
    except Exception:
        try:
            return datetime.fromisoformat(iso_datetime.replace("Z", "+00:00")).date()
        except Exception:
            return None


def _fetch_weather(lat, lon, iso_datetime, tz):
    """Real Open-Meteo daily forecast for the match's local date — free, no API key.
    Returns a dict, or None when the match is outside the ~16-day forecast horizon
    (caller then has no conditions). Cached on disk for WEATHER_TTL.
    """
    local_date = _match_local_date(iso_datetime, tz)
    if local_date is None:
        return None
    days_out = (local_date - datetime.now(timezone.utc).date()).days
    if days_out < 0 or days_out > WEATHER_HORIZON_DAYS:
        return None   # beyond forecast range → use climate normals

    ds = local_date.isoformat()
    ck = f"{lat:.3f},{lon:.3f},{ds}"
    with _io_lock:
        entry = _load_json(WEATHER_FILE).get(ck)
    if entry and (time.time() - entry.get("fetched_at", 0)) < WEATHER_TTL:
        return entry["weather"]

    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude":  f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "daily": ("temperature_2m_max,apparent_temperature_max,relative_humidity_2m_mean,"
                  "precipitation_probability_max,wind_speed_10m_max"),
        "timezone":   "auto",
        "start_date": ds,
        "end_date":   ds,
    })
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        daily = data.get("daily", {})
        def first(key):
            v = daily.get(key)
            return v[0] if isinstance(v, list) and v else None
        if first("temperature_2m_max") is None:
            return None
        weather = {
            "temp_max_c":      first("temperature_2m_max"),
            "feels_like_c":    first("apparent_temperature_max"),
            "humidity_pct":    first("relative_humidity_2m_mean"),
            "precip_prob_pct": first("precipitation_probability_max"),
            "wind_max_kmh":    first("wind_speed_10m_max"),
            "forecast_date":   ds,
            "days_out":        days_out,
        }
        with _io_lock:
            store = _load_json(WEATHER_FILE)
            store[ck] = {"weather": weather, "fetched_at": int(time.time())}
            _save_json(WEATHER_FILE, store)
        print(f"[weather] {ck}: {weather['temp_max_c']}°C (feels {weather['feels_like_c']}°C), {days_out}d out")
        return weather
    except Exception as e:
        print(f"[weather] fetch failed for {ck}: {e}")
        return None


def _venue_month_temp(venue, commence):
    """Venue June or July average, picked by the match month."""
    try:
        mo = datetime.fromisoformat(commence.replace("Z", "+00:00")).month
    except Exception:
        mo = 6
    if mo >= 7 and venue.get("avg_temp_july_c") is not None:
        return venue["avg_temp_july_c"]
    return venue.get("avg_temp_june_c")


def get_conditions_for_match(home, away, commence):
    """Conditions for a match from the sourced static venue DB + a live Open-Meteo
    forecast (within 16 days), else the venue's June/July climate normal. Roofed
    stadiums are treated as climate-controlled. Falls back to the legacy hand
    tables only if the fixture isn't in the static schedule."""
    info = static_data.venue_for_teams(home, away)
    if info:
        v = info["venue"]
        tz = v.get("timezone") or "UTC"
        local_ko = _local_kickoff(commence, tz)
        base = _venue_month_temp(v, commence)
        base_r = round(base) if isinstance(base, (int, float)) else None
        roofed = bool(v.get("has_roof"))
        notes = f"{v['stadium']}, {v['city']}" + (" — roofed / climate-controlled" if roofed else "")
        fc = None if roofed else _fetch_weather(v.get("latitude"), v.get("longitude"), commence, tz)
        if fc:
            def pick(val, fb):
                return round(val) if isinstance(val, (int, float)) else fb
            cond = {
                "city": v["city"], "stadium": v["stadium"], "has_roof": roofed,
                "altitude_m": v.get("altitude_m") or 0, "local_kickoff": local_ko,
                "avg_high_c": pick(fc.get("temp_max_c"), base_r),
                "feels_like_c": pick(fc.get("feels_like_c"), base_r),
                "humidity_pct": pick(fc.get("humidity_pct"), None),
                "precip_prob_pct": fc.get("precip_prob_pct"),
                "wind_max_kmh": pick(fc.get("wind_max_kmh"), None),
                "notes": notes, "source": "forecast", "days_out": fc.get("days_out"),
            }
        else:
            cond = {
                "city": v["city"], "stadium": v["stadium"], "has_roof": roofed,
                "altitude_m": v.get("altitude_m") or 0, "local_kickoff": local_ko,
                "avg_high_c": base_r, "feels_like_c": base_r, "humidity_pct": None,
                "precip_prob_pct": None, "wind_max_kmh": None, "notes": notes,
                "source": "controlled" if roofed else "climate_normal", "days_out": None,
            }
        return cond, v["venue_key"]

    # Fixture not in the sourced FIFA schedule — no guessing on venue/conditions.
    return None, None


def _fmt_conditions(cond, vk):
    if not cond:
        return "Venue not in the sourced FIFA schedule — do NOT speculate on venue, conditions, kick-off or weather; exclude conditions from this analysis."
    alt_note = f" *** ALTITUDE {cond['altitude_m']}m ***" if (cond.get("altitude_m") or 0) > 800 else ""
    src = cond.get("source")
    if src == "forecast":
        extra = ""
        if cond.get("precip_prob_pct") is not None:
            extra += f"  |  Rain chance: {cond['precip_prob_pct']}%"
        if cond.get("wind_max_kmh") is not None:
            extra += f"  |  Wind: {cond['wind_max_kmh']} km/h"
        hum = f"  |  Humidity: {cond['humidity_pct']}%" if cond.get("humidity_pct") is not None else ""
        weather_line = (f"LIVE FORECAST ({cond['days_out']}d out) — high: {cond['avg_high_c']}°C  |  "
                        f"Feels like: {cond['feels_like_c']}°C{hum}{extra}")
    elif src == "controlled":
        weather_line = "Roofed / climate-controlled stadium — weather not a factor."
    else:
        weather_line = f"Climate normal — venue avg temp: {cond.get('avg_high_c')}°C"
    venue_label = cond.get("stadium") or cond.get("city") or "venue"
    return (
        f"Venue: {venue_label}{alt_note}\n"
        f"Local kick-off: {cond['local_kickoff']}\n"
        f"{weather_line}\n"
        f"Assessment: {cond['notes']}"
    )


# ---------------------------------------------------------------------------
# Climate tolerance — which nations cope with heat / altitude (static, no API)
# ---------------------------------------------------------------------------
# Nations whose footballers are accustomed to high-altitude home venues
ALTITUDE_ADAPTED = {"mexico", "bolivia", "ecuador", "colombia", "peru"}
_TOL_RANK = {"low": 0, "medium": 1, "high": 2}


def _heat_tol(team):
    # Data-driven from teams.csv (sourced country avg annual temperature);
    # falls back to the hand-curated table only if the team isn't in the DB.
    c = static_data.team_climate(team)
    if c:
        t = c["avg_temp_c"]
        return "high" if t >= 22 else ("medium" if t >= 14 else "low")
    return "medium"


def weather_signal(home, away, commence):
    """Turn the venue forecast + each team's climate tolerance into a signal:
    which side the conditions favour, a goals lean, and a human-readable flag.
    Returns None when conditions are mild (no meaningful edge). Cheap — reads the
    cached forecast via get_conditions_for_match."""
    cond, vk = get_conditions_for_match(home, away, commence)
    if not cond:
        return None
    if cond.get("has_roof"):
        return None   # roofed / climate-controlled stadium — conditions neutralised
    feels    = cond.get("feels_like_c") or cond.get("avg_high_c") or 0
    humidity = cond.get("humidity_pct") or 0
    alt      = cond.get("altitude_m") or 0

    favours = disfavours = goals_lean = None
    types = []

    # --- heat / humidity ---
    # A live forecast gives a feels-like *max*; a climate normal is a monthly
    # *mean* (a few degrees lower for the same heat) — so use lower thresholds.
    if cond.get("source") == "forecast":
        hot_t, extreme_t = 33, 38
    else:
        hot_t, extreme_t = 26, 29
    heat_sev = None
    if feels >= extreme_t or (feels >= extreme_t - 4 and humidity >= 65):
        heat_sev = "extreme"
    elif feels >= hot_t:
        heat_sev = "hot"
    if heat_sev:
        types.append("heat")
        rh, ra = _TOL_RANK[_heat_tol(home)], _TOL_RANK[_heat_tol(away)]
        if rh != ra:
            favours, disfavours = (home, away) if rh > ra else (away, home)
        goals_lean = "under"   # heat slows games down

    # --- altitude ---
    alt_sev = None
    if alt >= 2000:
        alt_sev = "extreme"
    elif alt >= 1500:
        alt_sev = "notable"
    if alt_sev:
        types.append("altitude")
        ha = home.lower().strip() in ALTITUDE_ADAPTED
        aa = away.lower().strip() in ALTITUDE_ADAPTED
        if ha != aa and favours is None:
            favours, disfavours = (home, away) if ha else (away, home)
        if goals_lean is None:
            goals_lean = "over"   # thin air tends to open games up

    if not types:
        return None

    cond_txt = ""
    if "heat" in types:
        cond_txt = f"{cond['feels_like_c']}°C feels-like, {humidity}% humidity"
    if "altitude" in types:
        cond_txt = (cond_txt + ", " if cond_txt else "") + f"{alt}m altitude"

    severity = "extreme" if "extreme" in (heat_sev, alt_sev) else (heat_sev or alt_sev)
    emoji = "🌡️" if "heat" in types else "⛰️"
    if "heat" in types and "altitude" in types:
        emoji = "🌡️⛰️"

    if favours:
        headline = f"{cond_txt} — favours {favours}"
        detail = (f"{disfavours} ({_heat_tol(disfavours)} heat tolerance) likely to struggle in "
                  f"{cond_txt}; conditions favour {favours}.")
    else:
        headline = f"{cond_txt} — demanding for both"
        detail = f"Tough conditions ({cond_txt}) — affects both sides similarly."
    if goals_lean:
        detail += f" Goals lean: {goals_lean.upper()}."

    return {
        "types": types, "severity": severity, "emoji": emoji,
        "favours": favours, "disfavours": disfavours, "goals_lean": goals_lean,
        "headline": headline, "detail": detail,
        "source": cond.get("source"), "days_out": cond.get("days_out"),
        "feels_like_c": cond.get("feels_like_c"), "humidity_pct": humidity, "altitude_m": alt,
    }


def prewarm_weather(triples, max_workers=8):
    """Concurrently warm the on-disk forecast cache for a list of (home, away,
    commence) tuples, so per-match weather_signal() calls are then instant."""
    triples = list(triples)
    if not triples:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(triples))) as ex:
        futs = [ex.submit(get_conditions_for_match, h, a, c) for (h, a, c) in triples]
        for f in concurrent.futures.as_completed(futs):
            try:
                f.result()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _load_cache():
    # Live cache first; fall back to a committed seed (SEED_FILE) so a fresh
    # deploy with no local cache still shows analyst cards. The first _save_cache
    # writes CACHE_FILE, which then takes over.
    for p in (CACHE_FILE, SEED_FILE):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _cache_key(home, away):
    return hashlib.md5(f"{home.lower()}|{away.lower()}".encode()).hexdigest()


def invalidate_match_cache(pairs):
    """
    Drop the disk-cached analyst entry for each (home, away) pair so it gets
    re-analysed on the next fetch. Used by the injuries refresh to invalidate
    only the matches whose injury picture changed — instead of nuking the whole
    cache. Returns the number of entries removed.
    """
    with _io_lock:
        cache = _load_cache()
        removed = 0
        for home, away in pairs:
            if cache.pop(_cache_key(home, away), None) is not None:
                removed += 1
        if removed:
            _save_cache(cache)
    return removed


# ---------------------------------------------------------------------------
# Team data — two-tier cache
#   Profiles  : WC 2026 squad announcement — fetched once, never expires
#   Injuries  : Current injuries/suspensions — refreshed daily
# ---------------------------------------------------------------------------

def _load_json(path):
    if Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _team_key(team):
    return team.lower().strip()


def _web_search_text(prompt, max_uses=2, max_tokens=500, allowed_domains=None):
    """Run a single web-search call on the search model and return the text.
    allowed_domains (e.g. ["bbc.com"]) restricts results to trusted sources."""
    client = _get_search_client()
    tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains
    resp = client.messages.create(
        model      = SEARCH_MODEL,
        max_tokens = max_tokens,
        tools      = [tool],
        messages   = [{"role": "user", "content": prompt}],
    )
    return "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()


# --- Profiles (squad announcements, one-time) ---

# Squad data is now SOURCED from the official FIFA list (players.csv via
# static_data.squad_text) — no web search, no fabrication. See _team_context().

# --- Injuries: ONE tournament-wide digest (BBC), refreshed 12h ---

def _injury_digest_query():
    today = datetime.now().strftime("%-d %B %Y") if os.name != "nt" else datetime.now().strftime("%d %B %Y")
    return (
        f"As of {today}, summarise the latest confirmed injury and suspension news "
        f"for the 2026 FIFA World Cup. For each affected national team, list the player "
        f"name, their team, and the injury/suspension and expected availability. "
        f"Group by national team. Focus on the most recent news. If a major team has no "
        f"reported absences, you may note that."
    )


def fetch_wc_injury_digest(force=False):
    """
    ONE web search (restricted to BBC) for tournament-wide injury/suspension news,
    cached 12h. Replaces the old per-team search (which cost ~1 call per team).
    Returns a plain-text digest grouped by national team. Concurrency-safe.
    """
    with _io_lock:
        entry = _load_json(INJURY_DIGEST_FILE)
    if (not force and entry.get("digest")
            and (time.time() - entry.get("fetched_at", 0)) < INJURIES_TTL):
        return entry["digest"]

    try:
        text = _web_search_text(
            _injury_digest_query(),
            max_uses=3, max_tokens=900, allowed_domains=INJURY_DOMAINS,
        )
        if text:
            with _io_lock:
                _save_json(INJURY_DIGEST_FILE,
                           {"digest": text, "fetched_at": int(time.time())})
            print(f"[injuries] WC digest refreshed ({len(text)} chars)")
            return text
    except Exception as e:
        print(f"[injuries] digest fetch failed: {e}")

    return entry.get("digest", "No injury data available.")


def peek_injury_digest():
    """Return the currently cached digest text without triggering a search."""
    return (_load_json(INJURY_DIGEST_FILE) or {}).get("digest")


def _team_context(team):
    """The SOURCED squad (official FIFA list) for a team. Injuries are now a
    single tournament-wide digest injected separately into the prompt."""
    squad = static_data.squad_text(team)
    if squad:
        return "SQUAD (official FIFA 2026 squad list — authoritative):\n" + squad
    return "SQUAD: not found in official list."


def get_team_snapshots(home, away):
    """Both teams' SOURCED squad context (static — no network)."""
    return _team_context(home), _team_context(away)


# ---------------------------------------------------------------------------
# Claude prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior football betting analyst with 20 years of experience
specialising in international tournaments and FIFA World Cups. You think like a professional
gambler: you identify which outcomes make genuine footballing sense, consider ALL available
markets (match result, goals over/under, draw value), and only recommend bets where the
logic is sound — not just where the price happens to look big.

Your job: analyse World Cup 2026 matches and produce up to 3 specific recommended bets
across any combination of markets. Each recommended bet must have a clear football reason —
not just "the price is long". Factor in conditions, form, tactical matchup, and absences.

Always output valid JSON matching the exact schema requested — no markdown fences, no extra keys."""


def _build_prompt(home, away, commence, price_notes, weather_str,
                  home_ctx="", away_ctx="", injury_digest=""):
    context_section = ""
    if home_ctx or away_ctx:
        context_section = f"""
TEAM SQUADS — official FIFA 2026 lists (authoritative):
{home.upper()}: {home_ctx or 'Not available.'}

{away.upper()}: {away_ctx or 'Not available.'}
"""
    injury_section = ""
    if injury_digest:
        injury_section = f"""
INJURY / SUSPENSION NEWS — tournament-wide digest (source: BBC, indicative; covers
newsworthy absences, may not mention every team). Apply only the parts relevant to
{home} or {away}:
{injury_digest}
"""
    return f"""WC 2026 match: {home} vs {away} (kick-off UTC: {commence})

VENUE & CONDITIONS: {weather_str}
{context_section}{injury_section}
BOOKMAKER PRICE SIGNAL (for context — your recommendation must be driven by football logic first):
{price_notes}

Analyse this match as a professional gambler. Consider ALL these markets:
- Match result (1X2): {home} win | draw | {away} win
- Goals: over 2.5 | under 2.5 | over 1.5 | under 1.5
- Asian handicap: {home} (-0.5) | {home} (-1) | {home} (-1.5) | {home} (-2)
                  {away} (+0.5) | {away} (+1)  | {away} (+1.5)  | {away} (+2)

Handicap guide:
  "{home} (-1.5)" = {home} must WIN BY 2 OR MORE goals to win the bet
  "{away} (+1.5)" = {away} can lose by 1, draw, or win and still win the bet
  "{home} (-0.5)" = {home} must win by any margin (same as home win)

Identify the 1-3 outcomes that make genuine football sense. An outcome qualifies if:
  (a) there is a clear footballing reason it is likely or undervalued, AND
  (b) the risk/reward is reasonable given what you know

Do NOT recommend a bet just because the price is big. A 10/1 shot is still a bad bet if the
football logic doesn't support it. A 1.5/1 favourite at fair price is better than a 10/1 shot
backed purely by price signal.

Examples of good thinking:
- "Germany should win comfortably against Curaçao — recommend Germany (-1.5) not just Germany win"
- "Uzbekistan vs Colombia at altitude — recommend under 2.5 goals + Colombia win separately"
- "Even match — draw is the value outcome, over 1.5 goals likely but speculative"

Using the squad and injury data above, output ONLY this JSON:
{{
  "home_form": "Last known form, goal record, key players in 2 sentences.",
  "away_form": "Same for {away} in 2 sentences.",
  "key_absences": "Known injuries/suspensions or 'none known'.",
  "conditions_impact": "How heat/altitude/kickoff time affects each team specifically. Which team benefits?",
  "tactical_matchup": "Style clash in 2 sentences. Who does it favour?",
  "goals_assessment": "Expected goal total with reasoning. Over/under 2.5 call. BTTS likely or not and why.",
  "market_read": "Which side of each market (h2h, totals, handicap) is correctly priced, overpriced, or offers genuine value?",
  "recommended_bets": [
    {{
      "market": "h2h|totals|spreads",
      "outcome": "home_win|draw|away_win|over_2.5|under_2.5|over_1.5|under_1.5|home_-0.5|home_-1|home_-1.5|home_-2|away_+0.5|away_+1|away_+1.5|away_+2",
      "confidence": "high|medium|low",
      "reasoning": "The football reason — not the price — why this outcome makes sense. 2 sentences.",
      "strength": "strong|moderate|lean"
    }}
  ],
  "overall_summary": "3 sentences a punter can act on. Lead with the single best bet and why.",
  "intel_confidence": "high|medium|low",
  "knowledge_caveat": "What you don't know that matters most."
}}

Include 1 to 3 items in recommended_bets. Only include bets with genuine football logic.
If no outcome has a clear edge, return an empty array and explain in overall_summary."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_match_intel(home, away, commence, price_notes="No price signal."):
    """
    Return football intelligence for a match. Cached for CACHE_TTL seconds.
    Returns None if API key missing or call fails.
    """
    ck = _cache_key(home, away)
    with _io_lock:
        entry = _load_cache().get(ck)
    if entry and (time.time() - entry.get("cached_at", 0)) < CACHE_TTL:
        return entry["intel"]

    # Get venue conditions (live forecast inside 16 days, else June normals)
    cond, vk     = get_conditions_for_match(home, away, commence)
    cond_str     = _fmt_conditions(cond, vk)
    # Add the explicit climate-tolerance read so the analyst reasons consistently
    sig = weather_signal(home, away, commence)
    if sig:
        cond_str += f"\nClimate edge: {sig['detail']}"

    # Squad context (static) + the shared tournament-wide injury digest (one cached
    # BBC search, not one per team).
    home_ctx, away_ctx = get_team_snapshots(home, away)
    injury_digest = fetch_wc_injury_digest()

    try:
        client = _get_client()
        resp   = client.messages.create(
            model      = MODEL,
            max_tokens = 1500,
            system     = SYSTEM_PROMPT,
            messages   = [{"role": "user",
                           "content": _build_prompt(
                               home, away, commence, price_notes, cond_str,
                               home_ctx, away_ctx, injury_digest,
                           )}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        intel = json.loads(raw.strip())
        intel["conditions"] = cond
        intel["cached_at"]  = int(time.time())

        with _io_lock:
            cache = _load_cache()
            cache[ck] = {"intel": intel, "cached_at": int(time.time()),
                          "label": f"{home} vs {away}"}
            _save_cache(cache)
        return intel

    except Exception as e:
        print(f"[intel] {home} vs {away} failed: {e}")
        return None


def load_intel_from_disk():
    """
    Return {match_label: intel_dict} from disk cache — call at server startup
    to pre-populate in-memory cache without re-running any API calls.
    """
    result = {}
    cache  = _load_cache()
    now    = time.time()
    for ck, entry in cache.items():
        if (now - entry.get("cached_at", 0)) < CACHE_TTL and "label" in entry:
            result[entry["label"]] = entry["intel"]
    return result


def get_intel_batch(match_list, max_calls=15):
    """
    Fetch intel for a list of dicts with keys: home, away, commence, price_notes.
    Returns {cache_key: intel_dict}.
    Caps fresh matches at max_calls; runs them concurrently for speed.
    """
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

    # Concurrency is capped by ACCA env-tunable INTEL_WORKERS (default 1).
    # On Tier-1 limits, serialising the Sonnet analysis (1 worker) is actually
    # fastest end-to-end: parallel calls all 429 and then each burns its retry
    # budget re-sending tokens, which saturates the shared 30k/min bucket and
    # makes *everything* fail. One-at-a-time stays under the limit and completes.
    # Bump INTEL_WORKERS on a higher API tier for real parallelism.
    workers = max(1, min(int(os.environ.get("INTEL_WORKERS", "1")), len(to_fetch)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(get_match_intel, m["home"], m["away"],
                      m.get("commence", ""), m.get("price_notes", "")): m
            for m in to_fetch
        }
        for f in concurrent.futures.as_completed(futs):
            m = futs[f]
            try:
                intel = f.result()
                if intel:
                    results[_cache_key(m["home"], m["away"])] = intel
            except Exception as e:
                print(f"[intel] {m['home']} vs {m['away']} failed: {e}")

    print(f"[intel] {len(results)} matches served ({len(to_fetch)} fresh, {workers} workers)")
    return results
