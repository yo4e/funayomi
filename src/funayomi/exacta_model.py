"""Turnmark retrospective sandbox向けの説明可能な2連単確率モデル。

このモジュールは価格を読まない独立した確率経路だけを扱う。学習時には
clean cohortの結果を目的変数として読むが、予測時に参照するのはrace identity
とprogram partitionだけである。
"""

import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .combinations import EXACTA_COMBINATIONS
from .domain import NormalizedRace
from .errors import ChronologyError, DataContractError


ASHIYA_STADIUM_NUMBER = 21
PREDICTION_CUTOFF = "program"

NUMERIC_PROGRAM_FEATURES: Tuple[str, ...] = (
    "weight",
    "flying_count",
    "late_count",
    "average_start_timing",
    "national_win_rate",
    "national_top_2_percent",
    "national_top_3_percent",
    "local_win_rate",
    "local_top_2_percent",
    "local_top_3_percent",
    "motor_top_2_percent",
    "motor_top_3_percent",
    "boat_top_2_percent",
    "boat_top_3_percent",
)
RAW_PROGRAM_FEATURES: Tuple[str, ...] = (
    "entry_number",
    "rank_number",
) + NUMERIC_PROGRAM_FEATURES
FORBIDDEN_PREDICTION_FEATURES: Tuple[str, ...] = (
    "preview",
    "odds",
    "outcome",
    "result",
    "payout",
    "place_number",
    "technique",
    "result_start_timing",
)
_KNOWN_EXCEPTION_CODES = frozenset(
    ("妨", "エ", "転", "落", "沈", "不", "F", "L", "欠")
)
_ENTRY_NUMBERS: Tuple[int, ...] = (1, 2, 3, 4, 5, 6)
_MODEL_VERSION = "turnmark_retrospective_exacta_pl_v1"


class ModelConvergenceError(DataContractError):
    """optimizerが規定条件で収束しなかったためモデルを公開できない。"""


@dataclass(frozen=True)
class ProgramPreprocessor:
    """training partitionだけでfitされたprogram特徴変換器。"""

    numeric_medians: Tuple[float, ...]
    numeric_means: Tuple[float, ...]
    numeric_standard_deviations: Tuple[float, ...]
    feature_names: Tuple[str, ...]
    fitted_racer_rows: int

    @classmethod
    def fit(
        cls, programs: Sequence[Mapping[int, Mapping[str, Any]]]
    ) -> "ProgramPreprocessor":
        if not programs:
            raise DataContractError("前処理をfitする学習programがありません")
        rows = [
            racers[entry]
            for racers in programs
            for entry in _ENTRY_NUMBERS
        ]
        medians: List[float] = []
        for name in NUMERIC_PROGRAM_FEATURES:
            observed = sorted(
                value
                for value in (_finite_number(row.get(name)) for row in rows)
                if value is not None
            )
            medians.append(_median(observed) if observed else 0.0)

        imputed_columns: List[List[float]] = []
        for name, median in zip(NUMERIC_PROGRAM_FEATURES, medians):
            imputed_columns.append(
                [
                    median
                    if _finite_number(row.get(name)) is None
                    else float(_finite_number(row.get(name)))
                    for row in rows
                ]
            )
        means = [math.fsum(column) / len(column) for column in imputed_columns]
        standard_deviations = [
            math.sqrt(
                math.fsum((value - mean) ** 2 for value in column)
                / len(column)
            )
            for column, mean in zip(imputed_columns, means)
        ]
        names = tuple(
            [f"entry_number={entry}" for entry in range(1, 6)]
            + [
                "rank_number=1",
                "rank_number=2",
                "rank_number=3",
                "rank_number=unknown",
            ]
            + [f"{name}:standardized" for name in NUMERIC_PROGRAM_FEATURES]
            + [f"{name}:missing" for name in NUMERIC_PROGRAM_FEATURES]
        )
        return cls(
            numeric_medians=tuple(medians),
            numeric_means=tuple(means),
            numeric_standard_deviations=tuple(standard_deviations),
            feature_names=names,
            fitted_racer_rows=len(rows),
        )

    def transform(
        self, entry: int, racer: Mapping[str, Any]
    ) -> Tuple[float, ...]:
        if entry not in _ENTRY_NUMBERS:
            raise DataContractError(f"艇番が1〜6ではありません: {entry!r}")
        recorded_entry = _integer(racer.get("entry_number"))
        if recorded_entry != entry:
            raise DataContractError(
                "programの辞書キーとentry_numberが一致しません: "
                f"{entry!r} != {racer.get('entry_number')!r}"
            )

        values: List[float] = [
            1.0 if entry == category else 0.0 for category in range(1, 6)
        ]
        rank = _integer(racer.get("rank_number"))
        values.extend(
            (
                1.0 if rank == 1 else 0.0,
                1.0 if rank == 2 else 0.0,
                1.0 if rank == 3 else 0.0,
                1.0 if rank not in (1, 2, 3, 4) else 0.0,
            )
        )

        standardized: List[float] = []
        missing_indicators: List[float] = []
        for index, name in enumerate(NUMERIC_PROGRAM_FEATURES):
            raw = _finite_number(racer.get(name))
            missing = raw is None
            imputed = self.numeric_medians[index] if missing else float(raw)
            deviation = self.numeric_standard_deviations[index]
            standardized.append(
                0.0
                if deviation == 0.0
                else (imputed - self.numeric_means[index]) / deviation
            )
            missing_indicators.append(1.0 if missing else 0.0)
        values.extend(standardized)
        values.extend(missing_indicators)
        transformed = tuple(values)
        if len(transformed) != len(self.feature_names) or not all(
            math.isfinite(value) for value in transformed
        ):
            raise DataContractError("program特徴を有限の固定長vectorへ変換できません")
        return transformed


