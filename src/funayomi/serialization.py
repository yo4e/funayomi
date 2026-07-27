"""正規化レースの JSON 直列化。"""

from datetime import date
from typing import Any, Dict, List, Mapping, Optional

from .domain import (
    NormalizedRace,
    OddsSnapshot,
    PreviewSnapshot,
    ProgramSnapshot,
    RaceIdentity,
    RaceOutcome,
)
from .errors import DataContractError
from .normalize import SCHEMA_VERSION


def normalized_document(
    races: List[NormalizedRace],
    *,
    source_url: str,
    source_sha256: str,
    source_fetched_at: Optional[str],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "provider": "turnmark",
            "url": source_url,
            "sha256": source_sha256,
            "fetched_at": source_fetched_at,
        },
        "normalization": {
            "stadium_number": 21,
            "prediction_cutoff": "program",
            "odds_observed_at": None,
        },
        "races": [race_to_dict(race) for race in races],
    }


def race_to_dict(race: NormalizedRace) -> Dict[str, Any]:
    return {
        "identity": {
            "date": race.identity.date.isoformat(),
            "stadium_number": race.identity.stadium_number,
            "race_number": race.identity.race_number,
            "closed_at": race.identity.closed_at,
        },
        "availability": {
            "program": race.program.availability,
            "preview": race.preview.availability if race.preview else None,
            "odds": race.odds.availability,
            "outcome": race.outcome.availability,
        },
        "program": {
            "race_fields": dict(race.program.race_fields),
            "racers": _string_keys(race.program.racers),
        },
        "preview": (
            {
                "fields": dict(race.preview.fields),
                "racers": _string_keys(race.preview.racers),
            }
            if race.preview
            else None
        ),
        "odds": {
            "trifecta": dict(race.odds.trifecta),
            "exacta": dict(race.odds.exacta),
            "observed_at": race.odds.observed_at,
        },
        "outcome": {
            "status": race.outcome.status,
            "winning_trifectas": list(race.outcome.winning_trifectas),
            "trifecta_payouts": dict(race.outcome.trifecta_payouts),
            "exacta_status": race.outcome.exacta_status,
            "winning_exactas": list(race.outcome.winning_exactas),
            "exacta_payouts": dict(race.outcome.exacta_payouts),
            "racers": _string_keys(race.outcome.racers),
        },
        "eligibility": {
            "training": race.training_eligible,
            "evaluation": race.evaluation_eligible,
            "exacta_training": race.exacta_training_eligible,
            "exacta_evaluation": race.exacta_evaluation_eligible,
            "exacta_settlement": race.exacta_settlement_eligible,
        },
        "issues": list(race.issues),
        "source_sha256": race.source_sha256,
    }


def race_from_dict(value: Mapping[str, Any]) -> NormalizedRace:
    try:
        identity = _required_mapping(value, "identity")
        program = _required_mapping(value, "program")
        odds = _required_mapping(value, "odds")
        outcome = _required_mapping(value, "outcome")
        availability = _required_mapping(value, "availability")
        preview_value = value.get("preview")
        preview = None
        if isinstance(preview_value, Mapping):
            preview = PreviewSnapshot(
                fields=_required_mapping(preview_value, "fields"),
                racers=_integer_keys(_required_mapping(preview_value, "racers")),
                availability=str(
                    availability.get("preview") or "pre_race_timestamp_unverified"
                ),
            )
        return NormalizedRace(
            identity=RaceIdentity(
                date=date.fromisoformat(str(identity["date"])),
                stadium_number=int(identity["stadium_number"]),
                race_number=int(identity["race_number"]),
                closed_at=_optional_string(identity.get("closed_at")),
            ),
            program=ProgramSnapshot(
                race_fields=_required_mapping(program, "race_fields"),
                racers=_integer_keys(_required_mapping(program, "racers")),
                availability=str(
                    availability.get("program") or "pre_race_timestamp_unverified"
                ),
            ),
            preview=preview,
            odds=OddsSnapshot(
                trifecta=dict(_required_mapping(odds, "trifecta")),
                exacta=dict(_required_mapping(odds, "exacta")),
                observed_at=_optional_string(odds.get("observed_at")),
                availability=str(
                    availability.get("odds") or "historical_snapshot_time_unknown"
                ),
            ),
            outcome=RaceOutcome(
                status=str(outcome["status"]),
                winning_trifectas=tuple(str(item) for item in outcome["winning_trifectas"]),
                trifecta_payouts={
                    str(key): int(item)
                    for key, item in _required_mapping(
                        outcome, "trifecta_payouts"
                    ).items()
                },
                racers=_integer_keys(_required_mapping(outcome, "racers")),
                exacta_status=str(outcome["exacta_status"]),
                winning_exactas=tuple(
                    str(item) for item in outcome["winning_exactas"]
                ),
                exacta_payouts={
                    str(key): int(item)
                    for key, item in _required_mapping(
                        outcome, "exacta_payouts"
                    ).items()
                },
                availability=str(availability.get("outcome") or "post_race"),
            ),
            issues=tuple(str(item) for item in value.get("issues", ())),
            source_sha256=_optional_string(value.get("source_sha256")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataContractError("正規化キャッシュのレース構造が不正です") from exc


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise DataContractError(f"正規化キャッシュに {key} object がありません")
    return item


def _string_keys(value: Mapping[int, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(key): dict(item) for key, item in sorted(value.items())}


def _integer_keys(value: Mapping[str, Any]) -> Dict[int, Mapping[str, Any]]:
    result: Dict[int, Mapping[str, Any]] = {}
    for key, item in value.items():
        if not isinstance(item, Mapping):
            raise DataContractError("艇レコードがobjectではありません")
        result[int(key)] = dict(item)
    return result


def _optional_string(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None
