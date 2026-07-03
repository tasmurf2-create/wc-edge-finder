#!/usr/bin/env python3
"""
GAA intelligence layer — Claude analysis for hurling & gaelic football.

Mirrors football_intel.get_match_intel but GAA-tuned:
  - no static squad/ranking data (there is none for GAA) — team context comes
    from ONE web search per match over Irish GAA sources (form + panel news);
  - GAA markets (Match Winner 1X2, Handicap in points), venue neutrality
    (All-Ireland semis/finals are at neutral Croke Park — no home advantage);
  - structured JSON the GAA tab renders directly.

Reuses football_intel's Anthropic clients + web-search helper + JSON cache I/O
so we don't duplicate rate-limit/retry handling.
"""
import json
import time
import hashlib
import threading
from pathlib import Path
from datetime import datetime

from football_intel import (
    _get_client, _get_search_client, _load_json, _save_json, MODEL, SEARCH_MODEL,
)

CACHE_FILE = Path("gaa_intel_cache.json")
RESEARCH_FILE = Path("gaa_research_cache.json")   # per-team research, reused across fixtures
CACHE_TTL = 43200          # 12h — GAA news moves slowly; re-analyse twice a day
RESEARCH_TTL = 43200       # 12h — team form + injury news
PROMPT_VERSION = 2

# Irish GAA sources accessible to Anthropic's web-search crawler. NB: independent.ie
# and irishmirror.ie are blocked by the crawler (confirmed 400) — excluded, else the
# whole search request errors out. Widen only with domains verified to pass.
GAA_DOMAINS = ["rte.ie", "the42.ie", "gaa.ie", "hoganstand.com", "balls.ie",
               "sportsjoe.ie", "punditarena.com", "breakingnews.ie",
               "irishexaminer.com", "irishtimes.com", "sport.ie"]

_io_lock = threading.Lock()

SYSTEM_PROMPT = """You are a senior Gaelic Games analyst with deep knowledge of All-Ireland
hurling and gaelic football championship. You think like a professional gambler: you identify
which outcomes make genuine GAA sense across the available markets (match winner, handicap in
points).

Stay in your lane — you give the GAA read, NOT the value verdict. Prices and edges are computed
separately, so:
- You do NOT have reliable odds. Never crown a "best bet" or call anything "value". Rank outcomes
  by GAA logic only; let the price layer judge value.
- No absolutes like "no chance" — say low-probability, would need a big price.
- Weigh the favourite's WEAKNESSES too (defensive frailty, over-reliance on one forward, injuries,
  travel/fatigue), not just their strengths.

GROUND EVERYTHING IN THE PROVIDED RESEARCH. You are given a web-search digest of each county's
recent championship form and panel/injury news, plus the fixture and stage. You do NOT have
detailed per-player stats. So:
- Use the form digest provided; do NOT invent results, scorelines or records beyond it.
- VENUE: All-Ireland semi-finals and finals are played at NEUTRAL Croke Park — there is NO home
  advantage. The team named first is only the nominal "home" (fixture ordering), not a host.
- Championship knockout matches can go to extra time; a draw after normal time is a real (if
  lower-probability) market outcome.
- Flag anything you are unsure of in knowledge_caveat rather than inventing it.

Always output valid JSON matching the exact schema requested — no markdown fences, no extra keys."""


def _cache_key(home, away, sport):
    base = f"{home.lower().strip()}|{away.lower().strip()}|{sport}|v{PROMPT_VERSION}"
    return hashlib.sha1(base.encode()).hexdigest()[:16]


def _web_search(prompt, max_uses, max_tokens, model):
    """Web search over the GAA domain whitelist, on the chosen model. Returns text."""
    client = _get_client() if model == MODEL else _get_search_client()
    tool = {"type": "web_search_20250305", "name": "web_search",
            "max_uses": max_uses, "allowed_domains": GAA_DOMAINS}
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, tools=[tool],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content
                   if getattr(b, "type", None) == "text").strip()


def _research_team(team, sport):
    """Deep, cached research for ONE county: two focused searches (championship
    form/results, then team news/injuries), synthesised on Sonnet. Cached per
    team (RESEARCH_TTL) so a county is researched once and reused across fixtures.
    Cheap given the tiny field (~8 counties)."""
    tk = f"{team.lower().strip()}|{sport}|v{PROMPT_VERSION}"
    with _io_lock:
        cache = _load_json(RESEARCH_FILE) or {}
    entry = cache.get(tk)
    if entry and (time.time() - entry.get("cached_at", 0)) < RESEARCH_TTL:
        return entry["text"]

    today = datetime.now().strftime("%d %B %Y")
    year = datetime.now().year
    form_q = (
        f"As of {today}, list {team}'s results in the {year} All-Ireland senior {sport} "
        f"championship so far this season: opponent, competition round, and final score for "
        f"each game, most recent first. Then one line on their current form and their main "
        f"attacking and defensive strengths/weaknesses. Only state results you can source; "
        f"if you cannot find a result, say so rather than inventing one."
    )
    news_q = (
        f"As of {today}, what is the latest team news for the {team} senior {sport} panel "
        f"ahead of their next {year} All-Ireland championship game: confirmed injuries, "
        f"suspensions, doubts, and any players returning to fitness or the starting fifteen? "
        f"One line per player with the source's wording. If no news is reported, say so."
    )
    parts = []
    for label, q in (("FORM & RESULTS", form_q), ("TEAM NEWS & INJURIES", news_q)):
        try:
            txt = _web_search(q, max_uses=5, max_tokens=1800, model=MODEL)
            if txt:
                parts.append(f"### {label}\n{txt}")
        except Exception as e:
            print(f"[gaa_intel] {team} {label} search failed: {e}")
    text = "\n\n".join(parts)
    if text:
        with _io_lock:
            cache = _load_json(RESEARCH_FILE) or {}
            cache[tk] = {"text": text, "cached_at": int(time.time()), "team": team}
            _save_json(RESEARCH_FILE, cache)
    return text


