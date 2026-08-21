#!/usr/bin/env python3
"""
Club-name normalisation.

Odds feeds, news sources and the analyst all spell the same club differently
("Man Utd" / "Manchester United", "Spurs" / "Tottenham Hotspur", "Falkirk F.C."
/ "Falkirk"). Everything is mapped to ONE canonical token so a club lines up
across sources.

Canonical form: lowercase, accent-stripped, punctuation-collapsed, with common
club affixes (FC, AFC, CF, RCD, ...) removed, then aliased.

    normalize_team("Man Utd")            -> "manchester united"
    normalize_team("Atlético Madrid")    -> "atletico madrid"
    normalize_team("Falkirk F.C.")       -> "falkirk"
    match_key("Celtic", "Rangers")       -> frozenset({"celtic", "rangers"})

Zero dependencies (stdlib only).
"""
import re
import unicodedata

# Club affixes that carry no identity — dropped before aliasing. "Real",
# "Athletic" and "Sporting" are NOT here: they distinguish real clubs
# (Real Sociedad vs Sociedad, Athletic Bilbao vs Bilbao).
_AFFIXES = {
    "fc", "afc", "cf", "sc", "ac", "sd", "rcd", "cd", "ud", "rc", "club",
    "calcio", "cp", "sad",
}

# Canonical spelling -> the variants seen in the wild.
_ALIAS_GROUPS = {
    # ---- Premier League ----
    "manchester united":   ["man united", "man utd", "manutd", "man u"],
    "manchester city":     ["man city", "mancity"],
    "tottenham hotspur":   ["tottenham", "spurs"],
    "wolverhampton wanderers": ["wolves", "wolverhampton"],
    "brighton and hove albion": ["brighton", "brighton hove albion",
                                 "brighton & hove albion"],
    "newcastle united":    ["newcastle"],
    "west ham united":     ["west ham"],
    "nottingham forest":   ["nottm forest", "forest"],
    "leeds united":        ["leeds"],
    "bournemouth":         ["afc bournemouth"],
    "leicester city":      ["leicester"],
    "ipswich town":        ["ipswich"],
    "coventry city":       ["coventry"],
    "hull city":           ["hull"],
    "sheffield united":    ["sheffield utd"],
    "sheffield wednesday": ["sheffield weds"],
    "crystal palace":      ["palace"],
    "aston villa":         ["villa"],
    "west bromwich albion": ["west brom", "wba"],

    # ---- La Liga ----
    "atletico madrid":     ["atletico de madrid", "atleti", "atl madrid",
                            "club atletico de madrid"],
    "real betis":          ["betis", "real betis balompie"],
    "athletic bilbao":     ["athletic club", "athletic club bilbao"],
    "celta vigo":          ["celta", "celta de vigo", "rc celta"],
    "deportivo alaves":    ["alaves"],
    "real sociedad":       ["sociedad", "real sociedad de futbol"],
    "barcelona":           ["fc barcelona", "barca"],
    "real madrid":         ["real madrid cf"],
    "rayo vallecano":      ["rayo"],
    "sevilla":             ["sevilla fc"],
    "valencia":            ["valencia cf"],
    "villarreal":          ["villarreal cf"],
    "girona":              ["girona fc"],
    "getafe":              ["getafe cf"],
    "osasuna":             ["ca osasuna", "club atletico osasuna"],
    "mallorca":            ["rcd mallorca", "real mallorca"],
    "espanyol":            ["rcd espanyol", "espanyol barcelona"],
    "real oviedo":         ["oviedo"],
    "racing santander":    ["real racing club de santander", "racing de santander",
                            "real racing club"],
    "deportivo la coruna": ["deportivo", "depor", "rc deportivo"],
    "levante":             ["levante ud"],
    "elche":               ["elche cf"],

    # ---- Scottish Premiership ----
    "heart of midlothian": ["hearts"],
    "hibernian":           ["hibs"],
    "st johnstone":        ["saint johnstone"],
    "st mirren":           ["saint mirren"],
    "dundee united":       ["dundee utd"],
    "ross county":         ["county"],
    "greenock morton":     ["morton"],
    "queens park":         ["queen park"],
}

# Flattened variant -> canonical
ALIASES = {}
for _canon, _variants in _ALIAS_GROUPS.items():
    for _v in _variants:
        ALIASES[_v] = _canon


def _strip_affixes(tokens):
    """Drop leading/trailing club affixes ('afc bournemouth' -> 'bournemouth').
    Only trims the ends: an affix mid-name is usually part of the identity."""
    t = list(tokens)
    while t and t[0] in _AFFIXES:
        t.pop(0)
    while t and t[-1] in _AFFIXES:
        t.pop()
    return t or list(tokens)   # never normalise a name away to nothing


def normalize_team(name: str) -> str:
    """Lowercase, strip accents/punctuation, drop club affixes, apply aliases."""
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    # Dots/apostrophes close up ("F.C." -> "fc", "Queen's" -> "queens");
    # other punctuation splits ("Hove-Albion" -> "hove albion").
    n = re.sub(r"[.'’]", "", n)
    n = re.sub(r"[^a-zA-Z0-9\s]", " ", n).lower()
    tokens = n.split()
    tokens = _strip_affixes(tokens)
    n = " ".join(tokens)
    # alias in two passes: raw form first, then affix-stripped form
    return ALIASES.get(n, n)


def match_key(a: str, b: str):
    """Order-independent key for a fixture."""
    return frozenset({normalize_team(a), normalize_team(b)})


def is_draw(label: str) -> bool:
    return normalize_team(label) in ("draw", "tie", "draw tie")


# Back-compat alias — the pipeline historically called the underscore form.
_is_draw = is_draw


def display_name(name: str) -> str:
    """Title-cased canonical name for UI/prompt use ('man utd' ->
    'Manchester United'). Falls back to the input when unknown."""
    canon = normalize_team(name)
    if not canon:
        return name or ""
    return " ".join(w.capitalize() for w in canon.split())


if __name__ == "__main__":
    checks = [
        ("Man Utd", "manchester united"), ("Manchester United", "manchester united"),
        ("Spurs", "tottenham hotspur"), ("Tottenham Hotspur", "tottenham hotspur"),
        ("Atlético Madrid", "atletico madrid"), ("Atletico Madrid", "atletico madrid"),
        ("Falkirk F.C.", "falkirk"), ("AFC Bournemouth", "bournemouth"),
        ("Hearts", "heart of midlothian"), ("Brighton", "brighton and hove albion"),
        ("FC Barcelona", "barcelona"), ("Celta Vigo", "celta vigo"),
        ("Wolves", "wolverhampton wanderers"), ("Real Sociedad", "real sociedad"),
        ("Draw", "draw"),
    ]
    bad = 0
    for raw, want in checks:
        got = normalize_team(raw)
        ok = got == want
        bad += not ok
        print(f"{'ok ' if ok else 'FAIL'} {raw!r:26} -> {got!r}" + ("" if ok else f"  (want {want!r})"))
    print(f"\n{len(checks)-bad}/{len(checks)} passed")
