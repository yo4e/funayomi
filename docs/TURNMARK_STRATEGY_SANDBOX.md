# Turnmark 2連単strategy sandbox

Updated: **2026-07-27**

Status: **Gate X approved — retrospective implementation in progress**

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

## 7. 範囲外

- LZHまたは公式HTMLの収集
- 当日予想
- 実購入できた価格という主張
- 確認的またはlive ROIという主張
- UI
- 自動投票
- アカウント、決済、資金移動
- martingale、損失追跡、実資金に連動する賭け金調整

実装結果、全試行、失敗、fingerprintは、完了後にこの文書と
`docs/HANDOFF.md`へ追記します。
