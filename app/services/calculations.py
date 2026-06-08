from __future__ import annotations


def coerce_decimal_odds(decimal_odds) -> float:
    try:
        value = float(decimal_odds)
    except (TypeError, ValueError):
        raise ValueError("Decimal odds must be numeric")
    if value <= 1:
        raise ValueError("Decimal odds must be greater than 1")
    return value


def decimal_odds_to_implied_probability(decimal_odds) -> float:
    return 1 / coerce_decimal_odds(decimal_odds)


def implied_probability_to_fair_odds(probability) -> float:
    probability = float(probability)
    if probability <= 0 or probability > 1:
        raise ValueError("Probability must be between 0 and 1")
    return 1 / probability


def calculate_overround(probabilities) -> float:
    return sum(float(probability) for probability in probabilities) - 1


def calculate_no_vig_probabilities(outcome_odds: dict[str, float]) -> dict[str, float]:
    implied = {
        outcome: decimal_odds_to_implied_probability(odds)
        for outcome, odds in outcome_odds.items()
        if odds
    }
    total = sum(implied.values())
    if total <= 0:
        return {}
    return {outcome: probability / total for outcome, probability in implied.items()}


def calculate_expected_value(model_probability, decimal_odds) -> float:
    return float(model_probability) * coerce_decimal_odds(decimal_odds) - 1


def calculate_kelly_fraction(model_probability, decimal_odds) -> float:
    decimal_odds = coerce_decimal_odds(decimal_odds)
    model_probability = float(model_probability)
    if model_probability <= 0:
        return 0
    b = decimal_odds - 1
    q = 1 - model_probability
    kelly = (b * model_probability - q) / b
    return max(kelly, 0)


def calculate_suggested_stake(
    bankroll,
    decimal_odds,
    model_probability,
    kelly_fraction=0.25,
    max_stake=50,
) -> float:
    full_kelly = calculate_kelly_fraction(model_probability, decimal_odds)
    stake = full_kelly * float(kelly_fraction) * float(bankroll)
    stake = min(stake, float(max_stake))
    return round(max(stake, 0), 2)


def is_value_candidate(expected_value, threshold=0.05) -> bool:
    return float(expected_value) > float(threshold)