@dataclass(frozen=True)
class OptimizationSummary:
    converged: bool
    iterations: int
    initial_objective: float
    final_objective: float
    gradient_infinity_norm: float


@dataclass(frozen=True)
class ExactaProbabilityPrediction:
    probabilities: Mapping[str, float]
    training_start: Optional[date]
    training_end: Optional[date]
    training_races: int
    training_fingerprint: str
    model_fingerprint: str
    model_family: str
    prediction_cutoff: str = PREDICTION_CUTOFF
    feature_names: Tuple[str, ...] = RAW_PROGRAM_FEATURES

    @property
    def probability_sum(self) -> float:
        return math.fsum(self.probabilities.values())


@dataclass(frozen=True)
class _TrainingExample:
    race: NormalizedRace
    winner: str


class SmoothedExactaFrequencyModel:
    """学習partition内の枠番2連単頻度をDirichlet平滑化するbaseline。"""

    def __init__(
        self,
        counts: Mapping[str, int],
        training_races: int,
        *,
        prior_count_per_combination: float,
        training_start: Optional[date],
        training_end: Optional[date],
        training_fingerprint: str,
        trained_before: date,
    ):
        if (
            not math.isfinite(prior_count_per_combination)
            or prior_count_per_combination <= 0.0
        ):
            raise ValueError("事前カウントは有限の正数である必要があります")
        self.counts = {
            combination: int(counts.get(combination, 0))
            for combination in EXACTA_COMBINATIONS
        }
        if any(count < 0 for count in self.counts.values()):
            raise ValueError("観測カウントは負にできません")
        if sum(self.counts.values()) != training_races:
            raise DataContractError("学習レース数と2連単観測数が一致しません")
        self.training_races = training_races
        self.prior_count_per_combination = float(prior_count_per_combination)
        self.training_start = training_start
        self.training_end = training_end
        self.training_fingerprint = training_fingerprint
        self.trained_before = trained_before
        self.model_fingerprint = _fingerprint_json(
            {
                "family": "smoothed_entry_order_exacta_frequency",
                "training_fingerprint": training_fingerprint,
                "prior": self.prior_count_per_combination,
                "counts": self.counts,
            }
        )

    @classmethod
    def fit(
        cls,
        races: Iterable[NormalizedRace],
        *,
        prediction_date: date,
        prior_count_per_combination: float = 1.0,
    ) -> "SmoothedExactaFrequencyModel":
        examples, fingerprint = _collect_training_examples(
            races, prediction_date=prediction_date
        )
        counts = {combination: 0 for combination in EXACTA_COMBINATIONS}
        for example in examples:
            counts[example.winner] += 1
        dates = [example.race.identity.date for example in examples]
        return cls(
            counts,
            len(examples),
            prior_count_per_combination=prior_count_per_combination,
            training_start=min(dates) if dates else None,
            training_end=max(dates) if dates else None,
            training_fingerprint=fingerprint,
            trained_before=prediction_date,
        )

    def predict(self, race: NormalizedRace) -> ExactaProbabilityPrediction:
        _validate_prediction_race(race, self.trained_before)
        denominator = (
            self.training_races
            + len(EXACTA_COMBINATIONS) * self.prior_count_per_combination
        )
        probabilities = {
            combination: (
                self.counts[combination] + self.prior_count_per_combination
            )
            / denominator
            for combination in EXACTA_COMBINATIONS
        }
        _validate_probabilities(probabilities)
        return ExactaProbabilityPrediction(
            probabilities=probabilities,
            training_start=self.training_start,
            training_end=self.training_end,
            training_races=self.training_races,
            training_fingerprint=self.training_fingerprint,
            model_fingerprint=self.model_fingerprint,
            model_family="smoothed_entry_order_exacta_frequency",
            feature_names=("stadium_number", "program.entry_numbers"),
        )


