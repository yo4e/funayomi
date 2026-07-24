"""確率と歴史オッズを結合する期待値ランキング。"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .combinations import TRIFECTA_COMBINATIONS
from .domain import NormalizedRace
from .model import ProbabilityPrediction


@dataclass(frozen=True)
class RankedBet:
    rank: int
    combination: str
    predicted_probability: float
    odds: Optional[float]
    expected_return: Optional[float]
    expected_profit_rate: Optional[float]
    explanation: str
    observed_count: int
    training_races: int
    reliability: str
    qualifies: bool
    exclusion_reason: Optional[str]


@dataclass(frozen=True)
class RankingResult:
    date: str
    stadium_number: int
    race_number: int
    threshold: float
    decision: str
    qualifying_count: int
    rows: Tuple[RankedBet, ...]
    warnings: Tuple[str, ...]
    training_start: Optional[str]
    training_end: Optional[str]
    training_fingerprint: str
    prior_count_per_combination: float
    source_sha256: Optional[str]
    prediction_cutoff: str
    feature_names: Tuple[str, ...]


def rank_race(
    race: NormalizedRace,
    prediction: ProbabilityPrediction,
    *,
    threshold: float = 1.0,
) -> RankingResult:
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("期待回収率の閾値は0以上である必要があります")

    market_complete = all(
        _valid_odd(race.odds.trifecta.get(combination))
        for combination in TRIFECTA_COMBINATIONS
    )
    unsorted: List[RankedBet] = []
    for combination in TRIFECTA_COMBINATIONS:
        estimate = prediction.estimates[combination]
        odds = race.odds.trifecta.get(combination)
        if not _valid_odd(odds):
            expected_return = None
            expected_profit_rate = None
            exclusion_reason = "missing_or_invalid_odds"
            qualifies = False
        else:
            expected_return = estimate.probability * odds
            expected_profit_rate = expected_return - 1.0
            exclusion_reason = None
            qualifies = market_complete and expected_return >= threshold
        unsorted.append(
            RankedBet(
                rank=0,
                combination=combination,
                predicted_probability=estimate.probability,
                odds=odds,
                expected_return=expected_return,
                expected_profit_rate=expected_profit_rate,
                explanation=estimate.explanation,
                observed_count=estimate.observed_count,
                training_races=estimate.training_races,
                reliability=estimate.reliability,
                qualifies=qualifies,
                exclusion_reason=exclusion_reason,
            )
        )

    ordered = sorted(
        unsorted,
        key=lambda item: (
            item.expected_return is None,
            -(item.expected_return or 0.0),
            item.combination,
        ),
    )
    ranked = tuple(
        RankedBet(
            rank=index,
            combination=item.combination,
            predicted_probability=item.predicted_probability,
            odds=item.odds,
            expected_return=item.expected_return,
            expected_profit_rate=item.expected_profit_rate,
            explanation=item.explanation,
            observed_count=item.observed_count,
            training_races=item.training_races,
            reliability=item.reliability,
            qualifies=item.qualifies,
            exclusion_reason=item.exclusion_reason,
        )
        for index, item in enumerate(ordered, start=1)
    )
    qualifying_count = sum(item.qualifies for item in ranked)
    warnings = [
        "Turnmarkオッズのobserved_atは不明です。実購入可能な時点の価格とは断定できません。"
    ]
    if not market_complete:
        warnings.append(
            "3連単120通りのオッズが揃わないため、このレースは購入判断をSKIP_DATAとします。"
        )
    warnings.extend(
        issue for issue in race.issues if not issue.startswith("result_")
    )
    return RankingResult(
        date=race.identity.date.isoformat(),
        stadium_number=race.identity.stadium_number,
        race_number=race.identity.race_number,
        threshold=threshold,
        decision=(
            "SKIP_DATA"
            if not market_complete
            else ("CANDIDATES" if qualifying_count else "PASS")
        ),
        qualifying_count=qualifying_count,
        rows=ranked,
        warnings=tuple(dict.fromkeys(warnings)),
        training_start=(
            prediction.training_start.isoformat() if prediction.training_start else None
        ),
        training_end=(
            prediction.training_end.isoformat() if prediction.training_end else None
        ),
        training_fingerprint=prediction.training_fingerprint,
        prior_count_per_combination=prediction.prior_count_per_combination,
        source_sha256=race.source_sha256,
        prediction_cutoff=prediction.prediction_cutoff,
        feature_names=prediction.feature_names,
    )


def ranking_to_dict(result: RankingResult) -> Dict[str, Any]:
    return {
        "date": result.date,
        "stadium_number": result.stadium_number,
        "race_number": result.race_number,
        "threshold": result.threshold,
        "decision": result.decision,
        "qualifying_count": result.qualifying_count,
        "training": {
            "start": result.training_start,
            "end": result.training_end,
            "fingerprint": result.training_fingerprint,
            "prior_count_per_combination": result.prior_count_per_combination,
            "prediction_cutoff": result.prediction_cutoff,
            "features": list(result.feature_names),
        },
        "source_sha256": result.source_sha256,
        "warnings": list(result.warnings),
        "rankings": [
            {
                "rank": row.rank,
                "combination": row.combination,
                "predicted_probability": row.predicted_probability,
                "odds": row.odds,
                "expected_return": row.expected_return,
                "expected_profit_rate": row.expected_profit_rate,
                "explanation": row.explanation,
                "support": {
                    "combination_observations": row.observed_count,
                    "training_races": row.training_races,
                    "reliability": row.reliability,
                },
                "qualifies": row.qualifies,
                "exclusion_reason": row.exclusion_reason,
            }
            for row in result.rows
        ],
    }


def format_ranking_text(result: RankingResult) -> str:
    header = [
        f"日付: {result.date}",
        f"場: 芦屋 ({result.stadium_number}) / {result.race_number}R",
        f"判定: {result.decision} "
        f"(期待回収率 >= {result.threshold:.3f}: {result.qualifying_count}件)",
        f"学習期間: {result.training_start or '-'} 〜 {result.training_end or '-'}",
        f"学習fingerprint: {result.training_fingerprint}",
        f"平滑化事前カウントα（1組合せあたり）: "
        f"{result.prior_count_per_combination:g}",
        f"対象日原本SHA-256: {result.source_sha256 or '-'}",
        "注意: " + result.warnings[0],
        "",
        "順位  組合せ      確率      オッズ    期待回収率  期待利益率  支持数  信頼性",
    ]
    lines = list(header)
    for row in result.rows:
        odds = f"{row.odds:8.1f}" if row.odds is not None else "       -"
        expected_return = (
            f"{row.expected_return:10.4f}"
            if row.expected_return is not None
            else "         -"
        )
        expected_profit = (
            f"{row.expected_profit_rate:10.4f}"
            if row.expected_profit_rate is not None
            else "         -"
        )
        suffix = f"  除外:{row.exclusion_reason}" if row.exclusion_reason else ""
        lines.append(
            f"{row.rank:>4}  {row.combination:<7} "
            f"{row.predicted_probability:9.6f} {odds} "
            f"{expected_return} {expected_profit} "
            f"{row.observed_count:>4}/{row.training_races:<4} "
            f"{row.reliability}{suffix}"
        )
    if len(result.warnings) > 1:
        lines.extend(["", "データ警告:"])
        lines.extend(f"- {warning}" for warning in result.warnings[1:])
    return "\n".join(lines)


def _valid_odd(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(value) and value > 0
