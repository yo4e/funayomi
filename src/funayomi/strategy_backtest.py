"""Turnmark限定2連単strategy sandboxの固定予算portfolio評価。

予測確率と歴史オッズだけでportfolioを先に固定し、その後に結果を開いて
精算する。Turnmarkオッズの観測時点は不明なので、出力は常に
retrospective / non-actionableである。
"""

import math
import random
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .combinations import EXACTA_COMBINATIONS, parse_exacta_combination
from .domain import NormalizedRace
from .errors import DataContractError
from .portfolio import (
    PortfolioPlan,
    select_equal_payout_prefix,
    single_point_plan,
)
from .safety import (
    ACTIONABLE,
    REFUND_PROBABILITY_MODE,
    STRATEGY_STATUS,
)


STRATEGY_NAMES: Tuple[str, ...] = (
    "program_single",
    "blend_single",
    "program_dutch",
    "blend_dutch",
)


@dataclass(frozen=True)
class StrategyRaceInput:
    race: NormalizedRace
    fold_id: str
    meeting_id: str
    program_probabilities: Mapping[str, float]
    blend_probabilities: Mapping[str, float]


@dataclass(frozen=True)
class StakeRecord:
    combination: str
    stake_yen: int
    odds: float


@dataclass(frozen=True)
class PortfolioRaceRecord:
    strategy: str
    fold_id: str
    meeting_id: str
    date: str
    race_number: int
    decision: str
    selections: Tuple[StakeRecord, ...]
    coverage: float
    market_cost: float
    predicted_return: Optional[float]
    allocation_predicted_return: Optional[float]
    winning_combination: Optional[str]
    hit: bool
    stake_yen: int
    payout_yen: int
    refund_count: int
    refund_yen: int
    net_profit_yen: int
    exclusion_reason: Optional[str]


@dataclass(frozen=True)
class PeriodMetrics:
    key: str
    races: int
    bet_races: int
    hit_races: int
    tickets: int
    stake_yen: int
    payout_yen: int
    net_profit_yen: int
    return_rate: Optional[float]


@dataclass(frozen=True)
class BootstrapInterval:
    resamples: int
    seed: int
    return_rate_lower: Optional[float]
    return_rate_upper: Optional[float]
    maximum_drawdown_lower_yen: Optional[float]
    maximum_drawdown_upper_yen: Optional[float]


@dataclass(frozen=True)
class PortfolioStrategyResult:
    strategy: str
    evaluated_races: int
    skipped_races: int
    pass_races: int
    bet_races: int
    tickets: int
    hit_races: int
    total_stake_yen: int
    total_payout_yen: int
    total_refund_yen: int
    net_profit_yen: int
    return_rate: Optional[float]
    maximum_losing_streak: int
    maximum_drawdown_yen: int
    worst_meeting_profit_yen: Optional[int]
    largest_payout_yen: int
    largest_payout_share: Optional[float]
    return_without_largest_payout: Optional[float]
    monthly: Tuple[PeriodMetrics, ...]
    meetings: Tuple[PeriodMetrics, ...]
    bootstrap: BootstrapInterval
    races: Tuple[PortfolioRaceRecord, ...]


