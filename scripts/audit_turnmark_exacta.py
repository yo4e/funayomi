#!/usr/bin/env python3
"""固定Turnmark原本から芦屋2連単のGate A監査を再現する。

このスクリプトはネットワークへ接続せず、``raw/turnmark`` とsidecar
metadataだけを読み取る。賭式schema、予測モデル、バックテストは実装しない。
"""

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from itertools import permutations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


AUDIT_NAME = "turnmark_exacta_gate_a_v1"
DEFAULT_START = date(2026, 1, 1)
DEFAULT_END = date(2026, 7, 23)
DEFAULT_SOURCE_COMMIT = "34a3b0a15c0e221a71464bcd86b572c4b28f90a7"
ASHIYA_STADIUM_NUMBER = 21
ENTRY_NUMBERS = tuple(range(1, 7))
EXACTA_COMBINATIONS = tuple(
    f"{first}-{second}"
    for first, second in permutations(ENTRY_NUMBERS, 2)
)
EXACTA_COMBINATION_SET = frozenset(EXACTA_COMBINATIONS)
KNOWN_EXCEPTION_CODES = frozenset(
    ("F", "L", "欠", "妨", "エ", "転", "落", "沈", "不")
)
REFUND_CODES = frozenset(("F", "L"))
DIRECT_REFUND_KEYWORDS = frozenset(
    (
        "refund",
        "refunds",
        "refunded",
        "refund_amount",
        "return_amount",
    )
)


class DuplicateTrackingDict(dict):
    """JSON object内の重複キーを失わず記録するdict。"""

    def __init__(self, pairs: Sequence[Tuple[str, Any]]):
        super().__init__()
        self.duplicate_keys: List[str] = []
        for key, value in pairs:
            if key in self:
                self.duplicate_keys.append(key)
            self[key] = value


