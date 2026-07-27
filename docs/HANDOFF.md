# FunaYomi Handoff

Updated: **2026-07-27**

## Current state

Issue #1の非UI研究コアと、合意済みのTurnmark限定2連単strategy sandboxが
実装済みです。

- Phase 1 / M1: データ監査とデータ契約 — complete
- Phase 2 / M2: 透明な3連単基準確率モデル — complete
- Phase 3 / M3: 3連単期待値ランキング — complete
- Phase 4 / M4: 固定期間バックテスト、閾値pseudo-holdout — complete
- Issue #1 pre-merge hardening、最小CI、MIT — complete
- Option A / Work package 0 — complete
- Gate X / Turnmark 2連単strategy sandbox — complete
- Web UI、当日予想、定期収集、自動投票 — not started / scope外

実装はPython 3.9以上、実行時依存なしです。全研究出力は
`actionable: false` / `historical_research_only`で、実購入判断には使えません。

## Owner decisions and boundaries

### 2026-07-24

月野テンプレクスはIssue #1研究コアを条件付き承認しました。山田さんは
pre-merge hardening、MIT、2連単を唯一の主仮説とするOption A、
Work package 0、合法な時点付きsource調査を承認しました。

Work package 0の結論:

- Gate A:
  `CONDITIONAL_GO_RETROSPECTIVE_EXACTA_CONTRACT`
- Gate P:
  `NO_GO_HISTORICAL_CONFIRMATORY_USE`
- Gate D:
  `NO_GO_NO_ADOPTABLE_SOURCE`
- 確認的protocol `ashiya_exacta_pl_v1`:
  `HOLD_GATE_P_NO_GO`

### 2026-07-27

山田さんは公式翌日番組LZHを一旦の必須次工程から外し、次の条件だけで
Gate Xを承認しました。

- Turnmarkだけを使う
- retrospective hypothesis generationに限定する
- 全出力をnon-actionableにする
- 2連単schema、programモデル、市場blend、portfolio backtestを実装する
- UI、当日利用、価格collector、自動投票へ拡張しない
- 公式翌日番組LZHは廃案にせず、将来prospective program snapshotが
  必要になった場合の候補としてHoldする

Gate Xは完了しました。Gate P / DはNo-Go、Gate U locked future Turnmark
replicationは未承認のままです。

## Implemented files

### Legacy Issue #1 core

- `src/funayomi/cache.py` — 原本・正規化cache、SHA検証、revision退避
- `src/funayomi/turnmark.py` — Turnmark取得、JSON・有限数検証
- `src/funayomi/normalize.py` — 芦屋抽出、3連単・2連単、例外・結果状態
- `src/funayomi/domain.py` — program / preview / odds / outcomeの分離型
- `src/funayomi/model.py` — 3連単Dirichlet平滑化枠番頻度モデル
- `src/funayomi/ranking.py` — EV計算、`PASS` / `SKIP_DATA`
- `src/funayomi/backtest.py` — 固定期間3連単評価、払戻・F/L・不成立精算
- `src/funayomi/safety.py` — research-only / non-actionable metadata
- `src/funayomi/cli.py` — `fetch` / `rank` / `backtest`
- `scripts/threshold_holdout_study.py` — 閾値pseudo-holdout再現

### Work package 0

- `scripts/audit_turnmark_exacta.py` — 2連単全期間Gate A監査
- `scripts/audit_program_asof.py` — program完全性・Gate P監査
- `docs/EXACTA_DATA_AUDIT.md`
- `docs/PROGRAM_AS_OF_AUDIT.md`
- `docs/TIMESTAMPED_SOURCE_RESEARCH.md`
- `docs/RESEARCH_PROTOCOL.md`
- `protocols/ashiya_exacta_pl_v1.json`

### Turnmark exacta strategy sandbox

- `src/funayomi/combinations.py` — canonical 2連単30通り
- `src/funayomi/normalize.py` — schema v3、2連単odds / outcome / payout
- `src/funayomi/serialization.py` — schema v3 round trip
- `src/funayomi/exacta_model.py`
  - α=1の2連単枠番頻度baseline
  - program特徴Plackett–Luce
  - training-only補完・標準化・欠損indicator
  - 標準ライブラリの決定論的BFGS、非収束時fail-closed
- `src/funayomi/portfolio.py`
  - 正規化inverse odds市場確率
  - 幾何blend
  - value-density prefix
  - single / equal-payout dutching
- `src/funayomi/strategy_backtest.py`
  - 同一race budgetの4方式
  - outcomeを開く前のportfolio固定
  - F/L返還と未監査caseのsafe-stop
  - 月別・開催節別・drawdown・集中度・共通開催節bootstrap
- `scripts/run_turnmark_strategy_sandbox.py`
  - expanding inner L2 / blend選択
  - outer 4fold
  - persistent validation prediction cache
  - compact machine ledger