def run_portfolio_backtest(
    observations: Iterable[StrategyRaceInput],
    *,
    race_budget_yen: int = 1000,
    wager_unit_yen: int = 100,
    minimum_predicted_return: float = 1.10,
    maximum_market_cost: float = 0.50,
    bootstrap_resamples: int = 20_000,
    bootstrap_seed: int = 20_260_727,
) -> Mapping[str, PortfolioStrategyResult]:
    """同じrace budgetで4方式を評価する。

    market不完全レースは結果を開く前に全方式で ``SKIP_DATA`` とする。
    portfolio候補も結果参照前に4方式すべて固定し、その後で精算する。
    """

    _validate_configuration(
        race_budget_yen=race_budget_yen,
        wager_unit_yen=wager_unit_yen,
        minimum_predicted_return=minimum_predicted_return,
        maximum_market_cost=maximum_market_cost,
        bootstrap_resamples=bootstrap_resamples,
    )
    ordered = sorted(
        observations,
        key=lambda item: (
            item.race.identity.date,
            item.race.identity.race_number,
        ),
    )
    _ensure_unique_inputs(ordered)
    records: Dict[str, List[PortfolioRaceRecord]] = {
        strategy: [] for strategy in STRATEGY_NAMES
    }

    for observation in ordered:
        race = observation.race
        if not race.exacta_evaluation_eligible:
            for strategy in STRATEGY_NAMES:
                records[strategy].append(
                    _excluded_record(
                        observation,
                        strategy=strategy,
                        reason="incomplete_program_field",
                    )
                )
            continue
        odds = _complete_exacta_odds(race)
        if odds is None:
            for strategy in STRATEGY_NAMES:
                records[strategy].append(
                    _excluded_record(
                        observation,
                        strategy=strategy,
                        reason="incomplete_or_invalid_exacta_odds",
                    )
                )
            continue

        # このblockではprogram確率とoddsだけを読む。outcomeは読まない。
        plans = {
            "program_single": single_point_plan(
                observation.program_probabilities,
                odds,
                stake_yen=race_budget_yen,
                threshold=minimum_predicted_return,
            ),
            "blend_single": single_point_plan(
                observation.blend_probabilities,
                odds,
                stake_yen=race_budget_yen,
                threshold=minimum_predicted_return,
            ),
            "program_dutch": select_equal_payout_prefix(
                observation.program_probabilities,
                odds,
                budget_yen=race_budget_yen,
                unit_yen=wager_unit_yen,
                threshold=minimum_predicted_return,
                max_market_cost=maximum_market_cost,
            ),
            "blend_dutch": select_equal_payout_prefix(
                observation.blend_probabilities,
                odds,
                budget_yen=race_budget_yen,
                unit_yen=wager_unit_yen,
                threshold=minimum_predicted_return,
                max_market_cost=maximum_market_cost,
            ),
        }
        for strategy in STRATEGY_NAMES:
            records[strategy].append(
                _settle_plan(
                    observation,
                    strategy=strategy,
                    plan=plans[strategy],
                )
            )

    # 同じseedと同じ開催節順を4方式へ渡すことで、各bootstrap反復が
    # 同一のmeeting block resampleを共有する。
    return {
        strategy: _summarize_strategy(
            strategy,
            tuple(records[strategy]),
            bootstrap_resamples=bootstrap_resamples,
            bootstrap_seed=bootstrap_seed,
        )
        for strategy in STRATEGY_NAMES
    }


def portfolio_results_to_dict(
    results: Mapping[str, PortfolioStrategyResult],
) -> Dict[str, Any]:
    if tuple(results) != STRATEGY_NAMES:
        raise DataContractError("portfolio結果は固定4方式の順で必要です")
    return {
        "actionable": ACTIONABLE,
        "strategy_status": STRATEGY_STATUS,
        "research_class": "retrospective_hypothesis_generation_sandbox",
        "refund_probability_mode": REFUND_PROBABILITY_MODE,
        "strategies": {
            strategy: _strategy_to_dict(results[strategy])
            for strategy in STRATEGY_NAMES
        },
        "warnings": [
            "Turnmarkのprogram snapshotと2連単oddsは観測時点を確認できません。",
            "この結果はretrospectiveな仮説生成だけに使い、実購入可能性、"
            "確認的性能、将来収益を示しません。",
            "返還確率はモデル化せず、portfolio固定後に観測結果から実現返還だけを精算します。",
        ],
    }


