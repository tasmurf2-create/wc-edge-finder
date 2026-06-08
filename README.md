# World Cup Odds Tracker

A local Flask web app for tracking FIFA World Cup football odds from Odds-API.io. It stores odds snapshots in SQLite, compares bookmaker prices, charts odds movement, exports CSV files, and calculates possible value candidates from implied probability, no-vig probability, expected value, and conservative Kelly staking.

This is for personal analysis only. It does not publish public pages, manage user accounts, place bets, automate betting, provide affiliate links, or present betting advice.

## Windows setup

Open PowerShell in this folder:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts/init_db.py
python scripts/refresh_odds.py
python run.py
```

The app runs at:

http://127.0.0.1:5000

If `ODDS_API_KEY` is empty, the app still launches and shows stored data or setup messages. Add your Odds-API.io key to `.env`:

```text
ODDS_API_KEY=your-key-here
```

The full API key is never displayed in the UI.

## What the app does

- Fetches football events from Odds-API.io REST endpoints such as `/v3/events`.
- Filters events to World Cup-related competitions.
- Fetches odds from `/v3/odds`.
- Stores historical odds snapshots in SQLite.
- Compares bookmaker prices and highlights best prices.
- Shows odds movement over time with Plotly.
- Calculates implied probability, no-vig probability, expected value, and suggested fractional Kelly stakes.
- Saves analytical watchlist items.
- Exports latest odds, odds movement, watchlist, and value candidates to CSV.
- Stores normalized static World Cup reference data for countries, teams, venues, fixtures, fixture-team rows, local venue kick-off times, players, and squad memberships.

## What it does not do

- No bookmaker login.
- No bet placement.
- No automatic betting.
- No public publishing.
- No subscriptions.
- No machine-learning prediction model in version 1.
- No language implying certainty or guaranteed outcomes.

## Daily refresh with Windows Task Scheduler

1. Open Task Scheduler.
2. Choose **Create Basic Task**.
3. Set the trigger to daily.
4. Set the action to **Start a Program**.
5. Program: `C:\Users\tommu\worldcup-odds-app\.venv\Scripts\python.exe`
6. Arguments: `C:\Users\tommu\worldcup-odds-app\scripts\refresh_odds.py`
7. Start in: `C:\Users\tommu\worldcup-odds-app`

## Concepts

Implied probability converts decimal odds into the bookmaker's break-even probability:

```text
implied_probability = 1 / decimal_odds
```

Bookmaker margin, or overround, is the amount by which all implied probabilities in a market exceed 100 percent:

```text
overround = sum(implied_probabilities) - 1
```

No-vig probability removes the market margin by dividing each implied probability by the total implied probability across the market.

Expected value compares your model probability with the available decimal odds:

```text
EV = model_probability * decimal_odds - 1
```

Kelly staking estimates a stake fraction from your probability and odds. This app uses fractional Kelly and a maximum stake cap, because probability estimates can be wrong:

```text
b = decimal_odds - 1
kelly = (b * model_probability - (1 - model_probability)) / b
stake = bankroll * kelly * kelly_fraction
```

## Tests

Run:

```powershell
pytest
```

## Personal-use disclaimer

This app is for personal analysis only. Betting involves risk and can result in losses. Positive expected value depends entirely on the probability assumptions used.
