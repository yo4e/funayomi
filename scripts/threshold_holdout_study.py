#!/usr/bin/env python3
"""期待値閾値の3分割retrospective pseudo-holdout実験を再現する。"""

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from funayomi.backtest import BacktestResult, run_backtest
from funayomi.cache import LocalCache
from funayomi.repository import RaceRepository


TRAIN_START = date(2026, 1, 1)
TRAIN_END = date(2026, 3, 31)
VALIDATION_START = date(2026, 4, 1)
VALIDATION_END = date(2026, 4, 30)
TEST_START = date(2026, 5, 1)
TEST_END = date(2026, 6, 15)
CANDIDATE_THRESHOLDS = (
    1.00,
    1.25,
    1.50,
    2.00,
    3.00,
    5.00,
    8.00,
    10.00,
    12.00,
    15.00,
    20.00,
)
MIN_VALIDATION_BET_RACES = 20
MIN_VALIDATION_PURCHASES = 200
STAKE_PER_COMBINATION = 100
PRIOR_COUNT_PER_COMBINATION = 1.0


def select_threshold(
    results: Sequence[Tuple[float, BacktestResult]],
) -> Tuple[float, BacktestResult]:
    """事前固定した標本下限と回収率規則で閾値を1つ選ぶ。"""

    eligible = [
        (threshold, result)
        for threshold, result in results
        if result.bet_races >= MIN_VALIDATION_BET_RACES
        and result.purchase_count >= MIN_VALIDATION_PURCHASES
        and result.return_rate is not None
    ]
    if not eligible:
        raise ValueError("標本下限を満たす候補閾値がありません")
    return min(
        eligible,
        key=lambda item: (-float(item[1].return_rate), item[0]),
    )


def run_study(cache_dir: Path, *, offline: bool) -> Dict[str, Any]:
    repository = RaceRepository(LocalCache(cache_dir))
    validation_training = repository.races_between(
        TRAIN_START, TRAIN_END, offline=offline
    )
    validation_races = repository.races_between(
        VALIDATION_START, VALIDATION_END, offline=offline
    )
    validation_results = [
        (
            threshold,
            run_backtest(
                validation_training,
                validation_races,
                train_start=TRAIN_START,
                train_end=TRAIN_END,
                evaluation_start=VALIDATION_START,
                evaluation_end=VALIDATION_END,
                threshold=threshold,
                stake_per_combination=STAKE_PER_COMBINATION,
                prior_count_per_combination=PRIOR_COUNT_PER_COMBINATION,
            ),
        )
        for threshold in CANDIDATE_THRESHOLDS
    ]
    selected_threshold, selected_validation = select_threshold(
        validation_results
    )

    test_training = repository.races_between(
        TRAIN_START, VALIDATION_END, offline=offline
    )
    test_races = repository.races_between(TEST_START, TEST_END, offline=offline)
    selected_test = run_backtest(
        test_training,
        test_races,
        train_start=TRAIN_START,
        train_end=VALIDATION_END,
        evaluation_start=TEST_START,
        evaluation_end=TEST_END,
        threshold=selected_threshold,
        stake_per_combination=STAKE_PER_COMBINATION,
        prior_count_per_combination=PRIOR_COUNT_PER_COMBINATION,
    )
    baseline_test = (
        selected_test
        if selected_threshold == 1.0
        else run_backtest(
            test_training,
            test_races,
            train_start=TRAIN_START,
            train_end=VALIDATION_END,
            evaluation_start=TEST_START,
            evaluation_end=TEST_END,
            threshold=1.0,
            stake_per_combination=STAKE_PER_COMBINATION,
            prior_count_per_combination=PRIOR_COUNT_PER_COMBINATION,
        )
    )

    return {
        "study": "threshold_holdout_v1",
        "periods": {
            "training": {
                "start": TRAIN_START.isoformat(),
                "end": TRAIN_END.isoformat(),
            },
            "validation": {
                "start": VALIDATION_START.isoformat(),
                "end": VALIDATION_END.isoformat(),
            },
            "test": {
                "start": TEST_START.isoformat(),
                "end": TEST_END.isoformat(),
            },
        },
        "configuration": {
            "candidate_thresholds": list(CANDIDATE_THRESHOLDS),
            "minimum_validation_bet_races": MIN_VALIDATION_BET_RACES,
            "minimum_validation_purchases": MIN_VALIDATION_PURCHASES,
            "selection_metric": "maximum_return_rate",
            "tie_break": "lower_threshold",
            "stake_per_combination": STAKE_PER_COMBINATION,
            "prior_count_per_combination": PRIOR_COUNT_PER_COMBINATION,
        },
        "selection": {
            "selected_threshold": selected_threshold,
            "validation": _summary(selected_validation),
            "candidates": [
                {
                    "threshold": threshold,
                    "eligible": (
                        result.bet_races >= MIN_VALIDATION_BET_RACES
                        and result.purchase_count >= MIN_VALIDATION_PURCHASES
                    ),
                    **_summary(result),
                }
                for threshold, result in validation_results
            ],
        },
        "test": {
            "locked_threshold": _summary(selected_test),
            "threshold_1_baseline": _summary(baseline_test),
        },
        "fingerprints": {
            "validation_training": selected_validation.training_fingerprint,
            "validation_evaluation": selected_validation.evaluation_fingerprint,
            "test_training": selected_test.training_fingerprint,
            "test_evaluation": selected_test.evaluation_fingerprint,
        },
    }