def _settle_plan(
    observation: StrategyRaceInput,
    *,
    strategy: str,
    plan: PortfolioPlan,
) -> PortfolioRaceRecord:
    race = observation.race
    if plan.decision == "PASS":
        return PortfolioRaceRecord(
            strategy=strategy,
            fold_id=observation.fold_id,
            meeting_id=observation.meeting_id,
            date=race.identity.date.isoformat(),
            race_number=race.identity.race_number,
            decision="PASS",
            selections=(),
            coverage=plan.coverage,
            market_cost=plan.market_cost,
            predicted_return=plan.predicted_return,
            allocation_predicted_return=plan.allocation_predicted_return,
            winning_combination=None,
            hit=False,
            stake_yen=0,
            payout_yen=0,
            refund_count=0,
            refund_yen=0,
            net_profit_yen=0,
            exclusion_reason=None,
        )

    selections = tuple(
        StakeRecord(
            combination=item.combination,
            stake_yen=item.stake_yen,
            odds=item.odds,
        )
        for item in plan.allocations
    )
    if not selections:
        raise DataContractError("購入判定のportfolioに買い目がありません")
    total_stake = sum(item.stake_yen for item in selections)
    if total_stake != plan.cost_yen:
        raise DataContractError("portfolio planと買い目stake合計が一致しません")

    outcome = race.outcome
    if outcome.is_exacta_settleable:
        winner = outcome.winning_exacta
        nonstarters = set(outcome.nonstarter_entries)
        refunded = tuple(
            item
            for item in selections
            if set(parse_exacta_combination(item.combination)) & nonstarters
        )
        refund_count = len(refunded)
        refund_yen = sum(item.stake_yen for item in refunded)
        winning_selection = next(
            (
                item
                for item in selections
                if item.combination == winner
            ),
            None,
        )
        hit = winning_selection is not None
        winning_payout = (
            outcome.exacta_payouts[winner]
            * (winning_selection.stake_yen // 100)
            if winner is not None and winning_selection is not None
            else 0
        )
    else:
        raise DataContractError(
            "portfolio固定後の2連単を安全に精算できません: "
            f"{race.identity.date} {race.identity.race_number}R "
            f"status={outcome.exacta_status}"
        )
    payout = winning_payout + refund_yen
    return PortfolioRaceRecord(
        strategy=strategy,
        fold_id=observation.fold_id,
        meeting_id=observation.meeting_id,
        date=race.identity.date.isoformat(),
        race_number=race.identity.race_number,
        decision="BET",
        selections=selections,
        coverage=plan.coverage,
        market_cost=plan.market_cost,
        predicted_return=plan.predicted_return,
        allocation_predicted_return=plan.allocation_predicted_return,
        winning_combination=winner,
        hit=hit,
        stake_yen=total_stake,
        payout_yen=payout,
        refund_count=refund_count,
        refund_yen=refund_yen,
        net_profit_yen=payout - total_stake,
        exclusion_reason=None,
    )


def _excluded_record(
    observation: StrategyRaceInput,
    *,
    strategy: str,
    reason: str,
) -> PortfolioRaceRecord:
    race = observation.race
    return PortfolioRaceRecord(
        strategy=strategy,
        fold_id=observation.fold_id,
        meeting_id=observation.meeting_id,
        date=race.identity.date.isoformat(),
        race_number=race.identity.race_number,
        decision="SKIP_DATA",
        selections=(),
        coverage=0.0,
        market_cost=0.0,
        predicted_return=None,
        allocation_predicted_return=None,
        winning_combination=None,
        hit=False,
        stake_yen=0,
        payout_yen=0,
        refund_count=0,
        refund_yen=0,
        net_profit_yen=0,
        exclusion_reason=reason,
    )


def _summarize_strategy(
    strategy: str,
    records: Tuple[PortfolioRaceRecord, ...],
    *,
    bootstrap_resamples: int,
    bootstrap_seed: int,
) -> PortfolioStrategyResult:
    bet_records = tuple(item for item in records if item.decision == "BET")
    total_stake = sum(item.stake_yen for item in bet_records)
    total_payout = sum(item.payout_yen for item in bet_records)
    payouts = [item.payout_yen for item in bet_records]
    largest_payout = max(payouts, default=0)
    monthly = _group_metrics(records, key_name="month")
    meetings = _group_metrics(records, key_name="meeting")
    meeting_profits = [item.net_profit_yen for item in meetings]
    return PortfolioStrategyResult(
        strategy=strategy,
        evaluated_races=len(records),
        skipped_races=sum(item.decision == "SKIP_DATA" for item in records),
        pass_races=sum(item.decision == "PASS" for item in records),
        bet_races=len(bet_records),
        tickets=sum(len(item.selections) for item in bet_records),
        hit_races=sum(item.hit for item in bet_records),
        total_stake_yen=total_stake,
        total_payout_yen=total_payout,
        total_refund_yen=sum(item.refund_yen for item in bet_records),
        net_profit_yen=total_payout - total_stake,
        return_rate=total_payout / total_stake if total_stake else None,
        maximum_losing_streak=_maximum_losing_streak(bet_records),
        maximum_drawdown_yen=_maximum_drawdown(
            tuple(item.net_profit_yen for item in bet_records)
        ),
        worst_meeting_profit_yen=(
            min(meeting_profits) if meeting_profits else None
        ),
        largest_payout_yen=largest_payout,
        largest_payout_share=(
            largest_payout / total_payout if total_payout else None
        ),
        return_without_largest_payout=(
            (total_payout - largest_payout) / total_stake
            if total_stake
            else None
        ),
        monthly=monthly,
        meetings=meetings,
        bootstrap=_meeting_block_bootstrap(
            records,
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        ),
        races=records,
    )


def _group_metrics(
    records: Sequence[PortfolioRaceRecord],
    *,
    key_name: str,
) -> Tuple[PeriodMetrics, ...]:
    grouped: Dict[str, List[PortfolioRaceRecord]] = {}
    for item in records:
        key = item.date[:7] if key_name == "month" else item.meeting_id
        grouped.setdefault(key, []).append(item)
    results = []
    for key in sorted(grouped):
        values = grouped[key]
        bets = [item for item in values if item.decision == "BET"]
        stake = sum(item.stake_yen for item in bets)
        payout = sum(item.payout_yen for item in bets)
        results.append(
            PeriodMetrics(
                key=key,
                races=len(values),
                bet_races=len(bets),
                hit_races=sum(item.hit for item in bets),
                tickets=sum(len(item.selections) for item in bets),
                stake_yen=stake,
                payout_yen=payout,
                net_profit_yen=payout - stake,
                return_rate=payout / stake if stake else None,
            )
        )
    return tuple(results)


def _meeting_block_bootstrap(
    records: Sequence[PortfolioRaceRecord],
    *,
    resamples: int,
    seed: int,
) -> BootstrapInterval:
    if resamples == 0:
        return BootstrapInterval(
            resamples=0,
            seed=seed,
            return_rate_lower=None,
            return_rate_upper=None,
            maximum_drawdown_lower_yen=None,
            maximum_drawdown_upper_yen=None,
        )
    blocks: Dict[str, List[PortfolioRaceRecord]] = {}
    for item in records:
        blocks.setdefault(item.meeting_id, []).append(item)
    ordered_blocks = [
        tuple(blocks[key])
        for key in sorted(blocks)
    ]
    if not ordered_blocks:
        return BootstrapInterval(
            resamples=resamples,
            seed=seed,
            return_rate_lower=None,
            return_rate_upper=None,
            maximum_drawdown_lower_yen=None,
            maximum_drawdown_upper_yen=None,
        )
    generator = random.Random(seed)
    return_rates = []
    drawdowns = []
    for _ in range(resamples):
        stake = payout = 0
        net_sequence: List[int] = []
        for _block_index in range(len(ordered_blocks)):
            block = ordered_blocks[generator.randrange(len(ordered_blocks))]
            for item in block:
                if item.decision != "BET":
                    continue
                stake += item.stake_yen
                payout += item.payout_yen
                net_sequence.append(item.net_profit_yen)
        if stake:
            return_rates.append(payout / stake)
            drawdowns.append(float(_maximum_drawdown(tuple(net_sequence))))
    if not return_rates:
        return BootstrapInterval(
            resamples=resamples,
            seed=seed,
            return_rate_lower=None,
            return_rate_upper=None,
            maximum_drawdown_lower_yen=None,
            maximum_drawdown_upper_yen=None,
        )
    return BootstrapInterval(
        resamples=resamples,
        seed=seed,
        return_rate_lower=_percentile(return_rates, 0.025),
        return_rate_upper=_percentile(return_rates, 0.975),
        maximum_drawdown_lower_yen=_percentile(drawdowns, 0.025),
        maximum_drawdown_upper_yen=_percentile(drawdowns, 0.975),
    )


def _maximum_losing_streak(
    records: Sequence[PortfolioRaceRecord],
) -> int:
    current = maximum = 0
    for item in records:
        if not item.hit and item.payout_yen < item.stake_yen:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _maximum_drawdown(net_sequence: Sequence[int]) -> int:
    equity = peak = maximum = 0
    for net in net_sequence:
        equity += net
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("percentileには値が必要です")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(
        ordered[lower] * (1.0 - fraction)
        + ordered[upper] * fraction
    )


def _complete_exacta_odds(
    race: NormalizedRace,
) -> Optional[Mapping[str, float]]:
    if tuple(race.odds.exacta) != EXACTA_COMBINATIONS:
        return None
    values: Dict[str, float] = {}
    for combination in EXACTA_COMBINATIONS:
        value = race.odds.exacta.get(combination)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
        ):
            return None
        values[combination] = float(value)
    return values


