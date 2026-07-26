# 芦屋2連単 Plackett–Luce研究protocol v1

Updated: **2026-07-24**

Status: **design frozen / execution HOLD**

Machine-readable protocol:
[`protocols/ashiya_exacta_pl_v1.json`](../protocols/ashiya_exacta_pl_v1.json)

SHA-256:

```text
5c0f160d0aec74407fd82e05e826cbfdaa920cedcd22a51092926f24814cb24a
```

このprotocolはWork package 0で設計を固定するためのもので、モデルを実装・
実行する許可ではありません。Gate Pがhistorical confirmatory useに
No-Goであるため、賭式schema、Plackett–Luce、数値依存、nested evaluation、
future holdoutは開始しません。

## 1. 主仮説と推定対象

唯一のprimary confirmatory bet typeは2連単です。

> program特徴Plackett–Luceモデルは、平滑化枠番2連単頻度baselineより、
> clean race条件付き2連単確率のout-of-sample log lossを改善する。

単勝は1着確率の診断、3連単は順位確率の整合性診断だけに使います。結果を見て
primaryを単勝・3連単・ROIへ切り替えません。

primary clean raceは次を全て満たすものです。

- program/resultに1〜6号艇がある
- F/L、欠場、事故・失格等の既知例外艇がない
- 1着・2着が一意
- 正しい2連単払戻が1件あり、結果のtop-2と一致

3〜6着の同着はtop-2 partial likelihoodへ影響しないため許容します。監査期間
では1,184レースが該当しました。strictな1〜6着完全順列は1,183レースで、
差は2026-04-05 6Rの4着同着1件だけです。

オッズ、返還、経済収益はこの推定対象に含めません。

## 2. 比較モデル

Primary model:

```text
s_i = exp(x_i β)

P(a-b)
= s_a / Σs
× s_b / (Σs - s_a)
```

race平均のtop-2 partial negative log likelihoodに
`0.5 × λ × Σβ²`を加え、全係数を罰する計画です。interceptは置かず、
初期係数は全て0、race内の線形予測値から最大値を引いてから指数化します。

Baseline:

```text
P(a-b)
= (count(a-b) + 1)
  / (N + 30)
```

学習partition内の枠番2連単頻度だけを使う、対称Dirichlet
`α = 1 per combination` のbaselineです。一様30通りと時点不明のTurnmark
市場暗黙確率はdescriptive referenceに限定します。

v1ではpost-hoc calibration、gradient boosting、相互作用を追加しません。

## 3. 特徴と前処理

使用候補はprogram partitionだけです。

Categorical:

- `entry_number`: 6号艇を基準とするone-hot
- `rank_number`: 4を基準とし、unknownを明示したone-hot

Numeric:

- `weight`
- `flying_count`, `late_count`, `average_start_timing`
- 全国・当地のwin / top-2 / top-3率
- motor / boatのtop-2 / top-3率

各foldのtraining partitionだけで、数値のmedian補完、欠損indicator、
平均・母標準偏差による標準化をfitします。標準偏差0は標準化値0、clipなし、
相互作用なしです。

選手名・登録番号、年齢、支部・出身、motor / boat番号、preview、odds、
result、払戻、結果側ST、決まり手は禁止します。

候補特徴がいずれかのdevelopment月で20%を超えて欠損するか、
`prospective_preclose_verified` を証明できない場合は、外側結果を見る前に
全foldから除外します。特徴集合が変わるため、protocol versionとhashを更新
しない限り実行しません。

## 4. 正則化とoptimizer候補

```text
L2 λ = {0.01, 0.1, 1, 10, 100}
選択 = inner validation pooled mean log loss最小
同値 = 大きいλ
```

同値判定の絶対許容差は`1e-12`です。実装候補はfloat64、解析gradientの
SciPy L-BFGS-B、最大1,000 iteration、gradient infinity norm tolerance
`1e-8`です。未収束はfail-closedです。
SciPy / NumPy追加とこのoptimizerの採用はDecision checkpointまで未承認です。

