import math
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from funayomi.combinations import EXACTA_COMBINATIONS
from funayomi.domain import ProgramSnapshot
from scripts.run_turnmark_strategy_sandbox import (
    L2_CANDIDATES,
    assign_meeting_ids,
    compact_document,
    load_validation_cache,
    probability_quality,
    probability_signal_gate,
    select_l2_candidate,
    write_validation_cache,
)

from tests.helpers import make_race


def distribution(winner, probability):
    other = (1.0 - probability) / (len(EXACTA_COMBINATIONS) - 1)
    return {
        combination: probability if combination == winner else other
        for combination in EXACTA_COMBINATIONS
    }


class HyperparameterSelectionTests(unittest.TestCase):
    def test_l2_selection_pools_months_and_ties_to_larger_l2(self):
        cache = {}
        for month in ("2026-03", "2026-04"):
            for l2 in L2_CANDIDATES:
                loss = 1.0 if l2 in (1.0, 10.0) else 2.0
                cache[(month, l2)] = {
                    "status": "success",
                    "races": 10,
                    "sum_log_loss": loss * 10,
                    "mean_log_loss": loss,
                }

        selected, scores = select_l2_candidate(
            cache,
            ("2026-03", "2026-04"),
        )

        self.assertEqual(selected, 10.0)
        self.assertEqual(len(scores), len(L2_CANDIDATES))
        self.assertTrue(all(item["validation_races"] == 20 for item in scores))

    def test_l2_nonconvergence_is_ineligible(self):
        cache = {}
        for l2 in L2_CANDIDATES:
            cache[("2026-03", l2)] = {
                "status": "success",
                "races": 10,
                "sum_log_loss": 20.0,
                "mean_log_loss": 2.0,
            }
        cache[("2026-03", 100.0)] = {
            "status": "nonconvergence",
            "races": 0,
            "sum_log_loss": None,
            "mean_log_loss": None,
        }

        selected, scores = select_l2_candidate(cache, ("2026-03",))

        self.assertEqual(selected, 10.0)
        score_100 = next(item for item in scores if item["l2"] == 100.0)
        self.assertFalse(score_100["eligible"])

    def test_validation_cache_requires_matching_fingerprint_and_all_candidates(self):
        values = {}
        for month in ("2026-03", "2026-04", "2026-05", "2026-06"):
            for l2 in L2_CANDIDATES:
                values[(month, l2)] = {
                    "status": "success",
                    "races": 1,
                    "sum_log_loss": 1.0,
                    "mean_log_loss": 1.0,
                    "observations": [],
                }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation.json"

            write_validation_cache(
                path,
                cache_key="expected",
                validation_cache=values,
            )

            loaded = load_validation_cache(path, expected_key="expected")
            self.assertEqual(loaded, values)
            self.assertIsNone(
                load_validation_cache(path, expected_key="different")
            )


class MeetingAndQualityTests(unittest.TestCase):
    def test_meeting_ids_follow_title_day_number_and_date_boundaries(self):
        values = []
        for day, day_number, title in (
            (date(2026, 4, 1), 1, "A"),
            (date(2026, 4, 2), 2, "A"),
            (date(2026, 4, 4), 3, "A"),
            (date(2026, 4, 5), 1, "B"),
        ):
            race = make_race(day)
            values.append(
                replace(
                    race,
                    program=ProgramSnapshot(
                        race_fields={
                            "title": title,
                            "day_number": day_number,
                        },
                        racers=race.program.racers,
                    ),
                )
            )

        ids = assign_meeting_ids(values)

        self.assertEqual(ids[(date(2026, 4, 1), 1)], ids[(date(2026, 4, 2), 1)])
        self.assertNotEqual(ids[(date(2026, 4, 2), 1)], ids[(date(2026, 4, 4), 1)])
        self.assertNotEqual(ids[(date(2026, 4, 4), 1)], ids[(date(2026, 4, 5), 1)])

    def test_probability_quality_and_gate_use_race_level_outcomes(self):
        winner = "1-2"
        frequency = distribution(winner, 0.10)
        program = distribution(winner, 0.20)
        market = distribution(winner, 0.15)
        blend = distribution(winner, 0.25)
        rows = [
            {
                "winner": winner,
                "frequency": frequency,
                "program": program,
                "market": market,
                "blend": blend,
            }
            for _ in range(4)
        ]

        quality = probability_quality(rows)

        self.assertLess(
            quality["program"]["log_loss"],
            quality["frequency"]["log_loss"],
        )
        self.assertLess(
            quality["blend"]["log_loss"],
            quality["market"]["log_loss"],
        )
        folds = [
            {
                "probability_quality": {
                    "program_minus_frequency_log_loss": -0.1
                }
            }
            for _ in range(3)
        ] + [
            {
                "probability_quality": {
                    "program_minus_frequency_log_loss": 0.1
                }
            }
        ]
        gate = probability_signal_gate(folds, quality)
        self.assertEqual(
            gate["status"],
            "PASS_RETROSPECTIVE_SIGNAL_CANDIDATE",
        )
        self.assertFalse(gate["confirmatory_or_live_claim"])

    def test_compact_document_keeps_all_strategies_but_removes_race_rows(self):
        document = {
            "portfolio": {
                "strategies": {
                    name: {"metrics": {"bet_races": 1}, "races": [{"x": 1}]}
                    for name in (
                        "program_single",
                        "blend_single",
                        "program_dutch",
                        "blend_dutch",
                    )
                }
            }
        }

        compact = compact_document(document)

        self.assertEqual(
            set(compact["portfolio"]["strategies"]),
            {
                "program_single",
                "blend_single",
                "program_dutch",
                "blend_dutch",
            },
        )
        self.assertTrue(
            all(
                "races" not in value
                for value in compact["portfolio"]["strategies"].values()
            )
        )
        self.assertTrue(
            all(
                math.isfinite(value["metrics"]["bet_races"])
                for value in compact["portfolio"]["strategies"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
