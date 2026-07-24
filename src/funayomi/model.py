"""説明可能な3連単基準確率モデル。"""

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, Mapping, Optional, Tuple

from .combinations import TRIFECTA_COMBINATIONS
from .domain import NormalizedRace
from .errors import ChronologyError, DataContractError


PREDICTION_CUTOFF = "program"
PREDICTION_FEATURES: Tuple[str, ...] = (
    "stadium_number",
    "program.entry_numbers",
)
FORBIDDEN_PREDICTION_FEATURES: Tuple[str, ...] = (
    "preview",
    "odds",
    "outcome",
    "result",
    "payout",
    "place_number",
    "technique_number",
)


@dataclass(frozen=True)
class ProbabilityEstimate:
    combination: str
    probability: float
    observed_count: int
    training_races: int
    prior_count: float
    explanation: str
    reliability: str


@dataclass(frozen=True)
class ProbabilityPrediction:
    estimates: Mapping[str, ProbabilityEstimate]
    training_start: Optional[date]
    training_end: Optional[date]
    training_races: int
    training_fingerprint: str
    prior_count_per_combination: float
    prediction_cutoff: str = PREDICTION_CUTOFF
    feature_names: Tuple[str, ...] = PREDICTION_FEATURES

    @property
    def probability_sum(self) -> float:
        return math.fsum(item.probability for item in self.estimates.values())


class SmoothedTrifectaFrequencyModel:
    """芦屋の枠番3連単頻度を対称 Dirichlet 事前分布で平滑化する。

    各組み合わせの確率は ``(count + alpha) / (N + 120*alpha)``。
    予測時に読む特徴は場コードと6つの枠番だけで、オッズ、直前情報、
    結果、払戻は参照しない。
    """

    def __init__(
        self,
        counts: Mapping[str, int],
        training_races: int,
        *,
        prior_count_per_combination: float = 1.0,
        training_start: Optional[date] = None,
        training_end: Optional[date] = None,
        training_fingerprint: Optional[str] = None,
        trained_before: Optional[date] = None,
    ):
        if (
            not math.isfinite(prior_count_per_combination)
            or prior_count_per_combination <= 0
        ):
            raise ValueError("事前カウントは正である必要があります")
        self.counts = {
            combination: int(counts.get(combination, 0))
            for combination in TRIFECTA_COMBINATIONS
        }
        if any(value < 0 for value in self.counts.values()):
            raise ValueError("観測カウントは負にできません")
        if sum(self.counts.values()) != training_races:
            raise DataContractError("学習レース数と3連単観測数が一致しません")
        self.training_races = training_races
        self.prior_count_per_combination = float(prior_count_per_combination)
        self.training_start = training_start
        self.training_end = training_end
        self.training_fingerprint = training_fingerprint or hashlib.sha256(b"").hexdigest()
        self.trained_before = trained_before

    @classmethod
    def fit(
        cls,
        races: Iterable[NormalizedRace],
        *,
        prediction_date: date,
        prior_count_per_combination: float = 1.0,
    ) -> "SmoothedTrifectaFrequencyModel":
        counts: Counter[str] = Counter()
        included_dates = []
        fingerprint_rows = []
        seen_races = set()
        for race in sorted(
            races,
            key=lambda item: (
                item.identity.date,
                item.identity.race_number,
            ),
        ):
            if race.identity.date >= prediction_date:
                raise ChronologyError(
                    "学習レースは予測日より前に限定する必要があります: "
                    f"{race.identity.date} >= {prediction_date}"
                )
            if race.identity.stadium_number != 21:
                raise DataContractError(
                    "芦屋以外のレースを学習データへ混在できません: "
                    f"stadium={race.identity.stadium_number}"
                )
            race_key = (
                race.identity.date,
                race.identity.stadium_number,
                race.identity.race_number,
            )
            if race_key in seen_races:
                raise DataContractError(
                    "同じレースが学習データに重複しています: "
                    f"{race.identity.date} {race.identity.race_number}R"
                )
            seen_races.add(race_key)
            if not race.training_eligible:
                continue
            winning = race.outcome.winning_trifecta
            if winning not in TRIFECTA_COMBINATIONS:
                continue
            counts[winning] += 1
            included_dates.append(race.identity.date)
            fingerprint_rows.append(
                "|".join(
                    (
                        race.identity.date.isoformat(),
                        str(race.identity.race_number),
                        race.source_sha256 or "unknown",
                        winning,
                    )
                )
            )
        fingerprint = hashlib.sha256(
            "\n".join(fingerprint_rows).encode("utf-8")
        ).hexdigest()
        return cls(
            counts,
            sum(counts.values()),
            prior_count_per_combination=prior_count_per_combination,
            training_start=min(included_dates) if included_dates else None,
            training_end=max(included_dates) if included_dates else None,
            training_fingerprint=fingerprint,
            trained_before=prediction_date,
        )

    def predict(self, race: NormalizedRace) -> ProbabilityPrediction:
        if race.identity.stadium_number != 21:
            raise DataContractError("基準モデルは芦屋専用です")
        if self.trained_before is not None and race.identity.date < self.trained_before:
            raise ChronologyError(
                "モデルの予測可能日より前のレースは予測できません: "
                f"{race.identity.date} < {self.trained_before}"
            )
        if not race.has_full_field:
            raise DataContractError("6艇が揃わないレースの3連単確率は推定しません")

        denominator = (
            self.training_races
            + len(TRIFECTA_COMBINATIONS) * self.prior_count_per_combination
        )
        estimates: Dict[str, ProbabilityEstimate] = {}
        for combination in TRIFECTA_COMBINATIONS:
            count = self.counts[combination]
            probability = (
                count + self.prior_count_per_combination
            ) / denominator
            estimates[combination] = ProbabilityEstimate(
                combination=combination,
                probability=probability,
                observed_count=count,
                training_races=self.training_races,
                prior_count=self.prior_count_per_combination,
                explanation=(
                    "芦屋の枠番3連単頻度を対称Dirichlet事前分布で平滑化"
                    f"（観測 {count}/{self.training_races}、"
                    f"事前カウント {self.prior_count_per_combination:g}）"
                ),
                reliability=_reliability(count, self.training_races),
            )

        prediction = ProbabilityPrediction(
            estimates=estimates,
            training_start=self.training_start,
            training_end=self.training_end,
            training_races=self.training_races,
            training_fingerprint=self.training_fingerprint,
            prior_count_per_combination=self.prior_count_per_combination,
        )
        if not math.isclose(
            prediction.probability_sum, 1.0, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ArithmeticError("推定確率の合計が1になりません")
        return prediction


def _reliability(observed_count: int, training_races: int) -> str:
    if training_races < 120:
        return "low_total_support"
    if observed_count < 3:
        return "low_combination_support"
    if observed_count < 10:
        return "limited_combination_support"
    return "baseline_support"
