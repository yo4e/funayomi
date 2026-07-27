import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    ROOT / "protocols" / "turnmark_exacta_strategy_sandbox_v1.json"
)


class SandboxProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))

    def test_authorization_is_retrospective_and_non_actionable(self):
        self.assertEqual(
            self.protocol["execution_status"],
            "AUTHORIZED_RETROSPECTIVE_DEVELOPMENT",
        )
        self.assertFalse(self.protocol["research_class"]["actionable"])
        authorization = self.protocol["authorization"]
        self.assertTrue(authorization["exacta_schema_implementation"])
        self.assertTrue(authorization["program_model_implementation"])
        self.assertTrue(authorization["market_blend_implementation"])
        self.assertTrue(authorization["fixed_budget_portfolio_backtest"])
        self.assertFalse(authorization["future_locked_replication_start"])
        self.assertFalse(authorization["prospective_program_collection"])
        self.assertFalse(authorization["odds_collection"])
        self.assertFalse(authorization["automated_betting"])

    def test_lzh_and_confirmatory_gates_remain_on_hold(self):
        decision = self.protocol["owner_decision"]
        self.assertEqual(
            decision["official_next_day_program_lzh"],
            "HOLD_AS_POSSIBLE_FUTURE_PROSPECTIVE_SOURCE",
        )
        gates = self.protocol["gates"]
        self.assertEqual(
            gates["gate_p_historical"],
            "NO_GO_HISTORICAL_CONFIRMATORY_USE",
        )
        self.assertEqual(gates["gate_p_prospective"], "HOLD_LZH_NOT_ABANDONED")
        self.assertEqual(gates["gate_d"], "NO_GO_NO_ADOPTABLE_SOURCE")

    def test_comparison_set_and_trial_discipline_are_finite(self):
        self.assertEqual(
            self.protocol["probability_models"]["blend"]["lambda_candidates"],
            [0.0, 0.25, 0.5, 1.0],
        )
        self.assertEqual(
            self.protocol["strategy_comparisons"],
            [
                "program_single",
                "blend_single",
                "program_dutch",
                "blend_dutch",
            ],
        )
        self.assertTrue(
            self.protocol["trial_discipline"]["publish_all_four_strategies"]
        )
        self.assertEqual(
            self.protocol["trial_discipline"]["change_after_outer_results"],
            "new_protocol_id_and_hash",
        )

    def test_fixed_budget_and_risk_metrics_are_explicit(self):
        rules = self.protocol["portfolio_rules"]
        self.assertEqual(rules["race_budget_yen"], 1000)
        self.assertEqual(rules["wager_unit_yen"], 100)
        self.assertEqual(rules["minimum_predicted_return"], 1.1)
        self.assertEqual(rules["maximum_market_cost"], 0.5)
        metrics = self.protocol["evaluation"]["required_metrics"]
        self.assertIn("maximum_losing_streak", metrics)
        self.assertIn("maximum_drawdown", metrics)
        self.assertIn("worst_meeting_profit", metrics)
        self.assertIn("largest_payout_share_of_total_payout", metrics)
        self.assertIn("return_without_largest_payout", metrics)


if __name__ == "__main__":
    unittest.main()