## 5. Development fold

2026-01-01〜07-23は探索済みなので、結果はretrospective developmentとだけ
呼びます。実行が将来承認された場合のouter shadowは次です。

| Outer | Refit data | Shadow evaluation |
|---|---|---|
| 2026-04 | 2026-01-01〜03-31 | 04-01〜04-30 |
| 2026-05 | 2026-01-01〜04-30 | 05-01〜05-31 |
| 2026-06 | 2026-01-01〜05-31 | 06-01〜06-30 |
| 2026-07 partial | 2026-01-01〜06-30 | 07-01〜07-23 |

各outerで、2026-03からouter直前月までをinner validation月とし、その直前月
末までを2026-01-01開始のexpanding trainingにします。候補λごとに利用可能な
全inner validation raceのlog lossをpoolし、outer結果を開く前にλを1つ選び
ます。その後outer直前日まででrefitします。

最低実行条件:

- 各outerに48適格レースかつ2開催節
- pooledで300適格レースかつ10開催節

不足時は結果を見て月を併合したり別モデルを追加せず、
`INCONCLUSIVE_NO_MODEL_RESCUE` とします。

## 6. 開催節block

bootstrap単位はレースや舟券ではなく芦屋の開催節です。programの
`date`、`title`、`day_number`だけで再構成し、結果を使いません。

新しいblockの条件:

- `day_number == 1`
- titleが変わる
- 前開催日からday numberが1増えない
- 前開催日の翌日ではない

期間端の開催節はpartial blockとしてラベルを付け、一つのblockのまま残します。
境界が曖昧なら日単位へ黙って変更せず停止します。

全期間監査では20開催節を一意に再構成でき、完全18、左打切り1、右打切り1、
曖昧境界0でした。

## 7. Primary analysisとGate B

各outer shadow raceについて次を計算します。

```text
d_r
= negative_log_probability_true_exacta_PL
  - negative_log_probability_true_exacta_baseline
```

Primary statisticは全outer raceの `mean(d_r)` です。outer fold内で開催節を
観測block数と同数だけ復元抽出し、block内の全適格レースを同伴する層別
bootstrapを行います。

```text
resamples: 20,000
generator: PCG64
seed: 20260724
interval: two-sided percentile 95%
```

Gate Bの統計hard passは、95%区間の上限が厳密に0未満であることだけです。
加えて、決定性、30確率の正値・和1、時系列境界、partition漏洩防止、学習内
前処理、未収束時停止の機能テストを全て満たす必要があります。

次は必ず報告しますがhard passにはしません。

- 30クラスmulticlass Brier score
- top-choice hit rate
- calibration curve
- top-label ECE 10等件数bin
- fold別log-loss差
- feature / fold別欠損
- optimizer収束状態

Gate BのECEはpooled outer shadow予測から10等件数binを作ります。E1へ進む
場合はその境界を凍結します。時点不明の市場確率はdescriptiveのみです。

## 8. E1 / E2境界

E1はGate A、P、B通過と別承認後だけ開始します。

- 最低300適格レース
- 最低3暦月
- 最低12開催節
- 最大12暦月
- 結果公開前の予測をappend-only保存
- model、係数、特徴、protocol変更時は試行を終了して新versionを開始

CI幅の目標は、未実装モデルの残差を推測して今決めません。Gate B development
bootstrap後、E1開始前のversioned addendumで固定します。最大期間でも最低
条件または目標精度を満たさなければ `INCONCLUSIVE` です。

E2はGate DがNo-Goなので停止中です。購入規則、閾値、stakeは選びません。
自動投票・実資金操作は対象外です。

## 9. 試行台帳

実行が将来承認された場合は、少なくとも次のhashと予測を保存します。

- protocol file
- experiment config
- code commit
- input source SHA集合
- model artifact / coefficient
- prediction timestampと全30確率

全モデル、特徴、閾値、失敗を記録します。外側結果を見た救済変更は同じ試行に
混ぜず、新しいprotocol IDとhashを発行します。
