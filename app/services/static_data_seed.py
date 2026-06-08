from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db
from app.models import (
    Country,
    Fixture,
    FixtureTeam,
    Market,
    Player,
    SquadMembership,
    SquadPlayer,
    Team,
    Venue,
    WorldCupFixture,
    WorldCupTeam,
    WorldCupVenue,
)


TEAMS = [
    ("Algeria", "ALG", "J", 22.5, 800), ("Argentina", "ARG", "J", 14.8, 595),
    ("Australia", "AUS", "D", 21.7, 330), ("Austria", "AUT", "J", 7.0, 910),
    ("Belgium", "BEL", "G", 10.5, 181), ("Bosnia & Herzegovina", "BIH", "B", 10.1, 500),
    ("Brazil", "BRA", "C", 24.9, 320), ("Cape Verde", "CPV", "H", 24.0, 400),
    ("Canada", "CAN", "B", -5.4, 487), ("Colombia", "COL", "K", 24.8, 593),
    ("DR Congo", "COD", "K", 24.0, 726), ("Ivory Coast", "CIV", "E", 26.4, 250),
    ("Croatia", "CRO", "L", 11.9, 331), ("Curaçao", "CUW", "E", 27.5, 10),
    ("Czech Republic", "CZE", "A", 8.9, 430), ("Ecuador", "ECU", "E", 21.8, 1117),
    ("Egypt", "EGY", "G", 22.1, 321), ("England", "ENG", "L", 10.4, 162),
    ("France", "FRA", "I", 11.7, 375), ("Germany", "GER", "E", 9.6, 263),
    ("Ghana", "GHA", "L", 27.2, 190), ("Haiti", "HAI", "C", 24.9, 470),
    ("Iran", "IRN", "G", 17.3, 1305), ("Iraq", "IRQ", "I", 21.4, 312),
    ("Japan", "JPN", "F", 11.2, 438), ("Jordan", "JOR", "J", 18.3, 812),
    ("South Korea", "KOR", "A", 12.5, 282), ("Mexico", "MEX", "A", 21.0, 1111),
    ("Morocco", "MAR", "C", 18.0, 909), ("Netherlands", "NED", "F", 10.4, 30),
    ("New Zealand", "NZL", "G", 10.6, 388), ("Norway", "NOR", "I", 1.5, 460),
    ("Panama", "PAN", "L", 25.4, 360), ("Paraguay", "PAR", "D", 23.0, 178),
    ("Portugal", "POR", "K", 15.8, 372), ("Qatar", "QAT", "B", 27.0, 28),
    ("Saudi Arabia", "KSA", "H", 25.4, 665), ("Scotland", "SCO", "C", 8.5, 162),
    ("Senegal", "SEN", "I", 27.0, 69), ("South Africa", "RSA", "A", 17.5, 1034),
    ("Spain", "ESP", "H", 13.3, 660), ("Sweden", "SWE", "F", 2.1, 320),
    ("Switzerland", "SUI", "B", 6.5, 1350), ("Tunisia", "TUN", "F", 19.2, 246),
    ("Turkey", "TUR", "D", 11.1, 1132), ("Uruguay", "URU", "H", 17.6, 109),
    ("USA", "USA", "D", 8.6, 760), ("Uzbekistan", "UZB", "K", 13.0, 450),
]

