import copy
import hashlib
import math
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from funayomi.domain import ProgramSnapshot, RaceIdentity
from funayomi.errors import ChronologyError, DataContractError
from funayomi.exacta_model import (
    EXACTA_COMBINATIONS,
    FORBIDDEN_PREDICTION_FEATURES,
    ModelConvergenceError,
    NUMERIC_PROGRAM_FEATURES,
    ProgramPlackettLuceModel,
    SmoothedExactaFrequencyModel,
)


def make_exacta_race(
    day,
    *,
    race_number=1,
    stadium_number=21,
    winner="1-2",
    strengths=None,
    clean=True,
    source_sha256="fixture-source",
):
    first, second = (int(value) for value in winner.split("-"))
    order = [first, second] + [
        entry for entry in range(1, 7) if entry not in (first, second)
    ]
    place_by_entry = {
        entry: place for place, entry in enumerate(order, start=1)
    }
    strength_by_entry = strengths or {
        entry: float(7 - entry) for entry in range(1, 7)
    }
    racers = {}
    for entry in range(1, 7):
        record = {
            "entry_number": entry,
            "rank_number": (entry % 4) + 1,
        }
        for feature_index, name in enumerate(NUMERIC_PROGRAM_FEATURES):
            record[name] = (
                float(strength_by_entry[entry])
                if name == "national_win_rate"
                else 1.0 + feature_index / 10.0 + entry / 100.0
            )
        racers[entry] = record
    result_racers = {
        entry: {
            "entry_number": entry,
            "place_number": place_by_entry[entry],
            "place_number_source": str(place_by_entry[entry]),
        }
        for entry in range(1, 7)
    }
    return SimpleNamespace(
        identity=RaceIdentity(
            date=day,
            stadium_number=stadium_number,
            race_number=race_number,
            closed_at=None,
        ),
        program=ProgramSnapshot(race_fields={}, racers=racers),
        preview=SimpleNamespace(fields={"post_program": "ignored"}),
        odds=SimpleNamespace(exacta={"1-2": 9999.0}),
        outcome=SimpleNamespace(
            racers=result_racers,
            winning_exacta=winner if clean else None,
            exacta_payouts={winner: 1200} if clean else {},
            poison="must never be a prediction feature",
        ),
        exacta_training_eligible=clean,
        source_sha256=source_sha256,
    )


