#!/usr/bin/env python3
"""Turnmark番組特徴の完全性とas-of証跡を既存キャッシュだけで監査する。"""

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from funayomi.cache import LocalCache
from funayomi.domain import NormalizedRace
from funayomi.repository import RaceRepository, date_range


DEFAULT_START = date(2026, 1, 1)
DEFAULT_END = date(2026, 7, 23)
ASHIYA_STADIUM_NUMBER = "21"
JAPAN_TIME = ZoneInfo("Asia/Tokyo")

# 次期主仮説で候補にしているprogram由来の特徴だけを固定する。選手名・登録番号、
# モーター番号等の識別子とpreview/result/odds由来の値は含めない。
PROPOSED_FEATURES: Tuple[str, ...] = (
    "entry_number",
    "rank_number",
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

# ``closed_at`` は締切予定時刻であり、番組レコードを観測した時刻ではない。
PROVIDER_TIMESTAMP_FIELDS: Tuple[str, ...] = (
    "program_observed_at",
    "program_published_at",
    "program_updated_at",
    "observed_at",
    "published_at",
    "updated_at",
    "created_at",
    "fetched_at",
)


def audit_program_asof(
    cache_dir: Path,
    *,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
) -> Dict[str, Any]:
    """検証済みraw cacheと正規化レースから監査文書を作る。"""

    if start > end:
        raise ValueError("開始日は終了日以前である必要があります")

    cache = LocalCache(cache_dir)
    repository = RaceRepository(cache)
    races: List[NormalizedRace] = []
    raw_races: List[Mapping[str, Any]] = []
    source_days: List[Dict[str, str]] = []
    fetched_values: List[datetime] = []
    capture_records: List[Tuple[Mapping[str, Any], datetime]] = []
    missing_metadata_days: List[str] = []

    for day in date_range(start, end):
        payload = cache.read_raw(day)
        decoded = json.loads(payload.decode("utf-8"))
        races.extend(repository.races_on(day, offline=True))
        daily_raw_races = _ashiya_races(decoded)
        raw_races.extend(daily_raw_races)

        metadata = cache.read_raw_metadata(day)
        digest = metadata.get("sha256")
        fetched_at = metadata.get("fetched_at")
        if isinstance(digest, str):
            source_days.append({"date": day.isoformat(), "sha256": digest})
        else:
            missing_metadata_days.append(day.isoformat())
        if not isinstance(fetched_at, str):
            if day.isoformat() not in missing_metadata_days:
                missing_metadata_days.append(day.isoformat())
            continue
        parsed_fetched_at = _parse_datetime(fetched_at, default_timezone=timezone.utc)
        if parsed_fetched_at is not None:
            fetched_values.append(parsed_fetched_at)
            capture_records.extend(
                (raw_race, parsed_fetched_at) for raw_race in daily_raw_races
            )
        elif day.isoformat() not in missing_metadata_days:
            missing_metadata_days.append(day.isoformat())

    completeness = summarize_feature_completeness(races)
    timestamp_evidence = summarize_timestamp_evidence(raw_races)
    post_close = summarize_capture_vs_close(
        capture_records,
        total_raw_races=len(raw_races),
    )
    provider_timestamp_count = sum(timestamp_evidence.values())
    all_captures_after_close = (
        post_close["comparable_races"] > 0
        and post_close["captured_after_close"] == post_close["comparable_races"]
    )

    return {
        "audit": "turnmark_program_asof_v1",
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "calendar_days": (end - start).days + 1,
        },
        "population": {
            "source_days": len(source_days),
            "ashiya_races": len(races),
            "ashiya_raw_races": len(raw_races),
            "program_racer_rows": sum(len(race.program.racers) for race in races),
        },
        "feature_scope": {
            "source_partition": "program_only",
            "proposed_features": list(PROPOSED_FEATURES),
            "excluded_partitions": ["preview", "odds", "result"],
            "completeness": completeness,
        },
        "asof_evidence": {
            "normalized_availability_labels": dict(
                sorted(Counter(race.program.availability for race in races).items())
            ),
            "provider_timestamp_fields": timestamp_evidence,
            "provider_timestamp_value_count": provider_timestamp_count,
            "closed_at_interpretation": "race_closing_time_not_observation_time",
            "cache_fetched_at_interpretation": (
                "funayomi_acquisition_time_not_provider_observation_time"
            ),
            "capture_vs_close": post_close,
            "all_comparable_captures_after_close": all_captures_after_close,
        },
        "fingerprints": {
            "source_sha256_set": source_set_fingerprint(source_days),
            "source_day_records": source_days,
        },
        "metadata": {
            "missing_required_sidecar_days": missing_metadata_days,
            "fetched_at_parseable_days": len(fetched_values),
            "fetched_at_min": _format_datetime(min(fetched_values))
            if fetched_values
            else None,
            "fetched_at_max": _format_datetime(max(fetched_values))
            if fetched_values
            else None,
        },
        "gate_p": {
            "status": (
                "NO_GO_HISTORICAL_CONFIRMATORY_USE"
                if provider_timestamp_count == 0 or all_captures_after_close
                else "REVIEW_REQUIRED"
            ),
            "reason": (
                "provider program timestamp is absent and/or the retained cache "
                "does not prove pre-race observation"
            ),
            "model_implementation_authorized": False,
        },
    }


