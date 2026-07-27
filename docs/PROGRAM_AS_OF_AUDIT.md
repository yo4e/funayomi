# Turnmark program完全性・as-of監査

Updated: **2026-07-24**

Status: **Work package 0 complete — Gate P No-Go for historical confirmatory use**

Update 2026-07-27: Gate Pの結論は変わりません。その後、山田さんは
Turnmark限定・retrospective・non-actionableな別sandboxだけをGate Xとして
承認しました。確認的利用ではありません。現在の実装・結果は
[`TURNMARK_STRATEGY_SANDBOX.md`](TURNMARK_STRATEGY_SANDBOX.md) が正本です。

## 1. 結論

2026-01-01〜2026-07-23のTurnmark原本204日、芦屋1,284レース、
7,704艇レコードを再監査しました。

- 次期仮説で候補にしたprogram特徴16項目は、全7,704行で欠損0、非数値0
- 全1,284レースに1〜6号艇のprogramが存在
- provider payload内にprogramの公開・更新・観測時刻を示す値は0件
- 正規化値のavailabilityは全件 `pre_race_timestamp_unverified`
- 手元のsidecar `fetched_at` は全1,284レースで締切後

したがって、**値の完全性はGo、過去データを確認的な予測評価へ使うas-of境界は
No-Go** と判定します。`closed_at` はレースの締切時刻であってprogramの観測時刻
ではなく、sidecar `fetched_at` はFunaYomiが原本を取得した時刻であってprovider
の公開時刻ではありません。

この結論では2連単schema、Plackett–Luceモデル、数値依存、nested評価を実装
しません。Gate Pを満たす新しい証拠または将来snapshot収集契約は、次のowner
decisionで別途承認が必要です。

## 2. 監査母集団と再現性

| 項目 | 結果 |
|---|---:|
| 対象期間 | 2026-01-01〜2026-07-23 |
| 連続日数 / raw sidecar | 204 / 204 |
| 芦屋開催日 | 107 |
| 芦屋レース | 1,284 |
| program艇行 | 7,704 |
| 6艇program | 1,284 |
| raw / normalizedレース数差 | 0 |
| SHA sidecar不備 | 0日 |
| `fetched_at` parse不備 | 0日 |

日付とraw SHA-256を昇順で
`YYYY-MM-DD|sha256\n` に正規化した集合fingerprintは次です。

```text
12f45eba27872b505626c2447845d5d695315e8d01b5fe003b6bbf31d6137560
```

再現コマンド:

```bash
PYTHONPATH=src python3 scripts/audit_program_asof.py \
  --cache-dir data/cache \
  --start 2026-01-01 \
  --end 2026-07-23 \
  --format text
```

スクリプトはHTTP取得を行わず、SHA sidecarを検証できる既存raw cacheだけを
読みます。別SHAの原本で再実行した場合は、本書の結果を流用せず差分監査します。

## 3. 特徴完全性

次の16項目を、次期仮説のprogram-only候補として監査しました。

| 特徴群 | 項目 | 欠損 / 非数値 |
|---|---|---:|
| 枠・級 | `entry_number`, `rank_number` | 0 / 0 |
| 基本 | `weight`, `flying_count`, `late_count`, `average_start_timing` | 0 / 0 |
| 全国 | `national_win_rate`, `national_top_2_percent`, `national_top_3_percent` | 0 / 0 |
| 当地 | `local_win_rate`, `local_top_2_percent`, `local_top_3_percent` | 0 / 0 |
| モーター | `motor_top_2_percent`, `motor_top_3_percent` | 0 / 0 |
| ボート | `boat_top_2_percent`, `boat_top_3_percent` | 0 / 0 |

選手名、登録番号、年齢、支部、出身地、モーター番号、ボート番号は識別子または
事前仮説外なので候補に含めません。preview、odds、resultの値もprogram-only
経路には含めません。

欠損が0であることは「レース前に利用できた」証明ではありません。また、
アーカイブが後日改訂された場合、完全な現在値が過去時点にも存在したとは
限りません。

## 4. as-of証跡

各raw raceとracer recordについて、次の明示的な時刻候補を検索しました。

```text
program_observed_at
program_published_at
program_updated_at
observed_at
published_at
updated_at
created_at
fetched_at
```

全候補の非null値は0件でした。`closed_at` は1,284件すべてparse可能でしたが、
意味は締切時刻なので観測時刻候補には数えていません。

手元の204 sidecarは2026-07-24 13:07:10〜13:49:50 JSTに取得されており、
各日付のレース締切と比較できる1,284件すべてで締切後でした。この時刻は今回の
取得行為の監査証跡としては有効ですが、過去レースの事前snapshotを証明しません。

## 5. Gate P判定

```text
status: NO_GO_HISTORICAL_CONFIRMATORY_USE
model_implementation_authorized: false
```

Gate Pを通すには、少なくとも使用特徴ごとに次が必要です。

1. 意思決定時点より前に存在したことを示すprovider時刻、または
   FunaYomi自身の改変不能な取得時刻とraw SHA
2. 取得後に結果確定情報で上書きされない契約または差分監査
3. snapshotの取得頻度、保持期間、利用条件、失敗時の安全停止
4. foldごとに学習・検証・評価時点以前のsnapshotだけを選ぶ再現規則

現行アーカイブは探索的なschema・欠損監査には使えますが、program特徴モデルの
確認的な成績主張には使いません。