class ProgramPlackettLuceModel:
    """program-only特徴のL2正則化Plackett–Luceモデル。"""

    def __init__(
        self,
        coefficients: Sequence[float],
        preprocessor: ProgramPreprocessor,
        *,
        l2: float,
        training_start: date,
        training_end: date,
        training_races: int,
        training_fingerprint: str,
        trained_before: date,
        optimization: OptimizationSummary,
    ):
        coefficient_tuple = tuple(float(value) for value in coefficients)
        if (
            len(coefficient_tuple) != len(preprocessor.feature_names)
            or not all(math.isfinite(value) for value in coefficient_tuple)
        ):
            raise DataContractError("係数が特徴vectorと一致する有限値ではありません")
        if not optimization.converged:
            raise ModelConvergenceError("未収束モデルは生成できません")
        self.coefficients = coefficient_tuple
        self.preprocessor = preprocessor
        self.l2 = float(l2)
        self.training_start = training_start
        self.training_end = training_end
        self.training_races = training_races
        self.training_fingerprint = training_fingerprint
        self.trained_before = trained_before
        self.optimization = optimization
        self.model_fingerprint = _fingerprint_json(
            {
                "model_version": _MODEL_VERSION,
                "training_fingerprint": training_fingerprint,
                "l2": self.l2,
                "coefficients": self.coefficients,
                "preprocessor": {
                    "medians": preprocessor.numeric_medians,
                    "means": preprocessor.numeric_means,
                    "standard_deviations": (
                        preprocessor.numeric_standard_deviations
                    ),
                    "feature_names": preprocessor.feature_names,
                },
            }
        )

    @classmethod
    def fit(
        cls,
        races: Iterable[NormalizedRace],
        *,
        prediction_date: date,
        l2: float = 1.0,
        maximum_iterations: int = 1000,
        gradient_infinity_norm_tolerance: float = 1e-8,
    ) -> "ProgramPlackettLuceModel":
        if not math.isfinite(l2) or l2 <= 0.0:
            raise ValueError("L2係数は有限の正数である必要があります")
        if maximum_iterations < 1:
            raise ValueError("最大iterationは1以上である必要があります")
        if (
            not math.isfinite(gradient_infinity_norm_tolerance)
            or gradient_infinity_norm_tolerance <= 0.0
        ):
            raise ValueError("gradient toleranceは有限の正数である必要があります")

        examples, fingerprint = _collect_training_examples(
            races, prediction_date=prediction_date
        )
        if not examples:
            raise DataContractError("2連単clean cohortの学習レースがありません")
        programs = [_program_racers(example.race) for example in examples]
        preprocessor = ProgramPreprocessor.fit(programs)
        observations = [
            _make_observation(example, preprocessor) for example in examples
        ]
        coefficients, summary = _minimize_bfgs(
            observations,
            dimension=len(preprocessor.feature_names),
            l2=float(l2),
            maximum_iterations=maximum_iterations,
            gradient_tolerance=gradient_infinity_norm_tolerance,
        )
        if not summary.converged:
            raise ModelConvergenceError(
                "Plackett–Luce optimizerが収束しませんでした: "
                f"iterations={summary.iterations}, "
                f"gradient_inf={summary.gradient_infinity_norm:.6g}"
            )
        dates = [example.race.identity.date for example in examples]
        return cls(
            coefficients,
            preprocessor,
            l2=l2,
            training_start=min(dates),
            training_end=max(dates),
            training_races=len(examples),
            training_fingerprint=fingerprint,
            trained_before=prediction_date,
            optimization=summary,
        )

    def predict(self, race: NormalizedRace) -> ExactaProbabilityPrediction:
        racers = _validate_prediction_race(race, self.trained_before)
        feature_rows = tuple(
            self.preprocessor.transform(entry, racers[entry])
            for entry in _ENTRY_NUMBERS
        )
        linear_predictors = tuple(
            _dot(self.coefficients, row) for row in feature_rows
        )
        probabilities = _exacta_probabilities(linear_predictors)
        return ExactaProbabilityPrediction(
            probabilities=probabilities,
            training_start=self.training_start,
            training_end=self.training_end,
            training_races=self.training_races,
            training_fingerprint=self.training_fingerprint,
            model_fingerprint=self.model_fingerprint,
            model_family="program_plackett_luce",
            feature_names=tuple(
                f"program.racers[].{name}" for name in RAW_PROGRAM_FEATURES
            ),
        )


