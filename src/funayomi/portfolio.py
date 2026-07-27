"""2連単の確率と時点不明の歴史オッズを使う研究用portfolio計算。

このmoduleは購入推奨を作らない。入力は2連単30通りが完全である場合だけ
受け入れ、確率・価格の欠損や非有限値ではfail-closedする。

決定論を保つため、value densityが同じときはcanonicalな組合せ順、
lambdaのvalidation scoreが同じときは小さいlambdaを優先する。
"""

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .combinations import EXACTA_COMBINATIONS
from .errors import DataContractError


_COMBINATION_ORDER = {
    combination: index
    for index, combination in enumerate(EXACTA_COMBINATIONS)
}

DEFAULT_RACE_BUDGET_YEN = 1_000
DEFAULT_STAKE_UNIT_YEN = 100
DEFAULT_MIN_PREDICTED_RETURN = 1.10
DEFAULT_MAX_MARKET_COST = 0.50
PROBABILITY_TOLERANCE = 1e-12
SCORE_TIE_TOLERANCE = 1e-12


@dataclass(frozen=True)
class ValidationRace:
    """lambda選択に使う1レース分のvalidation入力。"""

    model_probabilities: Mapping[str, float]
    odds: Mapping[str, float]
    winning_combination: str


@dataclass(frozen=True)
class LambdaScore:
    blend_weight: float
    mean_log_loss: float


@dataclass(frozen=True)
class LambdaValidationResult:
    selected_lambda: float
    scores: Tuple[LambdaScore, ...]
    validation_races: int


@dataclass(frozen=True)
class CoverageCostPoint:
    """value-density順prefixのcoverage-cost frontier上の一点。

    ``cost`` は、prefix内のどの組合せが的中してもgross payoutを1に
    揃えるための理論stake ``sum(1 / odds)``。したがって理論上の
    予測回収率は ``coverage / cost`` になる。
    """

    prefix_size: int
    added_combination: str
    combinations: Tuple[str, ...]
    coverage: float
    cost: float
    predicted_return: float
    added_value_density: float


@dataclass(frozen=True)
class StakeAllocation:
    combination: str
    probability: float
    odds: float
    units: int
    stake_yen: int
    gross_payout_if_win_yen: float
    predicted_payout_yen: float


@dataclass(frozen=True)
class PortfolioPlan:
    """単点または1レース固定予算portfolioの研究上の評価結果。"""

    strategy: str
    decision: str
    threshold: float
    coverage: float
    cost_yen: int
    predicted_payout_yen: float
    predicted_return: Optional[float]
    allocation_predicted_return: Optional[float]
    allocations: Tuple[StakeAllocation, ...]
    market_cost: float


def normalize_market_probabilities(
    odds: Mapping[str, float],
) -> Dict[str, float]:
    """全30通りのinverse oddsを和1へ正規化した市場暗黙確率を返す。"""

    validated = _validate_odds(odds)
    inverse = {
        combination: 1.0 / validated[combination]
        for combination in EXACTA_COMBINATIONS
    }
    denominator = math.fsum(inverse.values())
    if not math.isfinite(denominator) or denominator <= 0:
        raise DataContractError("2連単市場確率を正規化できません")
    normalized = {
        combination: inverse[combination] / denominator
        for combination in EXACTA_COMBINATIONS
    }
    _validate_probabilities(normalized, label="市場暗黙確率")
    return normalized


def geometric_blend(
    model_probabilities: Mapping[str, float],
    market_probabilities: Mapping[str, float],
    blend_weight: float,
) -> Dict[str, float]:
    """``q^(1-lambda) * p^lambda`` を全30通りで正規化する。

    ``blend_weight=0`` は市場確率、``1`` はmodel確率をそのまま返す。
    """

    model = _validate_probabilities(model_probabilities, label="model確率")
    market = _validate_probabilities(market_probabilities, label="市場暗黙確率")
    weight = _validate_blend_weight(blend_weight)
    if weight == 0.0:
        return dict(market)
    if weight == 1.0:
        return dict(model)

    log_weights = {
        combination: (
            (1.0 - weight) * math.log(market[combination])
            + weight * math.log(model[combination])
        )
        for combination in EXACTA_COMBINATIONS
    }
    maximum = max(log_weights.values())
    unnormalized = {
        combination: math.exp(log_weights[combination] - maximum)
        for combination in EXACTA_COMBINATIONS
    }
    denominator = math.fsum(unnormalized.values())
    if not math.isfinite(denominator) or denominator <= 0:
        raise DataContractError("geometric blendを正規化できません")
    blended = {
        combination: unnormalized[combination] / denominator
        for combination in EXACTA_COMBINATIONS
    }
    _validate_probabilities(blended, label="blend確率")
    return blended


