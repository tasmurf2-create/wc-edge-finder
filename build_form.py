#!/usr/bin/env python3
"""
Build data/team_form.csv from the open international-results dataset.

Run manually to refresh (e.g. before the tournament / after a matchday):
    python build_form.py

It downloads ALL international results once, computes each WC team's recent
form from PLAYED matches, and writes a small local CSV. The app then reads that
CSV at analysis time — NO per-analysis web query.

During the tournament the server also calls compute_form()/write_form_csv()
itself (see football_intel.refresh_team_form) so freshly played WC results feed
the analyst without a manual rebuild.

Source: https://github.com/martj42/international_results  (public, no API key)
"""
import csv, io, urllib.request
from pathlib import Path
import static_data as sd

URL   = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
LAST_N = 8          # results to summarise per team
RECENT = 6          # detailed results to list
OUT   = Path(__file__).parent / "data" / "team_form.csv"
FIELDS = ["fifa_code", "as_of", "form", "record", "gf", "ga", "recent"]

# The 48 WC teams, by fifa_code (from the sourced teams list)
WC_CODES = {sd.team_code(t["country_name"]) or sd.team_code(t["team_name"])
            for t in sd._read("teams.csv")}
WC_CODES.discard(None)


def compute_form():
    """Download the international-results dataset and compute each WC team's
    recent form. Pure (no file write) so the server can diff against the current
    CSV before overwriting. Returns (as_of, {fifa_code: row_dict}) where row_dict
    has the keys form/record/gf/ga/recent."""
    raw = urllib.request.urlopen(URL, timeout=60).read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(raw)))
    played = [r for r in rows
              if r["home_score"].strip() not in ("", "NA")
              and r["away_score"].strip() not in ("", "NA")]
    played.sort(key=lambda r: r["date"])
    as_of = played[-1]["date"] if played else ""

    # Collect each WC team's matches (by mapping dataset names -> fifa_code)
    by_team = {c: [] for c in WC_CODES}
    for r in played:
        hc, ac = sd.team_code(r["home_team"]), sd.team_code(r["away_team"])
        for code, opp_name, gf, ga, loc in (
            (hc, r["away_team"], r["home_score"], r["away_score"], "H"),
            (ac, r["home_team"], r["away_score"], r["home_score"], "A"),
        ):
            if code in by_team:
                neutral = str(r.get("neutral", "")).strip().upper() == "TRUE"
                by_team[code].append({
                    "date": r["date"], "gf": int(gf), "ga": int(ga),
                    "opp": opp_name, "loc": "N" if neutral else loc,
                    "comp": r["tournament"],
                })

    by_code = {}
    for code in sorted(by_team):
        ms = by_team[code][-LAST_N:]
        if not ms:
            continue
        form = "".join("W" if m["gf"] > m["ga"] else "D" if m["gf"] == m["ga"] else "L" for m in ms)
        wdl = (form.count("W"), form.count("D"), form.count("L"))
        gf = sum(m["gf"] for m in ms); ga = sum(m["ga"] for m in ms)
        recent = "; ".join(
            f'{m["gf"]}-{m["ga"]} {m["opp"]} ({m["loc"]}, {m["comp"]})'
            for m in ms[-RECENT:]
        )
        by_code[code] = {"form": form, "record": f"{wdl[0]}W-{wdl[1]}D-{wdl[2]}L",
                         "gf": gf, "ga": ga, "recent": recent}
    return as_of, by_code


def read_form_csv():
    """Current team_form.csv as {fifa_code: row_dict}, or {} if missing.
    Used to diff against a freshly computed form so the server can re-analyse
    only the teams whose form actually changed."""
    if not OUT.exists():
        return {}
    with open(OUT, encoding="utf-8") as f:
        return {r["fifa_code"]: r for r in csv.DictReader(f)}


def write_form_csv(as_of, by_code):
    """Write {fifa_code: row_dict} to data/team_form.csv (sorted by code)."""
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for code in sorted(by_code):
            row = by_code[code]
            w.writerow([code, as_of, row["form"], row["record"],
                        row["gf"], row["ga"], row["recent"]])


def main():
    print("downloading results.csv ...")
    as_of, by_code = compute_form()
    print(f"latest played {as_of}")
    write_form_csv(as_of, by_code)
    print(f"wrote {OUT} for {len(by_code)} teams")


if __name__ == "__main__":
    main()
