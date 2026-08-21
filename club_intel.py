#!/usr/bin/env python3
"""
Club-football intelligence layer — Claude analysis for EPL / La Liga / SPFL.

Replaces the World Cup national-team model. Clubs have no FIFA ranking and no
fixed squad list, so grounding is ONE web search per fixture over trusted
league sources (form, table position, team news, head-to-head), which is then
handed to the analyst.

Pipeline per match:
    1. research   — Haiku + web search, restricted to the league's domains
    2. analysis   — Sonnet reads ONLY that research + the price signal
    3. cache      — JSON on disk, TTL-bounded

The output schema is unchanged from the World Cup app (recommended_bets[] with
market/outcome/confidence/reasoning), so the existing frontend renders it as-is.
"""
import os
import json
import time
import hashlib
import threading
import concurrent.futures
from datetime import datetime
from pathlib import Path

import anthropic

import leagues
import names

CACHE_FILE   = Path("intel_cache.json")
SEED_FILE    = Path("intel_seed.json")   # committed seed so a fresh deploy isn't empty
RESEARCH_FILE = Path("research_cache.json")

# Club team news moves fast (lineups ~1h pre-kickoff, injuries daily), but a
# re-analysis costs a search + a Sonnet call per match. 12h is the balance the
# GAA vertical settled on and it held up well.
CACHE_TTL    = 43200      # 12h — full analyst card
RESEARCH_TTL = 21600      # 6h  — the web-search snapshot underneath it

MODEL        = "claude-sonnet-4-6"             # match analysis (reasoning)
SEARCH_MODEL = "claude-haiku-4-5-20251001"     # web-search snapshots — cheaper, and
                                               # a SEPARATE rate-limit bucket so heavy
                                               # searches don't starve the analysis budget.
MAX_RETRIES  = 8

# Bump when the prompt changes in a way that should invalidate cached cards
# (it's part of the cache key, so old entries miss and re-analyse).
#   v1 (2026-08-21): initial club-football prompt.
#   v2 (2026-08-21): attribution discipline — research was mixing clubs up and the
#                    analyst repeated it (named Bournemouth's manager as Liverpool's).
#   v3 (2026-08-21): absence-of-evidence rule — it read "no injuries found" as
#                    "squad fully fit" and built an edge on it.
PROMPT_VERSION = 3

_client = None
_search_client = None
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
    global _search_client
    if _search_client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        _search_client = anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES)
    return _search_client


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def _load_cache():
    # Live cache first; fall back to the committed seed so a fresh deploy still
    # shows analyst cards. The first _save_cache writes CACHE_FILE, which wins after.
    for p in (CACHE_FILE, SEED_FILE):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json(path):
    if Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _cache_key(home, away):
    h, a = names.normalize_team(home), names.normalize_team(away)
    return hashlib.md5(f"{h}|{a}|v{PROMPT_VERSION}".encode()).hexdigest()


def _norm_label(label: str) -> str:
    """Normalize both club names in 'Home vs Away' for cache-key matching."""
    parts = label.split(" vs ", 1)
    if len(parts) == 2:
        return f"{names.normalize_team(parts[0])} vs {names.normalize_team(parts[1])}"
    return label.lower()


def invalidate_match_cache(pairs):
    """Drop the cached card for each (home, away) so it re-analyses next fetch.
    Returns the number of entries removed."""
    with _io_lock:
        cache = _load_cache()
        removed = 0
        for home, away in pairs:
            if cache.pop(_cache_key(home, away), None) is not None:
                removed += 1
        if removed:
            _save_cache(cache)
    return removed


def clear_research():
    """Drop every cached web-search snapshot so the next analysis re-searches.
    Used by the manual team-news refresh."""
    with _io_lock:
        if RESEARCH_FILE.exists():
            _save_json(RESEARCH_FILE, {})


def load_intel_from_disk():
    """All cached analyst cards keyed by 'Home vs Away' label, for warm start."""
    with _io_lock:
        cache = _load_cache()
    out = {}
    for entry in cache.values():
        label = entry.get("label")
        intel = entry.get("intel")
        if label and intel:
            out[label] = intel
            out[_norm_label(label)] = intel
    return out


# ---------------------------------------------------------------------------
# Step 1 — research (ONE web search per fixture)
# ---------------------------------------------------------------------------

def _research_key(home, away):
    return hashlib.md5(
        f"{names.normalize_team(home)}|{names.normalize_team(away)}".encode()
    ).hexdigest()


