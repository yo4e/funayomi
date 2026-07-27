"""2連単・3連単の一意な表現と検証。"""

from itertools import permutations
from typing import Iterable, Tuple


def combination_key(entries: Iterable[int]) -> str:
    """3つの異なる艇番を ``1-2-3`` 形式へ変換する。"""

    values = tuple(entries)
    if len(values) != 3:
        raise ValueError("3連単は3艇で構成する必要があります")
    if len(set(values)) != 3:
        raise ValueError("3連単の艇番は重複できません")
    if any(value not in range(1, 7) for value in values):
        raise ValueError("艇番は1から6である必要があります")
    return "-".join(str(value) for value in values)


def exacta_combination_key(entries: Iterable[int]) -> str:
    """2つの異なる艇番を ``1-2`` 形式へ変換する。"""

    values = tuple(entries)
    if len(values) != 2:
        raise ValueError("2連単は2艇で構成する必要があります")
    if len(set(values)) != 2:
        raise ValueError("2連単の艇番は重複できません")
    if any(value not in range(1, 7) for value in values):
        raise ValueError("艇番は1から6である必要があります")
    return "-".join(str(value) for value in values)


def parse_combination(value: str) -> Tuple[int, int, int]:
    """``1-2-3`` 形式を検証して艇番タプルへ変換する。"""

    try:
        entries = tuple(int(part) for part in value.split("-"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("3連単の形式が不正です") from exc
    if combination_key(entries) != value:
        raise ValueError("3連単は正規化済みの 1-2-3 形式で指定してください")
    return entries  # type: ignore[return-value]


def parse_exacta_combination(value: str) -> Tuple[int, int]:
    """``1-2`` 形式を検証して艇番タプルへ変換する。"""

    try:
        entries = tuple(int(part) for part in value.split("-"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("2連単の形式が不正です") from exc
    if exacta_combination_key(entries) != value:
        raise ValueError("2連単は正規化済みの 1-2 形式で指定してください")
    return entries  # type: ignore[return-value]


def generate_trifecta_combinations() -> Tuple[str, ...]:
    """6艇の3連単120通りを辞書順で返す。"""

    return tuple(combination_key(entries) for entries in permutations(range(1, 7), 3))


def generate_exacta_combinations() -> Tuple[str, ...]:
    """6艇の2連単30通りを辞書順で返す。"""

    return tuple(
        exacta_combination_key(entries)
        for entries in permutations(range(1, 7), 2)
    )


TRIFECTA_COMBINATIONS = generate_trifecta_combinations()
EXACTA_COMBINATIONS = generate_exacta_combinations()