def select_blend_lambda(
    races: Iterable[ValidationRace],
    candidate_lambdas: Sequence[float],
) -> LambdaValidationResult:
    """validation raceのmean log lossで有限候補からlambdaを1つ選ぶ。

    scoreが絶対誤差 ``1e-12`` 以内で同じ場合は、市場側へ保守的に縮約する
    小さいlambdaを選ぶ。
    """

    observations = tuple(races)
    if not observations:
        raise ValueError("lambda validationには1レース以上必要です")
    candidates = _validated_candidate_lambdas(candidate_lambdas)

    prepared = []
    for race in observations:
        if race.winning_combination not in _COMBINATION_ORDER:
            raise DataContractError(
                "validationの勝ち2連単がcanonical 30通りに含まれません"
            )
        model = _validate_probabilities(
            race.model_probabilities,
            label="validation model確率",
        )
        market = normalize_market_probabilities(race.odds)
        prepared.append((model, market, race.winning_combination))

    scores = []
    selected_lambda = candidates[0]
    selected_score = math.inf
    for candidate in candidates:
        losses = []
        for model, market, winner in prepared:
            blended = geometric_blend(model, market, candidate)
            losses.append(-math.log(blended[winner]))
        mean_log_loss = math.fsum(losses) / len(losses)
        score = LambdaScore(
            blend_weight=candidate,
            mean_log_loss=mean_log_loss,
        )
        scores.append(score)
        if (
            mean_log_loss < selected_score - SCORE_TIE_TOLERANCE
            or (
                math.isclose(
                    mean_log_loss,
                    selected_score,
                    rel_tol=0.0,
                    abs_tol=SCORE_TIE_TOLERANCE,
                )
                and candidate < selected_lambda
            )
        ):
            selected_lambda = candidate
            selected_score = mean_log_loss

    return LambdaValidationResult(
        selected_lambda=selected_lambda,
        scores=tuple(scores),
        validation_races=len(observations),
    )


def build_coverage_cost_frontier(
    probabilities: Mapping[str, float],
    odds: Mapping[str, float],
) -> Tuple[CoverageCostPoint, ...]:
    """``p * odds`` の降順で全prefixのcoverage-cost frontierを返す。

    value density同値時はcanonicalな2連単順を使う。
    """

    prediction = _validate_probabilities(probabilities, label="portfolio確率")
    market = _validate_odds(odds)
    ordered = sorted(
        EXACTA_COMBINATIONS,
        key=lambda combination: (
            -(prediction[combination] * market[combination]),
            _COMBINATION_ORDER[combination],
        ),
    )

    selected = []
    coverage_terms = []
    cost_terms = []
    points = []
    for combination in ordered:
        selected.append(combination)
        coverage_terms.append(prediction[combination])
        cost_terms.append(1.0 / market[combination])
        coverage = math.fsum(coverage_terms)
        cost = math.fsum(cost_terms)
        predicted_return = coverage / cost
        points.append(
            CoverageCostPoint(
                prefix_size=len(selected),
                added_combination=combination,
                combinations=tuple(selected),
                coverage=coverage,
                cost=cost,
                predicted_return=predicted_return,
                added_value_density=(
                    prediction[combination] * market[combination]
                ),
            )
        )
    return tuple(points)


