import math
import unittest
from dataclasses import replace
from datetime import date

from funayomi.combinations import EXACTA_COMBINATIONS
from funayomi.domain import OddsSnapshot, RaceOutcome
from funayomi.errors import DataContractError
from funayomi.strategy_backtest import (
    STRATEGY_NAMES,
    StrategyRaceInput,
    portfolio_results_to_dict,
    run_portfolio_backtest,
)

from tests.helpers import make_race


def probabilities(overrides=None):
    overrides = dict(overrides or {})
    remainder = 1.0 - math.fsum(overrides.values())
    default = remainder / (len(EXACTA_COMBINATIONS) - len(overrides))
    return {
        combination: float(overrides.get(combination, default))
        for combination in EXACTA_COMBINATIONS
    }


def exacta_odds(default=10.0, overrides=None):
    values = {
        combination: float(default) for combination in EXACTA_COMBINATIONS
    }
    values.update(overrides or {})
    return values


def exacta_race(
    day,
    *,
    race_number=1,
    winner="1-2",
    payout=500,
    odds=None,
    exacta_status="standard",
    nonstarter=None,
):
    base = make_race(
        day,
        race_number=race_number,
        winner=f"{winner}-3",
    )
    racers = {
        entry: dict(value) for entry, value in base.outcome.racers.items()
    }
    if nonstarter is not None:
        racers[nonstarter]["place_number"] = None
        racers[nonstarter]["place_number_source"] = "F"
    exacta_winners = (
        (winner,)
        if exacta_status in ("standard", "exception_settled", "inconsistent")
        else ()
    )
    return replace(
        base,
        odds=OddsSnapshot(
            trifecta=base.odds.trifecta,
            exacta=dict(
                odds
                if odds is not None
                else exacta_odds(10, {"1-2": 5, "1-3": 5})
            ),
        ),
        outcome=RaceOutcome(
            status=base.outcome.status,
            winning_trifectas=base.outcome.winning_trifectas,
            trifecta_payouts=base.outcome.trifecta_payouts,
            racers=racers,
            exacta_status=exacta_status,
            winning_exactas=exacta_winners,
            exacta_payouts=(
                {winner: payout} if exacta_winners else {}
            ),
        ),
    )


def observation(race, prediction=None):
    values = prediction or probabilities({"1-2": 0.30, "1-3": 0.20})
    return StrategyRaceInput(
        race=race,
        fold_id="outer_test",
        meeting_id="meeting-1",
        program_probabilities=values,
        blend_probabilities=values,
    )


class StrategyBacktestTests(unittest.TestCase):
    def test_four_strategies_use_equal_race_budget_and_settle_after_selection(self):
        race = exacta_race(date(2026, 4, 1))

        results = run_portfolio_backtest(
            [observation(race)],
            bootstrap_resamples=20,
        )

        self.assertEqual(tuple(results), STRATEGY_NAMES)
        for result in results.values():
            self.assertEqual(result.bet_races, 1)
            self.assertEqual(result.total_stake_yen, 1000)
            self.assertEqual(result.hit_races, 1)
            self.assertEqual(result.maximum_losing_streak, 0)
        self.assertEqual(results["program_single"].total_payout_yen, 5000)
        self.assertEqual(results["program_dutch"].tickets, 2)
        self.assertEqual(results["program_dutch"].total_payout_yen, 2500)
        self.assertEqual(
            results["program_dutch"].races[0].winning_combination,
            "1-2",
        )

    def test_pass_and_market_skip_do_not_require_settleable_outcome(self):
        inconsistent = exacta_race(
            date(2026, 4, 1),
            exacta_status="inconsistent",
        )
        passed = run_portfolio_backtest(
            [observation(inconsistent)],
            minimum_predicted_return=99,
            bootstrap_resamples=0,
        )
        self.assertTrue(
            all(result.pass_races == 1 for result in passed.values())
        )

        incomplete = dict(inconsistent.odds.exacta)
        incomplete["6-5"] = None
        skipped_race = replace(
            inconsistent,
            odds=replace(inconsistent.odds, exacta=incomplete),
        )
        skipped = run_portfolio_backtest(
            [observation(skipped_race)],
            bootstrap_resamples=0,
        )
        self.assertTrue(
            all(result.skipped_races == 1 for result in skipped.values())
        )

    def test_selected_unsettleable_race_fails_closed(self):
        race = exacta_race(
            date(2026, 4, 1),
            exacta_status="inconsistent",
        )

        with self.assertRaises(DataContractError):
            run_portfolio_backtest(
                [observation(race)],
                bootstrap_resamples=0,
            )

    def test_nonstarter_refunds_only_affected_selections(self):
        race = exacta_race(
            date(2026, 4, 1),
            exacta_status="exception_settled",
            nonstarter=3,
        )

        results = run_portfolio_backtest(
            [observation(race)],
            bootstrap_resamples=0,
        )

        dutch = results["program_dutch"].races[0]
        self.assertEqual(
            tuple(item.combination for item in dutch.selections),
            ("1-2", "1-3"),
        )
        self.assertEqual(dutch.refund_count, 1)
        self.assertEqual(dutch.refund_yen, 500)
        self.assertEqual(dutch.payout_yen, 3000)

    def test_metrics_drawdown_concentration_and_bootstrap_are_deterministic(self):
        races = [
            exacta_race(date(2026, 4, 1), race_number=1, winner="1-2"),
            exacta_race(date(2026, 4, 1), race_number=2, winner="2-1"),
            exacta_race(date(2026, 4, 2), race_number=1, winner="2-1"),
        ]
        observations = [
            replace(
                observation(race),
                meeting_id=(
                    "meeting-1"
                    if race.identity.date == date(2026, 4, 1)
                    else "meeting-2"
                ),
            )
            for race in races
        ]

        first = run_portfolio_backtest(
            observations,
            bootstrap_resamples=50,
            bootstrap_seed=123,
        )
        second = run_portfolio_backtest(
            reversed(observations),
            bootstrap_resamples=50,
            bootstrap_seed=123,
        )

        single = first["program_single"]
        self.assertEqual(single.maximum_losing_streak, 2)
        self.assertEqual(single.maximum_drawdown_yen, 2000)
        self.assertEqual(single.largest_payout_yen, 5000)
        self.assertEqual(single.largest_payout_share, 1.0)
        self.assertEqual(single.return_without_largest_payout, 0.0)
        self.assertEqual(single.bootstrap, second["program_single"].bootstrap)
        self.assertEqual(
            {result.bootstrap.seed for result in first.values()},
            {123},
        )
        self.assertEqual(len(single.monthly), 1)
        self.assertEqual(len(single.meetings), 2)

    def test_duplicate_evaluation_identity_and_invalid_configuration_fail(self):
        item = observation(exacta_race(date(2026, 4, 1)))
        with self.assertRaises(DataContractError):
            run_portfolio_backtest(
                [item, item],
                bootstrap_resamples=0,
            )
        with self.assertRaises(ValueError):
            run_portfolio_backtest(
                [item],
                race_budget_yen=950,
                bootstrap_resamples=0,
            )

    def test_machine_output_is_non_actionable(self):
        results = run_portfolio_backtest(
            [observation(exacta_race(date(2026, 4, 1)))],
            bootstrap_resamples=0,
        )

        document = portfolio_results_to_dict(results)

        self.assertFalse(document["actionable"])
        self.assertEqual(
            document["research_class"],
            "retrospective_hypothesis_generation_sandbox",
        )
        self.assertEqual(document["refund_probability_mode"], "not_modeled")
        self.assertIn("program_dutch", document["strategies"])


if __name__ == "__main__":
    unittest.main()
