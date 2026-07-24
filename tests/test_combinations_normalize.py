import math
import unittest
from datetime import date

from funayomi.combinations import (
    TRIFECTA_COMBINATIONS,
    combination_key,
    generate_trifecta_combinations,
    parse_combination,
)
from funayomi.errors import DataContractError
from funayomi.normalize import normalize_payload, normalize_race

from tests.helpers import (
    complete_odds,
    nested_odds,
    raw_payload,
    raw_race,
    result_racers,
)


class TrifectaCombinationTests(unittest.TestCase):
    def test_generates_exactly_120_unique_canonical_combinations(self):
        generated = generate_trifecta_combinations()

        self.assertEqual(len(generated), 120)
        self.assertEqual(len(set(generated)), 120)
        self.assertEqual(generated, TRIFECTA_COMBINATIONS)
        self.assertEqual(generated[0], "1-2-3")
        self.assertEqual(generated[-1], "6-5-4")
        for combination in generated:
            entries = parse_combination(combination)
            self.assertEqual(combination_key(entries), combination)
            self.assertEqual(len(set(entries)), 3)
            self.assertTrue(all(1 <= entry <= 6 for entry in entries))

    def test_rejects_noncanonical_or_impossible_combinations(self):
        invalid_values = (
            "",
            "1-2",
            "1-2-3-4",
            "1-1-2",
            "0-1-2",
            "1-2-7",
            "1/2/3",
            "a-b-c",
            "01-2-3",
            "1-02-3",
            " 1-2-3",
            "+1-2-3",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_combination(value)


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 5, 4)

    def test_extracts_only_ashiya_and_orders_races_numerically(self):
        payload = raw_payload(
            self.day,
            [
                raw_race(self.day, race_number=10),
                raw_race(self.day, race_number=2),
            ],
            include_other_stadium=True,
        )

        races = normalize_payload(payload, self.day, source_sha256="abc123")

        self.assertEqual([race.identity.race_number for race in races], [2, 10])
        self.assertTrue(all(race.identity.stadium_number == 21 for race in races))
        self.assertTrue(all(race.source_sha256 == "abc123" for race in races))

    def test_race_dictionary_keys_must_be_canonical_one_through_twelve(self):
        for invalid_key in ("01", "0", "13", 1):
            with self.subTest(invalid_key=invalid_key):
                payload = raw_payload(self.day, [raw_race(self.day)])
                races = payload["programs"]["stadiums"]["21"]["races"]
                race = races.pop("1")
                races[invalid_key] = race

                with self.assertRaises(DataContractError):
                    normalize_payload(payload, self.day)

    def test_malformed_root_is_not_silently_treated_as_an_empty_valid_day(self):
        malformed_values = ({}, {"programs": []}, {"programs": {"stadiums": []}})
        for value in malformed_values:
            with self.subTest(value=value):
                with self.assertRaises(DataContractError):
                    normalize_payload(value, self.day)

    def test_normalize_race_refuses_non_ashiya_record(self):
        raw = raw_race(self.day)
        raw["stadium_number"] = 24

        with self.assertRaises(DataContractError):
            normalize_race(raw, self.day)

    def test_normalizes_complete_nested_odds_to_all_120_keys(self):
        odds = complete_odds(default=15)
        odds["1-2-3"] = 42.5
        race = normalize_race(
            raw_race(self.day, odds=odds),
            self.day,
        )

        self.assertEqual(tuple(race.odds.trifecta), TRIFECTA_COMBINATIONS)
        self.assertEqual(len(race.odds.trifecta), 120)
        self.assertEqual(race.odds.trifecta["1-2-3"], 42.5)
        self.assertEqual(race.odds.trifecta["6-5-4"], 15.0)
        self.assertFalse(
            any("trifecta_odds_missing" in issue for issue in race.issues)
        )

    def test_missing_zero_negative_string_and_bool_odds_are_excluded(self):
        values = complete_odds(default=10)
        del values["1-2-3"]
        values["1-2-4"] = 0
        values["1-2-5"] = -1
        values["1-2-6"] = "12.3"
        values["1-3-2"] = True
        race = normalize_race(raw_race(self.day, odds=values), self.day)

        for combination in ("1-2-3", "1-2-4", "1-2-5", "1-2-6", "1-3-2"):
            with self.subTest(combination=combination):
                self.assertIsNone(race.odds.trifecta[combination])
        self.assertIn("trifecta_odds_unavailable_combinations:5", race.issues)
        self.assertIn("trifecta_odds_unavailable_zero:1", race.issues)
        self.assertIn("trifecta_odds_invalid_combinations:3", race.issues)

    def test_non_finite_odds_are_excluded_as_invalid(self):
        values = complete_odds(default=10)
        values["1-2-3"] = math.nan
        values["1-2-4"] = math.inf
        race = normalize_race(raw_race(self.day, odds=values), self.day)

        self.assertIsNone(race.odds.trifecta["1-2-3"])
        self.assertIsNone(race.odds.trifecta["1-2-4"])
        self.assertIn("trifecta_odds_unavailable_combinations:2", race.issues)
        self.assertIn("trifecta_odds_invalid_combinations:2", race.issues)

    def test_missing_result_is_explicitly_ineligible(self):
        raw = raw_race(self.day)
        raw.pop("result")

        race = normalize_race(raw, self.day)

        self.assertEqual(race.outcome.status, "missing")
        self.assertIsNone(race.outcome.winning_trifecta)
        self.assertFalse(race.training_eligible)
        # 評価時の選択可否を結果の有無で決めると未来情報漏洩になるため、
        # 6艇の事前情報があれば選択自体は可能。
        self.assertTrue(race.evaluation_eligible)
        self.assertIn("result_missing", race.issues)

    def test_dead_heat_or_multiple_payouts_is_non_standard(self):
        raw = raw_race(self.day)
        racers = result_racers("1-2-3")
        racers["2"]["place_number"] = 1
        raw["result"] = {
            "racers": racers,
            "payouts": {
                "trifecta": [
                    {"combination": "1-2-3", "amount": 1000},
                    {"combination": "2-1-3", "amount": 1000},
                ]
            },
        }

        race = normalize_race(raw, self.day)

        self.assertEqual(race.outcome.status, "multiple_trifecta_payouts")
        self.assertEqual(
            race.outcome.winning_trifectas, ("1-2-3", "2-1-3")
        )
        self.assertIsNone(race.outcome.winning_trifecta)
        self.assertFalse(race.training_eligible)
        self.assertTrue(race.evaluation_eligible)
        self.assertIn("result_non_standard_places", race.issues)
        self.assertIn("result_trifecta_payout_count:2", race.issues)

    def test_flying_or_late_nonstarter_with_single_payout_is_exception_settleable(self):
        for marker in ("F", "L"):
            with self.subTest(marker=marker):
                raw = raw_race(self.day, winner="1-2-3")
                raw["result"]["racers"]["6"]["place_number"] = None
                raw["result"]["racers"]["6"]["place_number_source"] = marker

                race = normalize_race(raw, self.day)

                self.assertEqual(race.outcome.status, "exception_settled")
                self.assertTrue(race.outcome.is_settleable)
                self.assertEqual(race.outcome.winning_trifecta, "1-2-3")
                self.assertEqual(race.outcome.nonstarter_entries, (6,))
                self.assertFalse(race.training_eligible)
                self.assertTrue(race.evaluation_eligible)
                self.assertIn("result_non_standard_places", race.issues)

    def test_no_trifecta_payout_is_explicit_not_established_outcome(self):
        raw = raw_race(self.day)
        raw["result"]["payouts"]["trifecta"] = []
        raw["result"]["racers"]["3"]["place_number"] = None
        raw["result"]["racers"]["3"]["place_number_source"] = "F"

        race = normalize_race(raw, self.day)

        self.assertEqual(race.outcome.status, "trifecta_not_established")
        self.assertFalse(race.outcome.is_settleable)
        self.assertEqual(race.outcome.winning_trifectas, ())
        self.assertFalse(race.training_eligible)
        self.assertTrue(race.evaluation_eligible)
        self.assertIn("result_trifecta_payout_count:0", race.issues)

    def test_missing_wrong_or_invalid_payout_data_is_inconsistent_not_refunded(self):
        cases = {}

        empty_with_normal_winner = raw_race(self.day)
        empty_with_normal_winner["result"]["payouts"]["trifecta"] = []
        cases["empty_with_normal_winner"] = empty_with_normal_winner

        empty_with_missing_racers = raw_race(self.day)
        empty_with_missing_racers["result"]["payouts"]["trifecta"] = []
        empty_with_missing_racers["result"].pop("racers")
        cases["empty_with_missing_racers"] = empty_with_missing_racers

        missing_container = raw_race(self.day)
        missing_container["result"].pop("payouts")
        cases["missing_container"] = missing_container

        missing_trifecta = raw_race(self.day)
        missing_trifecta["result"]["payouts"] = {}
        cases["missing_trifecta"] = missing_trifecta

        wrong_type = raw_race(self.day)
        wrong_type["result"]["payouts"]["trifecta"] = {}
        cases["wrong_type"] = wrong_type

        non_object_item = raw_race(self.day)
        non_object_item["result"]["payouts"]["trifecta"] = [None]
        cases["non_object_item"] = non_object_item

        invalid_combination = raw_race(self.day)
        invalid_combination["result"]["payouts"]["trifecta"] = [
            {"combination": "1-1-2", "amount": 1000}
        ]
        cases["invalid_combination"] = invalid_combination

        invalid_amount = raw_race(self.day)
        invalid_amount["result"]["payouts"]["trifecta"] = [
            {"combination": "1-2-3", "amount": 0}
        ]
        cases["invalid_amount"] = invalid_amount

        duplicate = raw_race(self.day)
        duplicate["result"]["payouts"]["trifecta"].append(
            {"combination": "1-2-3", "amount": 1200}
        )
        cases["duplicate"] = duplicate

        for label, raw in cases.items():
            with self.subTest(label=label):
                race = normalize_race(raw, self.day)
                self.assertEqual(race.outcome.status, "inconsistent")
                self.assertNotEqual(
                    race.outcome.status, "trifecta_not_established"
                )
                self.assertFalse(race.outcome.is_settleable)
                self.assertFalse(race.training_eligible)
                self.assertTrue(race.evaluation_eligible)

    def test_less_than_six_program_entries_is_ineligible(self):
        raw = raw_race(self.day, entries=(1, 2, 3, 4, 5))

        race = normalize_race(raw, self.day)

        self.assertFalse(race.has_full_field)
        self.assertFalse(race.training_eligible)
        self.assertFalse(race.evaluation_eligible)
        self.assertIn("program_field_not_six_entries", race.issues)

    def test_payout_combination_must_match_recorded_places(self):
        raw = raw_race(self.day, winner="1-2-3")
        raw["result"]["payouts"]["trifecta"][0]["combination"] = "2-1-3"

        race = normalize_race(raw, self.day)

        self.assertEqual(race.outcome.status, "inconsistent")
        self.assertFalse(race.outcome.is_settleable)
        self.assertFalse(race.training_eligible)
        self.assertTrue(
            any("mismatch" in issue for issue in race.issues),
            race.issues,
        )

    def test_program_snapshot_does_not_copy_post_race_or_market_fields(self):
        raw = raw_race(self.day)
        raw.update(
            {
                "payout": 999999,
                "place_number": 1,
                "technique_number": 7,
                "post_race_secret": "must not leak",
            }
        )
        raw["racers"]["1"].update(
            {"place_number": 1, "payout": 999999, "result": "won"}
        )

        race = normalize_race(raw, self.day)

        forbidden = {
            "payout",
            "place_number",
            "technique_number",
            "post_race_secret",
            "result",
            "odds",
        }
        self.assertTrue(forbidden.isdisjoint(race.program.race_fields))
        self.assertTrue(forbidden.isdisjoint(race.program.racers[1]))

    def test_date_and_race_number_mismatches_are_rejected(self):
        wrong_date = raw_race(self.day, race_number=1)
        wrong_date["date"] = "2026-05-03"
        wrong_race_number = raw_race(self.day, race_number=2)

        with self.assertRaises(DataContractError):
            normalize_race(
                wrong_date, self.day, expected_race_number=1
            )
        with self.assertRaises(DataContractError):
            normalize_race(
                wrong_race_number, self.day, expected_race_number=1
            )


if __name__ == "__main__":
    unittest.main()
