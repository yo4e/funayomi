# Turnmark 2連単strategy sandbox

Updated: **2026-07-27**

Status: **complete — retrospective / non-actionable (2026-07-27)**

## 1. Owner decision

山田さんは2026-07-27、次の範囲に限って新しい研究packageを承認しました。

- Turnmarkだけを使う
- retrospective hypothesis generationに限定する
- 全出力をnon-actionableとする
- 2連単schema、program特徴モデル、市場確率blend、固定予算portfolio
  backtestを実装する
- 公式翌日番組LZHは廃案にせず、将来prospectiveへ進む場合の候補としてHoldする

既存の確認的protocol
[`ashiya_exacta_pl_v1.json`](../protocols/ashiya_exacta_pl_v1.json) は
`HOLD_GATE_P_NO_GO` のまま変更しません。本sandboxは別protocol
[`turnmark_exacta_strategy_sandbox_v1.json`](../protocols/turnmark_exacta_strategy_sandbox_v1.json)
として、試行と結論を分離します。

## 2. 研究上の位置づけ

Turnmarkのprogramは意味上は事前情報ですが、保存snapshotの取得時点を証明
できません。オッズにも観測時刻がなく、購入可能な時点の価格とは断定
できません。

したがって本sandboxで調べられるのは、

> 時点不明のTurnmark歴史データ上で、programの残差信号と市場価格を
> 組み合わせた候補規則が、どのような的中・収益・下方リスク特性を示すか

までです。漏洩のない確認的性能、実購入可能な回収率、将来利益を主張
しません。

Gate PとGate DはNo-Goのままです。

## 3. 中心となる数理

2連単30通りのモデル確率を `p_i`、歴史オッズを `o_i` とします。

市場暗黙確率は、30通りで正規化します。

```text
q_i = (1 / o_i) / Σ_j (1 / o_j)
```

programモデルを市場へ幾何blendします。

```text
p(λ)_i ∝ q_i^(1 - λ) × p_i^λ
λ ∈ {0, 0.25, 0.5, 1}
```

買い目集合 `S` の予測カバー確率と市場コストは次です。

```text
coverage(S) = Σ_i∈S p_i
market_cost(S) = Σ_i∈S 1 / o_i
predicted_dutch_return(S) = coverage(S) / market_cost(S)
```

選択した買い目は、どれが的中しても概ね同じ総払戻になるように、1レース
固定予算を100円単位でdutchingします。買い目を増やせば的中率が上がるという
自明な関係を、同じrace exposureと市場コストの下で比較します。

prefixの適格判定には事前固定した理論値 `coverage / market_cost` を使います。
100円丸め後の期待回収率は `allocation_predicted_return` として別に記録し、
買い目集合の選択には使いません。

## 4. 結果を見る前に固定した比較

確率:

1. α=1の枠番2連単頻度baseline
2. program特徴Plackett–Luce
3. 正規化した時点不明の市場暗黙確率
4. programと市場のblend

portfolio:

1. `program_single`
2. `blend_single`
3. `program_dutch`
4. `blend_dutch`

全方式で1レースの仮想予算を1,000円、最小単位を100円に固定します。
singleとdutchで投資額を不公平に変えません。

portfolio候補は `p_i × o_i` の降順prefixだけです。dutch候補は、
予測回収率1.10以上かつ市場コスト0.50以下を満たす中から、予測coverageが
最大の集合を選びます。候補がなければ `PASS` です。

## 5. 時系列評価

outer evaluationは2026年4月、5月、6月、7月1〜23日の4foldです。
各foldでは、それ以前のデータだけでモデルと前処理をfitします。

programモデルのL2とblendの `λ` は、outerより前の月だけを使うexpanding
inner validationで選択します。outer結果を見て候補、閾値、買い目集合規則を
変えません。

確率評価:

- log loss
- Brier score
- 4foldの改善方向

portfolio評価:

- 購入レース、点数、的中レース
- 投資、払戻、損益、回収率
- 最大連敗、最大ドローダウン
- 最悪開催節
- 最大払戻への集中度
- 最大払戻を除いた回収率
- 月別・開催節別結果
- 開催節block bootstrapによる不確実性

## 6. 判断ゲート

### Gate S — probability signal

programモデルが枠番頻度baselineより、4fold中3fold以上でlog lossを改善し、
pooled差も負なら、retrospectiveなprogram signal候補とします。

### Gate R — risk robustness

同じrace exposureで、回収率、ドローダウン、連敗、活動量、払戻集中度の
Pareto関係を報告します。一つの恣意的な合成点で勝者を選びません。

### Gate U — locked Turnmark replication

現時点では未承認です。sandbox結果から方式を最大1本だけ凍結し、まだ結果を
見ていない将来のTurnmark期間へ一度だけ適用する場合は、別のowner decisionを
必要とします。通過してもGate P / Dの代わりにはなりません。

## 7. 正式実行結果

正式実行は、実装commit `40b3d860efedd79b6b51cd1cecde2eae80eddd47`
に対し、固定Turnmark cacheの2026-01-01〜07-23をofflineで読み、
outer 4foldと開催節block bootstrap 20,000回を実行しました。

### 7.1 確率品質

全foldでL2は `0.01`、blendの `λ` は `0.0` がinner validationから
選ばれました。`λ=0` は市場暗黙確率だけを使うことを意味します。

| outer fold | program log loss | 頻度baseline | 差 | 改善 |
|---|---:|---:|---:|---|
| 2026-04 | 2.5910 | 2.7498 | -0.1589 | yes |
| 2026-05 | 2.7788 | 2.7707 | +0.0081 | no |
| 2026-06 | 2.5405 | 2.7301 | -0.1896 | yes |
| 2026-07-01〜23 | 2.9264 | 3.0074 | -0.0810 | yes |
| pooled | 2.6906 | 2.8001 | -0.1095 | 3 / 4 fold |