def summarize_feature_completeness(
    races: Sequence[NormalizedRace],
) -> Dict[str, Any]:
    """候補特徴ごとに欠損と数値妥当性を数える。"""

    rows = [
        racer
        for race in races
        for _, racer in sorted(race.program.racers.items())
    ]
    fields: Dict[str, Dict[str, int]] = {}
    for field in PROPOSED_FEATURES:
        missing = sum(field not in row or row.get(field) is None for row in rows)
        non_numeric = sum(
            field in row
            and row.get(field) is not None
            and not _is_finite_number(row.get(field))
            for row in rows
        )
        fields[field] = {
            "rows": len(rows),
            "present_non_null": len(rows) - missing,
            "missing_or_null": missing,
            "non_numeric": non_numeric,
        }

    full_fields = sum(
        race.program.entry_numbers == (1, 2, 3, 4, 5, 6) for race in races
    )
    return {
        "races_with_six_entries": full_fields,
        "races_without_six_entries": len(races) - full_fields,
        "fields": fields,
    }


def summarize_timestamp_evidence(
    raw_races: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    """provider payload内の明示的な観測時刻候補を数える。"""

    counts = Counter()
    for race in raw_races:
        for field in PROVIDER_TIMESTAMP_FIELDS:
            if race.get(field) is not None:
                counts[field] += 1
        racers = race.get("racers")
        if isinstance(racers, Mapping):
            for racer in racers.values():
                if not isinstance(racer, Mapping):
                    continue
                for field in PROVIDER_TIMESTAMP_FIELDS:
                    if racer.get(field) is not None:
                        counts[f"racers.{field}"] += 1
    return {
        field: counts.get(field, 0)
        for field in (
            list(PROVIDER_TIMESTAMP_FIELDS)
            + [f"racers.{field}" for field in PROVIDER_TIMESTAMP_FIELDS]
        )
    }


def summarize_capture_vs_close(
    capture_records: Sequence[Tuple[Mapping[str, Any], datetime]],
    *,
    total_raw_races: Optional[int] = None,
) -> Dict[str, int]:
    """同じ日付のsidecar fetchと各レースのcloseを比較する。"""

    raw_race_count = (
        total_raw_races if total_raw_races is not None else len(capture_records)
    )
    comparable = 0
    before_or_at = 0
    after = 0
    unparseable = raw_race_count - len(capture_records)
    for race, fetched_at in capture_records:
        closed_at = _parse_datetime(race.get("closed_at"), default_timezone=JAPAN_TIME)
        if closed_at is None:
            unparseable += 1
            continue
        comparable += 1
        if fetched_at.astimezone(timezone.utc) <= closed_at.astimezone(timezone.utc):
            before_or_at += 1
        else:
            after += 1
    return {
        "comparable_races": comparable,
        "captured_before_or_at_close": before_or_at,
        "captured_after_close": after,
        "unparseable_close": unparseable,
    }


def source_set_fingerprint(source_days: Sequence[Mapping[str, str]]) -> str:
    canonical = "".join(
        f"{record['date']}|{record['sha256']}\n"
        for record in sorted(source_days, key=lambda item: item["date"])
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def format_text(document: Mapping[str, Any]) -> str:
    population = document["population"]
    completeness = document["feature_scope"]["completeness"]
    asof = document["asof_evidence"]
    capture = asof["capture_vs_close"]
    fields = completeness["fields"]
    lines = [
        "Turnmark program as-of監査",
        (
            f"期間: {document['period']['start']}〜{document['period']['end']} / "
            f"raw {population['source_days']}日 / 芦屋 {population['ashiya_races']}レース"
        ),
        (
            f"6艇program: {completeness['races_with_six_entries']} / "
            f"{population['ashiya_races']}レース"
        ),
        "",
        "候補特徴の欠損 / 非数値:",
    ]
    for field in PROPOSED_FEATURES:
        summary = fields[field]
        lines.append(
            f"- {field}: {summary['missing_or_null']} / {summary['non_numeric']}"
        )
    lines.extend(
        [
            "",
            (
                "provider観測時刻値: "
                f"{asof['provider_timestamp_value_count']} / "
                f"cache取得後締切: {capture['captured_after_close']}レース"
            ),
            f"Gate P: {document['gate_p']['status']}",
            (
                "注意: closed_atは締切時刻、sidecar fetched_atはFunaYomiの取得時刻で、"
                "providerの番組公開時刻ではありません。"
            ),
            f"source SHA集合fingerprint: {document['fingerprints']['source_sha256_set']}",
        ]
    )
    return "\n".join(lines)


def _ashiya_races(payload: Any) -> List[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    programs = payload.get("programs")
    stadiums = programs.get("stadiums") if isinstance(programs, Mapping) else None
    stadium = (
        stadiums.get(ASHIYA_STADIUM_NUMBER)
        if isinstance(stadiums, Mapping)
        else None
    )
    races = stadium.get("races") if isinstance(stadium, Mapping) else None
    if not isinstance(races, Mapping):
        return []
    return [value for value in races.values() if isinstance(value, Mapping)]


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _parse_datetime(value: Any, *, default_timezone: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_timezone)
    return parsed


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="Turnmarkキャッシュの場所",
    )
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(arguments: Optional[Iterable[str]] = None) -> int:
    parsed = build_parser().parse_args(arguments)
    document = audit_program_asof(
        parsed.cache_dir,
        start=parsed.start,
        end=parsed.end,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