VENUES = [
    ("Estadio Azteca", "Mexico City", "Mexico", "America/Mexico_City", 2240),
    ("Estadio Akron", "Guadalajara", "Mexico", "America/Mexico_City", 1566),
    ("Estadio BBVA", "Monterrey", "Mexico", "America/Monterrey", 540),
    ("BMO Field", "Toronto", "Canada", "America/Toronto", 76),
    ("BC Place", "Vancouver", "Canada", "America/Vancouver", 2),
    ("Mercedes-Benz Stadium", "Atlanta", "USA", "America/New_York", 320),
    ("Gillette Stadium", "Boston", "USA", "America/New_York", 88),
    ("AT&T Stadium", "Dallas", "USA", "America/Chicago", 185),
    ("NRG Stadium", "Houston", "USA", "America/Chicago", 15),
    ("GEHA Field at Arrowhead Stadium", "Kansas City", "USA", "America/Chicago", 270),
    ("SoFi Stadium", "Los Angeles", "USA", "America/Los_Angeles", 38),
    ("Hard Rock Stadium", "Miami", "USA", "America/New_York", 2),
    ("MetLife Stadium", "New York/New Jersey", "USA", "America/New_York", 2),
    ("Lincoln Financial Field", "Philadelphia", "USA", "America/New_York", 12),
    ("Levi's Stadium", "San Francisco Bay Area", "USA", "America/Los_Angeles", 2),
    ("Lumen Field", "Seattle", "USA", "America/Los_Angeles", 16),
]

FIXTURES = [
    (1, "Group stage", "A", "Mexico", "South Africa", "Estadio Azteca", "2026-06-11T19:00:00+00:00"),
    (2, "Group stage", "A", "South Korea", "Czech Republic", "Estadio Akron", "2026-06-12T02:00:00+00:00"),
    (3, "Group stage", "B", "Canada", "Bosnia & Herzegovina", "BMO Field", "2026-06-12T19:00:00+00:00"),
    (4, "Group stage", "D", "USA", "Paraguay", "SoFi Stadium", "2026-06-13T01:00:00+00:00"),
    (5, "Group stage", "B", "Qatar", "Switzerland", "Levi's Stadium", "2026-06-13T19:00:00+00:00"),
    (6, "Group stage", "C", "Brazil", "Morocco", "MetLife Stadium", "2026-06-13T22:00:00+00:00"),
    (7, "Group stage", "C", "Haiti", "Scotland", "Gillette Stadium", "2026-06-14T01:00:00+00:00"),
    (8, "Group stage", "D", "Australia", "Turkey", "BC Place", "2026-06-14T04:00:00+00:00"),
    (9, "Group stage", "E", "Germany", "Curaçao", "NRG Stadium", "2026-06-14T17:00:00+00:00"),
    (10, "Group stage", "F", "Netherlands", "Japan", "AT&T Stadium", "2026-06-14T20:00:00+00:00"),
    (11, "Group stage", "E", "Ivory Coast", "Ecuador", "Lincoln Financial Field", "2026-06-14T23:00:00+00:00"),
    (12, "Group stage", "F", "Sweden", "Tunisia", "Estadio BBVA", "2026-06-15T02:00:00+00:00"),
    (13, "Group stage", "H", "Spain", "Cape Verde", "Mercedes-Benz Stadium", "2026-06-15T16:00:00+00:00"),
    (14, "Group stage", "G", "Belgium", "Egypt", "Lumen Field", "2026-06-15T19:00:00+00:00"),
    (15, "Group stage", "H", "Saudi Arabia", "Uruguay", "Hard Rock Stadium", "2026-06-15T22:00:00+00:00"),
    (16, "Group stage", "G", "Iran", "New Zealand", "SoFi Stadium", "2026-06-16T01:00:00+00:00"),
    (17, "Group stage", "I", "France", "Senegal", "MetLife Stadium", "2026-06-16T19:00:00+00:00"),
    (18, "Group stage", "I", "Iraq", "Norway", "Gillette Stadium", "2026-06-16T22:00:00+00:00"),
    (19, "Group stage", "J", "Argentina", "Algeria", "GEHA Field at Arrowhead Stadium", "2026-06-17T01:00:00+00:00"),
    (20, "Group stage", "J", "Austria", "Jordan", "Levi's Stadium", "2026-06-17T04:00:00+00:00"),
    (21, "Group stage", "K", "Portugal", "DR Congo", "NRG Stadium", "2026-06-17T17:00:00+00:00"),
    (22, "Group stage", "L", "England", "Croatia", "AT&T Stadium", "2026-06-17T20:00:00+00:00"),
    (23, "Group stage", "L", "Ghana", "Panama", "BMO Field", "2026-06-17T23:00:00+00:00"),
    (24, "Group stage", "K", "Uzbekistan", "Colombia", "Estadio Azteca", "2026-06-18T02:00:00+00:00"),
]