- `protocols/turnmark_exacta_strategy_sandbox_v1.json`
- `docs/TURNMARK_STRATEGY_SANDBOX.md`
- `experiments/turnmark_exacta_strategy_sandbox_v1.json`

## Data and schema

監査基準:

- Turnmark API commit:
  `34a3b0a15c0e221a71464bcd86b572c4b28f90a7`
- 期間: 2026-01-01〜2026-07-23
- 全国日次JSON: 204日
- 芦屋: 107開催日、1,284レース
- raw manifest SHA-256:
  `92ebd6271d04ff2a914986fb21bf62d6f7882822ed53d6c15ab1239468967b65`

主要件数:

- 3連単120 canonical key: 1,284 / 1,284レース
- 3連単clean cohort: 1,183
- 2連単30 canonical key: 1,284 / 1,284レース
- 2連単clean probability cohort: 1,184
- 全30正オッズかつ歴史精算可能: 1,265
- 2連単不成立、top-2同着、複数払戻: 観測0
- 2連単の原因未定義0 odds: 6値 / 4レース

正規化schemaはv3です。旧v2 cacheは原本SHAが同じでも再正規化します。

Turnmarkは翌日に前日分を取得し、programとoddsの観測時刻を保存しません。

```text
program availability = pre_race_timestamp_unverified
odds availability = historical_snapshot_time_unknown
```

開始、前夜、締切、最終オッズとは断定しません。詳細は
`docs/DATA_CONTRACT.md`が正本です。

## Exacta sandbox protocol

事前固定した主な条件:

- protocol id: `turnmark_exacta_strategy_sandbox_v1`
- 研究区分: retrospective / non-actionable
- source: Turnmarkのみ
- outer: 2026年4月、5月、6月、7月1〜23日
- inner: outerより前の完全月、2026-01-01からexpanding fit
- L2候補: `0.01, 0.1, 1, 10, 100`
- blend λ候補: `0, 0.25, 0.5, 1`
- program / blend × single / dutchの4方式だけ
- race budget: 1,000円、wager unit: 100円
- minimum theoretical predicted return: 1.10
- maximum market cost: 0.50
- meeting block bootstrap: 20,000、seed `20260727`

prefix適格判定は、凍結protocolどおり理論値
`coverage / market_cost`を使います。100円丸め後の値は
`allocation_predicted_return`へ分け、選択には使いません。

protocol SHA-256:

```text
f4954e9d31f81b7b1b15a2a4a35037b07ee88d3cf32530e9532c72fdcd74f205
```

## Exacta sandbox results

正式実行の実装commit:

```text
40b3d860efedd79b6b51cd1cecde2eae80eddd47
```

### Probability quality

| fold | program log loss | frequency | program - frequency |
|---|---:|---:|---:|
| 2026-04 | 2.5910 | 2.7498 | -0.1589 |
| 2026-05 | 2.7788 | 2.7707 | +0.0081 |
| 2026-06 | 2.5405 | 2.7301 | -0.1896 |
| 2026-07-01〜23 | 2.9264 | 3.0074 | -0.0810 |
| pooled | 2.6906 | 2.8001 | -0.1095 |

- selected L2: 全fold `0.01`
- selected blend λ: 全fold `0.0`（市場100%）
- pooled market log loss: 2.4999
- Gate S:
  `PASS_RETROSPECTIVE_SIGNAL_CANDIDATE`
- 改善fold: 3 / 4
- 確認的またはlive claim: false

programは弱い枠番頻度baselineを改善しましたが、市場確率より悪い結果です。
市場に対する残差信号は確認できませんでした。

L2 `100`は3月・5月、`10`は5月・6月で非収束がありました。非収束candidateを
fail-closedし、全候補と月別statusをledgerへ残しています。

### Portfolio

評価744レース、全30正オッズ不完備で事前`SKIP_DATA`が9レース、
残り735レースを判定しました。

| 方式 | 購入R | 点数 | 的中R | 回収率 | 損益 | 最大連敗 | 最大DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| program single | 735 | 735 | 6 | 0.3112 | -506,300円 | 109 | 524,000円 |
| blend single | 0 | 0 | 0 | — | 0円 | 0 | 0円 |
| program dutch | 735 | 6,804 | 144 | 0.6081 | -288,070円 | 22 | 307,920円 |
| blend dutch | 0 | 0 | 0 | — | 0円 | 0 | 0円 |

20,000回bootstrap:

- program single
  - return 95%: 0.0913〜0.5901
  - maximum DD 95%: 330,900〜700,507.5円
- program dutch
  - return 95%: 0.4590〜0.7719
  - maximum DD 95%: 184,459〜407,060.75円

dutchはsingleより的中頻度、回収率、最大連敗、最大DD、最大払戻集中度を
改善しました。しかし回収率0.6081でbootstrap上限も1未満です。収益候補
ではありません。

