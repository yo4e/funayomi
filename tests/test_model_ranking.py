import dataclasses
import hashlib
import math
import unittest
from datetime import date

from funayomi.combinations import TRIFECTA_COMBINATIONS
from funayomi.domain import OddsSnapshot, PreviewSnapshot, RaceOutcome
from funayomi.errors import ChronologyError, DataContractError
from funayomi.model import (
    FORBIDDEN_PREDICTION_FEATURES,
    PREDICTION_CUTOFF,
    PREDICTION_FEATURES,
    SmoothedTrifectaFrequencyModel,
)
from funayomi.ranking import rank_race, ranking_to_dict

from tests.helpers import complete_odds, make_race


class ProbabilityModelTests(unittest.TestCase):
    def setUp(self):
        self.prediction_day = date(2026, 5, 10)

    def test_empty_history_is_smoothed_uniform_and_sums_to_one(self):
        model = SmoothedTrifectaFrequencyModel.fit(
            [], prediction_date=self.prediction_day, prior_count_per_combination=1
        )
        target = make_race(self.prediction_day)

        prediction = model.predict(target)

        self.assertEqual(len(prediction.estimates), 120)
        self.assertTrue(
            math.isclose(
                prediction.probability_sum,
                1.0,
                rel_tol=0,
                abs_tol=1e-12,
            )
        )
        for estimate in prediction.estimates.values():
            self.assertEqual(estimate.probability, 1 / 120)
            self.assertEqual(estimate.observed_count, 0)
            self.assertEqual(estimate.training_races, 0)
            self.assertEqual(estimate.reliability, "low_total_support")

    def test_dirichlet_smoothing_uses_only_eligible_historical_winners(self):
        races = [
            make_race(date(2026, 5, 3), race_number=2, winner="1-2-3"),
            make_race(date(2026, 5, 2), race_number=1, winner="1-2-3"),
            make_race(date(2026, 5, 4), race_number=3, winner="2-1-3"),
            make_race(
                date(2026, 5, 1),
                race_number=4,
                winner="6-5-4",
                outcome_status="non_standard",
            ),
        ]
        model = SmoothedTrifectaFrequencyModel.fit(
            reversed(races),
            prediction_date=self.prediction_day,
            prior_count_per_combination=0.5,
        )

        prediction = model.predict(make_race(self.prediction_day))

        self.assertEqual(model.training_races, 3)
        self.assertEqual(model.training_start, date(2026, 5, 2))
        self.assertEqual(model.training_end, date(2026, 5, 4))
        denominator = 3 + 120 * 0.5
        self.assertEqual(
            prediction.estimates["1-2-3"].probability, (2 + 0.5) / denominator
        )
        self.assertEqual(
            prediction.estimates["2-1-3"].probability, (1 + 0.5) / denominator
        )
        self.assertEqual(
            prediction.estimates["6-5-4"].probability, 0.5 / denominator
        )
        self.assertEqual(prediction.estimates["1-2-3"].observed_count, 2)

    def test_same_input_is_deterministic_regardless_of_iterable_order(self):
        races = [
            make_race(date(2026, 5, 1), race_number=2, winner="2-1-3"),
            make_race(date(2026, 5, 1), race_number=1, winner="1-2-3"),
            make_race(date(2026, 5, 2), race_number=1, winner="1-2-3"),
        ]
        first = SmoothedTrifectaFrequencyModel.fit(
            races, prediction_date=self.prediction_day
        ).predict(make_race(self.prediction_day))
        second = SmoothedTrifectaFrequencyModel.fit(
            list(reversed(races)), prediction_date=self.prediction_day
        ).predict(make_race(self.prediction_day))

        self.assertEqual(first, second)
        self.assertEqual(tuple(first.estimates), TRIFECTA_COMBINATIONS)
        self.assertEqual(len(first.training_fingerprint), 64)
        int(first.training_fingerprint, 16)

    def test_training_fingerprint_changes_with_audited_source(self):
        first_race = make_race(
            date(2026, 5, 1),
            winner="1-2-3",
            source_sha256="raw-version-one",
        )
        changed_source = dataclasses.replace(
            first_race,
            source_sha256="raw-version-two",
        )
        first = SmoothedTrifectaFrequencyModel.fit(
            [first_race], prediction_date=self.prediction_day
        ).predict(make_race(self.prediction_day))
        second = SmoothedTrifectaFrequencyModel.fit(
            [changed_source], prediction_date=self.prediction_day
        ).predict(make_race(self.prediction_day))

        self.assertNotEqual(
            first.training_fingerprint, second.training_fingerprint
        )
        empty = SmoothedTrifectaFrequencyModel.fit(
            [], prediction_date=self.prediction_day
        ).predict(make_race(self.prediction_day))
        self.assertEqual(
            empty.training_fingerprint,
            hashlib.sha256(b"").hexdigest(),
        )

    def test_duplicate_training_race_identity_is_rejected(self):
        race = make_race(date(2026, 5, 1), race_number=1)

        with self.assertRaises(DataContractError):
            SmoothedTrifectaFrequencyModel.fit(
                [race, race],
                prediction_date=self.prediction_day,
            )

    def test_fit_rejects_same_day_and_future_training_records(self):
        for training_day in (
            self.prediction_day,
            date(2026, 5, 11),
        ):
            with self.subTest(training_day=training_day):
                with self.assertRaises(ChronologyError):
                    SmoothedTrifectaFrequencyModel.fit(
                        [make_race(training_day)],
                        prediction_date=self.prediction_day,
                    )

    def test_predict_rejects_target_on_or_before_included_training_history(self):
        model = SmoothedTrifectaFrequencyModel.fit(
            [make_race(date(2026, 5, 5), winner="1-2-3")],
            prediction_date=self.prediction_day,
        )

        for target_day in (date(2026, 5, 4), date(2026, 5, 5)):
            with self.subTest(target_day=target_day):
                with self.assertRaises(ChronologyError):
                    model.predict(make_race(target_day))

    def test_fit_refuses_non_ashiya_training_records(self):
        with self.assertRaises(DataContractError):
            SmoothedTrifectaFrequencyModel.fit(
                [
                    make_race(
                        date(2026, 5, 1),
                        stadium_number=24,
                    )
                ],
                prediction_date=self.prediction_day,
            )

    def test_prediction_uses_program_boundary_not_preview_odds_or_outcome(self):
        model = SmoothedTrifectaFrequencyModel.fit(
            [make_race(date(2026, 5, 1), winner="1-2-3")],
            prediction_date=self.prediction_day,
        )
        target = make_race(self.prediction_day)
        changed_future = dataclasses.replace(
            target,
            preview=PreviewSnapshot(
                fields={"wind_speed": 99, "post_race": "poison"},
                racers={},
            ),
            odds=OddsSnapshot(
                trifecta=complete_odds(9999),
                observed_at="after-the-race",
            ),
            outcome=RaceOutcome(
                status="non_standard",
                winning_trifectas=("6-5-4", "5-6-4"),
                trifecta_payouts={"6-5-4": 999999},
                racers={},
            ),
        )

        baseline = model.predict(target)
        mutated = model.predict(changed_future)

        self.assertEqual(baseline, mutated)
        self.assertEqual(baseline.prediction_cutoff, PREDICTION_CUTOFF)
        self.assertEqual(baseline.feature_names, PREDICTION_FEATURES)
        feature_text = " ".join(baseline.feature_names).lower()
        for forbidden in FORBIDDEN_PREDICTION_FEATURES:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden.lower(), feature_text)

    def test_prediction_rejects_foreign_venue_and_incomplete_field(self):
        model = SmoothedTrifectaFrequencyModel.fit(
            [], prediction_date=self.prediction_day
        )
        with self.assertRaises(DataContractError):
            model.predict(
                make_race(self.prediction_day, stadium_number=24)
            )
        with self.assertRaises(DataContractError):
            model.predict(
                make_race(self.prediction_day, entries=(1, 2, 3, 4, 5))
            )

    def test_invalid_prior_and_inconsistent_direct_counts_are_rejected(self):
        for invalid_prior in (0, -1, math.nan, math.inf):
            with self.subTest(invalid_prior=invalid_prior):
                with self.assertRaises(ValueError):
                    SmoothedTrifectaFrequencyModel(
                        {},
                        0,
                        prior_count_per_combination=invalid_prior,
                    )
        with self.assertRaises(ValueError):
            SmoothedTrifectaFrequencyModel(
                {"1-2-3": -1}, -1, prior_count_per_combination=1
            )
        with self.assertRaises(DataContractError):
            SmoothedTrifectaFrequencyModel(
                {"1-2-3": 1}, 2, prior_count_per_combination=1
            )


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 5, 10)
        self.prediction = SmoothedTrifectaFrequencyModel.fit(
            [], prediction_date=self.day
        ).predict(make_race(self.day))

    def test_expected_value_formula_descending_sort_and_support(self):
        odds = complete_odds(
            10,
            {
                "1-2-3": 240,
                "1-3-2": 120,
            },
        )
        result = rank_race(
            make_race(self.day, odds=odds),
            self.prediction,
            threshold=1.5,
        )

        self.assertEqual(result.decision, "CANDIDATES")
        self.assertEqual(result.qualifying_count, 1)
        self.assertEqual(len(result.rows), 120)
        self.assertEqual(result.rows[0].combination, "1-2-3")
        self.assertEqual(result.rows[0].rank, 1)
        self.assertEqual(result.rows[0].expected_return, 2.0)
        self.assertEqual(result.rows[0].expected_profit_rate, 1.0)
        self.assertTrue(result.rows[0].qualifies)
        expected_values = [
            row.expected_return
            for row in result.rows
            if row.expected_return is not None
        ]
        self.assertEqual(expected_values, sorted(expected_values, reverse=True))
        for row in result.rows:
            self.assertEqual(
                row.expected_return,
                row.predicted_probability * row.odds,
            )
            self.assertEqual(
                row.expected_profit_rate,
                row.expected_return - 1,
            )
            self.assertEqual(row.training_races, 0)
            self.assertTrue(row.explanation)

    def test_equal_expected_values_use_canonical_combination_tie_break(self):
        result = rank_race(
            make_race(self.day, odds=complete_odds(10)),
            self.prediction,
            threshold=100,
        )

        self.assertEqual(
            [row.combination for row in result.rows],
            list(TRIFECTA_COMBINATIONS),
        )

    def test_no_qualifying_combination_returns_pass(self):
        result = rank_race(
            make_race(self.day, odds=complete_odds(10)),
            self.prediction,
            threshold=1.0,
        )

        self.assertEqual(result.decision, "PASS")
        self.assertEqual(result.qualifying_count, 0)
        self.assertFalse(any(row.qualifies for row in result.rows))

    def test_missing_or_zero_odds_skips_entire_market_safely(self):
        odds = complete_odds(500)
        odds.pop("1-2-3")
        odds["1-2-4"] = 0
        result = rank_race(
            make_race(self.day, odds=odds),
            self.prediction,
            threshold=1.0,
        )

        self.assertEqual(result.decision, "SKIP_DATA")
        self.assertEqual(result.qualifying_count, 0)
        self.assertFalse(any(row.qualifies for row in result.rows))
        by_combination = {row.combination: row for row in result.rows}
        for combination in ("1-2-3", "1-2-4"):
            row = by_combination[combination]
            self.assertIsNone(row.expected_return)
            self.assertIsNone(row.expected_profit_rate)
            self.assertEqual(row.exclusion_reason, "missing_or_invalid_odds")

    def test_threshold_is_inclusive_and_negative_threshold_is_rejected(self):
        odds = complete_odds(1)
        odds["1-2-3"] = 120
        result = rank_race(
            make_race(self.day, odds=odds),
            self.prediction,
            threshold=1.0,
        )
        self.assertTrue(
            next(
                row for row in result.rows if row.combination == "1-2-3"
            ).qualifies
        )
        for invalid_threshold in (-0.01, math.nan, math.inf):
            with self.subTest(invalid_threshold=invalid_threshold):
                with self.assertRaises(ValueError):
                    rank_race(
                        make_race(self.day),
                        self.prediction,
                        threshold=invalid_threshold,
                    )

    def test_non_finite_direct_market_odds_are_skip_data(self):
        for non_finite in (math.nan, math.inf):
            with self.subTest(non_finite=non_finite):
                result = rank_race(
                    make_race(
                        self.day,
                        odds=complete_odds(
                            10, {"1-2-3": non_finite}
                        ),
                    ),
                    self.prediction,
                )
                self.assertEqual(result.decision, "SKIP_DATA")
                row = next(
                    row
                    for row in result.rows
                    if row.combination == "1-2-3"
                )
                self.assertIsNone(row.expected_return)
                self.assertEqual(
                    row.exclusion_reason, "missing_or_invalid_odds"
                )

    def test_machine_readable_ranking_preserves_audit_fields(self):
        race = make_race(
            self.day,
            odds=complete_odds(10),
            issues=("fixture_warning",),
        )
        value = ranking_to_dict(rank_race(race, self.prediction, threshold=2))

        self.assertEqual(value["date"], self.day.isoformat())
        self.assertEqual(value["stadium_number"], 21)
        self.assertEqual(value["race_number"], 1)
        self.assertEqual(value["training"]["prediction_cutoff"], "program")
        self.assertEqual(value["training"]["features"], list(PREDICTION_FEATURES))
        self.assertEqual(
            value["training"]["fingerprint"],
            self.prediction.training_fingerprint,
        )
        self.assertIn("fixture_warning", value["warnings"])
        self.assertEqual(len(value["rankings"]), 120)
        self.assertEqual(
            value["rankings"][0]["support"]["training_races"], 0
        )


if __name__ == "__main__":
    unittest.main()
