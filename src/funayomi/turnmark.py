"""Turnmark API の取得処理。"""

import json
import math
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .cache import LocalCache
from .errors import DataContractError, DataUnavailableError


DEFAULT_BASE_URL = "https://turnmark.github.io/api/v1"
DEFAULT_USER_AGENT = "FunaYomi/0.1 (+https://github.com/yo4e/funayomi)"


class TurnmarkClient:
    def __init__(
        self,
        cache: LocalCache,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        opener: Optional[Callable[[Request, float], bytes]] = None,
    ):
        self.cache = cache
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener or self._open

    def url_for(self, day: date) -> str:
        return f"{self.base_url}/{day.year}/{day:%Y%m%d}.json"

    def fetch(self, day: date, *, refresh: bool = False, offline: bool = False) -> bytes:
        """指定日の原本を返す。

        既存キャッシュを優先し、``refresh`` のときだけ再取得する。
        ``offline`` ではネットワークへ接続しない。
        """

        if self.cache.has_raw(day) and not refresh:
            return self.cache.read_raw(day)
        if offline:
            raise DataUnavailableError(f"{day} の原本キャッシュがありません")

        url = self.url_for(day)
        request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
        try:
            payload = self._opener(request, self.timeout)
        except HTTPError as exc:
            if exc.code == 404:
                raise DataUnavailableError(f"{day} の Turnmark データはありません") from exc
            raise DataUnavailableError(
                f"Turnmark API が HTTP {exc.code} を返しました: {day}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise DataUnavailableError(f"Turnmark API の取得に失敗しました: {day}") from exc

        self._validate_json(payload, day)
        metadata = {
            "provider": "turnmark",
            "source_url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "size_bytes": len(payload),
        }
        self.cache.write_raw(day, payload, metadata, replace=refresh)
        return payload

    @classmethod
    def decode(cls, payload: bytes, day: date) -> Dict[str, Any]:
        def reject_non_finite(value: str) -> None:
            raise ValueError(f"非有限JSON数値は許可しません: {value}")

        try:
            value = json.loads(
                payload.decode("utf-8"),
                parse_constant=reject_non_finite,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise DataContractError(f"{day} の Turnmark JSON が不正です") from exc
        if not isinstance(value, dict):
            raise DataContractError(f"{day} の Turnmark JSON がobjectではありません")
        cls._ensure_finite(value, day)
        return value

    @classmethod
    def _validate_json(cls, payload: bytes, day: date) -> None:
        cls.decode(payload, day)

    @staticmethod
    def _open(request: Request, timeout: float) -> bytes:
        with urlopen(request, timeout=timeout) as response:
            return response.read()

    @classmethod
    def _ensure_finite(cls, value: Any, day: date) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise DataContractError(f"{day} の Turnmark JSON に非有限数値があります")
        if isinstance(value, dict):
            for item in value.values():
                cls._ensure_finite(item, day)
        elif isinstance(value, list):
            for item in value:
                cls._ensure_finite(item, day)