# Complete 104-match source data is kept compact below. It can be extended without schema changes.
MORE_FIXTURES_TEXT = """
25|Group stage|A|Czech Republic|South Africa|Mercedes-Benz Stadium|2026-06-18T16:00:00+00:00
26|Group stage|B|Switzerland|Bosnia & Herzegovina|SoFi Stadium|2026-06-18T19:00:00+00:00
27|Group stage|B|Canada|Qatar|BC Place|2026-06-18T22:00:00+00:00
28|Group stage|A|Mexico|South Korea|Estadio Akron|2026-06-19T01:00:00+00:00
29|Group stage|D|USA|Australia|Lumen Field|2026-06-19T19:00:00+00:00
30|Group stage|C|Scotland|Morocco|Gillette Stadium|2026-06-19T22:00:00+00:00
31|Group stage|C|Brazil|Haiti|Lincoln Financial Field|2026-06-20T00:30:00+00:00
32|Group stage|D|Turkey|Paraguay|Levi's Stadium|2026-06-20T03:00:00+00:00
33|Group stage|F|Netherlands|Sweden|NRG Stadium|2026-06-20T17:00:00+00:00
34|Group stage|E|Germany|Ivory Coast|BMO Field|2026-06-20T20:00:00+00:00
35|Group stage|E|Ecuador|Curaçao|GEHA Field at Arrowhead Stadium|2026-06-21T00:00:00+00:00
36|Group stage|F|Tunisia|Japan|Estadio BBVA|2026-06-21T04:00:00+00:00
37|Group stage|H|Spain|Saudi Arabia|Mercedes-Benz Stadium|2026-06-21T16:00:00+00:00
38|Group stage|G|Belgium|Iran|SoFi Stadium|2026-06-21T19:00:00+00:00
39|Group stage|H|Uruguay|Cape Verde|Hard Rock Stadium|2026-06-21T22:00:00+00:00
40|Group stage|G|New Zealand|Egypt|BC Place|2026-06-22T01:00:00+00:00
41|Group stage|J|Argentina|Austria|AT&T Stadium|2026-06-22T17:00:00+00:00
42|Group stage|I|France|Iraq|Lincoln Financial Field|2026-06-22T21:00:00+00:00
43|Group stage|I|Norway|Senegal|MetLife Stadium|2026-06-23T00:00:00+00:00
44|Group stage|J|Jordan|Algeria|Levi's Stadium|2026-06-23T03:00:00+00:00
45|Group stage|K|Portugal|Uzbekistan|NRG Stadium|2026-06-23T17:00:00+00:00
46|Group stage|L|England|Ghana|Gillette Stadium|2026-06-23T20:00:00+00:00
47|Group stage|L|Panama|Croatia|BMO Field|2026-06-23T23:00:00+00:00
48|Group stage|K|Colombia|DR Congo|Estadio Akron|2026-06-24T02:00:00+00:00
49|Group stage|B|Switzerland|Canada|BC Place|2026-06-24T19:00:00+00:00
50|Group stage|B|Bosnia & Herzegovina|Qatar|Lumen Field|2026-06-24T19:00:00+00:00
51|Group stage|C|Scotland|Brazil|Hard Rock Stadium|2026-06-24T22:00:00+00:00
52|Group stage|C|Morocco|Haiti|Mercedes-Benz Stadium|2026-06-24T22:00:00+00:00
53|Group stage|A|Czech Republic|Mexico|Estadio Azteca|2026-06-25T01:00:00+00:00
54|Group stage|A|South Africa|South Korea|Estadio BBVA|2026-06-25T01:00:00+00:00
55|Group stage|E|Curaçao|Ivory Coast|Lincoln Financial Field|2026-06-25T20:00:00+00:00
56|Group stage|E|Ecuador|Germany|MetLife Stadium|2026-06-25T20:00:00+00:00
57|Group stage|F|Japan|Sweden|AT&T Stadium|2026-06-25T23:00:00+00:00
58|Group stage|F|Tunisia|Netherlands|GEHA Field at Arrowhead Stadium|2026-06-25T23:00:00+00:00
59|Group stage|D|Turkey|USA|SoFi Stadium|2026-06-26T02:00:00+00:00
60|Group stage|D|Paraguay|Australia|Levi's Stadium|2026-06-26T02:00:00+00:00
61|Group stage|I|Norway|France|Gillette Stadium|2026-06-26T19:00:00+00:00
62|Group stage|I|Senegal|Iraq|BMO Field|2026-06-26T19:00:00+00:00
63|Group stage|H|Cape Verde|Saudi Arabia|NRG Stadium|2026-06-27T00:00:00+00:00
64|Group stage|H|Uruguay|Spain|Estadio Akron|2026-06-27T00:00:00+00:00
65|Group stage|G|Egypt|Iran|Lumen Field|2026-06-27T03:00:00+00:00
66|Group stage|G|New Zealand|Belgium|BC Place|2026-06-27T03:00:00+00:00
67|Group stage|L|Panama|England|MetLife Stadium|2026-06-27T21:00:00+00:00
68|Group stage|L|Croatia|Ghana|Lincoln Financial Field|2026-06-27T21:00:00+00:00
69|Group stage|K|Colombia|Portugal|Hard Rock Stadium|2026-06-27T23:30:00+00:00
70|Group stage|K|DR Congo|Uzbekistan|Mercedes-Benz Stadium|2026-06-27T23:30:00+00:00
71|Group stage|J|Algeria|Austria|GEHA Field at Arrowhead Stadium|2026-06-28T02:00:00+00:00
72|Group stage|J|Jordan|Argentina|AT&T Stadium|2026-06-28T02:00:00+00:00
73|Round of 32||2A|2B|SoFi Stadium|2026-06-28T19:00:00+00:00
74|Round of 32||1C|2F|NRG Stadium|2026-06-29T17:00:00+00:00
75|Round of 32||1E|3A/B/C/D/F|Gillette Stadium|2026-06-29T20:30:00+00:00
76|Round of 32||1F|2C|Estadio BBVA|2026-06-30T01:00:00+00:00
77|Round of 32||2E|2I|AT&T Stadium|2026-06-30T17:00:00+00:00
78|Round of 32||1I|3C/D/F/G/H|MetLife Stadium|2026-06-30T21:00:00+00:00
79|Round of 32||1A|3C/E/F/H/I|Estadio Azteca|2026-07-01T01:00:00+00:00
80|Round of 32||1L|3E/H/I/J/K|Mercedes-Benz Stadium|2026-07-01T16:00:00+00:00
81|Round of 32||1G|3A/E/H/I/J|Lumen Field|2026-07-01T20:00:00+00:00
82|Round of 32||1D|3B/E/F/I/J|Levi's Stadium|2026-07-02T00:00:00+00:00
83|Round of 32||1H|2J|SoFi Stadium|2026-07-02T19:00:00+00:00
84|Round of 32||2K|2L|BMO Field|2026-07-02T23:00:00+00:00
85|Round of 32||1B|3E/F/G/I/J|BC Place|2026-07-03T03:00:00+00:00
86|Round of 32||2D|2G|AT&T Stadium|2026-07-03T18:00:00+00:00
87|Round of 32||1J|2H|Hard Rock Stadium|2026-07-03T22:00:00+00:00
88|Round of 32||1K|3D/E/I/J/L|GEHA Field at Arrowhead Stadium|2026-07-04T01:30:00+00:00
89|Round of 16||W73|W75|NRG Stadium|2026-07-04T17:00:00+00:00
90|Round of 16||W74|W77|Lincoln Financial Field|2026-07-04T21:00:00+00:00
91|Round of 16||W76|W78|MetLife Stadium|2026-07-05T20:00:00+00:00
92|Round of 16||W79|W80|Estadio Azteca|2026-07-06T00:00:00+00:00
93|Round of 16||W83|W84|AT&T Stadium|2026-07-06T19:00:00+00:00
94|Round of 16||W81|W82|Lumen Field|2026-07-07T00:00:00+00:00
95|Round of 16||W86|W88|Mercedes-Benz Stadium|2026-07-07T16:00:00+00:00
96|Round of 16||W85|W87|BC Place|2026-07-07T20:00:00+00:00
97|Quarter-final||W89|W90|Gillette Stadium|2026-07-09T20:00:00+00:00
98|Quarter-final||W93|W94|SoFi Stadium|2026-07-10T19:00:00+00:00
99|Quarter-final||W91|W92|Hard Rock Stadium|2026-07-11T21:00:00+00:00
100|Quarter-final||W95|W96|GEHA Field at Arrowhead Stadium|2026-07-12T01:00:00+00:00
101|Semi-final||W97|W98|AT&T Stadium|2026-07-14T19:00:00+00:00
102|Semi-final||W99|W100|Mercedes-Benz Stadium|2026-07-15T19:00:00+00:00
103|Third-place play-off||L101|L102|Hard Rock Stadium|2026-07-18T21:00:00+00:00
104|Final||W101|W102|MetLife Stadium|2026-07-19T19:00:00+00:00
"""


