from app.services.odds_api_client import normalise_decimal_odds, normalise_market_name, normalise_odds_records


def test_odds_normalisation_handles_numeric_strings():
    assert normalise_decimal_odds("2.45") == 2.45


def test_market_aliases():
    assert normalise_market_name("ML") == "Match Winner / 1X2"
    assert normalise_market_name("Totals") == "Over/Under Goals"


def test_normalise_odds_records_nested_bookmakers():
    payload = [
        {
            "bookmakers": [
                {
                    "title": "Bet365",
                    "markets": [
                        {
                            "key": "moneyline",
                            "outcomes": [{"name": "France", "price": "2.10"}],
                        }
                    ],
                }
            ]
        }
    ]
    records = normalise_odds_records("event-1", payload)
    assert records[0]["decimal_odds"] == 2.10
    assert records[0]["market_name"] == "Match Winner / 1X2"
