import contextlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from funayomi.backtest import (
    backtest_to_dict,
    format_backtest_text,
    run_backtest,
)
from funayomi.cache import LocalCache
from funayomi.cli import main
from funayomi.errors import ChronologyError, DataContractError
from funayomi.normalize import SCHEMA_VERSION
from funayomi.serialization import (
    normalized_document,
    race_from_dict,
    race_to_dict,
)

from tests.helpers import (
    complete_odds,
    make_race,
    raw_payload,
    raw_race,
)


class SerializationTests(unittest.TestCase):
    def test_race_json_round_trip_preserves_all_separated_snapshots(self):
        original = make_race(
            date(2026, 5, 20),
            race_number=7,
            winner="2-1-3",
            payout=4320,
            odds=complete_odds(22.5, {"2-1-3": 43.2}),
            issues=("audited_fixture",),
            source_sha256="abc123",
        )

        serialized = race_to_dict(original)
        wire_value = json.loads(
            json.dumps(serialized, ensure_ascii=False, sort_keys=True)
        )
        restored = race_from_dict(wire_value)

        self.assertEqual(restored, original)
        self.assertIsNot(restored.program, restored.outcome)
        self.assertEqual(restored.source_sha256, "abc123")

    def test_normalized_document_records_source_hash_and_availability_boundary(self):
        race = make_race(date(2026, 5, 20))
        value = normalized_document(
            [race],
            source_url="https://example.test/20260520.json",
            source_sha256="deadbeef",
            source_fetched_at="2026-05-21T00:00:00+00:00",
        )

        self.assertEqual(value["schema_version"], SCHEMA_VERSION)
        self.assertEqual(value["source"]["provider"], "turnmark")
        self.assertEqual(value["source"]["sha256"], "deadbeef")
        self.assertEqual(value["normalization"]["stadium_number"], 21)
        self.assertEqual(value["normalization"]["prediction_cutoff"], "program")
        self.assertIsNone(value["normalization"]["odds_observed_at"])
        self.assertEqual(len(value["races"]), 1)

    def test_malformed_serialized_race_raises_data_contract_error(self):
        for value in ({}, {"identity": {}}, {"identity": [], "program": {}}):
            with self.subTest(value=value):
                with self.assertRaises(DataContractError):
                    race_from_dict(value)


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.train_start = date(2026, 5, 1)
        self.train_end = date(2026, 5, 5)
        self.eval_start = date(2026, 5, 10)
        self.eval_end = date(2026, 5, 14)

    def _run_mixed_backtest(self):
        training = [
            make_race(date(2026, 5, 2), winner="1-2-3"),
            make_race(
                date(2026, 5, 3),
                winner="6-5-4",
                outcome_status="non_standard",
            ),
            # 明示した学習期間外なのでモデルへ入らない。
            make_race(date(2026, 5, 9), winner="6-5-4"),
        ]
        candidate_odds = complete_odds(1, {"1-2-3": 100})
        evaluations = [
            make_race(
                date(2026, 5, 14),
                race_number=5,
                odds=complete_odds(1, {"1-2-3": None}),
            ),
            make_race(
                date(2026, 5, 13),
                race_number=4,
                odds=candidate_odds,
                entries=(1, 2, 3, 4, 5),
            ),
            make_race(
                date(2026, 5, 12),
                race_number=3,
                odds=complete_odds(1),
            ),
            make_race(
                date(2026, 5, 11),
                race_number=2,
                winner="1-3-2",
                odds=candidate_odds,
                payout=2500,
            ),
            make_race(
                date(2026, 5, 10),
                race_number=1,
                winner="1-2-3",
                odds=candidate_odds,
                payout=2000,
            ),
        ]
        return run_backtest(
            reversed(training),
            evaluations,
            train_start=self.train_start,
            train_end=self.train_end,
            evaluation_start=self.eval_start,
            evaluation_end=self.eval_end,
            threshold=1.5,
            stake_per_combination=100,
        )

    def test_chronological_backtest_counts_bets_hits_payout_pass_and_exclusions(self):
        result = self._run_mixed_backtest()

        self.assertEqual(result.training_races, 1)
        self.assertEqual(result.evaluation_races, 5)
        self.assertEqual(result.excluded_races, 2)
        self.assertEqual(result.pass_races, 1)
        self.assertEqual(result.bet_races, 2)
        self.assertEqual(result.purchase_count, 2)
        self.assertEqual(result.hit_count, 1)
        self.assertEqual(result.total_stake, 200)
        self.assertEqual(result.total_payout, 2000)
        self.assertEqual(result.net_profit, 1800)
        self.assertEqual(result.return_rate, 10.0)
        self.assertEqual(result.maximum_losing_streak, 1)
        self.assertEqual(result.maximum_drawdown, 100)
        self.assertEqual(
            [race.decision for race in result.races],
            ["BET", "BET", "PASS", "EXCLUDED", "EXCLUDED"],
        )
        self.assertEqual(
            [race.date for race in result.races],
            [
                "2026-05-10",
                "2026-05-11",
                "2026-05-12",
                "2026-05-13",
                "2026-05-14",
            ],
        )
        self.assertEqual(result.races[0].purchases, 1)
        self.assertTrue(result.races[0].hit)
        self.assertFalse(result.races[1].hit)
        self.assertEqual(
            result.races[3].decision,
            "EXCLUDED",
        )
        self.assertIsNotNone(result.races[3].exclusion_reason)
        self.assertEqual(
            result.races[4].exclusion_reason,
            "incomplete_or_invalid_odds",
        )

    def test_payout_scales_with_fixed_stake_per_combination(self):
        training = [make_race(date(2026, 5, 2), winner="1-2-3")]
        evaluation = [
            make_race(
                self.eval_start,
                winner="1-2-3",
                payout=1234,
                odds=complete_odds(1, {"1-2-3": 100}),
            )
        ]

        result = run_backtest(
            training,
            evaluation,
            train_start=self.train_start,
            train_end=self.train_end,
            evaluation_start=self.eval_start,
            evaluation_end=self.eval_start,
            threshold=1.5,
            stake_per_combination=200,
        )

        self.assertEqual(result.purchase_count, 1)
        self.assertEqual(result.total_stake, 200)
        self.assertEqual(result.total_payout, 2468)

    def test_accident_with_valid_payout_is_selected_then_settled_with_partial_refund(self):
        training = [make_race(date(2026, 5, 2), winner="1-2-3")]
        selected_odds = complete_odds(
            1,
            {
                "1-2-3": 100,
                "4-5-6": 200,
            },
        )
        racers = {
            entry: dict(value)
            for entry, value in make_race(
                self.eval_start, winner="1-2-3"
            ).outcome.racers.items()
        }
        racers[6]["place_number"] = None
        racers[6]["place_number_source"] = "F"
        accident = make_race(
            self.eval_start,
            winner="1-2-3",
            payout=2000,
            odds=selected_odds,
            outcome_status="exception_settled",
            outcome_racers=racers,
        )

        result = run_backtest(
            training,
            [accident],
            train_start=self.train_start,
            train_end=self.train_end,
            evaluation_start=self.eval_start,
            evaluation_end=self.eval_start,
            threshold=1.5,
            stake_per_combination=100,
        )

        self.assertEqual(result.bet_races, 1)
        self.assertEqual(result.purchase_count, 2)
        self.assertEqual(result.hit_count, 1)
        self.assertEqual(result.total_stake, 200)
        self.assertEqual(result.refund_count, 1)
        self.assertEqual(result.total_refund, 100)
        self.assertEqual(result.total_payout, 2100)
        self.assertEqual(result.net_profit, 1900)
        self.assertEqual(result.races[0].refunds, 1)
        self.assertEqual(result.races[0].refund_amount, 100)

    def test_accident_outcome_does_not_change_pre_outcome_selection(self):
        training = [make_race(date(2026, 5, 2), winner="1-2-3")]
        selected_odds = complete_odds(
            1,
            {
                "1-2-3": 100,
                "4-5-6": 200,
            },
        )
        standard = make_race(
            self.eval_start,
            winner="1-2-3",
            odds=selected_odds,
        )
        accident_racers = {
            entry: dict(value)
            for entry, value in standard.outcome.racers.items()
        }
        accident_racers[6]["place_number"] = None
        accident_racers[6]["place_number_source"] = "L"
        accident = make_race(
            self.eval_start,
            winner="1-2-3",
            odds=selected_odds,
            outcome_status="exception_settled",
            outcome_racers=accident_racers,
        )

        common = {
            "train_start": self.train_start,
            "train_end": self.train_end,
            "evaluation_start": self.eval_start,
            "evaluation_end": self.eval_start,
            "threshold": 1.5,
        }
        standard_result = run_backtest(training, [standard], **common)
        accident_result = run_backtest(training, [accident], **common)

        self.assertEqual(standard_result.bet_races, 1)
        self.assertEqual(accident_result.bet_races, 1)
        self.assertEqual(
            standard_result.purchase_count, accident_result.purchase_count
        )
        self.assertEqual(
            standard_result.total_stake, accident_result.total_stake
        )
        self.assertEqual(
            standard_result.races[0].decision,
            accident_result.races[0].decision,
        )

    def test_trifecta_not_established_refunds_every_selected_combination(self):
        training = [make_race(date(2026, 5, 2), winner="1-2-3")]
        selected_odds = complete_odds(
            1,
            {
                "1-2-3": 100,
                "4-5-6": 200,
            },
        )
        no_contest = make_race(
            self.eval_start,
            odds=selected_odds,
            outcome_status="trifecta_not_established",
            winning_trifectas=(),
            trifecta_payouts={},
        )

        result = run_backtest(
            training,
            [no_contest],
            train_start=self.train_start,
            train_end=self.train_end,
            evaluation_start=self.eval_start,
            evaluation_end=self.eval_start,
            threshold=1.5,
        )

        self.assertEqual(result.purchase_count, 2)
        self.assertEqual(result.total_stake, 200)
        self.assertEqual(result.refund_count, 2)
        self.assertEqual(result.total_refund, 200)
        self.assertEqual(result.total_payout, 200)
        self.assertEqual(result.net_profit, 0)
        self.assertEqual(result.hit_count, 0)
        self.assertEqual(result.maximum_losing_streak, 0)
        self.assertEqual(result.maximum_drawdown, 0)

    def test_selected_race_with_unsettleable_result_fails_closed(self):
        training = [make_race(date(2026, 5, 2), winner="1-2-3")]
        missing_result = make_race(
            self.eval_start,
            odds=complete_odds(1, {"1-2-3": 100}),
            outcome_status="missing",
            winning_trifectas=(),
            trifecta_payouts={},
        )
        inconsistent_with_payout = make_race(
            self.eval_start,
            odds=complete_odds(1, {"1-2-3": 100}),
            outcome_status="inconsistent",
            winner="1-2-3",
            payout=2000,
        )

        for label, race in (
            ("missing", missing_result),
            ("inconsistent_with_payout", inconsistent_with_payout),
        ):
            with self.subTest(label=label):
                with self.assertRaises(DataContractError):
                    run_backtest(
                        training,
                        [race],
                        train_start=self.train_start,
                        train_end=self.train_end,
                        evaluation_start=self.eval_start,
                        evaluation_end=self.eval_start,
                        threshold=1.5,
                    )

    def test_all_pass_has_no_stake_and_undefined_return_rate(self):
        result = run_backtest(
            [],
            [make_race(self.eval_start, odds=complete_odds(1))],
            train_start=self.train_start,
            train_end=self.train_end,
            evaluation_start=self.eval_start,
            evaluation_end=self.eval_start,
            threshold=999,
        )

        self.assertEqual(result.pass_races, 1)
        self.assertEqual(result.purchase_count, 0)
        self.assertEqual(result.total_stake, 0)
        self.assertEqual(result.total_payout, 0)
        self.assertIsNone(result.return_rate)
        self.assertEqual(result.maximum_losing_streak, 0)
        self.assertEqual(result.maximum_drawdown, 0)

    def test_invalid_period_boundaries_are_rejected(self):
        invalid_periods = (
            (
                date(2026, 5, 2),
                date(2026, 5, 1),
                date(2026, 5, 3),
                date(2026, 5, 4),
            ),
            (
                date(2026, 5, 1),
                date(2026, 5, 3),
                date(2026, 5, 3),
                date(2026, 5, 4),
            ),
            (
                date(2026, 5, 1),
                date(2026, 5, 2),
                date(2026, 5, 4),
                date(2026, 5, 3),
            ),
        )
        for periods in invalid_periods:
            with self.subTest(periods=periods):
                with self.assertRaises(ChronologyError):
                    run_backtest(
                        [],
                        [],
                        train_start=periods[0],
                        train_end=periods[1],
                        evaluation_start=periods[2],
                        evaluation_end=periods[3],
                    )

    def test_non_positive_or_non_hundred_yen_stake_is_rejected(self):
        for invalid_stake in (0, -100, 50, 150):
            with self.subTest(invalid_stake=invalid_stake):
                with self.assertRaises(ValueError):
                    run_backtest(
                        [],
                        [],
                        train_start=self.train_start,
                        train_end=self.train_end,
                        evaluation_start=self.eval_start,
                        evaluation_end=self.eval_end,
                        stake_per_combination=invalid_stake,
                    )

    def test_invalid_threshold_is_rejected_even_with_no_evaluation_races(self):
        for invalid_threshold in (-0.01, float("nan"), float("inf")):
            with self.subTest(invalid_threshold=invalid_threshold):
                with self.assertRaises(ValueError):
                    run_backtest(
                        [],
                        [],
                        train_start=self.train_start,
                        train_end=self.train_end,
                        evaluation_start=self.eval_start,
                        evaluation_end=self.eval_end,
                        threshold=invalid_threshold,
                    )

    def test_duplicate_evaluation_race_identity_is_rejected(self):
        race = make_race(self.eval_start)

        with self.assertRaises(DataContractError):
            run_backtest(
                [],
                [race, race],
                train_start=self.train_start,
                train_end=self.train_end,
                evaluation_start=self.eval_start,
                evaluation_end=self.eval_end,
            )

    def test_machine_readable_backtest_is_deterministic_and_auditable(self):
        first = backtest_to_dict(self._run_mixed_backtest())
        second = backtest_to_dict(self._run_mixed_backtest())

        self.assertEqual(first, second)
        self.assertIs(first["actionable"], False)
        self.assertEqual(first["strategy_status"], "historical_research_only")
        self.assertEqual(first["refund_probability_mode"], "not_modeled")
        self.assertEqual(first["strategy"]["comparison"], ">=")
        self.assertEqual(first["strategy"]["stake_per_combination"], 100)
        self.assertEqual(
            first["strategy"]["selection"], "all_qualifying_combinations"
        )
        self.assertEqual(first["metrics"]["purchase_count"], 2)
        self.assertTrue(first["warnings"])
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
        )

    def test_backtest_text_is_explicitly_historical_and_non_actionable(self):
        value = format_backtest_text(self._run_mixed_backtest())

        self.assertEqual(value.splitlines()[0], "FunaYomi 時系列バックテスト")
        self.assertEqual(value.splitlines()[1][:5], "利用制限:")
        self.assertIn("実購入判断には使用できません", value)
        self.assertIn("返還確率をモデル化していません", value)

    def test_probability_quality_includes_uniform_market_and_calibration(self):
        result = run_backtest(
            [make_race(date(2026, 5, 2), winner="1-2-3")],
            [make_race(self.eval_start, winner="1-2-3")],
            train_start=self.train_start,
            train_end=self.train_end,
            evaluation_start=self.eval_start,
            evaluation_end=self.eval_start,
            threshold=999,
        )
        quality = result.probability_quality

        self.assertEqual(quality.evaluated_races, 1)
        self.assertIsNotNone(quality.model_log_loss)
        self.assertIsNotNone(quality.uniform_log_loss)
        self.assertIsNotNone(quality.market_log_loss)
        self.assertIsNotNone(quality.model_brier_score)
        self.assertIsNotNone(quality.uniform_brier_score)
        self.assertIsNotNone(quality.market_brier_score)
        self.assertEqual(
            sum(bucket.sample_count for bucket in quality.calibration),
            120,
        )
        document = backtest_to_dict(result)
        self.assertEqual(document["probability_quality"]["evaluated_races"], 1)
        self.assertTrue(document["probability_quality"]["calibration"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache_dir = Path(self.temporary.name)
        self.day = date(2026, 5, 21)
        self._seed_day(self.day, [raw_race(self.day)])

    def _seed_day(self, day, races):
        payload = json.dumps(
            raw_payload(day, races), ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        LocalCache(self.cache_dir).write_raw(
            day,
            payload,
            {
                "provider": "turnmark",
                "source_url": f"https://example.test/{day:%Y%m%d}.json",
                "fetched_at": "2026-06-01T00:00:00+00:00",
            },
        )

    def _run_cli(self, arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            return_code = main(arguments)
        return return_code, stdout.getvalue(), stderr.getvalue()

    def test_rank_json_is_deterministic_and_offline_never_uses_network(self):
        arguments = [
            "rank",
            "--cache-dir",
            str(self.cache_dir),
            "--offline",
            "--date",
            self.day.isoformat(),
            "--race",
            "1",
            "--train-start",
            self.day.isoformat(),
            "--threshold",
            "999",
            "--format",
            "json",
        ]
        with patch(
            "funayomi.turnmark.urlopen",
            side_effect=AssertionError("network must not be used"),
        ) as urlopen:
            first = self._run_cli(arguments)
            second = self._run_cli(arguments)

        self.assertEqual(first, second)
        self.assertEqual(first[0], 0)
        self.assertEqual(first[2], "")
        value = json.loads(first[1])
        self.assertIs(value["actionable"], False)
        self.assertEqual(value["strategy_status"], "historical_research_only")
        self.assertEqual(value["refund_probability_mode"], "not_modeled")
        self.assertEqual(value["decision"], "PASS")
        self.assertEqual(len(value["rankings"]), 120)
        urlopen.assert_not_called()

    def test_rank_has_human_readable_text_output(self):
        return_code, stdout, stderr = self._run_cli(
            [
                "rank",
                "--cache-dir",
                str(self.cache_dir),
                "--offline",
                "--date",
                self.day.isoformat(),
                "--race",
                "1",
                "--train-start",
                self.day.isoformat(),
                "--format",
                "text",
            ]
        )

        self.assertEqual(return_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn(f"日付: {self.day.isoformat()}", stdout)
        self.assertIn("場: 芦屋 (21) / 1R", stdout)
        self.assertIn("順位", stdout)
        self.assertIn("期待回収率", stdout)
        self.assertIn("実購入判断には使用できません", stdout)

    def test_offline_missing_day_returns_domain_error_without_network(self):
        missing = date(2026, 5, 22)
        with patch(
            "funayomi.turnmark.urlopen",
            side_effect=AssertionError("network must not be used"),
        ) as urlopen:
            return_code, stdout, stderr = self._run_cli(
                [
                    "rank",
                    "--cache-dir",
                    str(self.cache_dir),
                    "--offline",
                    "--date",
                    missing.isoformat(),
                    "--race",
                    "1",
                    "--train-start",
                    missing.isoformat(),
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(return_code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("原本キャッシュがありません", stderr)
        urlopen.assert_not_called()

    def test_backtest_json_runs_entirely_from_seeded_cache(self):
        evaluation_day = date(2026, 5, 22)
        self._seed_day(
            evaluation_day,
            [
                raw_race(
                    evaluation_day,
                    odds=complete_odds(1, {"1-2-3": 100}),
                    winner="1-2-3",
                    payout=2000,
                )
            ],
        )
        with patch(
            "funayomi.turnmark.urlopen",
            side_effect=AssertionError("network must not be used"),
        ) as urlopen:
            return_code, stdout, stderr = self._run_cli(
                [
                    "backtest",
                    "--cache-dir",
                    str(self.cache_dir),
                    "--offline",
                    "--train-start",
                    self.day.isoformat(),
                    "--train-end",
                    self.day.isoformat(),
                    "--eval-start",
                    evaluation_day.isoformat(),
                    "--eval-end",
                    evaluation_day.isoformat(),
                    "--threshold",
                    "1.5",
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(return_code, 0)
        self.assertEqual(stderr, "")
        value = json.loads(stdout)
        self.assertIs(value["actionable"], False)
        self.assertEqual(value["strategy_status"], "historical_research_only")
        self.assertEqual(value["refund_probability_mode"], "not_modeled")
        self.assertEqual(value["metrics"]["training_races"], 1)
        self.assertEqual(value["metrics"]["evaluation_races"], 1)
        self.assertEqual(value["metrics"]["purchase_count"], 1)
        self.assertEqual(value["metrics"]["hit_count"], 1)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
