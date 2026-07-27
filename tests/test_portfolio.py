import math
import unittest

from funayomi.errors import DataContractError
from funayomi.portfolio import (
    EXACTA_COMBINATIONS,
    ValidationRace,
    build_coverage_cost_frontier,
    equal_payout_dutching,
    geometric_blend,
    normalize_market_probabilities,
    select_blend_lambda,
    select_equal_payout_prefix,
    single_point_plan,
)


def complete_odds(default=10.0, overrides=None):
    values = {combination: float(default) for combination in EXACTA_COMBINATIONS}
    values.update(overrides or {})
    return values


def probabilities(overrides=None):
    overrides = dict(overrides or {})
    remaining = 1.0 - math.fsum(overrides.values())
    other_count = len(EXACTA_COMBINATIONS) - len(overrides)
    default = remaining / other_count
    return {
        combination: float(overrides.get(combination, default))
        for combination in EXACTA_COMBINATIONS
    }


class MarketAndBlendTests(unittest.TestCase):
    def test_market_probability_is_normalized_inverse_odds(self):
        odds = complete_odds(10, {"1-2": 2, "1-3": 4})

        market = normalize_market_probabilities(odds)

        self.assertEqual(tuple(market), EXACTA_COMBINATIONS)
        self.assertTrue(
            math.isclose(
                math.fsum(market.values()),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        self.assertEqual(market["1-2"] / market["1-3"], 2.0)

    def test_geometric_blend_endpoints_and_normalization(self):
        model = probabilities({"1-2": 0.30, "1-3": 0.20})
        market = normalize_market_probabilities(
            complete_odds(20, {"1-2": 2, "1-3": 4})
        )

        self.assertEqual(geometric_blend(model, market, 0), market)
        self.assertEqual(geometric_blend(model, market, 1), model)
        middle = geometric_blend(model, market, 0.5)
        self.assertTrue(
            math.isclose(
                math.fsum(middle.values()),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        self.assertTrue(all(value > 0 for value in middle.values()))
        self.assertEqual(middle, geometric_blend(model, market, 0.5))

    def test_lambda_validation_selects_lowest_log_loss_and_ties_to_market(self):
        odds = complete_odds(10)
        informative_model = probabilities({"1-2": 0.50})
        selected = select_blend_lambda(
            [
                ValidationRace(
                    model_probabilities=informative_model,
                    odds=odds,
                    winning_combination="1-2",
                )
            ],
            [1.0, 0.0, 0.5],
        )

        self.assertEqual(selected.selected_lambda, 1.0)
        self.assertEqual(
            tuple(score.blend_weight for score in selected.scores),
            (0.0, 0.5, 1.0),
        )

        market = normalize_market_probabilities(odds)
        tie = select_blend_lambda(
            [
                ValidationRace(
                    model_probabilities=market,
                    odds=odds,
                    winning_combination="1-2",
                )
            ],
            [1.0, 0.5, 0.0],
        )
        self.assertEqual(tie.selected_lambda, 0.0)

    def test_invalid_lambda_and_invalid_probability_fail_closed(self):
        valid = probabilities()
        market = normalize_market_probabilities(complete_odds())
        for invalid_lambda in (-0.1, 1.1, math.nan, math.inf):
            with self.subTest(invalid_lambda=invalid_lambda):
                with self.assertRaises(ValueError):
                    geometric_blend(valid, market, invalid_lambda)

        missing = dict(valid)
        missing.pop("1-2")
        with self.assertRaises(DataContractError):
            geometric_blend(missing, market, 0.5)

        zero = dict(valid)
        zero["1-2"] = 0
        zero["1-3"] += valid["1-2"]
        with self.assertRaises(DataContractError):
            geometric_blend(zero, market, 0.5)


class FrontierAndStakeTests(unittest.TestCase):
    def setUp(self):
        self.probabilities = probabilities({"1-2": 0.30, "1-3": 0.20})
        self.odds = complete_odds(10, {"1-2": 5, "1-3": 5})

    def test_frontier_orders_by_value_density_with_canonical_tie_break(self):
        frontier = build_coverage_cost_frontier(
            self.probabilities,
            self.odds,
        )

        self.assertEqual(len(frontier), 30)
        self.assertEqual(frontier[0].added_combination, "1-2")
        self.assertEqual(frontier[1].added_combination, "1-3")
        self.assertEqual(frontier[0].coverage, 0.30)
        self.assertEqual(frontier[0].cost, 0.20)
        self.assertTrue(
            math.isclose(
                frontier[0].predicted_return,
                1.50,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        self.assertTrue(
            math.isclose(
                frontier[-1].coverage,
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        densities = [point.added_value_density for point in frontier]
        self.assertEqual(densities, sorted(densities, reverse=True))

    def test_single_point_uses_deterministic_best_and_can_pass(self):
        plan = single_point_plan(
            self.probabilities,
            self.odds,
            threshold=1.10,
        )

        self.assertEqual(plan.decision, "RESEARCH_PORTFOLIO")
        self.assertEqual(plan.allocations[0].combination, "1-2")
        self.assertEqual(plan.cost_yen, 100)
        self.assertEqual(plan.coverage, 0.30)
        self.assertEqual(plan.predicted_return, 1.50)

        passed = single_point_plan(
            self.probabilities,
            self.odds,
            threshold=2.0,
        )
        self.assertEqual(passed.decision, "PASS")

    def test_fixed_budget_dutching_uses_100_yen_units_and_approximates_payout(self):
        odds = complete_odds(10, {"1-2": 2, "1-3": 4})
        plan = equal_payout_dutching(
            self.probabilities,
            odds,
            ("1-3", "1-2"),
            budget_yen=1_000,
            unit_yen=100,
            threshold=0,
        )

        self.assertEqual(plan.decision, "RESEARCH_PORTFOLIO")
        self.assertEqual(plan.cost_yen, 1_000)
        self.assertEqual(sum(item.units for item in plan.allocations), 10)
        self.assertEqual(
            tuple(item.combination for item in plan.allocations),
            ("1-2", "1-3"),
        )
        self.assertEqual(
            tuple(item.units for item in plan.allocations),
            (7, 3),
        )
        gross = [item.gross_payout_if_win_yen for item in plan.allocations]
        self.assertLessEqual(max(gross) - min(gross), 400)
        self.assertTrue(
            math.isclose(
                plan.coverage,
                self.probabilities["1-2"] + self.probabilities["1-3"],
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        self.assertTrue(
            math.isclose(
                plan.allocation_predicted_return,
                plan.predicted_payout_yen / plan.cost_yen,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        self.assertTrue(
            math.isclose(
                plan.predicted_return,
                plan.coverage / plan.market_cost,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )

    def test_prefix_selector_maximizes_coverage_under_protocol_constraints(self):
        plan = select_equal_payout_prefix(
            self.probabilities,
            self.odds,
            budget_yen=1_000,
            unit_yen=100,
            threshold=1.10,
            max_market_cost=0.50,
        )

        self.assertEqual(plan.decision, "RESEARCH_PORTFOLIO")
        self.assertEqual(
            tuple(item.combination for item in plan.allocations),
            ("1-2", "1-3"),
        )
        self.assertEqual(plan.coverage, 0.50)
        self.assertLessEqual(plan.market_cost, 0.50)
        self.assertGreaterEqual(plan.predicted_return, 1.10)

        passed = select_equal_payout_prefix(
            self.probabilities,
            self.odds,
            threshold=99,
            max_market_cost=0.50,
        )
        self.assertEqual(passed.decision, "PASS")
        self.assertEqual(passed.allocations, ())
        self.assertIsNone(passed.predicted_return)
        self.assertIsNone(passed.allocation_predicted_return)

    def test_prefix_qualification_uses_frozen_theoretical_return(self):
        prediction = probabilities({"1-2": 0.55, "1-3": 0.001})
        odds = complete_odds(5, {"1-2": 2.1, "1-3": 100})

        plan = select_equal_payout_prefix(
            prediction,
            odds,
            budget_yen=1_000,
            unit_yen=100,
            threshold=1.10,
            max_market_cost=0.50,
        )

        self.assertEqual(
            tuple(item.combination for item in plan.allocations),
            ("1-2", "1-3"),
        )
        self.assertGreaterEqual(plan.predicted_return, 1.10)
        self.assertLess(plan.allocation_predicted_return, 1.10)

    def test_incomplete_or_invalid_market_fails_closed(self):
        incomplete = dict(self.odds)
        incomplete.pop("6-5")
        with self.assertRaises(DataContractError):
            normalize_market_probabilities(incomplete)
        with self.assertRaises(DataContractError):
            select_equal_payout_prefix(self.probabilities, incomplete)

        invalid = dict(self.odds)
        invalid["6-5"] = math.nan
        with self.assertRaises(DataContractError):
            build_coverage_cost_frontier(self.probabilities, invalid)

        invalid["6-5"] = 0
        with self.assertRaises(DataContractError):
            equal_payout_dutching(
                self.probabilities,
                invalid,
                ("1-2", "1-3"),
            )


if __name__ == "__main__":
    unittest.main()