def _research_query(home, away, league_name, commence):
    today = datetime.now().strftime("%d %B %Y")
    return f"""Today is {today}. Research the upcoming {league_name} match: {home} vs {away}.

Report ONLY what you can verify from the sources. Be concise and factual — this is
input for an analyst, not prose. Cover:

1. {home} — last 5 league results (score + opponent + home/away), current league
   position and points.
2. {away} — same.
3. Team news for BOTH: confirmed injuries, suspensions, doubts, and any expected
   return. Name players.
4. Head-to-head: last 2-3 meetings with scores.
5. Anything else genuinely decisive (manager change, European fixture 3 days prior,
   must-win context, long unbeaten/winless run).

If you cannot verify something, write "not found" for that item — do NOT guess a
scoreline, a table position or an injury. Accuracy matters far more than completeness.

CRITICAL — attribute every fact to the correct club. Search results for one fixture
often surface articles about other teams. Before you write a detail, confirm it is
about {home} or {away} specifically. Never carry a manager name, injury or result
across from an article about a different club. If a source is ambiguous about which
club it refers to, leave the item out entirely."""


def get_research(home, away, league_key, commence, force=False):
    """Cached web-search snapshot of club context. One search per fixture."""
    rk = _research_key(home, away)
    if not force:
        with _io_lock:
            store = _load_json(RESEARCH_FILE)
        entry = store.get(rk)
        if entry and (time.time() - entry.get("fetched_at", 0)) < RESEARCH_TTL:
            return entry.get("text", "")

    league_name = leagues.league_name(league_key) or "league"
    domains = leagues.domains_for(league_key)
    try:
        client = _get_search_client()
        tool = {"type": "web_search_20250305", "name": "web_search",
                "max_uses": 4, "allowed_domains": domains}
        resp = client.messages.create(
            model=SEARCH_MODEL,
            max_tokens=1400,
            tools=[tool],
            messages=[{"role": "user",
                       "content": _research_query(home, away, league_name, commence)}],
        )
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", None) == "text").strip()
    except Exception as e:
        print(f"[research] {home} vs {away} failed: {e}")
        return ""

    if text:
        with _io_lock:
            store = _load_json(RESEARCH_FILE)
            store[rk] = {"text": text, "fetched_at": int(time.time()),
                         "label": f"{home} vs {away}"}
            _save_json(RESEARCH_FILE, store)
    return text


# ---------------------------------------------------------------------------
# Step 2 — analysis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior football analyst covering the Premier League, La Liga and the
Scottish Premiership. You think like a professional gambler: you identify which outcomes make
genuine football sense across the available markets (match result, goals totals, Asian handicap).

Stay in your lane — you give the FOOTBALL read, NOT the value verdict. Prices and edges are
computed separately, so:
- You do NOT have reliable odds. Never crown a "best bet" or call anything "value". Rank outcomes
  by football logic only; let the price layer judge value.
- No absolutes like "no chance" — say low-probability, would need a big price.
- Weigh the favourite's WEAKNESSES too (defensive frailty, over-reliance on one striker, injuries,
  European hangover, congested fixture list), not just their strengths.

NUMBERS DISCIPLINE — this is the rule you break most often, so read it twice:
- Cite ONLY scorelines, table positions, run-lengths and player names that appear in the material
  you are given. If it is not there, you do not know it.
- NEVER invent a scoreline, a goal tally, a points total, a league position or an xG figure.
- If you lack a fact, write around it or say the picture is unclear — do not fill the gap with a
  plausible-sounding number. A vague-but-true sentence beats a specific-but-invented one.

ATTRIBUTION DISCIPLINE — the background you are given is assembled from multiple articles and
SOMETIMES MIXES CLUBS UP. It is your job to catch that, not repeat it:
- Before stating that a player, manager or result belongs to a club, check it is actually plausible
  for THAT club. If a detail looks like it belongs to a different team, drop it silently.
- NEVER name a manager unless you are independently confident they manage that club right now.
  Managers change constantly and a wrong name destroys the reader's trust in everything else.
  Write "the manager" / "a new appointment" rather than risk a wrong name.
- The same applies to signings and squad membership: if you are not sure a player is at that club
  this season, do not use them.

ABSENCE OF EVIDENCE IS NOT EVIDENCE OF ABSENCE — this one costs readers money:
- If no team news is listed for a side, that means it was NOT FOUND, not that the squad is fit.
  Write "no absentees confirmed" or "team news unclear" — NEVER "they have a clean bill of health"
  or "no injury concerns", and never build an argument on a side being at full strength.
