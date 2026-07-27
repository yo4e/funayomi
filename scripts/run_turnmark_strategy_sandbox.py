#!/usr/bin/env python3
"""Turnmark限定2連単strategy sandbox v1を再現する。"""

import argparse
import hashlib
import json
import math
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from funayomi.cache import LocalCache
from funayomi.combinations import EXACTA_COMBINATIONS
from funayomi.domain import NormalizedRace
from funayomi.errors import DataContractError
from funayomi.exacta_model import (
    ModelConvergenceError,
    ProgramPlackettLuceModel,
    SmoothedExactaFrequencyModel,
)
from funayomi.portfolio import (
    ValidationRace,
    geometric_blend,
    normalize_market_probabilities,
    select_blend_lambda,
)
from funayomi.repository import RaceRepository
from funayomi.safety import (
    ACTIONABLE,
    REFUND_PROBABILITY_MODE,
    STRATEGY_STATUS,
)
from funayomi.strategy_backtest import (
    STRATEGY_NAMES,
    StrategyRaceInput,
    portfolio_results_to_dict,
    run_portfolio_backtest,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    ROOT / "protocols" / "turnmark_exacta_strategy_sandbox_v1.json"
)
SOURCE_START = date(2026, 1, 1)
SOURCE_END = date(2026, 7, 23)
L2_CANDIDATES: Tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0)
BLEND_CANDIDATES: Tuple[float, ...] = (0.0, 0.25, 0.5, 1.0)
RACE_BUDGET_YEN = 1000
WAGER_UNIT_YEN = 100
MINIMUM_PREDICTED_RETURN = 1.10
MAXIMUM_MARKET_COST = 0.50
BOOTSTRAP_RESAMPLES = 20_000
BOOTSTRAP_SEED = 20_260_727
TIE_TOLERANCE = 1e-12
DEFAULT_WORKERS = max(1, min(4, os.cpu_count() or 1))
_VALIDATION_WORKER_RACES: Tuple[NormalizedRace, ...] = ()


@dataclass(frozen=True)
class MonthSpec:
    id: str
    start: date
    end: date


@dataclass(frozen=True)
class FoldSpec:
    id: str
    training_start: date
    training_end: date
    evaluation_start: date
    evaluation_end: date
    inner_month_ids: Tuple[str, ...]


INNER_MONTHS: Tuple[MonthSpec, ...] = (
    MonthSpec("2026-03", date(2026, 3, 1), date(2026, 3, 31)),
    MonthSpec("2026-04", date(2026, 4, 1), date(2026, 4, 30)),
    MonthSpec("2026-05", date(2026, 5, 1), date(2026, 5, 31)),
    MonthSpec("2026-06", date(2026, 6, 1), date(2026, 6, 30)),
)
OUTER_FOLDS: Tuple[FoldSpec, ...] = (
    FoldSpec(
        "outer_2026_04",
        SOURCE_START,
        date(2026, 3, 31),
        date(2026, 4, 1),
        date(2026, 4, 30),
        ("2026-03",),
    ),
    FoldSpec(
        "outer_2026_05",
        SOURCE_START,
        date(2026, 4, 30),
        date(2026, 5, 1),
        date(2026, 5, 31),
        ("2026-03", "2026-04"),
    ),
    FoldSpec(
        "outer_2026_06",
        SOURCE_START,
        date(2026, 5, 31),
        date(2026, 6, 1),
        date(2026, 6, 30),
        ("2026-03", "2026-04", "2026-05"),
    ),
    FoldSpec(
        "outer_2026_07_partial",
        SOURCE_START,
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 23),
        ("2026-03", "2026-04", "2026-05", "2026-06"),
    ),
)


