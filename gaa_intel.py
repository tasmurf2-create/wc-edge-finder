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
PROMPT_VERSION = 6         # bumped: confident analyst voice, no meta/research hedging

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

OUTPUT VOICE — you are writing the finished briefing a paying subscriber reads. Write like a
senior analyst who simply KNOWS the game:
- State facts and your read DIRECTLY and with conviction. Give hard facts and a clear conclusion.
- You will be given background information to work from. NEVER refer to it in your answer. Do not
  use phrases like "the research", "the digest", "the provided data/information", "verbatim",
  "sources", "grounded in", "per the research", "cannot be assessed/grounded", "without deeper
  detail", or "not provided". The reader must NEVER see how you got your information or what you
  were or weren't given. Zero meta-commentary about your inputs.
- Do NOT hedge in every sentence or apologise for missing detail. Be decisive. If one or two
  genuine unknowns actually matter (e.g. a key player's late fitness), mention them briefly in
  knowledge_caveat ONLY — never scatter caveats through the analysis.
- Every field should read as confident expert analysis, not a list of things you can't say.

FACTUAL ACCURACY (an internal rule — obey it, but NEVER mention it or explain it in the output):
- Only state a specific scoreline or exact points margin when you are confident it is genuinely
  correct. Do not invent, compute, round, or reuse a number from one match on another.
- If you're not certain of a precise figure, just describe it naturally in plain analyst language
  — "a commanding double-digit win", "a narrow one-score victory", "a heavy defeat" — with no
  hint that you're avoiding a number. (GAA scoring, for your own reading only: a goal = 3 points.)
- Your qualitative read (form, momentum, strengths, weaknesses, tactical shape, who's favoured)
  should be rich and confident — always give a real tactical read, never refuse one.

VENUE: All-Ireland semi-finals and finals are played at NEUTRAL Croke Park — there is NO home
advantage. The team named first is only the nominal "home" (fixture ordering), not a host.
Championship knockout matches can go to extra time; a draw after normal time is a real (if
lower-probability) market outcome.

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
    research_section = research or "(No extra background available — rely on your own knowledge.)"
    return f"""All-Ireland {sport} match: {home} vs {away}
Competition/stage: {competition}
Throw-in (UTC): {throw_in}
Venue: neutral (Croke Park for semi-finals/finals) — no home advantage.

BACKGROUND FACTS (for your eyes only — write as if you simply know these; NEVER mention them,
quote them as "the research", or say anything is "from the digest"/"verbatim"/"not provided"):
{research_section}

Write the finished analyst briefing. Consider these markets:
- Match Winner (1X2): {home} win | draw | {away} win
- Handicap (points): favourite gives a points start to the underdog (e.g. {home} -6, {away} +6)

Identify the 1-3 outcomes that make genuine GAA sense (a clear reason it is likely/undervalued,
and reasonable risk/reward). Follow the OUTPUT VOICE and FACTUAL ACCURACY rules from your system
prompt: confident, decisive, hard facts, no meta-commentary about your inputs, and don't state a
precise scoreline/margin unless you're sure it's real (otherwise describe it in plain words).

Output ONLY this JSON. Every string must read as a confident expert briefing with no reference to
"research"/"data"/"digest"/"not provided":
{{
  "home_form": "{home}'s recent championship form and momentum, stated confidently. Cite exact scores only if you're sure of them; otherwise describe the results in plain analyst language. 2-3 sentences.",
  "away_form": "Same for {away}. 2-3 sentences.",
  "key_absences": "Notable injuries/suspensions/returns for either side, or 'None reported'. State them plainly; do not invent.",
  "tactical_matchup": "Give a real stylistic read (e.g. running game vs traditional, half-back dominance, puckout battle, pace of attack) and who it favours. Be decisive — always offer a read, never refuse one. 2 sentences.",
  "points_assessment": "Expected scoring level and whether it should be tight or open. High/low-scoring lean, stated with conviction.",
  "market_read": "Which side of match-winner and handicap looks correctly or wrongly priced, and why, from the form/injury read.",
  "recommended_bets": [
    {{
      "market": "match_winner|handicap",
      "outcome": "home_win|draw|away_win|home_-6|away_+6|home_handicap|away_handicap",
      "confidence": "high|medium|low",
      "reasoning": "The GAA reason (not the price) this makes sense. 2 sentences. No 'value'/'best bet' language, no meta-commentary.",
      "strength": "strong|moderate|lean"
    }}
  ],
  "overall_summary": "3 sentences a punter can act on. Lead with the strongest GAA angle (not a 'best bet' — you don't have prices).",
  "intel_confidence": "high|medium|low",
  "knowledge_caveat": "The ONE or two genuine unknowns that most affect this call (e.g. a key player's late fitness). Keep it to real, specific unknowns — not generic 'limited data' hedging."
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