def _days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _parse_exacta_combination(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    parts = value.split("-")
    if len(parts) != 2:
        return None
    try:
        first, second = (int(part) for part in parts)
    except ValueError:
        return None
    normalized = f"{first}-{second}"
    if normalized != value or normalized not in EXACTA_COMBINATION_SET:
        return None
    return normalized


def _flatten_exacta(
    value: Any,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Turnmarkの二重objectをcanonical keyへ平坦化する。"""

    flattened: Dict[str, Any] = {}
    duplicate_paths: List[str] = []
    malformed_paths: List[str] = []
    if not isinstance(value, Mapping):
        return flattened, duplicate_paths, ["odds.exacta"]

    if isinstance(value, DuplicateTrackingDict):
        duplicate_paths.extend(
            f"odds.exacta.{key}" for key in value.duplicate_keys
        )
    for first, second_level in value.items():
        if not isinstance(second_level, Mapping):
            malformed_paths.append(f"odds.exacta.{first}")
            continue
        if isinstance(second_level, DuplicateTrackingDict):
            duplicate_paths.extend(
                f"odds.exacta.{first}.{second}"
                for second in second_level.duplicate_keys
            )
        for second, odds in second_level.items():
            flattened[f"{first}-{second}"] = odds
    return flattened, duplicate_paths, malformed_paths


def _entry_map(value: Any) -> Dict[int, Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    mapped: Dict[int, Mapping[str, Any]] = {}
    for raw_entry, racer in value.items():
        if not isinstance(racer, Mapping):
            continue
        try:
            entry = int(raw_entry)
        except (TypeError, ValueError):
            continue
        if str(entry) != str(raw_entry):
            continue
        mapped[entry] = racer
    return mapped


def _top_two(
    racers: Mapping[int, Mapping[str, Any]],
) -> Tuple[Optional[str], bool]:
    places: Dict[int, List[int]] = defaultdict(list)
    for entry, racer in racers.items():
        place = racer.get("place_number")
        if isinstance(place, int) and not isinstance(place, bool):
            places[place].append(entry)
    dead_heat = len(places[1]) > 1 or len(places[2]) > 1
    if len(places[1]) != 1 or len(places[2]) != 1:
        return None, dead_heat
    return f"{places[1][0]}-{places[2][0]}", dead_heat


def _full_order_is_clean(
    racers: Mapping[int, Mapping[str, Any]],
) -> bool:
    if set(racers) != set(ENTRY_NUMBERS):
        return False
    places = [
        racer.get("place_number")
        for racer in racers.values()
    ]
    return (
        all(
            isinstance(place, int) and not isinstance(place, bool)
            for place in places
        )
        and sorted(places) == list(ENTRY_NUMBERS)
    )


def _valid_payout(item: Any) -> Optional[Tuple[str, float]]:
    if not isinstance(item, Mapping):
        return None
    combination = _parse_exacta_combination(item.get("combination"))
    amount = item.get("amount")
    if (
        combination is None
        or not _is_number(amount)
        or float(amount) <= 0
    ):
        return None
    return combination, float(amount)


def _find_direct_refund_paths(
    value: Any,
    prefix: str = "",
) -> List[str]:
    found: List[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in DIRECT_REFUND_KEYWORDS:
                found.append(path)
            found.extend(_find_direct_refund_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(
                _find_direct_refund_paths(nested, f"{prefix}[{index}]")
            )
    return found


def _manifest_fingerprint(entries: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        list(entries),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _new_month_counter() -> Counter:
    return Counter(
        races=0,
        probability_training_eligible=0,
        economic_predecision_eligible=0,
        economic_settlement_eligible=0,
    )


def _summarize_meeting_blocks(
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """title・day_number・連続日から観測範囲内の開催節を復元する。"""

    ordered = sorted(records, key=lambda item: str(item["date"]))
    blocks: List[List[Mapping[str, Any]]] = []
    ambiguous_boundaries: List[Dict[str, Any]] = []
    for record in ordered:
        if not blocks:
            blocks.append([record])
            continue
        previous = blocks[-1][-1]
        previous_date = date.fromisoformat(str(previous["date"]))
        current_date = date.fromisoformat(str(record["date"]))
        continues = (
            record["title"] == previous["title"]
            and int(record["day_number"])
            == int(previous["day_number"]) + 1
            and (current_date - previous_date).days == 1
        )
        if continues:
            blocks[-1].append(record)
            continue
        if int(record["day_number"]) != 1:
            ambiguous_boundaries.append(
                {
                    "previous_date": previous["date"],
                    "date": record["date"],
                    "title": record["title"],
                    "day_number": record["day_number"],
                }
            )
        blocks.append([record])

    block_documents: List[Dict[str, Any]] = []
    title_counts: Counter = Counter()
    for index, block in enumerate(blocks, start=1):
        first = block[0]
        last = block[-1]
        left_censored = int(first["day_number"]) != 1
        right_censored = str(last["day_number_source"]) != "最終日"
        title_counts[str(first["title"])] += 1
        block_documents.append(
            {
                "sequence": index,
                "title": first["title"],
                "first_observed_date": first["date"],
                "last_observed_date": last["date"],
                "observed_day_numbers": [
                    item["day_number"] for item in block
                ],
                "observed_days": len(block),
                "left_censored": left_censored,
                "right_censored": right_censored,
                "complete_in_scope": not left_censored and not right_censored,
            }
        )

    repeated_titles = {
        title: count
        for title, count in sorted(title_counts.items())
        if count > 1
    }
    reconstructable = (
        bool(ordered)
        and not ambiguous_boundaries
    )
    return {
        "reconstructable": reconstructable,
        "status": (
            "possible_with_edge_censoring"
            if reconstructable
            else "ambiguous"
        ),
        "basis": (
            "daily consensus of title/day_number/day_number_source plus "
            "calendar continuity; title alone is not a unique meeting id"
        ),
        "observed_race_days": len(ordered),
        "inferred_blocks": len(block_documents),
        "complete_blocks": sum(
            bool(item["complete_in_scope"]) for item in block_documents
        ),
        "left_censored_blocks": sum(
            bool(item["left_censored"]) for item in block_documents
        ),
        "right_censored_blocks": sum(
            bool(item["right_censored"]) for item in block_documents
        ),
        "ambiguous_boundaries": ambiguous_boundaries,
        "repeated_titles_across_blocks": repeated_titles,
        "blocks": block_documents,
        "semantic_limit": (
            "Turnmark does not expose a provider-assigned meeting identifier"
        ),
    }


def run_audit(
    cache_dir: Path,
    *,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
    source_commit: str = DEFAULT_SOURCE_COMMIT,
) -> Dict[str, Any]:
    """指定期間の固定原本を監査し、機械可読な集計を返す。"""

    if end < start:
        raise ValueError("endはstart以降である必要があります")

    cache_dir = Path(cache_dir)
    counts: Counter = Counter()
    months: Dict[str, Counter] = defaultdict(_new_month_counter)
    exception_code_counts: Counter = Counter()
    fl_boat_count_distribution: Counter = Counter()
    fetched_at_values: List[str] = []
    manifest: List[Dict[str, Any]] = []
    direct_refund_paths = set()
    missing_raw_days: List[str] = []
    missing_metadata_days: List[str] = []
    sha_mismatch_days: List[str] = []
    invalid_json_days: List[str] = []
    source_metadata_anomalies: List[Dict[str, str]] = []
    key_anomaly_examples: List[Dict[str, Any]] = []
    invalid_value_examples: List[Dict[str, Any]] = []
    unexplained_zero_combinations: List[Dict[str, Any]] = []
    absent_market_anomalies: List[Dict[str, Any]] = []
    payout_anomaly_examples: List[Dict[str, Any]] = []
    winner_mismatch_examples: List[Dict[str, Any]] = []
    probability_exclusion_examples: List[Dict[str, Any]] = []
    exacta_clean_not_strict_examples: List[Dict[str, Any]] = []
    meeting_day_records: List[Dict[str, Any]] = []
    meeting_day_inconsistencies: List[Dict[str, Any]] = []

    expected_day_count = (end - start).days + 1
    for day in _days(start, end):
        raw_path = (
            cache_dir
            / "raw"
            / "turnmark"
            / str(day.year)
            / f"{day:%Y%m%d}.json"
        )
        metadata_path = raw_path.with_suffix(".metadata.json")
        if not raw_path.is_file():
            missing_raw_days.append(day.isoformat())
            continue
        payload = raw_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()

        if not metadata_path.is_file():
            missing_metadata_days.append(day.isoformat())
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            missing_metadata_days.append(day.isoformat())
            continue
        if not isinstance(metadata, Mapping):
            missing_metadata_days.append(day.isoformat())
            continue
        if metadata.get("sha256") != digest:
            sha_mismatch_days.append(day.isoformat())
            continue

        expected_url = (
            f"https://turnmark.github.io/api/v1/{day.year}/{day:%Y%m%d}.json"
        )
        if (
            metadata.get("provider") != "turnmark"
            or metadata.get("source_url") != expected_url
        ):
            source_metadata_anomalies.append(
                {
                    "date": day.isoformat(),
                    "provider": str(metadata.get("provider")),
                    "source_url": str(metadata.get("source_url")),
                }
            )
        if isinstance(metadata.get("fetched_at"), str):
            fetched_at_values.append(str(metadata["fetched_at"]))
        manifest.append(
            {
                "date": day.isoformat(),
                "sha256": digest,
                "size_bytes": len(payload),
            }
        )

        try:
            document = json.loads(
                payload,
                object_pairs_hook=DuplicateTrackingDict,
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            invalid_json_days.append(day.isoformat())
            continue
        try:
            stadiums = document["programs"]["stadiums"]
        except (KeyError, TypeError):
            counts["daily_structure_errors"] += 1
            continue
        stadium = stadiums.get(str(ASHIYA_STADIUM_NUMBER))
        if stadium is None:
            continue
        counts["ashiya_days"] += 1
        races = stadium.get("races") if isinstance(stadium, Mapping) else None
        if not isinstance(races, Mapping):
            counts["daily_structure_errors"] += 1
            continue

        meeting_values = {
            (
                race.get("title"),
                race.get("day_number"),
                race.get("day_number_source"),
            )
            for race in races.values()
            if isinstance(race, Mapping)
        }
        if (
            len(meeting_values) == 1
            and len(meeting_values) == len(
                {
                    value
                    for value in meeting_values
                    if isinstance(value[0], str)
                    and isinstance(value[1], int)
                    and not isinstance(value[1], bool)
                    and value[1] > 0
                    and isinstance(value[2], str)
                }
            )
        ):
            title, day_number, day_number_source = next(
                iter(meeting_values)
            )
            meeting_day_records.append(
                {
                    "date": day.isoformat(),
                    "title": title,
                    "day_number": day_number,
                    "day_number_source": day_number_source,
                }
            )
        else:
            meeting_day_inconsistencies.append(
                {
                    "date": day.isoformat(),
                    "values": [
                        [repr(value) for value in item]
                        for item in sorted(
                            meeting_values,
                            key=lambda item: repr(item),
                        )
                    ],
                }
            )

        for raw_race_number, race in races.items():
            counts["races"] += 1
            month = day.strftime("%Y-%m")
            month_counts = months[month]
            month_counts["races"] += 1
            identity = f"{day.isoformat()} {raw_race_number}R"
            if not isinstance(race, Mapping):
                counts["race_structure_errors"] += 1
                continue
            if (
                race.get("date") != day.isoformat()
                or race.get("stadium_number") != ASHIYA_STADIUM_NUMBER
            ):
                counts["identity_errors"] += 1
            try:
                if int(raw_race_number) != race.get("race_number"):
                    counts["identity_errors"] += 1
            except (TypeError, ValueError):
                counts["identity_errors"] += 1

            odds_section = race.get("odds")
            exacta_raw = (
                odds_section.get("exacta")
                if isinstance(odds_section, Mapping)
                else None
            )
            flattened, duplicate_paths, malformed_paths = _flatten_exacta(
                exacta_raw
            )
            keys = set(flattened)
            missing_keys = sorted(EXACTA_COMBINATION_SET - keys)
            extra_keys = sorted(keys - EXACTA_COMBINATION_SET)
            counts["missing_canonical_keys"] += len(missing_keys)
            counts["extra_keys"] += len(extra_keys)
            counts["duplicate_keys"] += len(duplicate_paths)
            counts["malformed_odds_paths"] += len(malformed_paths)
            if (
                not missing_keys
                and not extra_keys
                and not duplicate_paths
                and not malformed_paths
            ):
                counts["canonical_30_key_races"] += 1
            else:
                key_anomaly_examples.append(
                    {
                        "race": identity,
                        "missing": missing_keys,
                        "extra": extra_keys,
                        "duplicate_paths": duplicate_paths,
                        "malformed_paths": malformed_paths,
                    }
                )

            positive_keys = set()
            zero_keys = set()
            for combination in EXACTA_COMBINATIONS:
                if combination not in flattened:
                    continue
                value = flattened[combination]
                if value is None:
                    counts["null_odds"] += 1
                    category = "null"
                elif isinstance(value, bool) or not isinstance(
                    value, (int, float)
                ):
                    counts["invalid_type_odds"] += 1
                    category = "invalid_type"
                elif not math.isfinite(value):
                    counts["nonfinite_odds"] += 1
                    category = "nonfinite"
                elif value < 0:
                    counts["negative_odds"] += 1
                    category = "negative"
                elif value == 0:
                    counts["zero_odds"] += 1
                    zero_keys.add(combination)
                    category = "zero"
                else:
                    counts["positive_odds"] += 1
                    positive_keys.add(combination)
                    category = "positive"
                if category not in ("positive", "zero"):
                    invalid_value_examples.append(
                        {
                            "race": identity,
                            "combination": combination,
                            "category": category,
                            "value": repr(value),
                        }
                    )

            program = _entry_map(race.get("racers"))
            result = race.get("result")
            result_racers = _entry_map(
                result.get("racers") if isinstance(result, Mapping) else None
            )
            sources = {
                entry: racer.get("place_number_source")
                for entry, racer in result_racers.items()
            }
            exception_entries = {
                entry
                for entry, source in sources.items()
                if source in KNOWN_EXCEPTION_CODES
            }
            fl_entries = {
                entry
                for entry, source in sources.items()
                if source in REFUND_CODES
            }
            absent_entries = {
                entry for entry, source in sources.items() if source == "欠"
            }
            for source in sources.values():
                if source in KNOWN_EXCEPTION_CODES:
                    exception_code_counts[str(source)] += 1
            if exception_entries:
                counts["exception_races"] += 1
            if fl_entries:
                counts["fl_races"] += 1
                fl_boat_count_distribution[str(len(fl_entries))] += 1
                derived_refunds = {
                    combination
                    for combination in EXACTA_COMBINATIONS
                    if any(
                        int(part) in fl_entries
                        for part in combination.split("-")
                    )
                }
                counts["derived_refund_combinations"] += len(derived_refunds)
            if absent_entries:
                counts["absent_boat_races"] += 1
                counts["absent_boats"] += len(absent_entries)
                expected_unavailable = {
                    combination
                    for combination in EXACTA_COMBINATIONS
                    if any(
                        int(part) in absent_entries
                        for part in combination.split("-")
                    )
                }
                counts[
                    "zero_odds_explained_by_absent_boats"
                ] += len(zero_keys & expected_unavailable)
                counts[
                    "unexpected_positive_odds_with_absent_boats"
                ] += len(positive_keys & expected_unavailable)
                if zero_keys != expected_unavailable:
                    absent_market_anomalies.append(
                        {
                            "race": identity,
                            "absent_entries": sorted(absent_entries),
                            "expected_zero": sorted(expected_unavailable),
                            "actual_zero": sorted(zero_keys),
                        }
                    )
            unexplained_zeros = sorted(
                zero_keys
                - {
                    combination
                    for combination in EXACTA_COMBINATIONS
                    if any(
                        int(part) in absent_entries
                        for part in combination.split("-")
                    )
                }
            )
            if unexplained_zeros:
                counts["unattributed_zero_odds"] += len(unexplained_zeros)
                counts["unattributed_zero_odds_races"] += 1
                unexplained_zero_combinations.append(
                    {
                        "race": identity,
                        "combinations": unexplained_zeros,
                    }
                )

            direct_refund_paths.update(
                _find_direct_refund_paths(
                    {
                        "odds": odds_section,
                        "result": result,
                    }
                )
            )

            payouts_raw = (
                result.get("payouts", {}).get("exacta")
                if isinstance(result, Mapping)
                and isinstance(result.get("payouts"), Mapping)
                else None
            )
            if not isinstance(payouts_raw, list):
                counts["invalid_payout_array_races"] += 1
                payouts: List[Any] = []
            else:
                payouts = payouts_raw
            if len(payouts) == 0:
                counts["no_payout_races"] += 1
            elif len(payouts) == 1:
                counts["single_payout_races"] += 1
            else:
                counts["multiple_payout_races"] += 1

            parsed_payouts = [_valid_payout(item) for item in payouts]
            invalid_payout_items = sum(
                parsed is None for parsed in parsed_payouts
            )
            counts["invalid_payout_items"] += invalid_payout_items
            top_two, top_two_dead_heat = _top_two(result_racers)
            if top_two_dead_heat:
                counts["top_two_dead_heat_races"] += 1
            if top_two is None:
                counts["top_two_not_unique_races"] += 1
            if (
                len(parsed_payouts) == 1
                and parsed_payouts[0] is not None
                and top_two is not None
                and parsed_payouts[0][0] != top_two
            ):
                counts["payout_result_mismatch_races"] += 1

            valid_single_payout = (
                len(parsed_payouts) == 1
                and parsed_payouts[0] is not None
            )
            payout_matches_result = (
                valid_single_payout
                and top_two is not None
                and parsed_payouts[0][0] == top_two
            )
            if (
                not valid_single_payout
                or top_two_dead_heat
                or (top_two is not None and not payout_matches_result)
            ):
                payout_anomaly_examples.append(
                    {
                        "race": identity,
                        "payout_count": len(payouts),
                        "invalid_items": invalid_payout_items,
                        "top_two": top_two,
                        "top_two_dead_heat": top_two_dead_heat,
                    }
                )

            if valid_single_payout:
                winning_combination, amount = parsed_payouts[0]
                winning_odds = flattened.get(winning_combination)
                if _is_number(winning_odds) and float(winning_odds) > 0:
                    counts["winner_odds_comparable_races"] += 1
                    payout_multiple = amount / 100.0
                    if float(winning_odds) == payout_multiple:
                        counts["winner_odds_exact_matches"] += 1
                    elif (
                        float(winning_odds) >= 1000
                        and math.floor(payout_multiple)
                        == float(winning_odds)
                    ):
                        counts["winner_odds_floor_matches"] += 1
                    else:
                        counts["winner_odds_mismatches"] += 1
                        if fl_entries:
                            counts[
                                "winner_mismatches_with_fl"
                            ] += 1
                        else:
                            counts[
                                "winner_mismatches_without_fl"
                            ] += 1
                        winner_mismatch_examples.append(
                            {
                                "race": identity,
                                "combination": winning_combination,
                                "odds": winning_odds,
                                "payout": amount,
                                "fl_entries": sorted(fl_entries),
                            }
                        )
                else:
                    counts["winner_odds_not_comparable_races"] += 1

            exact_program = set(program) == set(ENTRY_NUMBERS)
            exact_result_entries = (
                set(result_racers) == set(ENTRY_NUMBERS)
            )
            clean_order = _full_order_is_clean(result_racers)
            strict_full_order_clean = (
                exact_program
                and clean_order
                and payout_matches_result
            )
            if strict_full_order_clean:
                counts["strict_full_order_clean_reference"] += 1
            probability_eligible = (
                exact_program
                and exact_result_entries
                and not exception_entries
                and top_two is not None
                and not top_two_dead_heat
                and payout_matches_result
            )
            if probability_eligible:
                counts["probability_training_eligible"] += 1
                month_counts["probability_training_eligible"] += 1
                if not strict_full_order_clean:
                    counts[
                        "exacta_clean_not_strict_full_order"
                    ] += 1
                    exacta_clean_not_strict_examples.append(
                        {
                            "race": identity,
                            "reason": (
                                "lower_place_tie_does_not_affect_unique_top_two"
                            ),
                        }
                    )
            else:
                counts["probability_training_excluded"] += 1
                if exception_entries:
                    counts[
                        "probability_excluded_with_exception"
                    ] += 1
                else:
                    counts[
                        "probability_excluded_without_exception"
                    ] += 1
                    probability_exclusion_examples.append(
                        {
                            "race": identity,
                            "reason": (
                                "program"
                                if not exact_program
                                else (
                                    "nonclean_order"
                                    if not clean_order
                                    else "payout"
                                )
                            ),
                        }
                    )
                if not exact_program:
                    counts["probability_exclusion_program"] += 1
                if not exact_result_entries:
                    counts["probability_exclusion_result_entries"] += 1
                if exception_entries:
                    counts["probability_exclusion_known_exception"] += 1
                if top_two is None or top_two_dead_heat:
                    counts[
                        "probability_exclusion_top_two_not_unique"
                    ] += 1
                if not payout_matches_result:
                    counts["probability_exclusion_payout"] += 1

            price_complete = (
                keys == EXACTA_COMBINATION_SET
                and not duplicate_paths
                and not malformed_paths
                and len(positive_keys) == len(EXACTA_COMBINATIONS)
            )
            if price_complete:
                counts["economic_predecision_eligible"] += 1
                month_counts["economic_predecision_eligible"] += 1
            else:
                counts["economic_predecision_excluded"] += 1

            settlement_eligible = (
                exact_program
                and price_complete
                and payout_matches_result
                and not top_two_dead_heat
            )
            if settlement_eligible:
                counts["economic_settlement_eligible"] += 1
                month_counts["economic_settlement_eligible"] += 1
                if fl_entries:
                    counts[
                        "economic_settlement_eligible_with_fl"
                    ] += 1
            else:
                counts["economic_settlement_excluded"] += 1

    integrity_blockers = (
        len(missing_raw_days)
        + len(missing_metadata_days)
        + len(sha_mismatch_days)
        + len(invalid_json_days)
        + len(source_metadata_anomalies)
        + counts["daily_structure_errors"]
        + counts["race_structure_errors"]
        + counts["identity_errors"]
        + counts["missing_canonical_keys"]
        + counts["extra_keys"]
        + counts["duplicate_keys"]
        + counts["malformed_odds_paths"]
        + counts["invalid_type_odds"]
        + counts["null_odds"]
        + counts["negative_odds"]
        + counts["nonfinite_odds"]
        + counts["invalid_payout_array_races"]
        + counts["invalid_payout_items"]
        + counts["no_payout_races"]
        + counts["payout_result_mismatch_races"]
        + counts["top_two_dead_heat_races"]
        + counts["top_two_not_unique_races"]
        + counts["multiple_payout_races"]
    )
    enough_probability_data = counts["probability_training_eligible"] > 0
    contract_pass = integrity_blockers == 0 and enough_probability_data
    recommendation = "CONDITIONAL_GO" if contract_pass else "NO_GO"
    exceptional_payout_observations = (
        counts["no_payout_races"]
        + counts["top_two_dead_heat_races"]
        + counts["multiple_payout_races"]
    )
    if exceptional_payout_observations:
        exceptional_payout_condition = (
            f"{counts['no_payout_races']} no-payout, "
            f"{counts['top_two_dead_heat_races']} top-two-dead-heat, and "
            f"{counts['multiple_payout_races']} multiple-payout races were "
            "observed and are integrity blockers until separately contracted"
        )
    else:
        exceptional_payout_condition = (
            "exacta non-establishment, top-two dead heat, and multiple "
            "payout were not observed; future occurrences must fail closed"
        )

    return {
        "audit": AUDIT_NAME,
        "scope": {
            "provider": "turnmark",
            "stadium_number": ASHIYA_STADIUM_NUMBER,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "expected_days": expected_day_count,
            "verified_cached_days": len(manifest),
            "ashiya_days": counts["ashiya_days"],
            "races": counts["races"],
            "source_repository_commit": source_commit,
            "source_commit_binding": (
                "documented_audit_context_not_embedded_in_daily_payload"
            ),
        },
        "fingerprints": {
            "algorithm": (
                "sha256(canonical-json([{date,sha256,size_bytes},...]))"
            ),
            "raw_manifest_sha256": _manifest_fingerprint(manifest),
            "manifest_entries": len(manifest),
            "raw_bytes": sum(
                int(entry["size_bytes"]) for entry in manifest
            ),
            "first_manifest_entry": manifest[0] if manifest else None,
            "last_manifest_entry": manifest[-1] if manifest else None,
            "first_fetched_at": (
                min(fetched_at_values) if fetched_at_values else None
            ),
            "last_fetched_at": (
                max(fetched_at_values) if fetched_at_values else None
            ),
        },
        "cache_integrity": {
            "missing_raw_days": missing_raw_days,
            "missing_metadata_days": missing_metadata_days,
            "sha_mismatch_days": sha_mismatch_days,
            "invalid_json_days": invalid_json_days,
            "source_metadata_anomalies": source_metadata_anomalies,
            "daily_structure_errors": counts["daily_structure_errors"],
            "race_structure_errors": counts["race_structure_errors"],
            "identity_errors": counts["identity_errors"],
        },
        "canonical_keys": {
            "expected_per_race": len(EXACTA_COMBINATIONS),
            "canonical_30_key_races": counts["canonical_30_key_races"],
            "missing_keys": counts["missing_canonical_keys"],
            "extra_keys": counts["extra_keys"],
            "duplicate_keys": counts["duplicate_keys"],
            "malformed_paths": counts["malformed_odds_paths"],
            "examples": key_anomaly_examples,
        },
        "odds": {
            "expected_canonical_values": (
                counts["races"] * len(EXACTA_COMBINATIONS)
            ),
            "positive": counts["positive_odds"],
            "zero": counts["zero_odds"],
            "null": counts["null_odds"],
            "invalid_type": counts["invalid_type_odds"],
            "negative": counts["negative_odds"],
            "nonfinite": counts["nonfinite_odds"],
            "invalid_value_examples": invalid_value_examples,
            "absent_boat_races": counts["absent_boat_races"],
            "absent_boats": counts["absent_boats"],
            "zero_explained_by_absent_boats": counts[
                "zero_odds_explained_by_absent_boats"
            ],
            "unexpected_positive_with_absent_boats": counts[
                "unexpected_positive_odds_with_absent_boats"
            ],
            "absent_market_anomalies": absent_market_anomalies,
            "unattributed_zero_races": counts[
                "unattributed_zero_odds_races"
            ],
            "unattributed_zero_values": counts["unattributed_zero_odds"],
            "unattributed_zero_combinations": (
                unexplained_zero_combinations
            ),
        },
        "payouts_and_results": {
            "single_payout_races": counts["single_payout_races"],
            "no_payout_races": counts["no_payout_races"],
            "multiple_payout_races": counts["multiple_payout_races"],
            "invalid_payout_array_races": counts[
                "invalid_payout_array_races"
            ],
            "invalid_payout_items": counts["invalid_payout_items"],
            "top_two_dead_heat_races": counts[
                "top_two_dead_heat_races"
            ],
            "top_two_not_unique_races": counts[
                "top_two_not_unique_races"
            ],
            "payout_result_mismatch_races": counts[
                "payout_result_mismatch_races"
            ],
            "anomaly_examples": payout_anomaly_examples,
        },
        "winning_odds_vs_payout": {
            "comparable_races": counts[
                "winner_odds_comparable_races"
            ],
            "exact_matches": counts["winner_odds_exact_matches"],
            "integer_floor_matches_at_1000_or_more": counts[
                "winner_odds_floor_matches"
            ],
            "mismatches": counts["winner_odds_mismatches"],
            "mismatches_with_fl": counts[
                "winner_mismatches_with_fl"
            ],
            "mismatches_without_fl": counts[
                "winner_mismatches_without_fl"
            ],
            "not_comparable": counts[
                "winner_odds_not_comparable_races"
            ],
            "mismatch_examples": winner_mismatch_examples,
        },
        "exceptions_and_refunds": {
            "exception_races": counts["exception_races"],
            "exception_boats_by_code": dict(
                sorted(exception_code_counts.items())
            ),
            "fl_races": counts["fl_races"],
            "fl_boat_count_distribution": dict(
                sorted(fl_boat_count_distribution.items())
            ),
            "direct_refund_fields_seen": sorted(direct_refund_paths),
            "refund_indicator_mode": (
                "derived_from_result.racers.place_number_source_F_or_L"
            ),
            "derived_refund_combinations": counts[
                "derived_refund_combinations"
            ],
            "semantic_limit": (
                "Turnmark has no observed refund target or refund amount field"
            ),
        },
        "eligibility": {
            "definitions": {
                "probability_training": (
                    "six program and result entries, no known exception boat, "
                    "unique result top two, one valid exacta payout matching "
                    "that top two; lower-place ties do not exclude and odds "
                    "are not required"
                ),
                "economic_predecision": (
                    "all 30 canonical exacta odds are finite and positive"
                ),
                "economic_settlement": (
                    "six program entries, economic_predecision eligibility, "
                    "one valid payout matching unique result top two; F/L "
                    "refund combinations are rule-derived"
                ),
            },
            "probability_training_eligible": counts[
                "probability_training_eligible"
            ],
            "probability_training_excluded": counts[
                "probability_training_excluded"
            ],
            "probability_exclusion_overlaps": {
                "program": counts["probability_exclusion_program"],
                "result_entries": counts[
                    "probability_exclusion_result_entries"
                ],
                "known_exception": counts[
                    "probability_exclusion_known_exception"
                ],
                "top_two_not_unique": counts[
                    "probability_exclusion_top_two_not_unique"
                ],
                "payout": counts["probability_exclusion_payout"],
                "with_exception": counts[
                    "probability_excluded_with_exception"
                ],
                "without_exception": counts[
                    "probability_excluded_without_exception"
                ],
            },
            "probability_exclusion_examples_without_exception": (
                probability_exclusion_examples
            ),
            "strict_full_order_clean_reference": counts[
                "strict_full_order_clean_reference"
            ],
            "exacta_clean_not_strict_full_order": counts[
                "exacta_clean_not_strict_full_order"
            ],
            "exacta_clean_not_strict_examples": (
                exacta_clean_not_strict_examples
            ),
            "economic_predecision_eligible": counts[
                "economic_predecision_eligible"
            ],
            "economic_predecision_excluded": counts[
                "economic_predecision_excluded"
            ],
            "economic_settlement_eligible": counts[
                "economic_settlement_eligible"
            ],
            "economic_settlement_eligible_with_fl": counts[
                "economic_settlement_eligible_with_fl"
            ],
            "economic_settlement_excluded": counts[
                "economic_settlement_excluded"
            ],
            "by_month": {
                month: dict(months[month])
                for month in sorted(months)
            },
        },
        "meeting_blocks": {
            "daily_field_inconsistencies": meeting_day_inconsistencies,
            **_summarize_meeting_blocks(meeting_day_records),
        },
        "gate_a": {
            "contract_pass": contract_pass,
            "recommendation": recommendation,
            "integrity_blocker_count": integrity_blockers,
            "go_scope": (
                "retrospective exacta probability-contract research only"
                if contract_pass
                else None
            ),
            "conditions": [
                (
                    "Gate P must independently establish program as-of "
                    "availability before model implementation or future holdout"
                ),
                (
                    f"{counts['economic_predecision_excluded']} races with "
                    "incomplete positive exacta odds are excluded from "
                    "economic evaluation"
                ),
                (
                    "refund combinations are derived from F/L codes; Turnmark "
                    "does not provide observed refund amounts"
                ),
                exceptional_payout_condition,
                (
                    "odds observed_at is unknown, so this audit cannot support "
                    "purchasable-price or profitability claims"
                ),
            ],
        },
    }


def format_text(document: Mapping[str, Any]) -> str:
    scope = document["scope"]
    keys = document["canonical_keys"]
    odds = document["odds"]
    payouts = document["payouts_and_results"]
    comparison = document["winning_odds_vs_payout"]
    refunds = document["exceptions_and_refunds"]
    eligibility = document["eligibility"]
    meetings = document["meeting_blocks"]
    gate = document["gate_a"]
    lines = [
        "Turnmark 芦屋2連単 Gate A監査",
        (
            f"期間: {scope['start']}〜{scope['end']} / "
            f"原本 {scope['verified_cached_days']}日 / "
            f"芦屋 {scope['ashiya_days']}開催日・{scope['races']}レース"
        ),
        (
            "manifest SHA-256: "
            f"{document['fingerprints']['raw_manifest_sha256']}"
        ),
        "",
        (
            "30 canonical keys: "
            f"{keys['canonical_30_key_races']}/{scope['races']} races / "
            f"missing {keys['missing_keys']} / extra {keys['extra_keys']} / "
            f"duplicate {keys['duplicate_keys']}"
        ),
        (
            f"odds values: positive {odds['positive']} / zero {odds['zero']} / "
            f"null {odds['null']} / invalid type {odds['invalid_type']}"
        ),
        (
            "zero attribution: absent boats "
            f"{odds['zero_explained_by_absent_boats']} / "
            f"unattributed {odds['unattributed_zero_values']} "
            f"({odds['unattributed_zero_races']} races)"
        ),
        (
            "exacta payouts: single "
            f"{payouts['single_payout_races']} / none "
            f"{payouts['no_payout_races']} / multiple "
            f"{payouts['multiple_payout_races']} / top-2 dead heat "
            f"{payouts['top_two_dead_heat_races']}"
        ),
        (
            "winning odds vs payout: exact "
            f"{comparison['exact_matches']} / floor "
            f"{comparison['integer_floor_matches_at_1000_or_more']} / mismatch "
            f"{comparison['mismatches']} "
            f"(with F/L {comparison['mismatches_with_fl']})"
        ),
        (
            f"F/L races: {refunds['fl_races']} / direct refund fields: "
            f"{len(refunds['direct_refund_fields_seen'])} / derived refunded "
            f"combinations: {refunds['derived_refund_combinations']}"
        ),
        (
            "eligibility: probability training "
            f"{eligibility['probability_training_eligible']} / "
            "economic predecision "
            f"{eligibility['economic_predecision_eligible']} / "
            "economic settlement "
            f"{eligibility['economic_settlement_eligible']}"
        ),
        (
            "meeting blocks: "
            f"{meetings['inferred_blocks']} inferred / "
            f"{meetings['complete_blocks']} complete / "
            f"status {meetings['status']}"
        ),
        "",
        (
            f"Gate A: {gate['recommendation']} "
            f"(integrity blockers: {gate['integrity_blocker_count']})"
        ),
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Turnmarkキャッシュのroot",
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=DEFAULT_START,
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=DEFAULT_END,
    )
    parser.add_argument(
        "--source-commit",
        default=DEFAULT_SOURCE_COMMIT,
        help="監査対象Turnmark repository commitの文書上の基準",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )
    return parser


def main(arguments: Optional[Iterable[str]] = None) -> int:
    parsed = build_parser().parse_args(arguments)
    document = run_audit(
        parsed.cache_dir,
        start=parsed.start,
        end=parsed.end,
        source_commit=parsed.source_commit,
    )
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
    return 0 if document["gate_a"]["contract_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
