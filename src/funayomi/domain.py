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
    exacta: Mapping[str, Optional[float]] = field(default_factory=dict)
    observed_at: Optional[str] = None
    availability: str = "historical_snapshot_time_unknown"


@dataclass(frozen=True)
class RaceOutcome:
    status: str
    winning_trifectas: Tuple[str, ...]
    trifecta_payouts: Mapping[str, int]
    racers: Mapping[int, Mapping[str, Any]]
    exacta_status: str = "missing"
    winning_exactas: Tuple[str, ...] = field(default_factory=tuple)
    exacta_payouts: Mapping[str, int] = field(default_factory=dict)
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
    def is_exacta_standard(self) -> bool:
        return self.exacta_status == "standard"

    @property
    def is_exacta_settleable(self) -> bool:
        winner = self.winning_exacta
        return (
            self.exacta_status in ("standard", "exception_settled")
            and winner is not None
            and winner in self.exacta_payouts
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

    @property
    def winning_exacta(self) -> Optional[str]:
        if len(self.winning_exactas) == 1:
            return self.winning_exactas[0]
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
    def exacta_training_eligible(self) -> bool:
        """既知例外がなく、一意な上位2艇と払戻が一致する確率学習対象。"""

        return self.has_full_field and self.outcome.is_exacta_standard

    @property
    def exacta_probability_training_eligible(self) -> bool:
        """監査用語との互換alias。"""

        return self.exacta_training_eligible

    @property
    def evaluation_eligible(self) -> bool:
        # 評価対象の選択可否を事後結果で決めない。オッズ完全性はランキング側で判定する。
        return self.has_full_field

    @property
    def exacta_evaluation_eligible(self) -> bool:
        # 2連単でも選択可否を事後結果で決めない。
        return self.has_full_field

    @property
    def exacta_settlement_eligible(self) -> bool:
        """結果を開いた後に2連単を一意に精算できるか。"""

        return self.outcome.is_exacta_settleable


JsonDict = Dict[str, Any]
