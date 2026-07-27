"""テスト用の最小データビルダー。

実データの例外を再現しやすいよう、Turnmark 風の原本と正規化済み
レコードの両方を生成する。
"""

from datetime import date
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from funayomi.combinations import TRIFECTA_COMBINATIONS, parse_combination
from funayomi.domain import (
    NormalizedRace,
    OddsSnapshot,
    PreviewSnapshot,
    ProgramSnapshot,
    RaceIdentity,
    RaceOutcome,
)


FULL_FIELD: Tuple[int, ...] = (1, 2, 3, 4, 5, 6)


def complete_odds(
    default: Optional[float] = 10.0,
    overrides: Optional[Mapping[str, Optional[float]]] = None,
) -> Dict[str, Optional[float]]:
    values = {combination: default for combination in TRIFECTA_COMBINATIONS}
    if overrides:
        values.update(overrides)
    return values


def nested_odds(values: Mapping[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    nested: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for combination, odd in values.items():
        first, second, third = parse_combination(combination)
        nested.setdefault(str(first), {}).setdefault(str(second), {})[
            str(third)
        ] = odd
    return nested


def program_racers(
    entries: Iterable[int] = FULL_FIELD,
) -> Dict[str, Dict[str, Any]]:
    return {
        str(entry): {
            "entry_number": entry,
            "name": f"選手{entry}",
            "number": 1000 + entry,
            "rank_number": (entry % 4) + 1,
            "age": 20 + entry,
            "weight": 50.0 + entry / 10,
            "national_win_rate": 5.0 + entry / 10,
            "motor_number": 10 + entry,
        }
        for entry in entries
    }


def result_racers(
    winner: str = "1-2-3",
    entries: Sequence[int] = FULL_FIELD,
) -> Dict[str, Dict[str, Any]]:
    leading = list(parse_combination(winner))
    order = leading + [entry for entry in entries if entry not in leading]
    place_by_entry = {
        entry: place for place, entry in enumerate(order, start=1)
    }
    return {
        str(entry): {
            "entry_number": entry,
            "course_number": entry,
            "start_timing": entry / 100,
            "place_number": place_by_entry[entry],
            "place_number_source": str(place_by_entry[entry]),
            "number": 1000 + entry,
            "name": f"選手{entry}",
        }
        for entry in entries
    }


def raw_race(
    day: date,
    *,
    race_number: int = 1,
    entries: Sequence[int] = FULL_FIELD,
    odds: Optional[Mapping[str, Any]] = None,
    winner: str = "1-2-3",
    payout: int = 1200,
) -> Dict[str, Any]:
    return {
        "date": day.isoformat(),
        "stadium_number": 21,
        "race_number": race_number,
        "closed_at": f"{day.isoformat()}T12:00:00+09:00",
        "grade_number": 5,
        "title": "テスト開催",
        "subtitle": "テスト",
        "distance": 1800,
        "day_number": 1,
        "racers": program_racers(entries),
        "preview": {
            "wind_speed": 2,
            "wave_height": 1,
            "racers": {
                str(entry): {
                    "entry_number": entry,
                    "course_number": entry,
                    "start_timing": entry / 100,
                    "exhibition_time": 6.70 + entry / 100,
                }
                for entry in entries
            },
        },
        "odds": {
            "trifecta": nested_odds(
                odds if odds is not None else complete_odds()
            )
        },
        "result": {
            "racers": result_racers(winner, entries),
            "payouts": {
                "trifecta": [
                    {"combination": winner, "amount": payout},
                ]
            },
        },
    }


def raw_payload(
    day: date,
    races: Sequence[Mapping[str, Any]],
    *,
    include_other_stadium: bool = True,
) -> Dict[str, Any]:
    stadiums: Dict[str, Any] = {
        "21": {
            "stadium_number": 21,
            "races": {
                str(race["race_number"]): dict(race) for race in races
            },
        }
    }
    if include_other_stadium:
        stadiums["24"] = {
            "stadium_number": 24,
            "races": {
                "1": {
                    "date": day.isoformat(),
                    "stadium_number": 24,
                    "race_number": 1,
                }
            },
        }
    return {"programs": {"stadiums": stadiums}}


def make_race(
    day: date,
    *,
    race_number: int = 1,
    stadium_number: int = 21,
    entries: Sequence[int] = FULL_FIELD,
    winner: str = "1-2-3",
    payout: int = 1200,
    outcome_status: str = "standard",
    winning_trifectas: Optional[Tuple[str, ...]] = None,
    trifecta_payouts: Optional[Mapping[str, int]] = None,
    outcome_racers: Optional[Mapping[int, Mapping[str, Any]]] = None,
    odds: Optional[Mapping[str, Optional[float]]] = None,
    preview: bool = True,
    issues: Tuple[str, ...] = (),
    source_sha256: Optional[str] = "fixture-sha256",
) -> NormalizedRace:
    program = {
        entry: {
            "entry_number": entry,
            "number": 1000 + entry,
            "rank_number": (entry % 4) + 1,
        }
        for entry in entries
    }
    winners = (
        winning_trifectas
        if winning_trifectas is not None
        else ((winner,) if outcome_status != "missing" else ())
    )
    payouts = (
        dict(trifecta_payouts)
        if trifecta_payouts is not None
        else {combination: payout for combination in winners}
    )
    return NormalizedRace(
        identity=RaceIdentity(
            date=day,
            stadium_number=stadium_number,
            race_number=race_number,
            closed_at=f"{day.isoformat()}T12:00:00+09:00",
        ),
        program=ProgramSnapshot(
            race_fields={"grade_number": 5, "title": "fixture"},
            racers=program,
        ),
        preview=(
            PreviewSnapshot(
                fields={"wind_speed": 2},
                racers={
                    entry: {
                        "entry_number": entry,
                        "course_number": entry,
                    }
                    for entry in entries
                },
            )
            if preview
            else None
        ),
        odds=OddsSnapshot(
            trifecta=dict(odds if odds is not None else complete_odds())
        ),
        outcome=RaceOutcome(
            status=outcome_status,
            winning_trifectas=winners,
            trifecta_payouts=payouts,
            racers=(
                dict(outcome_racers)
                if outcome_racers is not None
                else {
                    int(key): value
                    for key, value in result_racers(winner, entries).items()
                }
            ),
        ),
        issues=issues,
        source_sha256=source_sha256,
    )
