import json
import unittest
from datetime import date
from pathlib import Path


PROTOCOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "protocols"
    / "ashiya_exacta_pl_v1.json"
)


def load_protocol():
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


class ResearchProtocolTests(unittest.TestCase):
    def test_protocol_is_explicitly_non_executable_at_current_gates(self):
        protocol = load_protocol()

        self.assertEqual(protocol["execution_status"], "HOLD_GATE_P_NO_GO")
        self.assertEqual(
            protocol["gates"]["gate_p_historical"],
            "NO_GO_HISTORICAL_CONFIRMATORY_USE",
        )
        self.assertEqual(
            protocol["gates"]["gate_d"],
            "NO_GO_NO_ADOPTABLE_SOURCE",
        )
        for key in (
            "wager_schema_implementation",
            "model_implementation",
            "numeric_dependency_addition",
            "development_evaluation_execution",
            "future_holdout_start",
            "odds_collection",
        ):
            self.assertIs(protocol["authorization"][key], False)

    def test_primary_hypothesis_and_feature_boundary_are_frozen(self):
        protocol = load_protocol()

        self.assertEqual(
            protocol["hypothesis"]["primary_bet_type"],
            "exacta",
        )
        self.assertEqual(protocol["estimand"]["outcomes"], 30)
        self.assertFalse(protocol["estimand"]["odds_required"])
        self.assertEqual(protocol["features"]["partition"], "program_only")
        excluded = set(protocol["features"]["excluded"])
        self.assertTrue({"preview", "odds", "result", "payout"} <= excluded)
        self.assertEqual(
            protocol["primary_analysis"]["bootstrap"]["resamples"],
            20000,
        )
        self.assertEqual(
            protocol["primary_analysis"]["bootstrap"]["seed"],
            20260724,
        )

    def test_outer_shadow_periods_follow_refit_periods_without_overlap(self):
        protocol = load_protocol()

        for fold in protocol["development_folds"]["outer_shadow"]:
            refit_end = date.fromisoformat(fold["refit_end"])
            evaluation_start = date.fromisoformat(fold["evaluation_start"])
            evaluation_end = date.fromisoformat(fold["evaluation_end"])
            self.assertLess(refit_end, evaluation_start)
            self.assertLessEqual(evaluation_start, evaluation_end)


if __name__ == "__main__":
    unittest.main()