def single_point_plan(
    probabilities: Mapping[str, float],
    odds: Mapping[str, float],
    *,
    combination: Optional[str] = None,
    stake_yen: int = DEFAULT_STAKE_UNIT_YEN,
    threshold: float = DEFAULT_MIN_PREDICTED_RETURN,
) -> PortfolioPlan:
    """value density最大の単点、または指定した単点を100円単位で評価する。"""

    prediction = _validate_probabilities(probabilities, label="portfolio確率")
    market = _validate_odds(odds)
    _validate_threshold(threshold)
    _validate_money(stake_yen, DEFAULT_STAKE_UNIT_YEN, label="単点stake")

    if combination is None:
        combination = min(
            EXACTA_COMBINATIONS,
            key=lambda item: (
                -(prediction[item] * market[item]),
                _COMBINATION_ORDER[item],
            ),
        )
    elif combination not in _COMBINATION_ORDER:
        raise ValueError("単点の組合せはcanonicalな2連単で指定してください")

    allocation = _allocation(
        combination,
        prediction[combination],
        market[combination],
        stake_yen // DEFAULT_STAKE_UNIT_YEN,
        DEFAULT_STAKE_UNIT_YEN,
    )
    predicted_return = allocation.predicted_payout_yen / stake_yen
    return PortfolioPlan(
        strategy="single_point",
        decision=(
            "RESEARCH_PORTFOLIO"
            if predicted_return >= threshold
            else "PASS"
        ),
        threshold=threshold,
        coverage=prediction[combination],
        cost_yen=stake_yen,
        predicted_payout_yen=allocation.predicted_payout_yen,
        predicted_return=predicted_return,
        allocation_predicted_return=predicted_return,
        allocations=(allocation,),
        market_cost=1.0 / market[combination],
    )


def equal_payout_dutching(
    probabilities: Mapping[str, float],
    odds: Mapping[str, float],
    combinations: Sequence[str],
    *,
    budget_yen: int = DEFAULT_RACE_BUDGET_YEN,
    unit_yen: int = DEFAULT_STAKE_UNIT_YEN,
    threshold: float = DEFAULT_MIN_PREDICTED_RETURN,
) -> PortfolioPlan:
    """固定予算を100円単位で配り、的中時gross payoutを近似的に揃える。"""

    prediction = _validate_probabilities(probabilities, label="portfolio確率")
    market = _validate_odds(odds)
    selected = _validate_selected_combinations(combinations)
    _validate_threshold(threshold)
    _validate_money(budget_yen, unit_yen, label="1レース予算")
    _validate_unit(unit_yen)

    total_units = budget_yen // unit_yen
    if total_units < len(selected):
        raise ValueError(
            "equal-payout dutchingは各組合せへ最低1単位を配る予算が必要です"
        )
    units = _apportion_inverse_odds(
        selected,
        market,
        total_units=total_units,
    )
    allocations = tuple(
        _allocation(
            combination,
            prediction[combination],
            market[combination],
            units[combination],
            unit_yen,
        )
        for combination in selected
    )
    coverage = math.fsum(
        prediction[combination] for combination in selected
    )
    predicted_payout = math.fsum(
        allocation.predicted_payout_yen for allocation in allocations
    )
    market_cost = math.fsum(1.0 / market[item] for item in selected)
    predicted_return = coverage / market_cost
    allocation_predicted_return = predicted_payout / budget_yen
    return PortfolioPlan(
        strategy="equal_payout_dutching",
        decision=(
            "RESEARCH_PORTFOLIO"
            if predicted_return >= threshold
            else "PASS"
        ),
        threshold=threshold,
        coverage=coverage,
        cost_yen=budget_yen,
        predicted_payout_yen=predicted_payout,
        predicted_return=predicted_return,
        allocation_predicted_return=allocation_predicted_return,
        allocations=allocations,
        market_cost=market_cost,
    )