def seed_static_worldcup_data():
    normalized_summary = seed_normalized_worldcup_data()
    for name, code, group, temp, altitude in TEAMS:
        upsert(WorldCupTeam, "name", name, fifa_code=code, group_name=group, country_average_temp_c=temp, country_average_altitude_m=altitude, notes="Starter climate/altitude estimate; verify before analytical use.")
    for name, city, country, tz, altitude in VENUES:
        upsert(WorldCupVenue, "name", name, city=city, country=country, timezone=tz, altitude_m=altitude)
    for row in FIXTURES + parse_more_fixtures():
        match_number, stage, group, home, away, venue, kickoff = row
        upsert(
            WorldCupFixture,
            "match_number",
            match_number,
            stage=stage,
            group_name=group or None,
            home_team=home,
            away_team=away,
            venue_name=venue,
            kickoff_utc=datetime.fromisoformat(kickoff),
            source_note="Schedule seeded from public fixture listing checked 2026-06-06; verify against FIFA for final analytical use.",
        )
    db.session.commit()
    return normalized_summary


def seed_normalized_worldcup_data():
    for name, code, group, temp, altitude in TEAMS:
        country = upsert(
            Country,
            "name",
            clean_name(name),
            fifa_code=code,
            average_temp_c=temp,
            average_altitude_m=altitude,
            climate_notes="Starter climate/altitude estimate; verify before analytical use.",
        )
        db.session.flush()
        upsert(Team, "display_name", clean_name(name), country_id=country.id, group_name=group)

    for market_name, category in (
        ("Match Winner / 1X2", "match_result"),
        ("Over/Under Goals", "goals"),
        ("Both Teams To Score", "goals"),
        ("Draw No Bet", "match_result"),
        ("Double Chance", "match_result"),
        ("Asian Handicap", "handicap"),
        ("Correct Score", "score"),
        ("Outright Winner", "outright"),
    ):
        upsert(Market, "name", market_name, category=category)

    for name, city, country_name, tz, altitude in VENUES:
        country = upsert(Country, "name", clean_name(country_name))
        db.session.flush()
        upsert(
            Venue,
            "name",
            clean_name(name),
            city=city,
            country_id=country.id,
            timezone=tz,
            altitude_m=altitude,
        )

    db.session.flush()
    teams = {team.display_name: team for team in Team.query.all()}
    venues = {venue.name: venue for venue in Venue.query.all()}
    fixtures = FIXTURES + parse_more_fixtures()
    for row in fixtures:
        match_number, stage, group, home, away, venue_name, kickoff = row
        fixture = upsert(
            Fixture,
            "match_number",
            match_number,
            stage=stage,
            group_name=group or None,
            home_team_id=team_id_or_none(teams, home),
            away_team_id=team_id_or_none(teams, away),
            venue_id=venues[clean_name(venue_name)].id,
            kickoff_utc=datetime.fromisoformat(kickoff),
            status="scheduled",
            source_note="Seeded starter schedule; verify against FIFA for final analytical use.",
        )
        add_fixture_team(fixture, teams.get(clean_name(home)), "home")
        add_fixture_team(fixture, teams.get(clean_name(away)), "away")

    db.session.commit()
    return {
        "countries": Country.query.count(),
        "teams": Team.query.count(),
        "venues": Venue.query.count(),
        "fixtures": Fixture.query.count(),
        "fixture_teams": FixtureTeam.query.count(),
    }