- Do not treat one side's listed injuries plus another side's missing data as an advantage to the
  second side. That asymmetry is a gap in the information, not a football edge.

OUTPUT VOICE — you are writing the finished briefing a paying subscriber reads. Write like a
senior analyst who simply KNOWS the game:
- State facts and your read DIRECTLY and with conviction. Give a clear conclusion.
- You will be given background information to work from. NEVER refer to it in your answer. Do not
  use phrases like "the research", "the provided data/information", "sources", "grounded in",
  "per the research", "cannot be assessed", "without deeper detail", or "not provided". The reader
  must NEVER see how you got your information or what you were or weren't given. Zero
  meta-commentary about your inputs.
- Do NOT hedge in every sentence or apologise for missing detail. Be decisive.

Output STRICT JSON only — no markdown fence, no preamble."""


def _build_prompt(home, away, league_name, commence, research, price_notes):
    research_section = (
        f"BACKGROUND (form, table, team news, head-to-head):\n{research}\n"
        if research else
        "BACKGROUND: none available — rely on general knowledge of these clubs and say plainly "
        "where the picture is unclear. Do NOT invent recent results or team news.\n"
    )
    return f"""{league_name} match: {home} vs {away} (kick-off UTC: {commence})

{research_section}
BOOKMAKER PRICE SIGNAL (context only — your recommendation must be driven by football logic first):
{price_notes}

Analyse this match as a professional gambler. Consider ALL these markets:
- Match result (1X2): {home} win | draw | {away} win
- Goals: over 2.5 | under 2.5 | over 1.5 | under 1.5
- Asian handicap — EITHER team can take EITHER side:
    a team at -1.5 must WIN BY 2+        a team at +1.5 wins, draws, or loses by 1
    a team at -0.5 must WIN              a team at +0.5 wins or draws
  Give the NEGATIVE line to the side you expect to win by that margin — whichever team is the
  favourite, HOME OR AWAY. CRITICAL: if {away} is the favourite, the line is {away} -1.5
  (token away_-1.5), NOT {away} +1.5. Do not flip the sign.

Identify the 1-3 outcomes that make genuine football sense. An outcome qualifies if:
  (a) there is a clear footballing reason it is likely or undervalued, AND
  (b) the risk/reward is reasonable given what you know

Weigh what actually decides club matches: current form and momentum, home advantage (real but
league-dependent — it is worth more at Ibrox or Anfield than at a mid-table ground), squad
availability, fixture congestion and European involvement, motivation (title race, relegation
scrap, dead rubber), and style matchup (a high line against pace, a low block against a side with
no creativity to break it).

Output ONLY this JSON:
{{
  "home_form": "{home}'s current form and league standing — cite only results/positions you actually know. 2-3 sentences.",
  "away_form": "Same for {away}. 2-3 sentences.",
  "key_absences": "Injuries/suspensions that matter for either side. If a side's team news was not available say 'no absentees confirmed for X' — never claim a side is fully fit. Name players only if you are confident they are at that club. Do not invent.",
  "h2h_context": "Recent meetings between these clubs and whether the pattern is meaningful, or 'no reliable head-to-head'. 1-2 sentences.",
  "tactical_matchup": "How these two sides match up stylistically and who it favours. 2 sentences.",
  "goals_assessment": "Expected goal total reasoned from both sides' attacking and defensive quality. Over/under 2.5 call. BTTS view.",
  "market_read": "Which side of each market (1X2, totals, handicap) looks correctly priced or mispriced on the football read.",
  "recommended_bets": [
    {{
      "market": "h2h|totals|spreads",
      "outcome": "home_win|draw|away_win|over_2.5|under_2.5|over_1.5|under_1.5|home_-0.5|home_-1|home_-1.5|home_-2|home_+0.5|home_+1|home_+1.5|home_+2|away_-0.5|away_-1|away_-1.5|away_-2|away_+0.5|away_+1|away_+1.5|away_+2",
      "confidence": "high|medium|low",
      "reasoning": "The football reason — not the price — why this outcome makes sense. 2 sentences. Do not cite stats you were not given, and do not claim value or 'best bet'.",
      "strength": "strong|moderate|lean"
    }}
  ],
  "overall_summary": "3 sentences a punter can act on. Lead with the strongest FOOTBALL angle (not a 'best bet' — you don't have prices).",
  "intel_confidence": "high|medium|low",
  "knowledge_caveat": "What you don't know that matters most."
}}

