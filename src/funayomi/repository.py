"""取得、キャッシュ、正規化をまとめるデータリポジトリ。"""

from datetime import date, timedelta
from typing import Iterable, List, Optional

from .cache import LocalCache
from .domain import NormalizedRace
from .errors import DataContractError
from .normalize import SCHEMA_VERSION, normalize_payload
from .serialization import normalized_document, race_from_dict
from .turnmark import TurnmarkClient


class RaceRepository:
    def __init__(self, cache: LocalCache, client: Optional[TurnmarkClient] = None):
        self.cache = cache
        self.client = client or TurnmarkClient(cache)

    def races_on(
        self,
        day: date,
        *,
        refresh: bool = False,
        offline: bool = False,
    ) -> List[NormalizedRace]:
        payload = self.client.fetch(day, refresh=refresh, offline=offline)
        source_sha256 = self.cache.sha256(payload)
        cached = self.cache.read_normalized(day)
        if cached is not None and self._cache_matches(cached, source_sha256):
            return self._load_races(cached)

        decoded = self.client.decode(payload, day)
        races = normalize_payload(decoded, day, source_sha256=source_sha256)
        metadata = self.cache.read_raw_metadata(day)
        document = normalized_document(
            races,
            source_url=str(metadata.get("source_url") or self.client.url_for(day)),
            source_sha256=source_sha256,
            source_fetched_at=_optional_string(metadata.get("fetched_at")),
        )
        self.cache.write_normalized(day, document)
        return races

    def races_between(
        self,
        start: date,
        end: date,
        *,
        refresh: bool = False,
        offline: bool = False,
    ) -> List[NormalizedRace]:
        if start > end:
            raise ValueError("開始日は終了日以前である必要があります")
        races: List[NormalizedRace] = []
        for day in date_range(start, end):
            races.extend(self.races_on(day, refresh=refresh, offline=offline))
        return races

    @staticmethod
    def _cache_matches(document: dict, source_sha256: str) -> bool:
        source = document.get("source")
        return (
            document.get("schema_version") == SCHEMA_VERSION
            and isinstance(source, dict)
            and source.get("sha256") == source_sha256
        )

    @staticmethod
    def _load_races(document: dict) -> List[NormalizedRace]:
        values = document.get("races")
        if not isinstance(values, list):
            raise DataContractError("正規化キャッシュに races 配列がありません")
        return [race_from_dict(value) for value in values]


def date_range(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _optional_string(value: object) -> Optional[str]:
    return value if isinstance(value, str) and value else None