def parse_more_fixtures():
    rows = []
    for line in MORE_FIXTURES_TEXT.strip().splitlines():
        number, stage, group, home, away, venue, kickoff = line.split("|")
        rows.append((int(number), stage, group, home, away, venue, kickoff))
    return rows


def upsert(model, lookup_field, lookup_value, **values):
    item = model.query.filter(getattr(model, lookup_field) == lookup_value).first()
    if item is None:
        item = model(**{lookup_field: lookup_value})
        db.session.add(item)
    for key, value in values.items():
        setattr(item, key, value)
    return item


def add_fixture_team(fixture, team, home_away):
    if team is None:
        return None
    item = FixtureTeam.query.filter_by(fixture_id=fixture.id, team_id=team.id).first()
    if item is None:
        item = FixtureTeam(fixture_id=fixture.id, team_id=team.id)
        db.session.add(item)
    item.home_away = home_away
    return item


def team_id_or_none(teams, name):
    team = teams.get(clean_name(name))
    return team.id if team else None


def clean_name(value):
    return str(value).replace("CuraÃ§ao", "Curacao").strip()


def import_squad_rows(rows):
    count = 0
    for row in rows:
        team_name = row.get("team_name") or row.get("team") or row.get("country")
        player_name = row.get("name_on_shirt") or row.get("player") or row.get("name")
        if not team_name or not player_name:
            continue
        existing = SquadPlayer.query.filter_by(team_name=team_name, name_on_shirt=player_name).first()
        if existing is None:
            existing = SquadPlayer(team_name=team_name, name_on_shirt=player_name)
            db.session.add(existing)
        existing.shirt_number = int(row["shirt_number"]) if str(row.get("shirt_number", "")).isdigit() else None
        existing.position = row.get("position")
        existing.club = row.get("club")
        existing.source_note = row.get("source_note") or "Imported CSV"
        import_squad_membership(row, team_name, player_name)
        count += 1
    db.session.commit()
    return count


def import_squad_membership(row, team_name, player_name):
    team = Team.query.filter_by(display_name=clean_name(team_name)).first()
    if team is None:
        country = upsert(Country, "name", clean_name(team_name))
        db.session.flush()
        team = upsert(Team, "display_name", clean_name(team_name), country_id=country.id)
        db.session.flush()

    player = Player.query.filter_by(full_name=player_name).first()
    if player is None:
        player = Player(full_name=player_name)
        db.session.add(player)
        db.session.flush()
    player.primary_position = row.get("position")
    player.club = row.get("club")

    membership = SquadMembership.query.filter_by(team_id=team.id, player_id=player.id, tournament_year=2026).first()
    if membership is None:
        membership = SquadMembership(team_id=team.id, player_id=player.id, tournament_year=2026)
        db.session.add(membership)
    membership.shirt_number = int(row["shirt_number"]) if str(row.get("shirt_number", "")).isdigit() else None
    membership.position = row.get("position")
    membership.status = row.get("status") or "squad"
    membership.source_note = row.get("source_note") or "Imported CSV"