def _collect_training_examples(
    races: Iterable[NormalizedRace], *, prediction_date: date
) -> Tuple[List[_TrainingExample], str]:
    examples: List[_TrainingExample] = []
    fingerprint_rows: List[str] = []
    seen = set()
    ordered = sorted(
        races,
        key=lambda race: (
            race.identity.date,
            race.identity.stadium_number,
            race.identity.race_number,
        ),
    )
    for race in ordered:
        identity = race.identity
        if identity.date >= prediction_date:
            raise ChronologyError(
                "学習レースは予測日より前に限定する必要があります: "
                f"{identity.date} >= {prediction_date}"
            )
        if identity.stadium_number != ASHIYA_STADIUM_NUMBER:
            raise DataContractError(
                "芦屋以外のレースを学習データへ混在できません: "
                f"stadium={identity.stadium_number}"
            )
        race_key = (
            identity.date,
            identity.stadium_number,
            identity.race_number,
        )
        if race_key in seen:
            raise DataContractError(
                "同じレースが学習データに重複しています: "
                f"{identity.date} {identity.race_number}R"
            )
        seen.add(race_key)
        winner = _clean_exacta_winner(race)
        if winner is None:
            continue
        racers = _program_racers(race)
        example = _TrainingExample(race=race, winner=winner)
        examples.append(example)
        fingerprint_rows.append(
            json.dumps(
                {
                    "date": identity.date.isoformat(),
                    "stadium_number": identity.stadium_number,
                    "race_number": identity.race_number,
                    "source_sha256": getattr(race, "source_sha256", None),
                    "winner": winner,
                    "program": {
                        str(entry): {
                            name: _stable_scalar(racers[entry].get(name))
                            for name in RAW_PROGRAM_FEATURES
                        }
                        for entry in _ENTRY_NUMBERS
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return examples, hashlib.sha256(
        "\n".join(fingerprint_rows).encode("utf-8")
    ).hexdigest()


def _clean_exacta_winner(race: NormalizedRace) -> Optional[str]:
    try:
        racers = _program_racers(race)
    except DataContractError:
        return None
    if tuple(sorted(racers)) != _ENTRY_NUMBERS:
        return None
    outcome = getattr(race, "outcome", None)
    result_racers = getattr(outcome, "racers", None)
    if not isinstance(result_racers, Mapping):
        return None
    normalized_result: Dict[int, Mapping[str, Any]] = {}
    for raw_entry, racer in result_racers.items():
        entry = _integer(raw_entry)
        if (
            entry not in _ENTRY_NUMBERS
            or not isinstance(racer, Mapping)
            or entry in normalized_result
        ):
            return None
        normalized_result[entry] = racer
    if tuple(sorted(normalized_result)) != _ENTRY_NUMBERS:
        return None
    if any(
        racer.get("place_number_source") in _KNOWN_EXCEPTION_CODES
        for racer in normalized_result.values()
    ):
        return None
    top_two: List[int] = []
    for place in (1, 2):
        matches = [
            entry
            for entry, racer in normalized_result.items()
            if _integer(racer.get("place_number")) == place
        ]
        if len(matches) != 1:
            return None
        top_two.append(matches[0])
    winner = f"{top_two[0]}-{top_two[1]}"
    if winner not in EXACTA_COMBINATIONS:
        return None

    declared_winner = getattr(outcome, "winning_exacta", None)
    declared_winners = getattr(outcome, "winning_exactas", None)
    if declared_winners is not None:
        if (
            not isinstance(declared_winners, (tuple, list))
            or tuple(declared_winners) != (winner,)
        ):
            return None
    elif declared_winner is not None and declared_winner != winner:
        return None

    payouts = getattr(outcome, "exacta_payouts", None)
    if not isinstance(payouts, Mapping) or tuple(payouts) != (winner,):
        return None
    amount = payouts.get(winner)
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(float(amount))
        or float(amount) <= 0.0
    ):
        return None
    eligibility = getattr(race, "exacta_training_eligible", True)
    if eligibility is not True:
        return None
    return winner


def _validate_prediction_race(
    race: NormalizedRace, trained_before: date
) -> Mapping[int, Mapping[str, Any]]:
    identity = race.identity
    if identity.stadium_number != ASHIYA_STADIUM_NUMBER:
        raise DataContractError("2連単確率モデルは芦屋専用です")
    if identity.date < trained_before:
        raise ChronologyError(
            "モデルの予測可能日より前のレースは予測できません: "
            f"{identity.date} < {trained_before}"
        )
    return _program_racers(race)


def _program_racers(
    race: NormalizedRace,
) -> Mapping[int, Mapping[str, Any]]:
    program = getattr(race, "program", None)
    raw_racers = getattr(program, "racers", None)
    if not isinstance(raw_racers, Mapping):
        raise DataContractError("program.racersがありません")
    racers: Dict[int, Mapping[str, Any]] = {}
    for raw_entry, racer in raw_racers.items():
        entry = _integer(raw_entry)
        if (
            entry not in _ENTRY_NUMBERS
            or not isinstance(racer, Mapping)
            or entry in racers
        ):
            raise DataContractError("program.racersの艇番またはrecordが不正です")
        racers[entry] = racer
    if tuple(sorted(racers)) != _ENTRY_NUMBERS:
        raise DataContractError("6艇が揃わないレースの2連単確率は推定しません")
    for entry, racer in racers.items():
        if _integer(racer.get("entry_number")) != entry:
            raise DataContractError(
                "programの辞書キーとentry_numberが一致しません"
            )
    return racers


def _make_observation(
    example: _TrainingExample, preprocessor: ProgramPreprocessor
) -> Tuple[Tuple[Tuple[float, ...], ...], int, int]:
    racers = _program_racers(example.race)
    features = tuple(
        preprocessor.transform(entry, racers[entry]) for entry in _ENTRY_NUMBERS
    )
    first, second = (int(value) for value in example.winner.split("-"))
    return features, first - 1, second - 1


def _objective_and_gradient(
    coefficients: Sequence[float],
    observations: Sequence[
        Tuple[Tuple[Tuple[float, ...], ...], int, int]
    ],
    l2: float,
) -> Tuple[float, Tuple[float, ...]]:
    dimension = len(coefficients)
    gradient = [0.0] * dimension
    negative_log_likelihood = 0.0
    for features, first, second in observations:
        eta = tuple(_dot(coefficients, row) for row in features)
        maximum = max(eta)
        weights = tuple(math.exp(max(value - maximum, -700.0)) for value in eta)
        total = math.fsum(weights)
        remaining = math.fsum(
            weight for entry, weight in enumerate(weights) if entry != first
        )
        if (
            not math.isfinite(total)
            or not math.isfinite(remaining)
            or total <= 0.0
            or remaining <= 0.0
        ):
            raise ArithmeticError("Plackett–Luceの分母が有限の正数ではありません")
        negative_log_likelihood += (
            -(eta[first] - maximum)
            + math.log(total)
            - (eta[second] - maximum)
            + math.log(remaining)
        )
        # まず艇ごとの係数を求めてから特徴vectorへ加算する。featureごとに
        # softmax期待値を再計算しないため、標準ライブラリだけでも実用的な
        # 反復時間を保てる。
        entry_gradient_weights = tuple(
            weights[entry] / total
            + (0.0 if entry == first else weights[entry] / remaining)
            - (1.0 if entry == first else 0.0)
            - (1.0 if entry == second else 0.0)
            for entry in range(6)
        )
        for entry, entry_weight in enumerate(entry_gradient_weights):
            if entry_weight == 0.0:
                continue
            row = features[entry]
            for index in range(dimension):
                gradient[index] += entry_weight * row[index]
    race_count = len(observations)
    objective = negative_log_likelihood / race_count + 0.5 * l2 * math.fsum(
        value * value for value in coefficients
    )
    result_gradient = tuple(
        value / race_count + l2 * coefficients[index]
        for index, value in enumerate(gradient)
    )
    if not math.isfinite(objective) or not all(
        math.isfinite(value) for value in result_gradient
    ):
        raise ArithmeticError("目的関数またはgradientが有限ではありません")
    return objective, result_gradient


def _minimize_bfgs(
    observations: Sequence[
        Tuple[Tuple[Tuple[float, ...], ...], int, int]
    ],
    *,
    dimension: int,
    l2: float,
    maximum_iterations: int,
    gradient_tolerance: float,
) -> Tuple[Tuple[float, ...], OptimizationSummary]:
    coefficients = tuple(0.0 for _ in range(dimension))
    objective, gradient = _objective_and_gradient(
        coefficients, observations, l2
    )
    initial_objective = objective
    inverse_hessian = [
        [1.0 if row == column else 0.0 for column in range(dimension)]
        for row in range(dimension)
    ]
    gradient_norm = max(abs(value) for value in gradient)
    if gradient_norm <= gradient_tolerance:
        return coefficients, OptimizationSummary(
            converged=True,
            iterations=0,
            initial_objective=initial_objective,
            final_objective=objective,
            gradient_infinity_norm=gradient_norm,
        )

    for iteration in range(1, maximum_iterations + 1):
        direction = tuple(
            -math.fsum(
                inverse_hessian[row][column] * gradient[column]
                for column in range(dimension)
            )
            for row in range(dimension)
        )
        directional_derivative = _dot(gradient, direction)
        if not math.isfinite(directional_derivative) or directional_derivative >= 0:
            direction = tuple(-value for value in gradient)
            directional_derivative = -math.fsum(
                value * value for value in gradient
            )
            inverse_hessian = [
                [
                    1.0 if row == column else 0.0
                    for column in range(dimension)
                ]
                for row in range(dimension)
            ]

        step = 1.0
        accepted = False
        candidate = coefficients
        candidate_objective = objective
        candidate_gradient = gradient
        for _ in range(80):
            candidate = tuple(
                coefficient + step * delta
                for coefficient, delta in zip(coefficients, direction)
            )
            candidate_objective, candidate_gradient = _objective_and_gradient(
                candidate, observations, l2
            )
            if candidate_objective <= (
                objective + 1e-4 * step * directional_derivative
            ):
                accepted = True
                break
            step *= 0.5
        if not accepted:
            return coefficients, OptimizationSummary(
                converged=False,
                iterations=iteration,
                initial_objective=initial_objective,
                final_objective=objective,
                gradient_infinity_norm=max(abs(value) for value in gradient),
            )

        displacement = tuple(
            new - old for new, old in zip(candidate, coefficients)
        )
        gradient_change = tuple(
            new - old for new, old in zip(candidate_gradient, gradient)
        )
        curvature = _dot(displacement, gradient_change)
        coefficients = candidate
        objective = candidate_objective
        gradient = candidate_gradient
        gradient_norm = max(abs(value) for value in gradient)
        if gradient_norm <= gradient_tolerance:
            return coefficients, OptimizationSummary(
                converged=True,
                iterations=iteration,
                initial_objective=initial_objective,
                final_objective=objective,
                gradient_infinity_norm=gradient_norm,
            )

        displacement_norm = math.sqrt(
            math.fsum(value * value for value in displacement)
        )
        change_norm = math.sqrt(
            math.fsum(value * value for value in gradient_change)
        )
        if (
            curvature > 0.0
            and curvature > 1e-12 * displacement_norm * change_norm
            and math.isfinite(curvature)
        ):
            rho = 1.0 / curvature
            hessian_times_change = tuple(
                math.fsum(
                    inverse_hessian[row][column] * gradient_change[column]
                    for column in range(dimension)
                )
                for row in range(dimension)
            )
            y_h_y = _dot(gradient_change, hessian_times_change)
            scale = (1.0 + y_h_y * rho) * rho
            inverse_hessian = [
                [
                    inverse_hessian[row][column]
                    + scale * displacement[row] * displacement[column]
                    - rho
                    * (
                        hessian_times_change[row] * displacement[column]
                        + displacement[row] * hessian_times_change[column]
                    )
                    for column in range(dimension)
                ]
                for row in range(dimension)
            ]
        else:
            inverse_hessian = [
                [
                    1.0 if row == column else 0.0
                    for column in range(dimension)
                ]
                for row in range(dimension)
            ]

    return coefficients, OptimizationSummary(
        converged=False,
        iterations=maximum_iterations,
        initial_objective=initial_objective,
        final_objective=objective,
        gradient_infinity_norm=gradient_norm,
    )


def _exacta_probabilities(
    linear_predictors: Sequence[float],
) -> Dict[str, float]:
    if len(linear_predictors) != 6 or not all(
        math.isfinite(value) for value in linear_predictors
    ):
        raise DataContractError("6艇分の有限なlinear predictorが必要です")
    maximum = max(linear_predictors)
    weights = tuple(
        math.exp(max(value - maximum, -700.0))
        for value in linear_predictors
    )
    total = math.fsum(weights)
    minimum_log_probability = math.log(sys.float_info.min)
    raw: Dict[str, float] = {}
    for first in _ENTRY_NUMBERS:
        remaining = math.fsum(
            weight
            for entry, weight in enumerate(weights, start=1)
            if entry != first
        )
        if remaining <= 0.0 or not math.isfinite(remaining):
            raise ArithmeticError("2着条件付き確率の分母が不正です")
        for second in _ENTRY_NUMBERS:
            if second == first:
                continue
            log_probability = (
                math.log(weights[first - 1])
                - math.log(total)
                + math.log(weights[second - 1])
                - math.log(remaining)
            )
            raw[f"{first}-{second}"] = math.exp(
                max(log_probability, minimum_log_probability)
            )
    normalization = math.fsum(raw.values())
    probabilities = {
        combination: raw[combination] / normalization
        for combination in EXACTA_COMBINATIONS
    }
    _validate_probabilities(probabilities)
    return probabilities


def _validate_probabilities(probabilities: Mapping[str, float]) -> None:
    if tuple(probabilities) != EXACTA_COMBINATIONS:
        raise ArithmeticError("2連単30通りがcanonical orderで揃っていません")
    if not all(
        math.isfinite(value) and value > 0.0
        for value in probabilities.values()
    ):
        raise ArithmeticError("2連単確率は全て有限の正数である必要があります")
    if not math.isclose(
        math.fsum(probabilities.values()),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ArithmeticError("2連単確率の合計が1になりません")


def _median(values: Sequence[float]) -> float:
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / 2.0


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _integer(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _stable_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    return repr(value)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return math.fsum(first * second for first, second in zip(left, right))


def _fingerprint_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