def run_study(
    cache_dir: Path,
    *,
    offline: bool,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    code_commit_sha: Optional[str] = None,
    workers: int = DEFAULT_WORKERS,
) -> Dict[str, Any]:
    if workers < 1:
        raise ValueError("workersは1以上である必要があります")
    repository = RaceRepository(LocalCache(cache_dir))
    races = repository.races_between(
        SOURCE_START,
        SOURCE_END,
        offline=offline,
    )
    races = sorted(
        races,
        key=lambda item: (item.identity.date, item.identity.race_number),
    )
    _ensure_source_period(races)
    protocol_sha = hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest()
    meeting_ids = assign_meeting_ids(races)
    source_fingerprint = input_source_fingerprint(races)
    validation_cache_key = stable_hash(
        {
            "cache_schema": 1,
            "source_fingerprint": source_fingerprint,
            "protocol_sha256": protocol_sha,
            "exacta_model_sha256": hashlib.sha256(
                (ROOT / "src" / "funayomi" / "exacta_model.py").read_bytes()
            ).hexdigest(),
            "inner_months": [
                {
                    "id": item.id,
                    "start": item.start.isoformat(),
                    "end": item.end.isoformat(),
                }
                for item in INNER_MONTHS
            ],
            "l2_candidates": list(L2_CANDIDATES),
        }
    )
    validation_cache_path = (
        cache_dir
        / "research"
        / "turnmark_exacta_strategy_sandbox_v1_validation.json"
    )
    validation_cache = load_validation_cache(
        validation_cache_path,
        expected_key=validation_cache_key,
    )
    validation_cache_reused = validation_cache is not None
    if validation_cache is None:
        validation_cache = _build_validation_cache(races, workers=workers)
        write_validation_cache(
            validation_cache_path,
            cache_key=validation_cache_key,
            validation_cache=validation_cache,
        )
    fold_documents = []
    portfolio_inputs: List[StrategyRaceInput] = []
    all_probability_rows = []

    for fold in OUTER_FOLDS:
        selected_l2, l2_scores = select_l2_candidate(
            validation_cache,
            fold.inner_month_ids,
        )
        lambda_validation = _select_lambda_for_fold(
            validation_cache,
            fold.inner_month_ids,
            selected_l2=selected_l2,
        )
        training = [
            race
            for race in races
            if fold.training_start
            <= race.identity.date
            <= fold.training_end
        ]
        evaluation = [
            race
            for race in races
            if fold.evaluation_start
            <= race.identity.date
            <= fold.evaluation_end
        ]
        frequency_model = SmoothedExactaFrequencyModel.fit(
            training,
            prediction_date=fold.evaluation_start,
            prior_count_per_combination=1.0,
        )
        program_model = ProgramPlackettLuceModel.fit(
            training,
            prediction_date=fold.evaluation_start,
            l2=selected_l2,
        )
        fold_probability_rows = []
        for race in evaluation:
            if not race.exacta_evaluation_eligible:
                continue
            frequency = frequency_model.predict(race).probabilities
            program = program_model.predict(race).probabilities
            odds = usable_exacta_odds(race)
            market = (
                normalize_market_probabilities(odds)
                if odds is not None
                else None
            )
            blend = (
                geometric_blend(
                    program,
                    market,
                    lambda_validation.selected_lambda,
                )
                if market is not None
                else program
            )
            winner = (
                race.outcome.winning_exacta
                if race.exacta_training_eligible
                else None
            )
            probability_row = {
                "fold_id": fold.id,
                "date": race.identity.date.isoformat(),
                "race_number": race.identity.race_number,
                "winner": winner,
                "market_complete": odds is not None,
                "frequency": frequency,
                "program": program,
                "market": market,
                "blend": blend if market is not None else None,
            }
            fold_probability_rows.append(probability_row)
            all_probability_rows.append(probability_row)
            portfolio_inputs.append(
                StrategyRaceInput(
                    race=race,
                    fold_id=fold.id,
                    meeting_id=meeting_ids[
                        (
                            race.identity.date,
                            race.identity.race_number,
                        )
                    ],
                    program_probabilities=program,
                    blend_probabilities=blend,
                )
            )
        fold_quality = probability_quality(fold_probability_rows)
        fold_documents.append(
            {
                "fold_id": fold.id,
                "periods": {
                    "training": {
                        "start": fold.training_start.isoformat(),
                        "end": fold.training_end.isoformat(),
                    },
                    "evaluation": {
                        "start": fold.evaluation_start.isoformat(),
                        "end": fold.evaluation_end.isoformat(),
                    },
                    "inner_validation_months": list(fold.inner_month_ids),
                },
                "selection": {
                    "selected_l2": selected_l2,
                    "l2_candidates": l2_scores,
                    "selected_blend_lambda": (
                        lambda_validation.selected_lambda
                    ),
                    "blend_validation_races": (
                        lambda_validation.validation_races
                    ),
                    "blend_candidates": [
                        {
                            "lambda": item.blend_weight,
                            "mean_log_loss": item.mean_log_loss,
                        }
                        for item in lambda_validation.scores
                    ],
                },
                "models": {
                    "frequency": {
                        "training_races": frequency_model.training_races,
                        "training_fingerprint": (
                            frequency_model.training_fingerprint
                        ),
                        "model_fingerprint": (
                            frequency_model.model_fingerprint
                        ),
                    },
                    "program": {
                        "training_races": program_model.training_races,
                        "training_fingerprint": (
                            program_model.training_fingerprint
                        ),
                        "model_fingerprint": program_model.model_fingerprint,
                        "optimization": {
                            "converged": (
                                program_model.optimization.converged
                            ),
                            "iterations": (
                                program_model.optimization.iterations
                            ),
                            "initial_objective": (
                                program_model.optimization.initial_objective
                            ),
                            "final_objective": (
                                program_model.optimization.final_objective
                            ),
                            "gradient_infinity_norm": (
                                program_model.optimization.gradient_infinity_norm
                            ),
                        },
                    },
                },
                "probability_quality": fold_quality,
                "prediction_fingerprint": prediction_fingerprint(
                    fold_probability_rows
                ),
            }
        )

    portfolio_results = run_portfolio_backtest(
        portfolio_inputs,
        race_budget_yen=RACE_BUDGET_YEN,
        wager_unit_yen=WAGER_UNIT_YEN,
        minimum_predicted_return=MINIMUM_PREDICTED_RETURN,
        maximum_market_cost=MAXIMUM_MARKET_COST,
        bootstrap_resamples=bootstrap_resamples,
        bootstrap_seed=BOOTSTRAP_SEED,
    )
    probability_summary = probability_quality(all_probability_rows)
    gate_s = probability_signal_gate(fold_documents, probability_summary)
    portfolio_document = portfolio_results_to_dict(portfolio_results)
    portfolio_document["comparisons"] = risk_comparisons(portfolio_results)

    configuration = {
        "source_period": {
            "start": SOURCE_START.isoformat(),
            "end": SOURCE_END.isoformat(),
        },
        "l2_candidates": list(L2_CANDIDATES),
        "blend_candidates": list(BLEND_CANDIDATES),
        "race_budget_yen": RACE_BUDGET_YEN,
        "wager_unit_yen": WAGER_UNIT_YEN,
        "minimum_predicted_return": MINIMUM_PREDICTED_RETURN,
        "maximum_market_cost": MAXIMUM_MARKET_COST,
        "bootstrap_resamples": bootstrap_resamples,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "strategies": list(STRATEGY_NAMES),
    }
    resolved_commit = code_commit_sha or _current_commit()
    document = {
        "study_id": "turnmark_exacta_strategy_sandbox_v1",
        "actionable": ACTIONABLE,
        "strategy_status": STRATEGY_STATUS,
        "research_class": "retrospective_hypothesis_generation_sandbox",
        "refund_probability_mode": REFUND_PROBABILITY_MODE,
        "execution_date": date.today().isoformat(),
        "configuration": configuration,
        "provenance": {
            "protocol_path": str(PROTOCOL_PATH.relative_to(ROOT)),
            "protocol_sha256": protocol_sha,
            "configuration_sha256": stable_hash(configuration),
            "code_commit_sha": resolved_commit,
            "input_source_fingerprint": source_fingerprint,
            "prediction_fingerprint": prediction_fingerprint(
                all_probability_rows
            ),
            "execution_workers": workers,
            "validation_cache_reused": validation_cache_reused,
            "validation_cache_key": validation_cache_key,
        },
        "gates": {
            "gate_x": "PASS",
            "gate_s": gate_s,
            "gate_r": "DESCRIPTIVE_PARETO_ONLY",
            "gate_u": "NOT_AUTHORIZED",
            "gate_p": "NO_GO_HISTORICAL_CONFIRMATORY_USE",
            "gate_d": "NO_GO_NO_ADOPTABLE_SOURCE",
        },
        "folds": fold_documents,
        "probability_quality": probability_summary,
        "portfolio": portfolio_document,
        "warnings": [
            "Turnmark programとoddsのsnapshot時点は未確認です。",
            "本結果はretrospective hypothesis generationであり、"
            "実購入可能性、確認的性能、将来収益を示しません。",
            "outer結果を見た後に同じprotocol idの候補・閾値・規則を変更しません。",
            "公式翌日番組LZHは将来prospective候補としてHoldし、収集していません。",
        ],
    }
    return document


