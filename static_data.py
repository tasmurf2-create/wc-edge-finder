#!/usr/bin/env python3
"""
Static WC 2026 reference data loaded from /data CSVs (sourced from official FIFA
squad/schedule PDFs + compiled climate tables). Read once at import; never changes.

Provides:
  team_code(name)        -> FIFA code for an odds-feed team name (alias-aware)
  team_climate(name)     -> {avg_temp_c, elevation_m, ...} from teams.csv
  venue_for_teams(h, a)  -> {match, venue} real fixture + stadium conditions
  squad(name)            -> list of player dicts from players.csv
"""
import csv
import re
import unicodedata
from pathlib import Path

DATA = Path(__file__).parent / "data"


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _read(name):
    p = DATA / name
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---- teams ----------------------------------------------------------------
_teams = {}        # fifa_code -> row
_name2code = {}     # normalized name -> fifa_code
for t in _read("teams.csv"):
    _teams[t["fifa_code"]] = t
    _name2code[_norm(t["team_name"])] = t["fifa_code"]
    _name2code[_norm(t.get("country_name", ""))] = t["fifa_code"]

# Odds-feed / common name variants -> FIFA code
_ALIASES = {
    "southkorea": "KOR", "korearepublic": "KOR", "korea": "KOR",
    "czechrepublic": "CZE", "czechia": "CZE",
    "unitedstates": "USA", "usa": "USA", "unitedstatesofamerica": "USA",
    "turkey": "TUR", "turkiye": "TUR",
    "ivorycoast": "CIV", "cotedivoire": "CIV",
    "iran": "IRN", "iriran": "IRN",
    "capeverde": "CPV", "caboverde": "CPV", "capeverdeislands": "CPV",
    "drcongo": "COD", "congodr": "COD", "democraticrepublicofthecongo": "COD",
    "bosniaherzegovina": "BIH", "bosniaandherzegovina": "BIH",
    "curacao": "CUW", "curaaao": "CUW",  # 2nd covers a cedilla-mangling encoding path
}
for k, v in _ALIASES.items():
    _name2code.setdefault(k, v)


def team_code(name):
    return _name2code.get(_norm(name))


# ---- FIFA world ranking (team_facts.csv) ----------------------------------
_facts = {r["fifa_code"]: r for r in _read("team_facts.csv")}


def team_rank(name):
    """Current FIFA world ranking position for a team, or None if unknown."""
    code = team_code(name)
    row = _facts.get(code) if code else None
    if not row:
        return None
    try:
        return int(row["fifa_rank"])
    except (ValueError, KeyError, TypeError):
        return None


# ---- recent form (team_form.csv, built by build_form.py) -------------------
_form = {r["fifa_code"]: r for r in _read("team_form.csv")}


def team_form_text(name):
    """Sourced recent-form summary for the analyst prompt, or '' if unknown.
    Built offline from the international-results dataset (no live query)."""
    code = team_code(name)
    r = _form.get(code) if code else None
    if not r:
        return ""
    n = len(r.get("form", ""))
    return (f"RECENT FORM (last {n}, to {r['as_of']}, SOURCED): {r['form']} "
            f"({r['record']}; GF {r['gf']} / GA {r['ga']}). "
            f"Latest: {r['recent']}")


def team_climate(name):
    code = team_code(name)
    if not code:
        return None
    t = _teams[code]
    try:
        return {
            "fifa_code": code,
            "name": t["team_name"],
            "avg_temp_c": float(t["average_annual_temp_c"]),
            "elevation_m": float(t["mean_elevation_m"]),
            "group": t.get("group_letter"),
        }
    except (ValueError, KeyError):
        return None


# ---- venues ---------------------------------------------------------------
_venues = {v["venue_key"]: v for v in _read("venues.csv")}


def _venue_conditions(v):
    def f(key):
        try:
            return float(v[key])
        except (ValueError, KeyError, TypeError):
            return None
    return {
        "venue_key":    v["venue_key"],
        "stadium":      v.get("stadium"),
        "city":         v.get("display_city"),
        "timezone":     v.get("timezone"),
        "latitude":     f("latitude"),
        "longitude":    f("longitude"),
        "altitude_m":   f("altitude_m"),
        "avg_temp_june_c": f("avg_temp_june_c"),
        "avg_temp_july_c": f("avg_temp_july_c"),
        "has_roof":     str(v.get("has_roof", "0")).strip() in ("1", "true", "True"),
    }