def select_equal_payout_prefix(
    probabilities: Mapping[str, float],
    odds: Mapping[str, float],
    *,
    budget_yen: int = DEFAULT_RACE_BUDGET_YEN,
    unit_yen: int = DEFAULT_STAKE_UNIT_YEN,
    threshold: float = DEFAULT_MIN_PREDICTED_RETURN,
    max_market_cost: float = DEFAULT_MAX_MARKET_COST,
) -> PortfolioPlan:
    """protocol制約を満たすprefixのうちcoverage最大のportfolioを返す。

    prefixはvalue density順で固定する。protocolで事前固定した理論値
    ``coverage / market_cost`` が ``threshold`` 以上、理論market costが
    ``max_market_cost`` 以下、かつ各組合せへ最低1単位を割り当てられる候補
    だけを比較する。100円丸め後の期待値は選択に使わず、別フィールドで返す。
    """

    _validate_threshold(threshold)
    if not math.isfinite(max_market_cost) or max_market_cost <= 0:
        raise ValueError("max_market_costは有限の正数である必要があります")
    _validate_unit(unit_yen)
    _validate_money(budget_yen, unit_yen, label="1レース予算")

    frontier = build_coverage_cost_frontier(probabilities, odds)
    max_combinations = budget_yen // unit_yen
    qualifying = []
    for point in frontier:
        if point.prefix_size > max_combinations:
            break
        if point.cost > max_market_cost:
            continue
        if point.predicted_return < threshold:
            continue
        plan = equal_payout_dutching(
            probabilities,
            odds,
            point.combinations,
            budget_yen=budget_yen,
            unit_yen=unit_yen,
            threshold=threshold,
        )
        qualifying.append((point, plan))

    if not qualifying:
        return PortfolioPlan(
            strategy="equal_payout_prefix",
            decision="PASS",
            threshold=threshold,
            coverage=0.0,
            cost_yen=0,
            predicted_payout_yen=0.0,
            predicted_return=None,
            allocation_predicted_return=None,
            allocations=(),
            market_cost=0.0,
        )

    # coverageは正の確率をprefixへ追加するたび増える。念のため同値時は
    # protocolどおり低いmarket cost、canonical順で決定論的に選ぶ。
    _, selected = max(
        qualifying,
        key=lambda candidate: (
            candidate[0].coverage,
            -candidate[0].cost,
            tuple(
                -_COMBINATION_ORDER[item.combination]
                for item in candidate[1].allocations
            ),
        ),
    )
    return PortfolioPlan(
        strategy="equal_payout_prefix",
        decision=selected.decision,
        threshold=selected.threshold,
        coverage=selected.coverage,
        cost_yen=selected.cost_yen,
        predicted_payout_yen=selected.predicted_payout_yen,
        predicted_return=selected.predicted_return,
        allocation_predicted_return=selected.allocation_predicted_return,
        allocations=selected.allocations,
        market_cost=selected.market_cost,
    )


def _validate_probabilities(
    probabilities: Mapping[str, float],
    *,
    label: str,
) -> Dict[str, float]:
    _validate_exact_keys(probabilities, label=label)
    values = {}
    for combination in EXACTA_COMBINATIONS:
        value = _finite_number(probabilities[combination], label=label)
        if value <= 0:
            raise DataContractError(
                f"{label}は全30通りで正である必要があります: {combination}"
            )
        values[combination] = value
    total = math.fsum(values.values())
    if not math.isclose(
        total,
        1.0,
        rel_tol=0.0,
        abs_tol=PROBABILITY_TOLERANCE,
    ):
        raise DataContractError(f"{label}の合計が1ではありません: {total!r}")
    return values


def _validate_odds(odds: Mapping[str, float]) -> Dict[str, float]:
    _validate_exact_keys(odds, label="2連単odds")
    values = {}
    for combination in EXACTA_COMBINATIONS:
        value = _finite_number(odds[combination], label="2連単odds")
        if value <= 0:
            raise DataContractError(
                "2連単oddsは全30通りで正である必要があります: "
                f"{combination}"
            )
        values[combination] = value
    return values


def _validate_exact_keys(values: Mapping[str, float], *, label: str) -> None:
    keys = set(values)
    expected = set(EXACTA_COMBINATIONS)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise DataContractError(
            f"{label}はcanonical 30通りと完全一致する必要があります"
            f"（missing={missing}, extra={extra}）"
        )


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise DataContractError(f"{label}にboolは使えません")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise DataContractError(f"{label}に数値でない値があります") from exc
    if not math.isfinite(converted):
        raise DataContractError(f"{label}に非有限値があります")
    return converted