def _ensure_unique_inputs(observations: Sequence[StrategyRaceInput]) -> None:
    seen = set()
    for item in observations:
        race = item.race
        key = (
            race.identity.date,
            race.identity.stadium_number,
            race.identity.race_number,
        )
        if key in seen:
            raise DataContractError(
                "同じ評価レースが重複しています: "
                f"{race.identity.date} {race.identity.race_number}R"
            )
        seen.add(key)


def _validate_configuration(
    *,
    race_budget_yen: int,
    wager_unit_yen: int,
    minimum_predicted_return: float,
    maximum_market_cost: float,
    bootstrap_resamples: int,
) -> None:
    if (
        wager_unit_yen <= 0
        or race_budget_yen <= 0
        or race_budget_yen % wager_unit_yen != 0
        or wager_unit_yen % 100 != 0
    ):
        raise ValueError("予算と購入単位は100円の正の倍数で整合する必要があります")
    if (
        not math.isfinite(minimum_predicted_return)
        or minimum_predicted_return < 0.0
    ):
        raise ValueError("予測回収率閾値は有限の0以上である必要があります")
    if (
        not math.isfinite(maximum_market_cost)
        or maximum_market_cost <= 0.0
    ):
        raise ValueError("最大market costは有限の正数である必要があります")
    if bootstrap_resamples < 0:
        raise ValueError("bootstrap回数は0以上である必要があります")


