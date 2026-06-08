import pytest

from app.services.calculations import (
    calculate_expected_value,
    calculate_kelly_fraction,
    calculate_no_vig_probabilities,
    calculate_overround,
    calculate_suggested_stake,
    decimal_odds_to_implied_probability,
    implied_probability_to_fair_odds,
    is_value_candidate,
)


def test_decimal_odds_to_implied_probability():
    assert decimal_odds_to_implied_probability(2.0) == pytest.approx(0.5)


def test_implied_probability_to_fair_odds():
    assert implied_probability_to_fair_odds(0.25) == pytest.approx(4.0)


def test_overround_calculation():
    assert calculate_overround([0.52, 0.30, 0.24]) == pytest.approx(0.06)


def test_no_vig_probability_calculation():
    result = calculate_no_vig_probabilities({"Home": 2.0, "Draw": 3.5, "Away": 4.0})
    assert sum(result.values()) == pytest.approx(1.0)
    assert result["Home"] > result["Away"]


def test_expected_value_calculation():
    assert calculate_expected_value(0.55, 2.1) == pytest.approx(0.155)


def test_kelly_fraction():
    assert calculate_kelly_fraction(0.55, 2.1) == pytest.approx(0.140909, rel=1e-4)


def test_fractional_kelly_stake():
    assert calculate_suggested_stake(1000, 2.1, 0.55, kelly_fraction=0.25, max_stake=50) == pytest.approx(35.23)


def test_max_stake_cap():
    assert calculate_suggested_stake(10000, 3.0, 0.5, kelly_fraction=1, max_stake=50) == 50


def test_negative_ev_not_flagged():
    assert not is_value_candidate(calculate_expected_value(0.40, 2.0), threshold=0.05)


def test_positive_ev_above_threshold_flagged():
    assert is_value_candidate(calculate_expected_value(0.55, 2.1), threshold=0.05)
