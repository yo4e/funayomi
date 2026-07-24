"""FunaYomi の非UI実行入口。"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .backtest import backtest_to_dict, format_backtest_text, run_backtest
from .cache import LocalCache
from .errors import ChronologyError, FunaYomiError, RaceNotFoundError
from .model import SmoothedTrifectaFrequencyModel
from .ranking import format_ranking_text, rank_race, ranking_to_dict
from .repository import RaceRepository, date_range


DEFAULT_CACHE_DIR = Path("data/cache")
DEFAULT_HISTORY_START = date(2026, 1, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="funayomi",
        description="芦屋3連単の説明可能な期待値ランキング・コア",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser(
        "fetch", help="Turnmark日次原本を取得し、芦屋だけを正規化する"
    )
    _add_cache_argument(fetch_parser)
    fetch_parser.add_argument("--start", type=_date_argument, required=True)
    fetch_parser.add_argument("--end", type=_date_argument, required=True)
    fetch_parser.add_argument(
        "--refresh",
        action="store_true",
        help="既存キャッシュを明示的に再取得する",
    )
    fetch_parser.add_argument(
        "--format", choices=("text", "json"), default="text"
    )
    fetch_parser.set_defaults(handler=_handle_fetch)

    rank_parser = subparsers.add_parser(
        "rank", help="過去の芦屋レースを期待回収率順に表示する"
    )
    _add_cache_argument(rank_parser)
    _add_offline_argument(rank_parser)
    rank_parser.add_argument("--date", type=_date_argument, required=True)
    rank_parser.add_argument("--race", type=int, choices=range(1, 13), required=True)
    rank_parser.add_argument(
        "--train-start", type=_date_argument, default=DEFAULT_HISTORY_START
    )
    rank_parser.add_argument("--threshold", type=float, default=1.0)
    rank_parser.add_argument("--alpha", type=float, default=1.0)
    rank_parser.add_argument(
        "--format", choices=("text", "json"), default="text"
    )
    rank_parser.set_defaults(handler=_handle_rank)

    backtest_parser = subparsers.add_parser(
        "backtest", help="固定した学習期間と後続評価期間で検証する"
    )
    _add_cache_argument(backtest_parser)
    _add_offline_argument(backtest_parser)
    backtest_parser.add_argument(
        "--train-start", type=_date_argument, required=True
    )
    backtest_parser.add_argument("--train-end", type=_date_argument, required=True)
    backtest_parser.add_argument("--eval-start", type=_date_argument, required=True)
    backtest_parser.add_argument("--eval-end", type=_date_argument, required=True)
    backtest_parser.add_argument("--threshold", type=float, default=1.0)
    backtest_parser.add_argument("--alpha", type=float, default=1.0)
    backtest_parser.add_argument(
        "--stake", type=int, default=100, help="1組合せあたりの仮想購入額"
    )
    backtest_parser.add_argument(
        "--format", choices=("text", "json"), default="text"
    )
    backtest_parser.set_defaults(handler=_handle_backtest)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except (FunaYomiError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


def _handle_fetch(arguments: argparse.Namespace) -> int:
    if arguments.start > arguments.end:
        raise ValueError("開始日は終了日以前である必要があります")
    repository = _repository(arguments.cache_dir)
    daily: List[Dict[str, Any]] = []
    total_races = 0
    for day in date_range(arguments.start, arguments.end):
        races = repository.races_on(day, refresh=arguments.refresh)
        digest = repository.cache.sha256(repository.cache.read_raw(day))
        daily.append(
            {
                "date": day.isoformat(),
                "ashiya_races": len(races),
                "source_sha256": digest,
            }
        )
        total_races += len(races)
    result = {
        "start": arguments.start.isoformat(),
        "end": arguments.end.isoformat(),
        "days": len(daily),
        "ashiya_races": total_races,
        "cache_dir": str(arguments.cache_dir),
        "daily": daily,
    }
    _print_output(
        result,
        arguments.format,
        text=(
            f"{result['start']} 〜 {result['end']} の{result['days']}日を保存しました。\n"
            f"芦屋レース: {result['ashiya_races']}件\n"
            f"キャッシュ: {result['cache_dir']}"
        ),
    )
    return 0


def _handle_rank(arguments: argparse.Namespace) -> int:
    if arguments.train_start > arguments.date:
        raise ValueError("学習開始日は予測日以前である必要があります")
    repository = _repository(arguments.cache_dir)
    races = repository.races_between(
        arguments.train_start,
        arguments.date,
        offline=arguments.offline,
    )
    target = next(
        (
            race
            for race in races
            if race.identity.date == arguments.date
            and race.identity.race_number == arguments.race
        ),
        None,
    )
    if target is None:
        raise RaceNotFoundError(
            f"{arguments.date} の芦屋 {arguments.race}R はありません"
        )
    training = [race for race in races if race.identity.date < arguments.date]
    model = SmoothedTrifectaFrequencyModel.fit(
        training,
        prediction_date=arguments.date,
        prior_count_per_combination=arguments.alpha,
    )
    prediction = model.predict(target)
    result = rank_race(target, prediction, threshold=arguments.threshold)
    _print_output(
        ranking_to_dict(result),
        arguments.format,
        text=format_ranking_text(result),
    )
    return 0


def _handle_backtest(arguments: argparse.Namespace) -> int:
    if not (
        arguments.train_start
        <= arguments.train_end
        < arguments.eval_start
        <= arguments.eval_end
    ):
        raise ChronologyError(
            "期間は train_start <= train_end < eval_start <= eval_end "
            "である必要があります"
        )
    repository = _repository(arguments.cache_dir)
    all_races = repository.races_between(
        arguments.train_start,
        arguments.eval_end,
        offline=arguments.offline,
    )
    result = run_backtest(
        all_races,
        all_races,
        train_start=arguments.train_start,
        train_end=arguments.train_end,
        evaluation_start=arguments.eval_start,
        evaluation_end=arguments.eval_end,
        threshold=arguments.threshold,
        stake_per_combination=arguments.stake,
        prior_count_per_combination=arguments.alpha,
    )
    _print_output(
        backtest_to_dict(result),
        arguments.format,
        text=format_backtest_text(result),
    )
    return 0


def _repository(cache_dir: Path) -> RaceRepository:
    cache = LocalCache(cache_dir)
    return RaceRepository(cache)


def _print_output(value: Dict[str, Any], output_format: str, *, text: str) -> None:
    if output_format == "json":
        print(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
        )
    else:
        print(text)


def _add_cache_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"原本・正規化キャッシュの保存先（既定: {DEFAULT_CACHE_DIR}）",
    )


def _add_offline_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--offline",
        action="store_true",
        help="ネットワークを使わず既存キャッシュだけを読む",
    )


def _date_argument(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日付は YYYY-MM-DD 形式で指定してください") from exc


if __name__ == "__main__":
    raise SystemExit(main())