def _build_validation_cache(
    races: Sequence[NormalizedRace],
    *,
    workers: int,
) -> Mapping[Tuple[str, float], Dict[str, Any]]:
    tasks = tuple(
        (month.id, month.start, month.end, l2)
        for month in INNER_MONTHS
        for l2 in L2_CANDIDATES
    )
    if workers == 1:
        results = (
            _fit_validation_task_with_races(tuple(races), task)
            for task in tasks
        )
        return {
            (month_id, l2): value
            for month_id, l2, value in results
        }

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_validation_worker,
        initargs=(tuple(races),),
    ) as executor:
        results = executor.map(_fit_validation_task, tasks)
        return {
            (month_id, l2): value
            for month_id, l2, value in results
        }


def _initialize_validation_worker(
    races: Tuple[NormalizedRace, ...],
) -> None:
    global _VALIDATION_WORKER_RACES
    _VALIDATION_WORKER_RACES = races


def _fit_validation_task(
    task: Tuple[str, date, date, float],
) -> Tuple[str, float, Dict[str, Any]]:
    if not _VALIDATION_WORKER_RACES:
        raise RuntimeError("validation workerにrace dataがありません")
    return _fit_validation_task_with_races(_VALIDATION_WORKER_RACES, task)


def _fit_validation_task_with_races(
    races: Sequence[NormalizedRace],
    task: Tuple[str, date, date, float],
) -> Tuple[str, float, Dict[str, Any]]:
    month_id, month_start, month_end, l2 = task
    training = [
        race for race in races if race.identity.date < month_start
    ]
    validation = [
        race
        for race in races
        if month_start <= race.identity.date <= month_end
        and race.exacta_training_eligible
    ]
    try:
        model = ProgramPlackettLuceModel.fit(
            training,
            prediction_date=month_start,
            l2=l2,
        )
        observations = []
        losses = []
        for race in validation:
            prediction = model.predict(race).probabilities
            winner = race.outcome.winning_exacta
            if winner is None:
                raise DataContractError(
                    "clean validation raceに一意な2連単結果がありません"
                )
            losses.append(-math.log(prediction[winner]))
            observations.append(
                {
                    "probabilities": prediction,
                    "winner": winner,
                    "odds": usable_exacta_odds(race),
                }
            )
        value = {
            "status": "success",
            "mean_log_loss": (
                math.fsum(losses) / len(losses)
                if losses
                else None
            ),
            "sum_log_loss": math.fsum(losses),
            "races": len(losses),
            "model_fingerprint": model.model_fingerprint,
            "optimization": {
                "iterations": model.optimization.iterations,
                "gradient_infinity_norm": (
                    model.optimization.gradient_infinity_norm
                ),
            },
            "observations": observations,
        }
    except ModelConvergenceError as exc:
        value = {
            "status": "nonconvergence",
            "error": str(exc),
            "mean_log_loss": None,
            "sum_log_loss": None,
            "races": 0,
            "observations": [],
        }
    return month_id, l2, value


