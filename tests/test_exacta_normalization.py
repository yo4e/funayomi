import json
import math
import unittest
from datetime import date
from typing import Any, Dict, Mapping, Optional

from funayomi.combinations import (
    EXACTA_COMBINATIONS,
    exacta_combination_key,
    generate_exacta_combinations,
    parse_exacta_combination,
)
from funayomi.errors import DataContractError
from funayomi.normalize import SCHEMA_VERSION, normalize_race
from funayomi.serialization import race_from_dict, race_to_dict

from tests.helpers import raw_race


def complete_exacta_odds(
    default: Any = 10.0,
    overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    values = {combination: default for combination in EXACTA_COMBINATIONS}
    if overrides:
        values.update(overrides)
    return values


def nested_exacta_odds(
    values: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    nested: Dict[str, Dict[str, Any]] = {}
    for combination, odd in values.items():
        first, second = parse_exacta_combination(combination)
        nested.setdefault(str(first), {})[str(second)] = odd
    return nested


def exacta_ready_race(
    day: date,
    *,
    odds: Optional[Mapping[str, Any]] = None,
    winner: str = "1-2-3",
    exacta_winner: str = "1-2",
    exacta_payout: int = 830,
) -> Dict[str, Any]:
    raw = raw_race(day, winner=winner)
    raw["odds"]["exacta"] = nested_exacta_odds(
        odds if odds is not None else complete_exacta_odds()
    )
    raw["result"]["payouts"]["exacta"] = [
        {"combination": exacta_winner, "amount": exacta_payout}
    ]
    return raw


class ExactaCombinationTests(unittest.TestCase):
    def test_generates_exactly_30_unique_canonical_combinations(self):
        generated = generate_exacta_combinations()

        self.assertEqual(generated, EXACTA_COMBINATIONS)
        self.assertEqual(len(generated), 30)
        self.assertEqual(len(set(generated)), 30)
        self.assertEqual(generated[0], "1-2")
        self.assertEqual(generated[-1], "6-5")
        for combination in generated:
            entries = parse_exacta_combination(combination)
            self.assertEqual(exacta_combination_key(entries), combination)
            self.assertEqual(len(set(entries)), 2)

    def test_rejects_noncanonical_or_impossible_exacta_combinations(self):
        invalid_values = (
            "",
            "1",
            "1-2-3",
            "1-1",
            "0-1",
            "1-7",
            "1/2",
            "a-b",
            "01-2",
            "1-02",
            " 1-2",
            "+1-2",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_exacta_combination(value)


class ExactaNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 5, 4)

    def test_normalizes_all_odds_and_clean_exacta_outcome(self):
        odds = complete_exacta_odds(15, {"1-2": 8.3})

        race = normalize_race(
            exacta_ready_race(self.day, odds=odds),
            self.day,
        )

        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertEqual(tuple(race.odds.exacta), EXACTA_COMBINATIONS)
        self.assertEqual(len(race.odds.exacta), 30)
        self.assertEqual(race.odds.exacta["1-2"], 8.3)
        self.assertEqual(race.odds.exacta["6-5"], 15.0)
        self.assertEqual(race.outcome.exacta_status, "standard")
        self.assertEqual(race.outcome.winning_exactas, ("1-2",))
        self.assertEqual(race.outcome.winning_exacta, "1-2")
        self.assertEqual(race.outcome.exacta_payouts, {"1-2": 830})
        self.assertTrue(race.outcome.is_exacta_settleable)
        self.assertTrue(race.exacta_training_eligible)
        self.assertTrue(race.exacta_probability_training_eligible)
        self.assertTrue(race.exacta_evaluation_eligible)
        self.assertTrue(race.exacta_settlement_eligible)
        self.assertFalse(any("exacta_odds_missing" in item for item in race.issues))

    def test_missing_or_invalid_exacta_odds_are_none_and_reported(self):
        odds = complete_exacta_odds()
        del odds["1-2"]
        odds["1-3"] = 0
        odds["1-4"] = -1
        odds["1-5"] = "8.5"
        odds["1-6"] = True
        odds["2-1"] = math.inf

        race = normalize_race(
            exacta_ready_race(self.day, odds=odds),
            self.day,
        )

        for combination in ("1-2", "1-3", "1-4", "1-5", "1-6", "2-1"):
            with self.subTest(combination=combination):
                self.assertIsNone(race.odds.exacta[combination])
        self.assertIn("exacta_odds_unavailable_combinations:6", race.issues)
        self.assertIn("exacta_odds_unavailable_zero:1", race.issues)
        self.assertIn("exacta_odds_invalid_combinations:4", race.issues)

    def test_lower_place_tie_remains_clean_for_exacta_only(self):
        raw = exacta_ready_race(self.day)
        raw["result"]["racers"]["5"]["place_number"] = 4
        raw["result"]["racers"]["5"]["place_number_source"] = "4"

        race = normalize_race(raw, self.day)

        self.assertEqual(race.outcome.status, "exception_settled")
        self.assertFalse(race.training_eligible)
        self.assertEqual(race.outcome.exacta_status, "standard")
        self.assertTrue(race.exacta_training_eligible)
        self.assertEqual(race.outcome.winning_exacta, "1-2")

    def test_known_result_exceptions_are_not_probability_clean_but_can_settle(self):
        for marker in ("F", "L", "転"):
            with self.subTest(marker=marker):
                raw = exacta_ready_race(self.day)
                raw["result"]["racers"]["6"]["place_number"] = None
                raw["result"]["racers"]["6"]["place_number_source"] = marker

                race = normalize_race(raw, self.day)

                self.assertEqual(
                    race.outcome.exacta_status, "exception_settled"
                )
                self.assertFalse(race.exacta_training_eligible)
                self.assertTrue(race.exacta_evaluation_eligible)
                self.assertTrue(race.outcome.is_exacta_settleable)
                self.assertTrue(race.exacta_settlement_eligible)

    def test_exacta_payout_mismatch_fails_closed(self):
        raw = exacta_ready_race(
            self.day,
            exacta_winner="2-1",
        )

        race = normalize_race(raw, self.day)

        self.assertEqual(race.outcome.exacta_status, "inconsistent")
        self.assertEqual(race.outcome.winning_exacta, "2-1")
        self.assertFalse(race.outcome.is_exacta_settleable)
        self.assertFalse(race.exacta_training_eligible)
        self.assertFalse(race.exacta_settlement_eligible)
        self.assertIn("result_exacta_payout_order_mismatch", race.issues)

    def test_top_two_dead_heat_and_multiple_payouts_fail_closed(self):
        raw = exacta_ready_race(self.day)
        raw["result"]["racers"]["2"]["place_number"] = 1
        raw["result"]["racers"]["2"]["place_number_source"] = "1"
        raw["result"]["payouts"]["exacta"] = [
            {"combination": "1-2", "amount": 830},
            {"combination": "2-1", "amount": 830},
        ]

        race = normalize_race(raw, self.day)

        self.assertEqual(
            race.outcome.exacta_status, "multiple_exacta_payouts"
        )
        self.assertEqual(race.outcome.winning_exactas, ("1-2", "2-1"))
        self.assertIsNone(race.outcome.winning_exacta)
        self.assertFalse(race.outcome.is_exacta_settleable)
        self.assertFalse(race.exacta_training_eligible)
        self.assertIn("result_exacta_top_two_not_unique", race.issues)
        self.assertIn("result_exacta_payout_count:2", race.issues)

    def test_missing_or_invalid_exacta_payout_is_inconsistent(self):
        cases = {}
        missing = exacta_ready_race(self.day)
        missing["result"]["payouts"].pop("exacta")
        cases["missing"] = missing

        wrong_type = exacta_ready_race(self.day)
        wrong_type["result"]["payouts"]["exacta"] = {}
        cases["wrong_type"] = wrong_type

        invalid_combination = exacta_ready_race(self.day)
        invalid_combination["result"]["payouts"]["exacta"] = [
            {"combination": "1-1", "amount": 830}
        ]
        cases["invalid_combination"] = invalid_combination

        invalid_amount = exacta_ready_race(self.day)
        invalid_amount["result"]["payouts"]["exacta"] = [
            {"combination": "1-2", "amount": 0}
        ]
        cases["invalid_amount"] = invalid_amount

        duplicate = exacta_ready_race(self.day)
        duplicate["result"]["payouts"]["exacta"].append(
            {"combination": "1-2", "amount": 900}
        )
        cases["duplicate"] = duplicate

        for label, raw in cases.items():
            with self.subTest(label=label):
                race = normalize_race(raw, self.day)
                self.assertEqual(
                    race.outcome.exacta_status, "inconsistent"
                )
                self.assertFalse(race.outcome.is_exacta_settleable)
                self.assertFalse(race.exacta_training_eligible)

    def test_unobserved_empty_exacta_payout_fails_closed(self):
        raw = exacta_ready_race(self.day)
        raw["result"]["racers"]["2"]["place_number"] = None
        raw["result"]["racers"]["2"]["place_number_source"] = "F"
        raw["result"]["payouts"]["exacta"] = []

        race = normalize_race(raw, self.day)

        self.assertEqual(race.outcome.exacta_status, "inconsistent")
        self.assertEqual(race.outcome.winning_exactas, ())
        self.assertFalse(race.outcome.is_exacta_settleable)
        self.assertFalse(race.exacta_training_eligible)
        self.assertIn("result_exacta_payout_count:0", race.issues)

    def test_serialization_round_trip_preserves_exacta_and_rejects_old_shape(self):
        original = normalize_race(exacta_ready_race(self.day), self.day)

        value = race_to_dict(original)
        restored = race_from_dict(
            json.loads(json.dumps(value, ensure_ascii=False))
        )

        self.assertEqual(restored, original)
        self.assertEqual(value["odds"]["exacta"]["1-2"], 10.0)
        self.assertEqual(value["outcome"]["exacta_status"], "standard")
        self.assertTrue(value["eligibility"]["exacta_training"])
        self.assertTrue(value["eligibility"]["exacta_evaluation"])
        self.assertTrue(value["eligibility"]["exacta_settlement"])

        value["odds"].pop("exacta")
        with self.assertRaises(DataContractError):
            race_from_dict(value)


if __name__ == "__main__":
    unittest.main()
