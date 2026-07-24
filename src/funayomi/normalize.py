"""Turnmark の日次 JSON から芦屋レースだけを正規化する。"""

import math
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .combinations import TRIFECTA_COMBINATIONS, combination_key, parse_combination
from .domain import (
    NormalizedRace,
    OddsSnapshot,
    PreviewSnapshot,
    ProgramSnapshot,
    RaceIdentity,
    RaceOutcome,
)
from .errors import DataContractError


SCHEMA_VERSION = 2
ASHIYA_STADIUM_NUMBER = 21

PROGRAM_RACE_FIELDS: Tuple[str, ...] = (
    "grade_number",
    "title",
    "subtitle",
    "distance",
    "day_number",
)
PROGRAM_RACER_FIELDS: Tuple[str, ...] = (
    "entry_number",
    "name",
    "number",
    "rank_number",
    "branch_number",
    "birthplace_number",
    "age",
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
    "motor_number",
    "motor_top_2_percent",
    "motor_top_3_percent",
    "boat_number",
    "boat_top_2_percent",
    "boat_top_3_percent",
)
PREVIEW_FIELDS: Tuple[str, ...] = (
    "wind_speed",
    "wind_direction_number",
    "wave_height",
    "weather_number",
    "air_temperature",
    "water_temperature",
)
PREVIEW_RACER_FIELDS: Tuple[str, ...] = (
    "entry_number",
    "course_number",
    "start_timing",
    "weight",
    "weight_adjustment",
    "exhibition_time",
    "tilt_adjustment",
)
RESULT_RACER_FIELDS: Tuple[str, ...] = (
    "entry_number",
    "course_number",
    "start_timing",
    "place_number",
    "place_number_source",
    "number",
    "name",
)
OBSERVED_EXCEPTION_CODES = frozenset(("妨", "エ", "転", "落", "沈", "不", "F", "L", "欠"))


def normalize_payload(
    payload: Mapping[str, Any],
    expected_date: date,
    *,
    source_sha256: Optional[str] = None,
) -> List[NormalizedRace]:
    """日次レスポンスから芦屋だけを抽出する。"""

    programs_value = payload.get("programs")
    if not isinstance(programs_value, Mapping):
        raise DataContractError("Turnmark JSON に programs object がありません")
    stadiums_value = programs_value.get("stadiums")
    if not isinstance(stadiums_value, Mapping):
        raise DataContractError("Turnmark JSON に programs.stadiums object がありません")
    stadium_value = stadiums_value.get(str(ASHIYA_STADIUM_NUMBER))
    if stadium_value is None:
        return []
    if not isinstance(stadium_value, Mapping):
        raise DataContractError("芦屋 stadium record がobjectではありません")
    races_value = stadium_value.get("races")
    if not isinstance(races_value, Mapping):
        raise DataContractError("芦屋 stadium record に races object がありません")
    races = races_value
    normalized: List[NormalizedRace] = []
    for race_key, raw_race in sorted(races.items(), key=_numeric_item_key):
        parsed_race_key = _as_int(race_key)
        if (
            not isinstance(race_key, str)
            or parsed_race_key is None
            or str(parsed_race_key) != race_key
            or parsed_race_key not in range(1, 13)
        ):
            raise DataContractError(
                f"レース辞書キーは正規形の文字列1〜12である必要があります: {race_key!r}"
            )
        race_mapping = _mapping(raw_race)
        normalized.append(
            normalize_race(
                race_mapping,
                expected_date,
                expected_race_number=parsed_race_key,
                source_sha256=source_sha256,
            )
        )
    return normalized