def _research(home, away, sport):
    """Compose per-team deep research for both counties in a fixture."""
    h = _research_team(home, sport)
    a = _research_team(away, sport)
    blocks = []
    if h:
        blocks.append(f"===== {home.upper()} =====\n{h}")
    if a:
        blocks.append(f"===== {away.upper()} =====\n{a}")
    return "\n\n".join(blocks)


def _build_prompt(home, away, sport, competition, throw_in, research):
    research_section = research or "No research returned — reason cautiously and flag low confidence."
    return f"""All-Ireland {sport} match: {home} vs {away}
Competition/stage: {competition}
Throw-in (UTC): {throw_in}
Venue: neutral (Croke Park for semi-finals/finals) — no home advantage.

RESEARCH DIGEST (web search over Irish GAA sources — form + panel/injury news):
{research_section}

Analyse as a professional GAA gambler. Consider these markets:
- Match Winner (1X2): {home} win | draw | {away} win
- Handicap (points): favourite gives a points start to the underdog (e.g. {home} -6, {away} +6)

Identify the 1-3 outcomes that make genuine GAA sense (a clear reason it is likely/undervalued,
and reasonable risk/reward). Ground every claim in the research digest; do not invent stats.

Output ONLY this JSON:
{{
  "home_form": "{home}'s recent championship form from the research. Cite real results/scores where given; do not invent. 2-3 sentences.",
  "away_form": "Same for {away}. 2-3 sentences.",
  "key_absences": "Injuries/suspensions/returns from the research only, or 'none reported'. Do not invent.",
  "tactical_matchup": "Likely stylistic matchup (e.g. running game vs traditional, half-back dominance, goalkeeper puckouts). Who does it favour? 2 sentences. Flag uncertainty rather than inventing.",
  "points_assessment": "Expected scoring level and whether it should be a tight or open game, reasoned from the form digest. High/low-scoring lean.",
  "market_read": "Which side of match-winner and handicap looks correctly or wrongly priced based on the form/injury read.",
  "recommended_bets": [
    {{
      "market": "match_winner|handicap",
      "outcome": "home_win|draw|away_win|home_-6|away_+6|home_handicap|away_handicap",
      "confidence": "high|medium|low",
      "reasoning": "The GAA reason (not the price) grounded in form/injuries. 2 sentences. No 'value'/'best bet' language.",
      "strength": "strong|moderate|lean"
    }}
  ],
  "overall_summary": "3 sentences a punter can act on. Lead with the strongest GAA angle (not a 'best bet' — you don't have prices).",
  "intel_confidence": "high|medium|low",
  "knowledge_caveat": "What you don't know that matters most (e.g. late team-news, weather)."
}}

Include 1 to 3 items in recommended_bets. If no outcome has a clear edge, return an empty array
and explain in overall_summary."""


def get_gaa_intel(home, away, sport, competition="", throw_in=""):
    """Return GAA intel dict for one match (disk-cached CACHE_TTL). None on failure."""
    ck = _cache_key(home, away, sport)
    with _io_lock:
        cache = _load_json(CACHE_FILE) or {}
    entry = cache.get(ck)
    if entry and (time.time() - entry.get("cached_at", 0)) < CACHE_TTL:
        return entry["intel"]

    research = _research(home, away, sport)
    try:
        client = _get_client()
        resp = client.messages.create(
            model=MODEL, max_tokens=2200, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(
                home, away, sport, competition, throw_in, research)}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        intel = json.loads(raw.strip())
        intel["cached_at"] = int(time.time())
        intel["sport"] = sport
        with _io_lock:
            cache = _load_json(CACHE_FILE) or {}
            cache[ck] = {"intel": intel, "cached_at": int(time.time()),
                         "label": f"{home} vs {away}"}
            _save_json(CACHE_FILE, cache)
        return intel
    except Exception as e:
        print(f"[gaa_intel] {home} vs {away} failed: {e}")
        return None


def get_gaa_intel_batch(games):
    """games: list of {home, away, sport, competition, throw_in}.
    Returns {cache_key: intel}. Serial — GAA has only a handful of games."""
    out = {}
    for g in games:
        intel = get_gaa_intel(g["home"], g["away"], g.get("sport", "hurling"),
                              g.get("competition", ""), g.get("throw_in", ""))
        if intel:
            out[_cache_key(g["home"], g["away"], g.get("sport", "hurling"))] = intel
    return out


def intel_key(home, away, sport):
    """Public cache-key helper so the server can look up cached intel per game."""
    return _cache_key(home, away, sport)


def clear_cache():
    """Delete the intel + research disk caches so the next run re-fetches fresh
    form/injury news (used by the manual 'Refresh analysis' action)."""
    for f in (CACHE_FILE, RESEARCH_FILE):
        try:
            if f.exists():
                f.unlink()
        except Exception as e:
            print(f"[gaa_intel] could not clear {f}: {e}")