def _summary(result: BacktestResult) -> Dict[str, Any]:
    return {
        "threshold": result.threshold,
        "training_races": result.training_races,
        "evaluation_races": result.evaluation_races,
        "excluded_races": result.excluded_races,
        "pass_races": result.pass_races,
        "bet_races": result.bet_races,
        "purchase_count": result.purchase_count,
        "hit_count": result.hit_count,
        "total_stake": result.total_stake,
        "total_payout": result.total_payout,
        "total_refund": result.total_refund,
        "net_profit": result.net_profit,
        "return_rate": result.return_rate,
        "maximum_losing_streak": result.maximum_losing_streak,
        "maximum_drawdown": result.maximum_drawdown,
    }


def format_text(document: Dict[str, Any]) -> str:
    lines = [
        "期待値閾値 3分割 retrospective pseudo-holdout実験",
        (
            "期間: 学習 "
            f"{document['periods']['training']['start']}〜"
            f"{document['periods']['training']['end']} / 検証 "
            f"{document['periods']['validation']['start']}〜"
            f"{document['periods']['validation']['end']} / テスト "
            f"{document['periods']['test']['start']}〜"
            f"{document['periods']['test']['end']}"
        ),
        "",
        "検証期間の候補:",
        "閾値  対象  購入点数  的中  回収率  損益",
    ]
    for candidate in document["selection"]["candidates"]:
        lines.append(
            f"{candidate['threshold']:>5.2f}  "
            f"{'yes' if candidate['eligible'] else ' no':>4}  "
            f"{candidate['purchase_count']:>8}  "
            f"{candidate['hit_count']:>4}  "
            f"{_percent(candidate['return_rate']):>7}  "
            f"{candidate['net_profit']:>+9}円"
        )
    selected = document["selection"]["selected_threshold"]
    locked = document["test"]["locked_threshold"]
    baseline = document["test"]["threshold_1_baseline"]
    lines.extend(
        [
            "",
            f"固定した閾値: {selected:.2f}",
            "",
            "固定テスト:",
            "方式      購入点数  的中  回収率  損益  最大連敗  最大DD",
            (
                f"選択閾値  {locked['purchase_count']:>8}  "
                f"{locked['hit_count']:>4}  "
                f"{_percent(locked['return_rate']):>7}  "
                f"{locked['net_profit']:>+9}円  "
                f"{locked['maximum_losing_streak']:>8}  "
                f"{locked['maximum_drawdown']:>8}円"
            ),
            (
                f"閾値1.00  {baseline['purchase_count']:>8}  "
                f"{baseline['hit_count']:>4}  "
                f"{_percent(baseline['return_rate']):>7}  "
                f"{baseline['net_profit']:>+9}円  "
                f"{baseline['maximum_losing_streak']:>8}  "
                f"{baseline['maximum_drawdown']:>8}円"
            ),
        ]
    )
    return "\n".join(lines)


def _percent(value: Any) -> str:
    return "-" if value is None else f"{float(value) * 100:.1f}%"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Turnmarkキャッシュの場所",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="既存キャッシュだけを使用する",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )
    return parser


def main(arguments: Optional[Iterable[str]] = None) -> int:
    parsed = build_parser().parse_args(arguments)
    document = run_study(parsed.cache_dir, offline=parsed.offline)
    if parsed.format == "json":
        print(
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    else:
        print(format_text(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