Include 1 to 3 items in recommended_bets. Only include bets with genuine football logic.
If no outcome has a clear edge, return an empty array and explain in overall_summary."""


def get_match_intel(home, away, commence, league_key=None,
                    price_notes="No price signal.", force=False):
    """Football intelligence for one fixture. Cached for CACHE_TTL seconds.
    Returns None if the API key is missing or the call fails."""
    ck = _cache_key(home, away)
    if not force:
        with _io_lock:
            entry = _load_cache().get(ck)
        if entry and (time.time() - entry.get("cached_at", 0)) < CACHE_TTL:
            return entry["intel"]

    league_name = leagues.league_name(league_key) or "League"
    research = get_research(home, away, league_key, commence, force=force)

    try:
        client = _get_client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2800,   # verbose matches truncate the JSON below this
            system=SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": _build_prompt(home, away, league_name,
                                                commence, research, price_notes)}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        intel = json.loads(raw.strip())
        intel["cached_at"]  = int(time.time())
        intel["commence"]   = commence
        intel["league"]     = league_name
        intel["league_key"] = league_key
        intel["has_research"] = bool(research)

        with _io_lock:
            cache = _load_cache()
            cache[ck] = {"intel": intel, "cached_at": int(time.time()),
                         "label": f"{home} vs {away}"}
            _save_cache(cache)
        return intel

    except Exception as e:
        print(f"[intel] {home} vs {away} failed: {e}")
        return None


def get_intel_batch(match_list, max_calls=15, on_result=None):
    """
    Fetch intel for a list of dicts with keys: home, away, commence, league_key,
    price_notes. Returns {cache_key: intel_dict}.
    Caps fresh matches at max_calls; serves the rest from cache.

    on_result(label, intel) is called as EACH card lands, so the UI can fill in
    one match at a time instead of waiting for the whole batch — a full matchweek
    is ~24 serial Sonnet calls, which is many minutes end to end.
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

    # Concurrency is capped by INTEL_WORKERS (default 1). On Tier-1 limits,
    # serialising the Sonnet analysis is actually fastest end-to-end: parallel
    # calls all 429, then each burns its retry budget re-sending tokens, which
    # saturates the shared 30k/min bucket and makes *everything* fail. One at a
    # time stays under the limit and completes. Bump on a higher API tier.
    workers = max(1, min(int(os.environ.get("INTEL_WORKERS", "1")), len(to_fetch)))
    print(f"[intel] {len(results)} from cache, {len(to_fetch)} fresh "
          f"({workers} worker{'s' if workers > 1 else ''})")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(get_match_intel, m["home"], m["away"], m.get("commence", ""),
                      m.get("league_key"), m.get("price_notes", "No price signal.")): m
            for m in to_fetch
        }
        for f in concurrent.futures.as_completed(futs):
            m = futs[f]
            label = f"{m['home']} vs {m['away']}"
            try:
                intel = f.result()
                if intel:
                    results[_cache_key(m["home"], m["away"])] = intel
                    print(f"[intel] {label} ok")
                    if on_result:
                        try:
                            on_result(label, intel)
                        except Exception as cb_err:
                            print(f"[intel] publish {label} failed: {cb_err}")
            except Exception as e:
                print(f"[intel] {label} failed: {e}")
    return results


def intel_status():
    """Cache/freshness summary for /api/status."""
    with _io_lock:
        cache = _load_cache()
        research = _load_json(RESEARCH_FILE)
    newest = max((e.get("cached_at", 0) for e in cache.values()), default=0)
    return {
        "cards": len(cache),
        "research_snapshots": len(research),
        "newest_card_age_h": round((time.time() - newest) / 3600, 1) if newest else None,
        "model": MODEL,
        "search_model": SEARCH_MODEL,
        "prompt_version": PROMPT_VERSION,
        "key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


if __name__ == "__main__":
    import sys
    h = sys.argv[1] if len(sys.argv) > 2 else "Arsenal"
    a = sys.argv[2] if len(sys.argv) > 2 else "Coventry City"
    lk = sys.argv[3] if len(sys.argv) > 3 else "soccer_epl"
    print(f"--- research: {h} vs {a} ({leagues.league_name(lk)}) ---")
    r = get_research(h, a, lk, "")
    print(r or "(none)")
    print("\n--- analysis ---")
    intel = get_match_intel(h, a, "", league_key=lk)
    print(json.dumps(intel, indent=2, ensure_ascii=False) if intel else "FAILED")