blendは全foldで市場100%を選び、正規化市場確率が理論閾値1.10を満たさない
ため全PASSでした。ゼロ投資・ゼロDDを勝者とは扱いません。

Gate Rは `DESCRIPTIVE_PARETO_ONLY` です。scalar winnerを作っていません。

### Trial history and reproducibility

1. 結果生成前に停止した逐次runtime smoke
2. 4 worker、bootstrap 10回のintegration dry run
3. dry run後の独立監査で、prefix理論式とbootstrap共通resampleのprotocol
   不一致を発見
4. outer結果へ合わせず凍結protocolへ実装を修正
5. 実装commitを固定し、bootstrap 20,000回で正式run
6. validation cache利用runを再実行し、cache flag以外のJSON完全一致

正式ledger:

- path:
  `experiments/turnmark_exacta_strategy_sandbox_v1.json`
- SHA-256:
  `8125caabcc52811683a38083809623875ab67101182b65057b66e62726432a4a`
- input source fingerprint:
  `0d78468991840f75ec87e32ff57954271e1150df18089288ee7f4a864056037b`
- prediction fingerprint:
  `5ed2f468836a6e43d5093fa70334dd8a93c5ebe9eb34c46b606094f783eb5317`
- cache flag以外を除いた再実行JSON SHA-256:
  `a1624bcbae57b7eb379f0d649f7cf451686739478ee7dbc73e459c751145732f`

## Legacy research results

Issue #1の3連単結果も有効な失敗記録として残します。

- fixed split:
  - 学習2026-05-01〜06-15、評価06-16〜07-23
  - 21,269点、54的中、回収率0.8219、損益-378,760円
  - 最大連敗16、最大DD 825,540円
- threshold pseudo-holdout:
  - 4月に閾値8.00を選択
  - 5月1日〜6月15日に1,573点、的中0、回収率0.0210
  - 検証黒字は高配当1件への適合

詳細は `docs/THRESHOLD_HOLDOUT_STUDY.md` が正本です。

## Verification status

ローカル:

```text
PYTHONPATH=src:. python3 -m unittest discover -s tests -v
Ran 138 tests
OK

PYTHONPATH=src:. python3 -m compileall -q src scripts tests
OK

git diff --check
OK
```

独立read-only統合監査:

- programモデルの時系列境界、inner / outer分離、Gate S: blockingなし
- schema精算監査で、未観測の2連単不成立を全返還と推測する問題を発見し、
  fail-closedへ修正
- portfolio監査で、prefix適格判定とbootstrap seedのprotocol不一致を発見し、
  凍結protocolへ修正
- 修正後の再監査: blockingなし

GitHub:

- branch: `codex/issue-1-core`
- Issue #1:
  `https://github.com/yo4e/funayomi/issues/1`
- 月野レビュー:
  `https://github.com/yo4e/funayomi/issues/1#issuecomment-5066592698`
- open pull request: 0
- sandbox実装・結果commit:
  `cd1b6cff9995c6809508fcd521eb8e1dc9fd16c5`
- GitHub Actions:
  Python 3.9 / 3.14のunit test・compileが成功
  - `https://github.com/yo4e/funayomi/actions/runs/30231661083`

## Known limits

1. Turnmark oddsの観測時刻と購入可能時点は不明
2. Turnmark programのhistorical as-of証跡はない
3. 1〜5月の一部は後日backfill
4. Turnmarkの過去ファイルは後日修正され得る
5. 1,000倍以上のoddsは小数精度を失う
6. 返還fieldはなく、F/Lだけ公式規則と結果codeから導出
7. 2連単不成立、top-2同着、複数払戻は観測0で、初観測時はsafe-stop
8. 2連単の原因未定義0 oddsが6値 / 4レースあり、補完しない
9. 約7か月の全期間を監査・探索済みで、人間にとって未使用ではない
10. Gate Sは弱いfrequency baselineとのretrospective比較だけ
11. programモデルはmarket確率より悪く、blendは市場100%を選択
12. 購入した2方式は大幅赤字で、dutchのbootstrap上限も1未満
13. `P(win) × odds`は返還確率を含まないpoint estimate
14. Gate P / DはNo-Go、Gate Uは未承認
15. 公式翌日番組LZHは利用条件・field対応未確認で、収集していない
16. UI、当日data、realtime odds、自動投票は未実装

## Exact restart point

次の再開地点は一つです。

> **山田さんが、Gate Sでは弱いbaselineに対するprogram信号が見えた一方、
> 市場を上回らず全購入方式が赤字だった正式結果を確認し、この研究線を
> ここで終了するか、現在期間を再調整せず新しいprimary仮説を1つだけ
> pre-registerするv2設計packageを承認するか判断する。**

この判断までは、Gate U、追加閾値・λ・特徴・賭式探索、LZH収集、
prospective収集、価格collector、UI、当日予想、自動投票を開始しません。
LZHは廃案ではなく、将来必要になった場合の候補としてHoldします。