def normalize_race(
    raw: Mapping[str, Any],
    expected_date: date,
    *,
    expected_race_number: Optional[int] = None,
    source_sha256: Optional[str] = None,
) -> NormalizedRace:
    issues: List[str] = []
    raw_date = raw.get("date")
    if raw_date != expected_date.isoformat():
        raise DataContractError(
            f"日付が要求日と一致しません: {raw_date!r} != {expected_date.isoformat()!r}"
        )
    stadium_number = _as_int(raw.get("stadium_number"))
    if stadium_number != ASHIYA_STADIUM_NUMBER:
        raise DataContractError(f"芦屋以外のレースを正規化しようとしました: {stadium_number}")
    race_number = _as_int(raw.get("race_number"))
    if expected_race_number is not None and race_number != expected_race_number:
        raise DataContractError(
            "レース番号が辞書キーと一致しません: "
            f"{race_number!r} != {expected_race_number!r}"
        )
    if race_number is None:
        raise DataContractError("race_number がありません")
    if race_number not in range(1, 13):
        raise DataContractError(f"race_number は1〜12である必要があります: {race_number}")

    program_racers, program_issues = _normalize_numbered_records(
        raw.get("racers"), PROGRAM_RACER_FIELDS
    )
    issues.extend(f"program_{value}" for value in program_issues)
    if tuple(sorted(program_racers)) != (1, 2, 3, 4, 5, 6):
        issues.append("program_field_not_six_entries")

    preview, preview_issues = _normalize_preview(raw.get("preview"))
    issues.extend(preview_issues)
    odds, odds_issues = _normalize_odds(raw.get("odds"))
    issues.extend(odds_issues)
    outcome, outcome_issues = _normalize_outcome(raw.get("result"), program_racers)
    issues.extend(outcome_issues)

    return NormalizedRace(
        identity=RaceIdentity(
            date=expected_date,
            stadium_number=stadium_number,
            race_number=race_number,
            closed_at=_as_optional_str(raw.get("closed_at")),
        ),
        program=ProgramSnapshot(
            race_fields=_select(raw, PROGRAM_RACE_FIELDS),
            racers=program_racers,
        ),
        preview=preview,
        odds=odds,
        outcome=outcome,
        issues=tuple(sorted(set(issues))),
        source_sha256=source_sha256,
    )


def _normalize_preview(
    value: Any,
) -> Tuple[Optional[PreviewSnapshot], List[str]]:
    if not isinstance(value, Mapping) or not value:
        return None, ["preview_missing"]
    racers, racer_issues = _normalize_numbered_records(
        value.get("racers"), PREVIEW_RACER_FIELDS
    )
    issues = [f"preview_{item}" for item in racer_issues]
    if tuple(sorted(racers)) != (1, 2, 3, 4, 5, 6):
        issues.append("preview_field_not_six_entries")
    return PreviewSnapshot(fields=_select(value, PREVIEW_FIELDS), racers=racers), issues


def _normalize_odds(value: Any) -> Tuple[OddsSnapshot, List[str]]:
    issues: List[str] = []
    odds_mapping = _mapping(value)
    trifecta = _mapping(odds_mapping.get("trifecta"))
    normalized: Dict[str, Optional[float]] = {}
    invalid_count = 0
    unavailable_zero_count = 0
    for key in TRIFECTA_COMBINATIONS:
        first, second, third = parse_combination(key)
        raw_value = (
            _mapping(_mapping(trifecta.get(str(first))).get(str(second))).get(str(third))
        )
        odd = _positive_float(raw_value)
        if (
            isinstance(raw_value, (int, float))
            and not isinstance(raw_value, bool)
            and raw_value == 0
        ):
            unavailable_zero_count += 1
        elif raw_value is not None and odd is None:
            invalid_count += 1
        normalized[key] = odd
    missing_count = sum(value is None for value in normalized.values())
    if not trifecta:
        issues.append("trifecta_odds_missing")
    if missing_count:
        issues.append(f"trifecta_odds_unavailable_combinations:{missing_count}")
    if unavailable_zero_count:
        issues.append(
            f"trifecta_odds_unavailable_zero:{unavailable_zero_count}"
        )
    if invalid_count:
        issues.append(f"trifecta_odds_invalid_combinations:{invalid_count}")
    return OddsSnapshot(trifecta=normalized), issues


