"""利用者へ安全に伝えるためのドメイン例外。"""


class FunaYomiError(Exception):
    """FunaYomi が想定している実行エラー。"""


class DataUnavailableError(FunaYomiError):
    """指定日の Turnmark データを取得できない。"""


class DataContractError(FunaYomiError):
    """入力がサポート対象のデータ契約を満たさない。"""


class ChronologyError(FunaYomiError):
    """学習期間と評価期間の時系列境界が不正。"""


class RaceNotFoundError(FunaYomiError):
    """指定した芦屋レースが存在しない。"""
