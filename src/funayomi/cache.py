"""Turnmark 原本と正規化データを分離して保存するローカルキャッシュ。"""

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import DataContractError


class LocalCache:
    """日付単位の再現可能なキャッシュ。

    原本は ``raw/turnmark``、派生データは ``normalized/ashiya`` に分離する。
    refresh を明示しない限り、既存の原本は上書きしない。
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def raw_path(self, day: date) -> Path:
        return self.root / "raw" / "turnmark" / str(day.year) / f"{day:%Y%m%d}.json"

    def raw_metadata_path(self, day: date) -> Path:
        return self.raw_path(day).with_suffix(".metadata.json")

    def raw_revision_path(self, day: date, digest: str) -> Path:
        return (
            self.root
            / "raw"
            / "turnmark"
            / "revisions"
            / str(day.year)
            / f"{day:%Y%m%d}.{digest}.json"
        )

    def normalized_path(self, day: date) -> Path:
        return self.root / "normalized" / "ashiya" / str(day.year) / f"{day:%Y%m%d}.json"

    def has_raw(self, day: date) -> bool:
        return self.raw_path(day).is_file()

    def read_raw(self, day: date) -> bytes:
        payload = self.raw_path(day).read_bytes()
        metadata = self.read_raw_metadata(day)
        expected = metadata.get("sha256")
        actual = self.sha256(payload)
        if not isinstance(expected, str):
            raise DataContractError(
                f"原本キャッシュのSHA-256メタデータがありません: {self.raw_path(day)}"
            )
        if expected != actual:
            raise DataContractError(
                f"原本キャッシュのSHA-256が一致しません: {self.raw_path(day)}"
            )
        return payload

    def read_raw_metadata(self, day: date) -> Dict[str, Any]:
        path = self.raw_metadata_path(day)
        if not path.is_file():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise DataContractError(f"原本メタデータがobjectではありません: {path}")
        return value

    def write_raw(
        self,
        day: date,
        payload: bytes,
        metadata: Dict[str, Any],
        *,
        replace: bool = False,
    ) -> str:
        path = self.raw_path(day)
        if path.exists() and not replace:
            return self.sha256(self.read_raw(day))
        if path.exists() and replace:
            previous = self.read_raw(day)
            previous_digest = self.sha256(previous)
            revision_path = self.raw_revision_path(day, previous_digest)
            if not revision_path.exists():
                self._atomic_write_bytes(revision_path, previous)
                previous_metadata = self.read_raw_metadata(day)
                previous_metadata["sha256"] = previous_digest
                self._atomic_write_json(
                    revision_path.with_suffix(".metadata.json"),
                    previous_metadata,
                )
        digest = self.sha256(payload)
        stored_metadata = dict(metadata)
        stored_metadata["sha256"] = digest
        self._atomic_write_bytes(path, payload)
        self._atomic_write_json(self.raw_metadata_path(day), stored_metadata)
        return digest

    def read_normalized(self, day: date) -> Optional[Dict[str, Any]]:
        path = self.normalized_path(day)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise DataContractError(f"正規化キャッシュがobjectではありません: {path}")
        return value

    def write_normalized(self, day: date, value: Dict[str, Any]) -> None:
        self._atomic_write_json(self.normalized_path(day), value)

    @staticmethod
    def sha256(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _atomic_write_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(payload)
        os.replace(str(temporary), str(path))

    @classmethod
    def _atomic_write_json(cls, path: Path, value: Dict[str, Any]) -> None:
        payload = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        cls._atomic_write_bytes(path, payload)