Gate Sは `PASS_RETROSPECTIVE_SIGNAL_CANDIDATE` です。ただし市場暗黙確率の
pooled log lossは2.4999でprogramモデルより良く、inner validationも全foldで
市場100%を選びました。これは「弱い枠番頻度baselineを超えるprogram信号は
あるが、この期間の市場価格に対する残差信号は確認できなかった」という結果
です。確認的性能や将来性能の通過ではありません。

L2候補は全てledgerへ残しました。`100` は3月、5月で非収束、`10` は5月、
6月で非収束したため、該当outer foldの選択候補としてfail-closedしました。
非収束を有利なscoreへ置換していません。

### 7.2 固定予算portfolio

評価744レースのうち、2連単30オッズが揃わない9レースは結果を見る前に
`SKIP_DATA`、残り735レースを規則どおり判定しました。

| 方式 | 購入R | 点数 | 的中R | 回収率 | 損益 | 最大連敗 | 最大DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `program_single` | 735 | 735 | 6 | 0.3112 | -506,300円 | 109 | 524,000円 |
| `blend_single` | 0 | 0 | 0 | — | 0円 | 0 | 0円 |
| `program_dutch` | 735 | 6,804 | 144 | 0.6081 | -288,070円 | 22 | 307,920円 |
| `blend_dutch` | 0 | 0 | 0 | — | 0円 | 0 | 0円 |

開催節block bootstrapの95% percentile区間は次でした。

| 方式 | 回収率95%区間 | 最大DD 95%区間 |
|---|---:|---:|
| `program_single` | 0.0913〜0.5901 | 330,900〜700,507.5円 |
| `program_dutch` | 0.4590〜0.7719 | 184,459〜407,060.75円 |

`program_dutch` は同じ購入レース数と1レース予算で、単点より的中頻度、
回収率、最大連敗、最大DD、最大払戻集中度を改善しました。しかし回収率は
0.6081で、bootstrap上限も1未満です。したがって「ドローダウンを小さくする
方向のPareto改善」は観測したものの、収益候補とは判定しません。

blend 2方式は、inner validationが市場100%を選び、正規化市場確率では
`p_i × odds_i` が控除相当分だけ1未満になるため、閾値1.10を満たす候補が
ありませんでした。ゼロ投資・ゼロDDはrisk-adjustedな勝者ではなく、
`PASS`という正式結果です。

Gate Rは事前固定どおり `DESCRIPTIVE_PARETO_ONLY` です。単一の合成点や
「勝者」を後付けしていません。

## 8. 試行履歴と再現情報

実装中の試行も隠さず区別します。

1. 逐次実行のsmoke runは所要時間確認のため結果生成前に意図的に停止。
2. 4 worker・bootstrap 10回のintegration dry runを実行。Gate Sは3 / 4、
   `program_single`回収率0.3112、当時の`program_dutch`回収率0.6048、
   blend 2方式は全PASSだった。
3. dry run後の独立監査で、dutch prefixの適格判定と4方式のbootstrap乱数が
   凍結protocolに一致しない問題を発見。outer結果へ合わせた変更ではなく、
   protocolの理論式と共通resampleへ実装を修正し、正式結果を最初から再計算。
4. bootstrap 20,000回の正式runを実行し、compact ledgerを保存。
5. validation prediction cacheを使って同条件を再実行。
   `validation_cache_reused` 以外のJSONは完全一致した。

再現コマンド:

```bash
PYTHONPATH=src:. python3 scripts/run_turnmark_strategy_sandbox.py \
  --cache-dir data/cache \
  --offline \
  --bootstrap-resamples 20000 \
  --format json \
  --compact \
  --code-commit-sha 40b3d860efedd79b6b51cd1cecde2eae80eddd47 \
  --workers 4
```

正式ledger:

- [`experiments/turnmark_exacta_strategy_sandbox_v1.json`](../experiments/turnmark_exacta_strategy_sandbox_v1.json)
- ledger SHA-256:
  `8125caabcc52811683a38083809623875ab67101182b65057b66e62726432a4a`
- protocol SHA-256:
  `f4954e9d31f81b7b1b15a2a4a35037b07ee88d3cf32530e9532c72fdcd74f205`
- input source fingerprint:
  `0d78468991840f75ec87e32ff57954271e1150df18089288ee7f4a864056037b`
- prediction fingerprint:
  `5ed2f468836a6e43d5093fa70334dd8a93c5ebe9eb34c46b606094f783eb5317`
- cache状態以外を正規化した再実行JSON SHA-256:
  `a1624bcbae57b7eb379f0d649f7cf451686739478ee7dbc73e459c751145732f`

## 9. 現在の境界と将来候補

- LZHまたは公式HTMLの収集
- 当日予想
- 実購入できた価格という主張
- 確認的またはlive ROIという主張
- UI
- 自動投票
- アカウント、決済、資金移動
- martingale、損失追跡、実資金に連動する賭け金調整

公式翌日番組LZHは廃案ではありません。利用条件とfield契約を人間が確認した
うえで、将来prospective program snapshotが必要になった場合の候補として
Holdします。ただし今回の次工程にはせず、収集・問い合わせ・実装を開始して
いません。

Gate P / DはNo-Go、Gate Uは未承認です。本sandbox結果を見て同じ期間の
閾値、λ、特徴、買い目規則を救済調整する場合は、別protocol idと全試行記録が
必要です。
