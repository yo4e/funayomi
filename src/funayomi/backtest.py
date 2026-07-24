"""固定期間の時系列バックテスト計算核。"""

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .combinations import parse_combination
from .domain import NormalizedRace
from .errors import ChronologyError, DataContractError
from .model import ProbabilityPrediction, SmoothedTrifectaFrequencyModel
from .ranking import rank_race


@dataclass(frozen=True)
class BacktestRace:
    date: str
    race_number: int
    decision: str
    purchases: int
    hit: bool
    stake: int
    payout: int
    refunds: int
    refund_amount: int
    selected_combinations: Tuple[str, ...]
    winning_combination: Optional[str]
    exclusion_reason: Optional[str]


@dataclass(frozen=True)
class CalibrationBucket:
    lower: float
    upper: float
    sample_count: int
    mean_predicted_probability: float
    observed_frequency: float


@dataclass(frozen=True)
class ProbabilityQuality:
    evaluated_races: int
    model_log_loss: Optional[float]
    uniform_log_loss: Optional[float]
    market_log_loss: Optional[float]
    model_brier_score: Optional[float]
    uniform_brier_score: Optional[float]
    market_brier_score: Optional[float]
    top_choice_hit_rate: Optional[float]
    calibration: Tuple[CalibrationBucket, ...]


@dataclass(frozen=True)
class BacktestResult:
    train_start: str
    train_end: str
    evaluation_start: str
    evaluation_end: str
    threshold: float
    stake_per_combination: int
    prior_count_per_combination: float
    training_fingerprint: str
    evaluation_fingerprint: str
    training_races: int
    evaluation_races: int
    excluded_races: int
    pass_races: int
    bet_races: int
    purchase_count: int
    hit_count: int
    total_stake: int
    total_payout: int
    refund_count: int
    total_refund: int
    net_profit: int
    return_rate: Optional[float]
    maximum_losing_streak: int
    maximum_drawdown: int
    probability_quality: ProbabilityQuality
    races: Tuple[BacktestRace, ...]
    warnings: Tuple[str, ...]