def _validate_blend_weight(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("lambdaにboolは使えません")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("lambdaは有限の数値である必要があります") from exc
    if not math.isfinite(converted) or not 0.0 <= converted <= 1.0:
        raise ValueError("lambdaは0以上1以下の有限値である必要があります")
    return converted


def _validated_candidate_lambdas(values: Sequence[float]) -> Tuple[float, ...]:
    if not values:
        raise ValueError("lambda候補は1つ以上必要です")
    converted = tuple(sorted(_validate_blend_weight(value) for value in values))
    if len(set(converted)) != len(converted):
        raise ValueError("lambda候補は重複できません")
    return converted


def _validate_threshold(value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError("予測回収率thresholdは有限の0以上である必要があります")


def _validate_unit(unit_yen: int) -> None:
    if isinstance(unit_yen, bool) or not isinstance(unit_yen, int):
        raise ValueError("stake unitは整数円で指定してください")
    if unit_yen <= 0 or unit_yen % 100 != 0:
        raise ValueError("stake unitは正の100円単位で指定してください")


def _validate_money(value: int, unit_yen: int, *, label: str) -> None:
    _validate_unit(unit_yen)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label}は整数円で指定してください")
    if value <= 0 or value % unit_yen != 0:
        raise ValueError(f"{label}は正でstake unitの倍数にしてください")


def _validate_selected_combinations(
    combinations: Sequence[str],
) -> Tuple[str, ...]:
    selected = tuple(combinations)
    if not selected:
        raise ValueError("dutching対象を1つ以上指定してください")
    if len(set(selected)) != len(selected):
        raise ValueError("dutching対象の2連単は重複できません")
    invalid = [item for item in selected if item not in _COMBINATION_ORDER]
    if invalid:
        raise ValueError(f"canonicalでない2連単があります: {invalid}")
    # 呼出順に依存させず、allocationもcanonical順で固定する。
    return tuple(sorted(selected, key=_COMBINATION_ORDER.__getitem__))


def _apportion_inverse_odds(
    combinations: Tuple[str, ...],
    odds: Mapping[str, float],
    *,
    total_units: int,
) -> Dict[str, int]:
    """inverse odds比をHamilton法で整数化し、各組合せへ最低1単位配る。"""

    remaining = list(combinations)
    available_units = total_units
    fixed: Dict[str, int] = {}
    quotas: Dict[str, float] = {}
    while remaining:
        denominator = math.fsum(1.0 / odds[item] for item in remaining)
        quotas = {
            item: available_units * (1.0 / odds[item]) / denominator
            for item in remaining
        }
        below_one = [item for item in remaining if quotas[item] < 1.0]
        if not below_one:
            break
        for item in below_one:
            fixed[item] = 1
            available_units -= 1
        remaining = [item for item in remaining if item not in fixed]
        if available_units < len(remaining):
            raise ArithmeticError("最低1単位を満たすdutching配分を作れません")

    allocated = dict(fixed)
    if remaining:
        floors = {item: int(math.floor(quotas[item])) for item in remaining}
        allocated.update(floors)
        leftover = total_units - sum(allocated.values())
        remainders = sorted(
            remaining,
            key=lambda item: (
                -(quotas[item] - floors[item]),
                _COMBINATION_ORDER[item],
            ),
        )
        for item in remainders[:leftover]:
            allocated[item] += 1

    if (
        set(allocated) != set(combinations)
        or any(units < 1 for units in allocated.values())
        or sum(allocated.values()) != total_units
    ):
        raise ArithmeticError("dutching配分の整数化に失敗しました")
    return allocated


def _allocation(
    combination: str,
    probability: float,
    odds: float,
    units: int,
    unit_yen: int,
) -> StakeAllocation:
    stake = units * unit_yen
    gross = stake * odds
    return StakeAllocation(
        combination=combination,
        probability=probability,
        odds=odds,
        units=units,
        stake_yen=stake,
        gross_payout_if_win_yen=gross,
        predicted_payout_yen=probability * gross,
    )