def synthetic_training_races(count=48):
    start = date(2026, 1, 1)
    races = []
    for index in range(count):
        first = index % 6 + 1
        second = (index + 1) % 6 + 1
        strengths = {entry: 1.0 for entry in range(1, 7)}
        strengths[first] = 10.0
        strengths[second] = 7.0
        races.append(
            make_exacta_race(
                start + timedelta(days=index // 12),
                race_number=index % 12 + 1,
                winner=f"{first}-{second}",
                strengths=strengths,
                source_sha256=f"source-{index // 12}",
            )
        )
    return races


class ExactaFrequencyBaselineTests(unittest.TestCase):
    def test_canonical_space_and_smoothed_probabilities(self):
        self.assertEqual(len(EXACTA_COMBINATIONS), 30)
        self.assertEqual(len(set(EXACTA_COMBINATIONS)), 30)
        races = [
            make_exacta_race(date(2026, 1, 1), race_number=1, winner="1-2"),
            make_exacta_race(date(2026, 1, 1), race_number=2, winner="1-2"),
            make_exacta_race(date(2026, 1, 1), race_number=3, winner="2-1"),
        ]
        model = SmoothedExactaFrequencyModel.fit(
            reversed(races),
            prediction_date=date(2026, 1, 2),
            prior_count_per_combination=1.0,
        )

        prediction = model.predict(make_exacta_race(date(2026, 1, 2)))

        self.assertEqual(tuple(prediction.probabilities), EXACTA_COMBINATIONS)
        self.assertAlmostEqual(prediction.probability_sum, 1.0, places=14)
        self.assertEqual(prediction.probabilities["1-2"], 3 / 33)
        self.assertEqual(prediction.probabilities["2-1"], 2 / 33)
        self.assertEqual(prediction.probabilities["6-5"], 1 / 33)
        self.assertEqual(model.training_races, 3)

    def test_empty_baseline_is_uniform_but_invalid_prior_is_rejected(self):
        model = SmoothedExactaFrequencyModel.fit(
            [], prediction_date=date(2026, 1, 2)
        )
        prediction = model.predict(make_exacta_race(date(2026, 1, 2)))
        self.assertTrue(
            all(value == 1 / 30 for value in prediction.probabilities.values())
        )
        self.assertEqual(
            prediction.training_fingerprint,
            hashlib.sha256(b"").hexdigest(),
        )
        with self.assertRaises(ValueError):
            SmoothedExactaFrequencyModel.fit(
                [],
                prediction_date=date(2026, 1, 2),
                prior_count_per_combination=0,
            )


class ProgramPlackettLuceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.races = synthetic_training_races()
        cls.prediction_date = date(2026, 1, 10)
        cls.model = ProgramPlackettLuceModel.fit(
            cls.races,
            prediction_date=cls.prediction_date,
            l2=0.1,
        )

    def test_optimizer_converges_and_improves_penalized_training_objective(self):
        summary = self.model.optimization
        self.assertTrue(summary.converged)
        self.assertLess(summary.final_objective, summary.initial_objective)
        self.assertLessEqual(summary.gradient_infinity_norm, 1e-8)
        self.assertGreater(summary.iterations, 0)
        self.assertEqual(self.model.training_races, len(self.races))

    def test_prediction_is_positive_canonical_and_sums_to_one(self):
        strengths = {entry: 1.0 for entry in range(1, 7)}
        strengths[4] = 12.0
        strengths[2] = 8.0
        prediction = self.model.predict(
            make_exacta_race(
                self.prediction_date,
                winner="4-2",
                strengths=strengths,
            )
        )

        self.assertEqual(tuple(prediction.probabilities), EXACTA_COMBINATIONS)
        self.assertTrue(
            all(
                math.isfinite(value) and value > 0
                for value in prediction.probabilities.values()
            )
        )
        self.assertTrue(
            math.isclose(
                prediction.probability_sum,
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        self.assertEqual(
            max(prediction.probabilities, key=prediction.probabilities.get),
            "4-2",
        )

    def test_prediction_reads_program_not_preview_odds_or_outcome(self):
        target = make_exacta_race(self.prediction_date, winner="1-2")
        poisoned = copy.copy(target)
        poisoned.preview = SimpleNamespace(fields={"wind_speed": -999})
        poisoned.odds = SimpleNamespace(exacta={"6-5": 1e12})
        poisoned.outcome = SimpleNamespace(
            racers={},
            winning_exacta="6-5",
            exacta_payouts={"6-5": 999999},
        )

        baseline = self.model.predict(target)
        mutated = self.model.predict(poisoned)

        self.assertEqual(baseline, mutated)
        feature_text = " ".join(baseline.feature_names).lower()
        for forbidden in FORBIDDEN_PREDICTION_FEATURES:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, feature_text)

    def test_fit_is_order_deterministic_and_fingerprint_covers_program_and_source(self):
        reversed_model = ProgramPlackettLuceModel.fit(
            reversed(self.races),
            prediction_date=self.prediction_date,
            l2=0.1,
        )
        self.assertEqual(self.model.coefficients, reversed_model.coefficients)
        self.assertEqual(
            self.model.training_fingerprint,
            reversed_model.training_fingerprint,
        )
        self.assertEqual(
            self.model.model_fingerprint,
            reversed_model.model_fingerprint,
        )

        changed = list(self.races)
        first = copy.copy(changed[0])
        first.source_sha256 = "different-source"
        changed[0] = first
        changed_model = ProgramPlackettLuceModel.fit(
            changed,
            prediction_date=self.prediction_date,
            l2=0.1,
        )
        self.assertNotEqual(
            self.model.training_fingerprint,
            changed_model.training_fingerprint,
        )

    def test_preprocessing_is_fitted_only_on_training_rows(self):
        self.assertEqual(
            self.model.preprocessor.fitted_racer_rows,
            len(self.races) * 6,
        )
        medians = self.model.preprocessor.numeric_medians
        target = make_exacta_race(self.prediction_date)
        target.program.racers[1]["weight"] = 1e100

        self.model.predict(target)

        self.assertEqual(self.model.preprocessor.numeric_medians, medians)

    def test_chronology_duplicate_venue_and_prediction_boundaries_fail_closed(self):
        with self.assertRaises(ChronologyError):
            ProgramPlackettLuceModel.fit(
                [make_exacta_race(self.prediction_date)],
                prediction_date=self.prediction_date,
            )
        duplicate = make_exacta_race(date(2026, 1, 1))
        with self.assertRaises(DataContractError):
            ProgramPlackettLuceModel.fit(
                [duplicate, duplicate],
                prediction_date=self.prediction_date,
            )
        with self.assertRaises(DataContractError):
            ProgramPlackettLuceModel.fit(
                [
                    make_exacta_race(
                        date(2026, 1, 1), stadium_number=24
                    )
                ],
                prediction_date=self.prediction_date,
            )
        with self.assertRaises(ChronologyError):
            self.model.predict(make_exacta_race(date(2026, 1, 9)))
        with self.assertRaises(DataContractError):
            self.model.predict(
                make_exacta_race(
                    self.prediction_date, stadium_number=24
                )
            )

    def test_only_clean_exacta_cohort_is_used(self):
        clean = make_exacta_race(date(2026, 1, 1), race_number=1)
        no_payout = make_exacta_race(
            date(2026, 1, 1), race_number=2, clean=False
        )
        exception = make_exacta_race(
            date(2026, 1, 1), race_number=3, winner="2-1"
        )
        exception.outcome.racers[6]["place_number_source"] = "F"
        baseline = SmoothedExactaFrequencyModel.fit(
            [clean, no_payout, exception],
            prediction_date=date(2026, 1, 2),
        )
        self.assertEqual(baseline.training_races, 1)
        with self.assertRaises(DataContractError):
            ProgramPlackettLuceModel.fit(
                [no_payout, exception],
                prediction_date=date(2026, 1, 2),
            )

    def test_nonconvergence_never_returns_a_model(self):
        with self.assertRaises(ModelConvergenceError):
            ProgramPlackettLuceModel.fit(
                self.races,
                prediction_date=self.prediction_date,
                l2=0.01,
                maximum_iterations=1,
                gradient_infinity_norm_tolerance=1e-15,
            )

    def test_constructor_rejects_invalid_hyperparameters(self):
        for invalid in (0.0, -1.0, math.inf, math.nan):
            with self.subTest(l2=invalid):
                with self.assertRaises(ValueError):
                    ProgramPlackettLuceModel.fit(
                        self.races,
                        prediction_date=self.prediction_date,
                        l2=invalid,
                    )
        with self.assertRaises(ValueError):
            ProgramPlackettLuceModel.fit(
                self.races,
                prediction_date=self.prediction_date,
                maximum_iterations=0,
            )


if __name__ == "__main__":
    unittest.main()
