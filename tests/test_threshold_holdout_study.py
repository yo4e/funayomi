import unittest
from types import SimpleNamespace

from scripts.threshold_holdout_study import format_text, select_threshold


def result(*, return_rate, bet_races=20, purchase_count=200):
    return SimpleNamespace(
        return_rate=return_rate,
        bet_races=bet_races,
        purchase_count=purchase_count,
    )


class ThresholdSelectionTests(unittest.TestCase):
    def test_selects_highest_eligible_return_rate_and_lower_threshold_on_tie(self):
        selected_threshold, _ = select_threshold(
            [
                (8.0, result(return_rate=1.2)),
                (5.0, result(return_rate=1.2)),
                (10.0, result(return_rate=9.9, purchase_count=199)),
                (12.0, result(return_rate=9.9, bet_races=19)),
            ]
        )

        self.assertEqual(selected_threshold, 5.0)

    def test_refuses_to_select_when_no_candidate_meets_sample_floor(self):
        with self.assertRaises(ValueError):
            select_threshold(
                [
                    (8.0, result(return_rate=2.0, purchase_count=199)),
                    (10.0, result(return_rate=None, purchase_count=500)),
                ]
            )

    def test_human_output_includes_losing_streak_and_drawdown(self):
        summary = {
            "purchase_count": 200,
            "hit_count": 0,
            "return_rate": 0.02,
            "net_profit": -19600,
            "maximum_losing_streak": 168,
            "maximum_drawdown": 19600,
        }
        document = {
            "periods": {
                "training": {"start": "2026-01-01", "end": "2026-03-31"},
                "validation": {"start": "2026-04-01", "end": "2026-04-30"},
                "test": {"start": "2026-05-01", "end": "2026-06-15"},
            },
            "selection": {
                "selected_threshold": 8.0,
                "candidates": [
                    {
                        "threshold": 8.0,
                        "eligible": True,
                        **summary,
                    }
                ],
            },
            "test": {
                "locked_threshold": summary,
                "threshold_1_baseline": {
                    **summary,
                    "maximum_losing_streak": 16,
                },
            },
        }

        output = format_text(document)

        self.assertIn("最大連敗", output)
        self.assertIn("     168", output)
        self.assertIn("      16", output)
        self.assertIn("19600円", output)


if __name__ == "__main__":
    unittest.main()