def load_validation_cache(
    path: Path,
    *,
    expected_key: str,
) -> Optional[Mapping[Tuple[str, float], Dict[str, Any]]]:
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(document, Mapping)
        or document.get("cache_schema") != 1
        or document.get("cache_key") != expected_key
        or not isinstance(document.get("values"), Mapping)
    ):
        return None
    result: Dict[Tuple[str, float], Dict[str, Any]] = {}
    for month in INNER_MONTHS:
        for l2 in L2_CANDIDATES:
            key = validation_cache_key(month.id, l2)
            value = document["values"].get(key)
            if not isinstance(value, Mapping):
                return None
            result[(month.id, l2)] = dict(value)
    return result


def write_validation_cache(
    path: Path,
    *,
    cache_key: str,
    validation_cache: Mapping[Tuple[str, float], Mapping[str, Any]],
) -> None:
    values = {
        validation_cache_key(month.id, l2): validation_cache[(month.id, l2)]
        for month in INNER_MONTHS
        for l2 in L2_CANDIDATES
    }
    document = {
        "cache_schema": 1,
        "cache_key": cache_key,
        "values": values,
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def validation_cache_key(month_id: str, l2: float) -> str:
    return f"{month_id}|{l2:.17g}"


def select_l2_candidate(
    validation_cache: Mapping[Tuple[str, float], Mapping[str, Any]],
    month_ids: Sequence[str],
) -> Tuple[float, List[Dict[str, Any]]]:
    if not month_ids:
        raise ValueError("L2選択にはinner validation月が必要です")
    scores = []
    selected: Optional[float] = None
    selected_score = math.inf
    for l2 in L2_CANDIDATES:
        parts = [validation_cache[(month_id, l2)] for month_id in month_ids]
        eligible = all(
            part.get("status") == "success"
            and int(part.get("races", 0)) > 0
            for part in parts
        )
        count = sum(int(part.get("races", 0)) for part in parts)
        mean = (
            math.fsum(float(part["sum_log_loss"]) for part in parts) / count
            if eligible and count
            else None
        )
        scores.append(
            {
                "l2": l2,
                "eligible": eligible,
                "validation_races": count,
                "mean_log_loss": mean,
                "months": [
                    {
                        "month": month_id,
                        "status": validation_cache[(month_id, l2)]["status"],
                        "races": validation_cache[(month_id, l2)]["races"],
                        "mean_log_loss": validation_cache[
                            (month_id, l2)
                        ]["mean_log_loss"],
                    }
                    for month_id in month_ids
                ],
            }
        )
        if not eligible or mean is None:
            continue
        if (
            mean < selected_score - TIE_TOLERANCE
            or (
                math.isclose(
                    mean,
                    selected_score,
                    rel_tol=0.0,
                    abs_tol=TIE_TOLERANCE,
                )
                and (selected is None or l2 > selected)
            )
        ):
            selected = l2
            selected_score = mean
    if selected is None:
        raise ModelConvergenceError(
            "全L2候補がinner validationで利用不能です"
        )
    return selected, scores


def _select_lambda_for_fold(
    validation_cache: Mapping[Tuple[str, float], Mapping[str, Any]],
    month_ids: Sequence[str],
    *,
    selected_l2: float,
):
    observations = []
    for month_id in month_ids:
        part = validation_cache[(month_id, selected_l2)]
        if part["status"] != "success":
            raise ModelConvergenceError(
                "選択L2のinner predictionが利用できません"
            )
        for item in part["observations"]:
            if item["odds"] is None:
                continue
            observations.append(
                ValidationRace(
                    model_probabilities=item["probabilities"],
                    odds=item["odds"],
                    winning_combination=item["winner"],
                )
            )
    return select_blend_lambda(observations, BLEND_CANDIDATES)


def probability_quality(
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    clean_rows = [row for row in rows if row.get("winner") is not None]
    market_rows = [row for row in clean_rows if row.get("market") is not None]
    result = {
        "clean_races": len(clean_rows),
        "market_complete_clean_races": len(market_rows),
    }
    for name in ("frequency", "program"):
        result[name] = _probability_metric(clean_rows, name)
    for name in ("market", "blend"):
        result[name] = _probability_metric(market_rows, name)
    if clean_rows:
        differences = [
            -math.log(row["program"][row["winner"]])
            + math.log(row["frequency"][row["winner"]])
            for row in clean_rows
        ]
        result["program_minus_frequency_log_loss"] = (
            math.fsum(differences) / len(differences)
        )
    else:
        result["program_minus_frequency_log_loss"] = None
    if market_rows:
        blend_differences = [
            -math.log(row["blend"][row["winner"]])
            + math.log(row["market"][row["winner"]])
            for row in market_rows
        ]
        result["blend_minus_market_log_loss"] = (
            math.fsum(blend_differences) / len(blend_differences)
        )
    else:
        result["blend_minus_market_log_loss"] = None
    return result


def probability_signal_gate(
    fold_documents: Sequence[Mapping[str, Any]],
    pooled: Mapping[str, Any],
) -> Dict[str, Any]:
    fold_differences = [
        fold["probability_quality"][
            "program_minus_frequency_log_loss"
        ]
        for fold in fold_documents
    ]
    improving_folds = sum(
        value is not None and float(value) < 0.0
        for value in fold_differences
    )
    pooled_difference = pooled["program_minus_frequency_log_loss"]
    passed = (
        improving_folds >= 3
        and pooled_difference is not None
        and float(pooled_difference) < 0.0
    )
    return {
        "status": (
            "PASS_RETROSPECTIVE_SIGNAL_CANDIDATE"
            if passed
            else "NO_GO_RETROSPECTIVE_SIGNAL"
        ),
        "improving_folds": improving_folds,
        "required_improving_folds": 3,
        "fold_differences": fold_differences,
        "pooled_program_minus_frequency_log_loss": pooled_difference,
        "confirmatory_or_live_claim": false_value(),
    }


def risk_comparisons(results: Mapping[str, Any]) -> Dict[str, Any]:
    pairs = (
        ("program", "program_single", "program_dutch"),
        ("blend", "blend_single", "blend_dutch"),
    )
    comparisons = {}
    for label, single_name, dutch_name in pairs:
        single = results[single_name]
        dutch = results[dutch_name]
        dutch_not_worse_return = (
            single.return_rate is not None
            and dutch.return_rate is not None
            and dutch.return_rate >= single.return_rate
        )
        dutch_not_worse_downside = (
            dutch.maximum_drawdown_yen <= single.maximum_drawdown_yen
            and dutch.maximum_losing_streak
            <= single.maximum_losing_streak
        )
        comparisons[label] = {
            "single": single_name,
            "dutch": dutch_name,
            "dutch_not_worse_return": dutch_not_worse_return,
            "dutch_not_worse_drawdown_and_streak": dutch_not_worse_downside,
            "observed_dutch_pareto_dominates": (
                dutch_not_worse_return and dutch_not_worse_downside
            ),
            "selection_authorized": False,
        }
    return comparisons


def assign_meeting_ids(
    races: Sequence[NormalizedRace],
) -> Mapping[Tuple[date, int], str]:
    by_day: Dict[date, List[NormalizedRace]] = {}
    for race in races:
        by_day.setdefault(race.identity.date, []).append(race)
    result: Dict[Tuple[date, int], str] = {}
    previous_day: Optional[date] = None
    previous_title: Optional[str] = None
    previous_day_number: Optional[int] = None
    current_id: Optional[str] = None
    block_index = 0
    for day in sorted(by_day):
        values = sorted(by_day[day], key=lambda item: item.identity.race_number)
        titles = {
            str(item.program.race_fields.get("title") or "") for item in values
        }
        day_numbers = {
            _optional_int(item.program.race_fields.get("day_number"))
            for item in values
        }
        if len(titles) != 1 or len(day_numbers) != 1 or None in day_numbers:
            raise DataContractError(
                f"開催節境界に使うtitle/day_numberが日内で一意ではありません: {day}"
            )
        title = next(iter(titles))
        day_number = next(iter(day_numbers))
        new_block = (
            previous_day is None
            or day_number == 1
            or title != previous_title
            or day != previous_day + timedelta(days=1)
            or day_number != previous_day_number + 1
        )
        if new_block:
            block_index += 1
            current_id = f"ashiya-{day.isoformat()}-{block_index:02d}"
        if current_id is None:
            raise AssertionError("開催節IDが生成されませんでした")
        for race in values:
            result[(day, race.identity.race_number)] = current_id
        previous_day = day
        previous_title = title
        previous_day_number = day_number
    return result


def usable_exacta_odds(
    race: NormalizedRace,
) -> Optional[Mapping[str, float]]:
    if tuple(race.odds.exacta) != EXACTA_COMBINATIONS:
        return None
    result = {}
    for combination in EXACTA_COMBINATIONS:
        value = race.odds.exacta.get(combination)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
        ):
            return None
        result[combination] = float(value)
    return result


def prediction_fingerprint(rows: Sequence[Mapping[str, Any]]) -> str:
    compact = [
        {
            "fold_id": row["fold_id"],
            "date": row["date"],
            "race_number": row["race_number"],
            "frequency": row["frequency"],
            "program": row["program"],
            "market": row["market"],
            "blend": row["blend"],
        }
        for row in rows
    ]
    return stable_hash(compact)


def input_source_fingerprint(races: Sequence[NormalizedRace]) -> str:
    rows = [
        {
            "date": race.identity.date.isoformat(),
            "race_number": race.identity.race_number,
            "source_sha256": race.source_sha256,
        }
        for race in races
    ]
    return stable_hash(rows)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def compact_document(document: Mapping[str, Any]) -> Dict[str, Any]:
    value = json.loads(
        json.dumps(document, ensure_ascii=False, allow_nan=False)
    )
    for strategy in STRATEGY_NAMES:
        value["portfolio"]["strategies"][strategy].pop("races", None)
    return value


def format_text(document: Mapping[str, Any]) -> str:
    lines = [
        "Turnmark 2連単strategy sandbox v1",
        "利用制限: retrospective hypothesis generation / non-actionable",
        (
            "Gate S: "
            f"{document['gates']['gate_s']['status']} "
            f"({document['gates']['gate_s']['improving_folds']}/4 folds)"
        ),
        "Gate R: DESCRIPTIVE_PARETO_ONLY",
        "",
        "Outer fold:",
        "fold                 L2      blend λ  program LL  frequency LL",
    ]
    for fold in document["folds"]:
        quality = fold["probability_quality"]
        lines.append(
            f"{fold['fold_id']:<20} "
            f"{fold['selection']['selected_l2']:>7g} "
            f"{fold['selection']['selected_blend_lambda']:>8.2f} "
            f"{quality['program']['log_loss']:>11.4f} "
            f"{quality['frequency']['log_loss']:>12.4f}"
        )
    lines.extend(
        [
            "",
            "Portfolio:",
            "strategy          betR tickets hitR return   net       maxDD    streak",
        ]
    )
    for strategy in STRATEGY_NAMES:
        metrics = document["portfolio"]["strategies"][strategy]["metrics"]
        return_rate = metrics["return_rate"]
        lines.append(
            f"{strategy:<17} "
            f"{metrics['bet_races']:>4} "
            f"{metrics['tickets']:>7} "
            f"{metrics['hit_races']:>4} "
            f"{('-' if return_rate is None else f'{return_rate:.4f}'):>7} "
            f"{metrics['net_profit_yen']:>+9} "
            f"{metrics['maximum_drawdown_yen']:>8} "
            f"{metrics['maximum_losing_streak']:>7}"
        )
    lines.extend(
        [
            "",
            "注意: Turnmarkのprogram/odds時点は未確認です。",
            "実購入可能性、確認的性能、将来収益を示す結果ではありません。",
        ]
    )
    return "\n".join(lines)


def _probability_metric(
    rows: Sequence[Mapping[str, Any]],
    name: str,
) -> Dict[str, Any]:
    if not rows:
        return {"races": 0, "log_loss": None, "brier_score": None}
    losses = []
    briers = []
    for row in rows:
        probabilities = row[name]
        winner = row["winner"]
        losses.append(-math.log(probabilities[winner]))
        briers.append(
            math.fsum(
                (
                    probabilities[combination]
                    - (1.0 if combination == winner else 0.0)
                )
                ** 2
                for combination in EXACTA_COMBINATIONS
            )
        )
    return {
        "races": len(rows),
        "log_loss": math.fsum(losses) / len(losses),
        "brier_score": math.fsum(briers) / len(briers),
    }


def _ensure_source_period(races: Sequence[NormalizedRace]) -> None:
    if not races:
        raise DataContractError("芦屋レースがありません")
    if races[0].identity.date < SOURCE_START or races[-1].identity.date > SOURCE_END:
        raise DataContractError("sandbox source period外のレースが混在しています")
    seen = set()
    for race in races:
        key = (
            race.identity.date,
            race.identity.stadium_number,
            race.identity.race_number,
        )
        if key in seen:
            raise DataContractError("sandbox sourceレースが重複しています")
        seen.add(key)


def _optional_int(value: Any) -> Optional[int]:
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


def _current_commit() -> Optional[str]:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def false_value() -> bool:
    """JSON出力で意図が明瞭なfalseを返す。"""

    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Turnmark cache directory",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="既存cacheだけを使う",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="JSONからrace明細を省いたtrial ledgerを出力する",
    )
    parser.add_argument(
        "--bootstrap-resamples",
        type=int,
        default=BOOTSTRAP_RESAMPLES,
        help="正式protocolは20000。テスト実行時だけ小さくできる",
    )
    parser.add_argument(
        "--code-commit-sha",
        default=None,
        help="結果を生成したimplementation commit",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"独立なinner fitの並列数（既定: {DEFAULT_WORKERS}）",
    )
    return parser


def main(arguments: Optional[Iterable[str]] = None) -> int:
    parsed = build_parser().parse_args(arguments)
    document = run_study(
        parsed.cache_dir,
        offline=parsed.offline,
        bootstrap_resamples=parsed.bootstrap_resamples,
        code_commit_sha=parsed.code_commit_sha,
        workers=parsed.workers,
    )
    if parsed.format == "json":
        value = compact_document(document) if parsed.compact else document
        print(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
        )
    else:
        print(format_text(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