def run_backtest(
    training_races: Iterable[NormalizedRace],
    evaluation_races: Iterable[NormalizedRace],
    *,
    train_start: date,
    train_end: date,
    evaluation_start: date,
    evaluation_end: date,
    threshold: float = 1.0,
    stake_per_combination: int = 100,
    prior_count_per_combination: float = 1.0,
) -> BacktestResult:
    if not (train_start <= train_end < evaluation_start <= evaluation_end):
        raise ChronologyError(
            "期間は train_start <= train_end < evaluation_start <= evaluation_end "
            "である必要があります"
        )
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("期待回収率の閾値は有限の0以上である必要があります")
    if stake_per_combination <= 0 or stake_per_combination % 100 != 0:
        raise ValueError("1点あたりの購入額は100円の正の倍数である必要があります")

    training = sorted(
        (
            race
            for race in training_races
            if train_start <= race.identity.date <= train_end
        ),
        key=lambda race: (race.identity.date, race.identity.race_number),
    )
    evaluation = sorted(
        (
            race
            for race in evaluation_races
            if evaluation_start <= race.identity.date <= evaluation_end
        ),
        key=lambda race: (race.identity.date, race.identity.race_number),
    )
    _ensure_unique_races(evaluation, "評価")
    evaluation_fingerprint = _race_fingerprint(evaluation)
    model = SmoothedTrifectaFrequencyModel.fit(
        training,
        prediction_date=evaluation_start,
        prior_count_per_combination=prior_count_per_combination,
    )

    race_results: List[BacktestRace] = []
    quality_observations: List[Tuple[ProbabilityPrediction, NormalizedRace]] = []
    purchase_count = hit_count = total_stake = total_payout = 0
    refund_count = total_refund = 0
    excluded_races = pass_races = bet_races = 0
    losing_streak = maximum_losing_streak = 0
    equity = peak_equity = maximum_drawdown = 0

    for race in evaluation:
        if not race.has_full_field:
            excluded_races += 1
            race_results.append(
                BacktestRace(
                    date=race.identity.date.isoformat(),
                    race_number=race.identity.race_number,
                    decision="EXCLUDED",
                    purchases=0,
                    hit=False,
                    stake=0,
                    payout=0,
                    refunds=0,
                    refund_amount=0,
                    selected_combinations=(),
                    winning_combination=None,
                    exclusion_reason="incomplete_program_field",
                )
            )
            continue

        prediction = model.predict(race)
        ranking = rank_race(race, prediction, threshold=threshold)
        if ranking.decision == "SKIP_DATA":
            excluded_races += 1
            race_results.append(
                BacktestRace(
                    date=race.identity.date.isoformat(),
                    race_number=race.identity.race_number,
                    decision="EXCLUDED",
                    purchases=0,
                    hit=False,
                    stake=0,
                    payout=0,
                    refunds=0,
                    refund_amount=0,
                    selected_combinations=(),
                    winning_combination=None,
                    exclusion_reason="incomplete_or_invalid_odds",
                )
            )
            continue
        selected = [row for row in ranking.rows if row.qualifies]
        if race.outcome.is_settleable:
            quality_observations.append((prediction, race))
        if not selected:
            pass_races += 1
            race_results.append(
                BacktestRace(
                    date=race.identity.date.isoformat(),
                    race_number=race.identity.race_number,
                    decision="PASS",
                    purchases=0,
                    hit=False,
                    stake=0,
                    payout=0,
                    refunds=0,
                    refund_amount=0,
                    selected_combinations=(),
                    winning_combination=None,
                    exclusion_reason=None,
                )
            )
            continue

        bet_races += 1
        purchases = len(selected)
        race_stake = purchases * stake_per_combination
        winner = race.outcome.winning_trifecta
        hit = winner is not None and any(row.combination == winner for row in selected)
        selected_combinations = tuple(sorted(row.combination for row in selected))
        if race.outcome.status == "trifecta_not_established":
            race_refunds = purchases
        elif race.outcome.is_settleable:
            nonstarters = set(race.outcome.nonstarter_entries)
            race_refunds = sum(
                bool(set(parse_combination(combination)) & nonstarters)
                for combination in selected_combinations
            )
        else:
            raise DataContractError(
                "購入候補確定後の3連単を安全に精算できません: "
                f"{race.identity.date} {race.identity.race_number}R "
                f"status={race.outcome.status}"
            )
        race_refund_amount = race_refunds * stake_per_combination
        winning_payout = (
            race.outcome.trifecta_payouts[winner] * (stake_per_combination // 100)
            if hit and winner is not None
            else 0
        )
        race_payout = winning_payout + race_refund_amount
        purchase_count += purchases
        total_stake += race_stake
        total_payout += race_payout
        refund_count += race_refunds
        total_refund += race_refund_amount
        if hit:
            hit_count += 1
            losing_streak = 0
        elif race_payout < race_stake:
            losing_streak += 1
            maximum_losing_streak = max(maximum_losing_streak, losing_streak)
        else:
            losing_streak = 0

        equity += race_payout - race_stake
        peak_equity = max(peak_equity, equity)
        maximum_drawdown = max(maximum_drawdown, peak_equity - equity)
        race_results.append(
            BacktestRace(
                date=race.identity.date.isoformat(),
                race_number=race.identity.race_number,
                decision="BET",
                purchases=purchases,
                hit=hit,
                stake=race_stake,
                payout=race_payout,
                refunds=race_refunds,
                refund_amount=race_refund_amount,
                selected_combinations=selected_combinations,
                winning_combination=winner,
                exclusion_reason=None,
            )
        )

    return BacktestResult(
        train_start=train_start.isoformat(),
        train_end=train_end.isoformat(),
        evaluation_start=evaluation_start.isoformat(),
        evaluation_end=evaluation_end.isoformat(),
        threshold=threshold,
        stake_per_combination=stake_per_combination,
        prior_count_per_combination=prior_count_per_combination,
        training_fingerprint=model.training_fingerprint,
        evaluation_fingerprint=evaluation_fingerprint,
        training_races=model.training_races,
        evaluation_races=len(evaluation),
        excluded_races=excluded_races,
        pass_races=pass_races,
        bet_races=bet_races,
        purchase_count=purchase_count,
        hit_count=hit_count,
        total_stake=total_stake,
        total_payout=total_payout,
        refund_count=refund_count,
        total_refund=total_refund,
        net_profit=total_payout - total_stake,
        return_rate=(
            total_payout / total_stake if total_stake > 0 else None
        ),
        maximum_losing_streak=maximum_losing_streak,
        maximum_drawdown=maximum_drawdown,
        probability_quality=_compute_probability_quality(quality_observations),
        races=tuple(race_results),
        warnings=(
            "Turnmarkオッズの観測時刻は不明です。この結果は歴史スナップショットによる計算核の検証で、実購入可能性や将来収益を示しません。",
            "閾値は評価結果を見る前に固定し、評価後の調整結果を正式性能として扱わないでください。",
        ),
    )


def backtest_to_dict(result: BacktestResult) -> Dict[str, Any]:
    return {
        "periods": {
            "training": {"start": result.train_start, "end": result.train_end},
            "evaluation": {
                "start": result.evaluation_start,
                "end": result.evaluation_end,
            },
        },
        "strategy": {
            "threshold": result.threshold,
            "comparison": ">=",
            "stake_per_combination": result.stake_per_combination,
            "prior_count_per_combination": result.prior_count_per_combination,
            "selection": "all_qualifying_combinations",
        },
        "fingerprints": {
            "training": result.training_fingerprint,
            "evaluation": result.evaluation_fingerprint,
        },
        "metrics": {
            "training_races": result.training_races,
            "evaluation_races": result.evaluation_races,
            "excluded_races": result.excluded_races,
            "pass_races": result.pass_races,
            "bet_races": result.bet_races,
            "purchase_count": result.purchase_count,
            "hit_count": result.hit_count,
            "total_stake": result.total_stake,
            "total_payout": result.total_payout,
            "refund_count": result.refund_count,
            "total_refund": result.total_refund,
            "net_profit": result.net_profit,
            "return_rate": result.return_rate,
            "maximum_losing_streak": result.maximum_losing_streak,
            "maximum_drawdown": result.maximum_drawdown,
        },
        "probability_quality": {
            "evaluated_races": result.probability_quality.evaluated_races,
            "model": {
                "log_loss": result.probability_quality.model_log_loss,
                "brier_score": result.probability_quality.model_brier_score,
            },
            "uniform": {
                "log_loss": result.probability_quality.uniform_log_loss,
                "brier_score": result.probability_quality.uniform_brier_score,
            },
            "market_implied": {
                "log_loss": result.probability_quality.market_log_loss,
                "brier_score": result.probability_quality.market_brier_score,
            },
            "top_choice_hit_rate": result.probability_quality.top_choice_hit_rate,
            "calibration": [
                {
                    "lower": bucket.lower,
                    "upper": bucket.upper,
                    "sample_count": bucket.sample_count,
                    "mean_predicted_probability": bucket.mean_predicted_probability,
                    "observed_frequency": bucket.observed_frequency,
                }
                for bucket in result.probability_quality.calibration
            ],
        },
        "warnings": list(result.warnings),
        "races": [
            {
                "date": item.date,
                "race_number": item.race_number,
                "decision": item.decision,
                "purchases": item.purchases,
                "hit": item.hit,
                "stake": item.stake,
                "payout": item.payout,
                "refunds": item.refunds,
                "refund_amount": item.refund_amount,
                "selected_combinations": list(item.selected_combinations),
                "winning_combination": item.winning_combination,
                "exclusion_reason": item.exclusion_reason,
            }
            for item in result.races
        ],
    }


def format_backtest_text(result: BacktestResult) -> str:
    return "\n".join(
        [
            "FunaYomi 時系列バックテスト",
            f"学習期間: {result.train_start} 〜 {result.train_end} "
            f"({result.training_races}有効R)",
            f"評価期間: {result.evaluation_start} 〜 {result.evaluation_end} "
            f"({result.evaluation_races}R、除外{result.excluded_races}R)",
            f"固定ルール: 期待回収率 >= {result.threshold:.3f} の全組合せを"
            f"各{result.stake_per_combination}円",
            f"平滑化事前カウントα（1組合せあたり）: "
            f"{result.prior_count_per_combination:g}",
            f"学習fingerprint: {result.training_fingerprint}",
            f"評価fingerprint: {result.evaluation_fingerprint}",
            f"購入レース: {result.bet_races} / PASS: {result.pass_races}",
            f"購入数: {result.purchase_count}",
            f"的中数: {result.hit_count}",
            f"総投資: {result.total_stake}円",
            f"総払戻: {result.total_payout}円",
            f"返還: {result.refund_count}組 / {result.total_refund}円",
            f"損益: {result.net_profit}円",
            "回収率: "
            + (
                f"{result.return_rate:.4f}"
                if result.return_rate is not None
                else "-"
            ),
            f"最大連敗（購入レース単位）: {result.maximum_losing_streak}",
            f"最大ドローダウン: {result.maximum_drawdown}円",
            "確率品質 "
            f"({result.probability_quality.evaluated_races}R): "
            f"log loss={_format_optional(result.probability_quality.model_log_loss)}, "
            f"Brier={_format_optional(result.probability_quality.model_brier_score)}",
            "比較: "
            f"一様log loss={_format_optional(result.probability_quality.uniform_log_loss)}, "
            f"市場log loss={_format_optional(result.probability_quality.market_log_loss)}",
            "",
            "注意:",
            *[f"- {warning}" for warning in result.warnings],
        ]
    )


def _race_fingerprint(races: Iterable[NormalizedRace]) -> str:
    rows = [
        "|".join(
            (
                race.identity.date.isoformat(),
                str(race.identity.stadium_number),
                str(race.identity.race_number),
                race.source_sha256 or "unknown",
            )
        )
        for race in races
    ]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _compute_probability_quality(
    observations: Iterable[Tuple[ProbabilityPrediction, NormalizedRace]],
) -> ProbabilityQuality:
    values = list(observations)
    if not values:
        return ProbabilityQuality(
            evaluated_races=0,
            model_log_loss=None,
            uniform_log_loss=None,
            market_log_loss=None,
            model_brier_score=None,
            uniform_brier_score=None,
            market_brier_score=None,
            top_choice_hit_rate=None,
            calibration=(),
        )

    model_log_loss = uniform_log_loss = market_log_loss = 0.0
    model_brier = uniform_brier = market_brier = 0.0
    top_choice_hits = 0
    bounds = (
        (0.0, 0.005),
        (0.005, 0.01),
        (0.01, 0.02),
        (0.02, 0.05),
        (0.05, 0.1),
        (0.1, 1.000000000001),
    )
    calibration = [[0, 0.0, 0] for _ in bounds]

    for prediction, race in values:
        winner = race.outcome.winning_trifecta
        if winner is None:
            continue
        probabilities = {
            combination: prediction.estimates[combination].probability
            for combination in prediction.estimates
        }
        inverse_odds = {
            combination: 1.0 / odd
            for combination, odd in race.odds.trifecta.items()
            if odd is not None and math.isfinite(odd) and odd > 0
        }
        if len(inverse_odds) != len(probabilities):
            continue
        overround = math.fsum(inverse_odds.values())
        market_probabilities = {
            combination: value / overround
            for combination, value in inverse_odds.items()
        }

        model_log_loss -= math.log(probabilities[winner])
        uniform_log_loss += math.log(len(probabilities))
        market_log_loss -= math.log(market_probabilities[winner])
        model_brier += math.fsum(
            (
                probability - (1.0 if combination == winner else 0.0)
            )
            ** 2
            for combination, probability in probabilities.items()
        )
        uniform_probability = 1.0 / len(probabilities)
        uniform_brier += math.fsum(
            (
                uniform_probability - (1.0 if combination == winner else 0.0)
            )
            ** 2
            for combination in probabilities
        )
        market_brier += math.fsum(
            (
                probability - (1.0 if combination == winner else 0.0)
            )
            ** 2
            for combination, probability in market_probabilities.items()
        )
        top_choice = max(
            probabilities,
            key=lambda combination: probabilities[combination],
        )
        top_choice_hits += int(top_choice == winner)
        for combination, probability in probabilities.items():
            for index, (lower, upper) in enumerate(bounds):
                if lower <= probability < upper:
                    calibration[index][0] += 1
                    calibration[index][1] += probability
                    calibration[index][2] += int(combination == winner)
                    break

    count = len(values)
    buckets = tuple(
        CalibrationBucket(
            lower=lower,
            upper=upper,
            sample_count=int(bucket[0]),
            mean_predicted_probability=bucket[1] / bucket[0],
            observed_frequency=bucket[2] / bucket[0],
        )
        for (lower, upper), bucket in zip(bounds, calibration)
        if bucket[0]
    )
    return ProbabilityQuality(
        evaluated_races=count,
        model_log_loss=model_log_loss / count,
        uniform_log_loss=uniform_log_loss / count,
        market_log_loss=market_log_loss / count,
        model_brier_score=model_brier / count,
        uniform_brier_score=uniform_brier / count,
        market_brier_score=market_brier / count,
        top_choice_hit_rate=top_choice_hits / count,
        calibration=buckets,
    )


def _format_optional(value: Optional[float]) -> str:
    return f"{value:.4f}" if value is not None else "-"


def _ensure_unique_races(races: Iterable[NormalizedRace], label: str) -> None:
    seen = set()
    for race in races:
        key = (
            race.identity.date,
            race.identity.stadium_number,
            race.identity.race_number,
        )
        if key in seen:
            raise DataContractError(
                f"{label}データに同じレースが重複しています: "
                f"{race.identity.date} {race.identity.race_number}R"
            )
        seen.add(key)
