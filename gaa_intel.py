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
CACHE_TTL = 43200          # 12h — GAA news moves slowly; re-analyse twice a day
PROMPT_VERSION = 5         # bumped: numbers-discipline (no fabricated scorelines/margins)

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

NUMBERS DISCIPLINE (critical — recent write-ups fabricated margins):
- NEVER state a scoreline (e.g. "2-26 to 1-18") or an exact points margin (e.g. "won by 14")
  unless that EXACT figure appears verbatim in the research digest for THAT specific match.
- Do NOT compute, infer, estimate or round a margin yourself, and do NOT carry a number from one
  match over to another. If two matches happen to share a figure, that is suspicious — only keep
  it if the digest states it for each match independently.
- If you don't have the exact figure, describe it QUALITATIVELY instead — "a comfortable
  double-digit win", "a narrow victory", "a heavy defeat" — never a made-up precise number.
- (GAA scoring, for reading the digest only: a goal = 3 points; "2-26" = 32. But prefer to quote
  the digest's own wording rather than doing arithmetic.)
- Your qualitative read (form, momentum, strengths/weaknesses, who's favoured) should stay rich;
  it is ONLY the precise numbers that must be sourced or omitted.

- VENUE: All-Ireland semi-finals and finals are played at NEUTRAL Croke Park — there is NO home
  advantage. The team named first is only the nominal "home" (fixture ordering), not a host.
- Championship knockout matches can go to extra time; a draw after normal time is a real (if
  lower-probability) market outcome.
- Flag anything you are unsure of in knowledge_caveat rather than inventing it.

Always output valid JSON matching the exact schema requested — no markdown fences, no extra keys."""


def _cache_key(home, away, sport):
    base = f"{home.lower().strip()}|{away.lower().strip()}|{sport}|v{PROMPT_VERSION}"
    return hashlib.sha1(base.encode()).hexdigest()[:16]


def _web_search(prompt, max_uses, max_tokens):
    """Web search over the GAA domain whitelist, on the cheap SEARCH_MODEL (Haiku)
    — a SEPARATE rate-limit bucket from the Sonnet analysis, so the token-heavy
    search results don't starve (or 429) the analysis budget. temperature=0 keeps
    the synthesis of results consistent run-to-run."""
    client = _get_search_client()
    tool = {"type": "web_search_20250305", "name": "web_search",
            "max_uses": max_uses, "allowed_domains": GAA_DOMAINS}
    resp = client.messages.create(
        model=SEARCH_MODEL, max_tokens=max_tokens, temperature=0, tools=[tool],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content
                   if getattr(b, "type", None) == "text").strip()


def _research(home, away, sport):
    """TWO focused Haiku searches per game — one for results/form/H2H, one for
    team news/injuries — so the analysis sees the FULL picture and stops flipping
    conclusions between runs. Both on cheap Haiku (separate rate bucket); runs only
    on an intel cache miss (result cached 12h + persisted in Upstash)."""
    today = datetime.now().strftime("%d %B %Y")
    year = datetime.now().year
    form_q = (
        f"As of {today}, for the {year} All-Ireland senior {sport} championship match "
        f"{home} v {away}, give for EACH county:\n"
        f"- their championship results this season with scores (most recent first),\n"
        f"- current form and their main strength and main weakness,\n"
        f"and the recent head-to-head record between {home} and {away}.\n"
        f"Only state what you can source; if unknown, say so. Be concise."
    )
    news_q = (
        f"As of {today}, latest team news for both {home} and {away} senior {sport} "
        f"panels ahead of their {year} All-Ireland championship match: confirmed "
        f"injuries, suspensions, doubts, and any players returning to fitness or the "
        f"starting line-up. One line per player with the source's wording. If no news "
        f"is reported for a county, say so."
    )
    parts = []
    for label, q in (("FORM, RESULTS & HEAD-TO-HEAD", form_q), ("TEAM NEWS & INJURIES", news_q)):
        try:
            txt = _web_search(q, max_uses=3, max_tokens=1200)
            if txt:
                parts.append(f"### {label}\n{txt}")
        except Exception as e:
            print(f"[gaa_intel] {label} search failed for {home} v {away}: {e}")
    return "\n\n".join(parts)


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
Follow the NUMBERS DISCIPLINE: quote a scoreline or exact margin ONLY if it appears verbatim in
the research for that match — otherwise describe it qualitatively ("comfortable double-digit
win", "narrow win"). Never compute a margin or reuse a number across matches.

Output ONLY this JSON:
{{
  "home_form": "{home}'s recent championship form from the research. Quote exact scores/margins ONLY if verbatim in the research; otherwise stay qualitative (do not fabricate or compute numbers). 2-3 sentences.",
  "away_form": "Same for {away}, same numbers discipline. 2-3 sentences.",
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
            model=MODEL, max_tokens=2200, temperature=0, system=SYSTEM_PROMPT,
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
    """Delete the intel disk cache so the next run re-fetches fresh form/injury
    news (used by the manual 'Refresh analysis' action)."""
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
    except Exception as e:
        print(f"[gaa_intel] could not clear {CACHE_FILE}: {e}")