def _strategy_to_dict(result: PortfolioStrategyResult) -> Dict[str, Any]:
    return {
        "metrics": {
            "evaluated_races": result.evaluated_races,
            "skipped_races": result.skipped_races,
            "pass_races": result.pass_races,
            "bet_races": result.bet_races,
            "tickets": result.tickets,
            "hit_races": result.hit_races,
            "total_stake_yen": result.total_stake_yen,
            "total_payout_yen": result.total_payout_yen,
            "total_refund_yen": result.total_refund_yen,
            "net_profit_yen": result.net_profit_yen,
            "return_rate": result.return_rate,
            "maximum_losing_streak": result.maximum_losing_streak,
            "maximum_drawdown_yen": result.maximum_drawdown_yen,
            "worst_meeting_profit_yen": result.worst_meeting_profit_yen,
            "largest_payout_yen": result.largest_payout_yen,
            "largest_payout_share": result.largest_payout_share,
            "return_without_largest_payout": (
                result.return_without_largest_payout
            ),
        },
        "bootstrap": {
            "resamples": result.bootstrap.resamples,
            "seed": result.bootstrap.seed,
            "return_rate_95_interval": [
                result.bootstrap.return_rate_lower,
                result.bootstrap.return_rate_upper,
            ],
            "maximum_drawdown_yen_95_interval": [
                result.bootstrap.maximum_drawdown_lower_yen,
                result.bootstrap.maximum_drawdown_upper_yen,
            ],
        },
        "monthly": [_period_to_dict(item) for item in result.monthly],
        "meetings": [_period_to_dict(item) for item in result.meetings],
        "races": [
            {
                "fold_id": item.fold_id,
                "meeting_id": item.meeting_id,
                "date": item.date,
                "race_number": item.race_number,
                "decision": item.decision,
                "selections": [
                    {
                        "combination": selection.combination,
                        "stake_yen": selection.stake_yen,
                        "odds": selection.odds,
                    }
                    for selection in item.selections
                ],
                "coverage": item.coverage,
                "market_cost": item.market_cost,
                "predicted_return": item.predicted_return,
                "allocation_predicted_return": (
                    item.allocation_predicted_return
                ),
                "winning_combination": item.winning_combination,
                "hit": item.hit,
                "stake_yen": item.stake_yen,
                "payout_yen": item.payout_yen,
                "refund_count": item.refund_count,
                "refund_yen": item.refund_yen,
                "net_profit_yen": item.net_profit_yen,
                "exclusion_reason": item.exclusion_reason,
            }
            for item in result.races
        ],
    }


def _period_to_dict(item: PeriodMetrics) -> Dict[str, Any]:
    return {
        "key": item.key,
        "races": item.races,
        "bet_races": item.bet_races,
        "hit_races": item.hit_races,
        "tickets": item.tickets,
        "stake_yen": item.stake_yen,
        "payout_yen": item.payout_yen,
        "net_profit_yen": item.net_profit_yen,
        "return_rate": item.return_rate,
    }