# ---- matches --------------------------------------------------------------
_match_venue = {}   # frozenset({home_code, away_code}) -> match row
for m in _read("matches.csv"):
    h, a = m.get("home_team_code"), m.get("away_team_code")
    if h and a:
        _match_venue[frozenset((h, a))] = m


# ---- rounds (sourced from matches.csv stage + derived group matchday) -------
_match_round = {}   # frozenset({home_code, away_code}) -> (label, order)
_KO_ORDER = {
    "Round of 32": 4, "Round of 16": 5, "Quarter-final": 6, "Quarter-finals": 6,
    "Semi-final": 7, "Semi-finals": 7, "Third Place Playoff": 8, "Final": 9,
}


def _build_rounds():
    from collections import defaultdict
    rows = _read("matches.csv")
    groups = defaultdict(list)
    for m in rows:
        if m.get("stage") == "Group Stage" and m.get("group_letter"):
            groups[m["group_letter"]].append(m)
        else:
            h, a = m.get("home_team_code"), m.get("away_team_code")
            if h and a:
                st = m.get("stage", "")
                _match_round[frozenset((h, a))] = (st, _KO_ORDER.get(st, 10))
    # Group stage: sort each group's 6 matches by kickoff, 2 per matchday.
    for g, ms in groups.items():
        ms.sort(key=lambda m: m.get("kickoff_utc", ""))
        for i, m in enumerate(ms):
            md = i // 2 + 1
            h, a = m.get("home_team_code"), m.get("away_team_code")
            if h and a:
                _match_round[frozenset((h, a))] = (f"Group Stage R{md}", md)


_build_rounds()


def match_round(home, away):
    """(label, order) for a fixture, sourced from the schedule — or None."""
    hc, ac = team_code(home), team_code(away)
    if not hc or not ac:
        return None
    return _match_round.get(frozenset((hc, ac)))


def venue_for_teams(home, away):
    """Real fixture + stadium conditions for a match, or None if unmatched."""
    hc, ac = team_code(home), team_code(away)
    if not hc or not ac:
        return None
    m = _match_venue.get(frozenset((hc, ac)))
    if not m:
        return None
    v = _venues.get(m["venue_key"])
    if not v:
        return None
    return {"match": m, "venue": _venue_conditions(v)}


# ---- squads ---------------------------------------------------------------
_squads = {}        # fifa_code -> [player rows]
for p in _read("players.csv"):
    _squads.setdefault(p["team_code"], []).append(p)


def squad(name):
    code = team_code(name)
    return _squads.get(code, []) if code else []


def _age_from_dob(dob):
    try:
        d, m, y = dob.split("/")
        from datetime import date
        b = date(int(y), int(m), int(d))
        today = date(2026, 6, 11)   # tournament start
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    except Exception:
        return None


def squad_text(name):
    """Concise, sourced squad block for the analyst prompt — by position, with
    club and age. From the official FIFA squad list (players.csv)."""
    sq = squad(name)
    if not sq:
        return ""
    from collections import defaultdict
    groups = defaultdict(list)
    for p in sq:
        groups[p.get("position", "?")].append(p)
    lines = []
    for pos in ("GK", "DF", "MF", "FW"):
        items = []
        for p in groups.get(pos, []):
            nm = (p.get("name_on_shirt") or p.get("player_name") or "").strip()
            club = (p.get("club") or "").strip()
            age = _age_from_dob(p.get("dob", ""))
            items.append(f"{nm} ({club}{', ' + str(age) if age else ''})")
        if items:
            lines.append(f"{pos}: " + "; ".join(items))
    return "\n".join(lines)


def squad_league_countries(name):
    """Distribution of league-country codes the squad's players are based in
    (e.g. {'FRA': 8, 'ENG': 7}) — proxy for what climate they're acclimatised to."""
    out = {}
    for p in squad(name):
        m = re.search(r"\(([A-Z]{3})\)", p.get("club", ""))
        if m:
            out[m.group(1)] = out.get(m.group(1), 0) + 1
    return out


if __name__ == "__main__":
    print("teams:", len(_teams), "venues:", len(_venues),
          "fixtures:", len(_match_venue), "squads:", len(_squads))
    for h, a in [("Brazil", "Haiti"), ("Switzerland", "Qatar"), ("South Korea", "Czech Republic")]:
        r = venue_for_teams(h, a)
        v = r["venue"] if r else None
        print(f"{h} vs {a}: ", v["stadium"] if v else "NO MATCH",
              "|", v["city"] if v else "", "| alt", v["altitude_m"] if v else "",
              "| Jun", v["avg_temp_june_c"] if v else "", "| roof", v["has_roof"] if v else "")
