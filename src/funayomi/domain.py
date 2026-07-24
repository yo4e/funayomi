"""正規化後のドメインモデル。

予測時点の入力、価格、結果を別オブジェクトに分け、結果を予測特徴へ
誤って渡しにくくする。
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class RaceIdentity:
    date: date
    stadium_number: int
    race_number: int
    closed_at: Optional[str]


@dataclass(frozen=True)
class ProgramSnapshot:
    """出走表時点として扱う特徴。実際の公開時刻は API に存在しない。"""

    race_fields: Mapping[str, Any]
    racers: Mapping[int, Mapping[str, Any]]
    availability: str = "pre_race_timestamp_unverified"

    @property
    def entry_numbers(self) -> Tuple[int, ...]:
        return tuple(sorted(self.racers))


@dataclass(frozen=True)
class PreviewSnapshot:
    fields: Mapping[str, Any]
    racers: Mapping[int, Mapping[str, Any]]
    availability: str = "pre_race_timestamp_unverified"


@dataclass(frozen=True)
class OddsSnapshot:
    trifecta: Mapping[str, Optional[float]]
    observed_at: Optional[str] = None
    availability: str = "historical_snapshot_time_unknown"


@dataclass(frozen=True)
class RaceOutcome:
    status: str
    winning_trifectas: Tuple[str, ...]
    trifecta_payouts: Mapping[str, int]
    racers: Mapping[int, Mapping[str, Any]]
    availability: str = "post_race"

    @property
    def is_standard(self) -> bool:
        return self.status == "standard"

    @property
    def is_settleable(self) -> bool:
        winner = self.winning_trifecta
        return (
            self.status in ("standard", "exception_settled")
            and winner is not None
            and winner in self.trifecta_payouts
        )

    @property
    def nonstarter_entries(self) -> Tuple[int, ...]:
        return tuple(
            sorted(
                entry
                for entry, racer in self.racers.items()
                if racer.get("place_number_source") in ("F", "L")
            )
        )

    @property
    def winning_trifecta(self) -> Optional[str]:
        if len(self.winning_trifectas) == 1:
            return self.winning_trifectas[0]
        return None


@dataclass(frozen=True)
class NormalizedRace:
    identity: RaceIdentity
    program: ProgramSnapshot
    preview: Optional[PreviewSnapshot]
    odds: OddsSnapshot
    outcome: RaceOutcome
    issues: Tuple[str, ...] = field(default_factory=tuple)
    source_sha256: Optional[str] = None

    @property
    def has_full_field(self) -> bool:
        return self.program.entry_numbers == (1, 2, 3, 4, 5, 6)

    @property
    def training_eligible(self) -> bool:
        return self.has_full_field and self.outcome.is_standard

    @property
    def evaluation_eligible(self) -> bool:
        # 評価対象の選択可否を事後結果で決めない。オッズ完全性はランキング側で判定する。
        return self.has_full_field


JsonDict = Dict[str, Any]