def _normalize_outcome(
    value: Any,
    program_racers: Mapping[int, Mapping[str, Any]],
) -> Tuple[RaceOutcome, List[str]]:
    if not isinstance(value, Mapping) or not value:
        return (
            RaceOutcome(
                status="missing",
                winning_trifectas=(),
                trifecta_payouts={},
                racers={},
            ),
            ["result_missing"],
        )
    racers, racer_issues = _normalize_numbered_records(
        value.get("racers"), RESULT_RACER_FIELDS
    )
    issues = [f"result_{item}" for item in racer_issues]
    raw_payouts_container = value.get("payouts")
    payouts_container = _mapping(raw_payouts_container)
    raw_payouts = payouts_container.get("trifecta")
    payout_array_valid = isinstance(raw_payouts, list)
    if not isinstance(raw_payouts_container, Mapping):
        issues.append("result_payouts_missing_or_invalid")
    if "trifecta" not in payouts_container:
        issues.append("result_trifecta_payout_missing")
    elif not payout_array_valid:
        issues.append("result_trifecta_payout_not_array")
    payout_items: Sequence[Any] = raw_payouts if payout_array_valid else ()
    payouts: Dict[str, int] = {}
    invalid_payout_items = 0
    for item in payout_items:
        if not isinstance(item, Mapping):
            issues.append("result_trifecta_payout_not_object")
            invalid_payout_items += 1
            continue
        combination = item.get("combination")
        amount = _as_int(item.get("amount"))
        try:
            if not isinstance(combination, str):
                raise ValueError
            parse_combination(combination)
        except ValueError:
            issues.append(f"result_invalid_trifecta:{combination!r}")
            invalid_payout_items += 1
            continue
        if amount is None or amount <= 0:
            issues.append(f"result_invalid_payout:{combination}")
            invalid_payout_items += 1
            continue
        if combination in payouts:
            issues.append(f"result_duplicate_trifecta:{combination}")
            invalid_payout_items += 1
            continue
        payouts[combination] = amount

    places = [_as_int(racer.get("place_number")) for racer in racers.values()]
    standard_places = (
        tuple(sorted(racers)) == (1, 2, 3, 4, 5, 6)
        and sorted(place for place in places if place is not None) == [1, 2, 3, 4, 5, 6]
    )
    derived_entries = []
    for target_place in (1, 2, 3):
        matching_entries = [
            entry
            for entry, racer in racers.items()
            if _as_int(racer.get("place_number")) == target_place
        ]
        if len(matching_entries) != 1:
            derived_entries = []
            break
        derived_entries.append(matching_entries[0])
    derived_winner = combination_key(derived_entries) if derived_entries else None
    payout_matches_places = (
        derived_winner is not None and tuple(payouts) == (derived_winner,)
    )
    standard = (
        tuple(sorted(program_racers)) == (1, 2, 3, 4, 5, 6)
        and standard_places
        and len(payouts) == 1
        and payout_matches_places
    )
    if not standard_places:
        issues.append("result_non_standard_places")
    if len(payouts) != 1:
        issues.append(f"result_trifecta_payout_count:{len(payouts)}")
    if len(payouts) == 1 and not payout_matches_places:
        issues.append("result_trifecta_payout_order_mismatch")
    explicit_no_trifecta = (
        payout_array_valid
        and len(payout_items) == 0
        and derived_winner is None
        and tuple(sorted(racers)) == (1, 2, 3, 4, 5, 6)
        and any(
            racer.get("place_number_source") in OBSERVED_EXCEPTION_CODES
            for racer in racers.values()
        )
    )
    payout_data_valid = (
        payout_array_valid
        and invalid_payout_items == 0
        and len(payouts) == len(payout_items)
    )
    if standard and payout_data_valid:
        status = "standard"
    elif explicit_no_trifecta:
        status = "trifecta_not_established"
    elif not payout_data_valid:
        status = "inconsistent"
    elif len(payouts) > 1:
        status = "multiple_trifecta_payouts"
    elif not payout_matches_places:
        status = "inconsistent"
    else:
        status = "exception_settled"
    return (
        RaceOutcome(
            status=status,
            winning_trifectas=tuple(sorted(payouts)),
            trifecta_payouts=payouts,
            racers=racers,
        ),
        issues,
    )


def _normalize_numbered_records(
    value: Any, fields: Iterable[str]
) -> Tuple[Dict[int, Dict[str, Any]], List[str]]:
    records = _mapping(value)
    normalized: Dict[int, Dict[str, Any]] = {}
    issues: List[str] = []
    for raw_key, raw_record in records.items():
        key = _as_int(raw_key)
        if key is None or key not in range(1, 7):
            issues.append(f"invalid_entry_key:{raw_key!r}")
            continue
        record = _mapping(raw_record)
        entry_number = _as_int(record.get("entry_number"))
        if entry_number != key:
            issues.append(f"entry_number_mismatch:{raw_key!r}")
        selected = _select(record, fields)
        selected["entry_number"] = key
        normalized[key] = selected
    return normalized, issues


def _select(value: Mapping[str, Any], fields: Iterable[str]) -> Dict[str, Any]:
    return {field: value.get(field) for field in fields}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> Optional[int]:
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


def _positive_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        return None
    return result


def _as_optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _numeric_item_key(item: Tuple[Any, Any]) -> Tuple[int, str]:
    parsed = _as_int(item[0])
    return (parsed if parsed is not None else 10_000, str(item[0]))
