# FunaYomi 次期方針案

Updated: **2026-07-24**

Status: **internal sub-agent reviewed draft — awaiting review by Tsukino
(the project designer in ChatGPT)**

この文書は、現行の3連単基準モデルとバックテスト結果を受けて、次に何を
検証するかを決めるための設計案です。実装開始の許可ではありません。

`docs/SUBAGENT_DESIGN_REVIEW.md` のCodex内部レビューは反映済みです。
この草案はまだ月野によるレビューを受けていません。月野のレビュー結果は、
山田さんから受け取った後に出典を明記して反映します。内部レビューと
月野のレビューを混同しません。

## 1. 現在わかっていること

1. 平滑化した枠番3連単頻度モデルは一様分布より良いものの、評価期間の
   log lossとBrier scoreでは正規化市場暗黙確率より悪かった。
2. 閾値を上げた見かけ上の黒字は、単一の高配当に依存した。
3. 3分割retrospective pseudo-holdoutでは、検証期間で選んだ閾値8.00が
   次期間に1,573点・的中0・回収率2.10%となり、再現しなかった。
4. clean cohort 1,183レースを120カテゴリへ直接配る現在の方式は、
   単純平均で1カテゴリ約9.9件にすぎない。実際の分布はさらに不均衡である。
5. Turnmarkの歴史オッズは観測時刻不明であり、実際に購入可能だった価格とは
   断定できない。
6. 2026-01-01〜07-23の結果はすでに監査・探索に使用済みであり、今後の
   「完全未使用テスト」として扱えない。

したがって、次に優先すべきなのは閾値の再調整ではなく、確率モデルの構造、
賭式の次元、評価方法、購入可能オッズの時点を分けて改善することです。

## 2. 推奨する二本立て

### Track A — 確率モデル研究

目的は、program cutoffで利用可能と証明できる情報だけを使い、枠番頻度
モデルより較正の良い確率を作れるか確認することです。

唯一のprimary confirmatory bet typeは **2連単** とし、主仮説を次に固定する
案です。

> program特徴Plackett–Luceモデルは、真の未来データにおける2連単の
> log lossを、平滑化枠番頻度モデルより改善するか。

各賭式の役割:

1. 2連単: primary。モデル選択とconfirmatory evaluationの対象
2. 単勝: 1着周辺確率の診断だけに使うsecondary
3. 3連単: 同じ順位モデルから導く確率整合性とsecondary evaluation

単勝・3連単のROIを見てprimaryを切り替えません。賭式を増やした理由は、
利益が出そうだからではなく、3連単より少ないカテゴリで確率モデルの
妥当性を検証しやすいからです。全賭式・全モデル・全購入規則の試行を
同じ台帳へ残します。

clean cohort 1,183レースを単純にカテゴリ数で割ると、参考値は次の通りです。

| 賭式 | 結果カテゴリ数 | 1カテゴリあたり参考件数 |
|---|---:|---:|
| 単勝 | 6 | 約197 |
| 2連単 | 30 | 約39 |
| 3連単 | 120 | 約10 |

これは実際の適格件数や分布を保証しません。Turnmark原本に `win` と
`exacta` のオッズ・払戻キーが存在することだけは確認済みですが、全期間の
完全性、欠場、F/L、返還、不成立、同着はまだ賭式別に監査していません。

また、現在のprogram availabilityは `pre_race_timestamp_unverified` です。
programという名称だけを根拠に事前情報と見なしません。Gate Pで特徴ごとに
次を契約化します。

- providerとsource path
- snapshot `acquired_at`
- provider `observed_at` の有無
- race closeとの時間差
- 許可するprediction cutoff

歴史programのas-of時点を証明できない場合、既存データはretrospective
developmentに限定します。真の未来holdoutでは、結果公開前に取得・保存した
program snapshotだけを使います。

### Track B — 購入可能価格の研究

目的は、期待値計算へ使うオッズが予測時点で実際に観測・購入可能だったかを
追跡できる状態にすることです。

必要条件:

- `observed_at`、`retrieved_at`、source URL、原本SHAを保存
- 予測生成時刻がオッズ観測時刻より後、レース締切より前であることを検証
- 同一レースの複数時点スナップショットを上書きしない
- 欠測・遅延・取得失敗時は予想を出さない
- 利用条件が確認できる合法・安定・低頻度の取得方法だけを採用
- BOAT RACE公式サイトの無許可高頻度スクレイピングを作らない

使用可能な時刻付きオッズ源はまだ選定していません。データ源調査と収集開始は、
別の明示的な判断ゲートです。これが成立しない間、正式な未来評価はlog loss、
Brier score、較正だけとし、EV選択・ROIは
`historical_snapshot_time_unknown` による探索結果に限定します。

経済評価では、decision時点で観測したオッズ、実払戻、decision後の価格変化を
分離し、締切までに表示edgeが消えた割合も記録します。

## 3. 次の確率モデル候補

### 3.1 比較対象

複雑なモデルだけを単独で評価せず、同じfoldで次を比較します。

1. 一様分布
2. 現行の平滑化枠番頻度モデル
3. 枠番だけのPlackett–Luceモデル
4. program特徴を使う正則化Plackett–Luceモデル
5. 正規化市場暗黙確率

gradient boosting等は、この段階では追加しません。透明な順位モデルが
基準モデルを上回らないうちに候補数を増やすと、多重比較だけが増えるためです。

### 3.2 Plackett–Luceを候補にする理由

各艇 `i` のprogram特徴 `x_i` と係数 `β` から、正の強さを次で定義します。

```text
s_i = exp(x_i β)
```

primaryの2連単 `a-b` は次の確率です。

```text
P(a-b)
= s_a / Σs
× s_b / (Σs - s_a)
```

学習目的は、実際の1着・2着に対するtop-2 partial log likelihoodとL2正則化
です。3連単 `a-b-c` はsecondaryとして次で導きます。

```text
P(a-b-c)
= s_a / Σs
× s_b / (Σs - s_a)
× s_c / (Σs - s_a - s_b)
```

この方式には次の利点があります。

- 120カテゴリを独立に数えず、艇の強さを賭式間で共有できる
- 1着、2着、3着の順序構造を表現できる
- 全組み合わせの確率和を1にできる
- 係数と使用特徴を説明できる
- 単勝、2連単、3連単を同じ潜在強度から比較できる

既知の限界としてIIA（他艇からの独立性）仮定があります。艇同士の相互作用や
レース展開を完全に表す生成モデルとは見なさず、透明な順位基準モデルとして
評価します。

### 3.3 program cutoffで使う候補特徴

- entry number
- racer rank
- national / local win rate
- national / local top-2 / top-3 percent
- average start timing
- flying / late count
- motor top-2 / top-3 percent
- boat top-2 / top-3 percent
- weight
- 欠損indicator

禁止:

- odds、払戻、着順、決まり手、結果側ST
- テスト期間全体から計算した平均・標準偏差・カテゴリ
- 観測時刻が確定していないpreview特徴
- 結果を見てから追加した特徴や交互作用

標準化、欠損補完、カテゴリ符号化も学習期間だけでfitします。

「必要最小限の交互作用」のような曖昧な追加は認めません。実装前の
machine-readable protocolで、次を全て列挙してhashを固定します。

- 使用する特徴block
- 連続値の変換と標準化
- racer rank等の符号化
- 欠損補完とindicator
- 許可する交互作用の完全な一覧
- L2候補集合
- optimizerと停止条件
- calibration手法と候補

外側foldの結果を見てこの集合を変えた場合は、新しいprotocolと試行番号を
発行します。

### 3.4 較正

予測精度の主目的はtop-1的中率ではなく、確率の較正です。

- primary: log loss
- secondary: Brier score、calibration curve、ECE、top-choice hit rate
- calibration手法を使う場合はvalidation期間だけでfit
- calibration手法も1候補として試行数へ数える
- 高EV帯は予測確率、実績頻度、標本数を同時に表示

## 4. 賭式拡張の設計

2連単を採用する場合、3連単専用コードへ条件分岐を足し続けず、最小限の
賭式境界を設けます。

```text
Wager specification
├─ canonical combinations
├─ odds normalization
├─ payout normalization
├─ outcome / multiple-winner representation
└─ refund and settlement policy
```

最初に必要なのは機能実装ではなく、2連単の全期間監査です。

監査項目:

1. 全レースで30通りが一意に存在するか
2. `0`、null、型不正、余分・欠落キー
3. 勝ちオッズと払戻の整合
4. 欠場艇を含む販売対象外組み合わせ
5. F/L返還と、オッズ再計算後払戻の差
6. 不成立、同着、複数払戻
7. 学習、予測、精算それぞれの適格件数
8. Turnmark原本SHAと監査期間

監査に合格するまで、2連単の収益バックテストを実行しません。

## 5. 評価計画

### 5.1 既存期間の扱い

2026-01-01〜07-23はすでに結果を見ています。ここでの再評価は
**development / retrospective exploration** と明記し、最終性能と呼びません。

開発中のモデル比較には、月単位のnested expanding-windowを使います。

```text
外側training内をさらに時系列分割
→ 内側validationで前処理・L2・較正を選択
→ 外側shadow foldを一度だけ評価
→ 1か月進めて繰り返す
```

fold境界、モデル候補、特徴、正則化候補、較正方法、閾値候補は実行前に
機械可読設定へ固定します。外側shadow foldをモデル・特徴・前処理・較正の
選択へ再利用しません。外側結果を見て候補を増やした場合は、別protocol・
別試行として記録します。

不確実性の再標本化は、舟券や単一レースを独立と見なしません。同一開催内の
相関を保つため、開催または開催日blockでbootstrapします。

### 5.2 真の未来holdout

正式な性能主張に使えるのは、この計画の承認後に新しく蓄積するデータだけです。

確率品質と経済成績を別holdoutにします。

### E1 — probability holdout

log loss、Brier score、較正だけをconfirmatoryに評価します。

提案する最低条件:

- holdout開始日は方針承認時に固定
- 最低300の適格芦屋レース
- かつ最低3暦月
- 予測を結果公開前に保存
- モデル、係数、特徴定義をholdout中に変更しない
- 変更が必要なら、その時点でholdoutを打ち切り、新しい試行として開始

300レース・3か月は最低線であり、十分な証拠を保証しません。開始前に
development dataの開催日block bootstrapで、paired log-loss差の目標CI幅に
必要な標本数を定めます。終了は「必要標本数と3暦月の遅い方」、最大12暦月と
し、最大期間で精度不足なら `INCONCLUSIVE` と報告します。

### E2 — economic holdout

Gate Dを通過した時刻付き購入可能オッズがある場合だけ、EV・仮想購入・ROIを
confirmatoryに評価します。

- 購入規則は1つだけ事前固定
- decision oddsと実払戻を分離
- 予測、選択、オッズsnapshotを結果公開前にappend-only保存
- 必要標本数または目標CI幅と、最大終了期間を開始前に固定
- E2結果を見て閾値・top N・最大投資額を選ばない

E1、E2ともshadow evaluationです。自動投票や実資金操作はしません。

append-only recordには次を含めます。

- protocol hash
- experiment config hash
- code commit hash
- input data / source hash
- model artifact / coefficient hash
- prediction timestamp、prediction、selection

### 5.3 報告する指標

予測品質:

- log loss
- Brier score
- calibration / ECE
- top-choice hit rate
- 同じcutoffの市場価格がある場合だけ、同一foldの市場暗黙確率と公平に比較

時点不明のTurnmark市場確率は、より遅い情報を含む可能性があるため、
descriptive referenceに限定します。

仮想購入:

- 対象レース、購入レース、見送りレース
- 購入点数、総投資、総払戻、返還
- 的中数、回収率、損益
- 最大連敗、最大ドローダウン
- 月別、オッズ帯別、EV帯別
- 最大払戻1件が全払戻へ占める割合
- 最大的中1件を除いた感度分析
- 開催または開催日block bootstrapによる不確実性区間

最大的一件を除く分析は実際の払戻を改変するためではなく、成績が一件に
依存していないかを示す補助指標です。

## 6. 判断ゲート

### Gate A — 2連単データ契約

Go条件:

- 全監査対象レースについて、30通り、払戻、例外、返還を再現可能に
  正規化できる
- 予測前情報と結果情報を分離できる
- 壊れたデータを安全に除外・停止できる
- 適格件数と除外理由を期間別に報告できる

No-Go:

- 返還や不成立を安全に精算できない
- primaryのモデル比較に必要な適格件数を確保できない

### Gate P — program as-of契約

Go条件:

- primary特徴ごとにprovider、source path、`acquired_at`、`observed_at`の有無、
  race closeとの時間差、prediction cutoffを記録できる
- retrospective developmentとfuture holdoutを区別できる
- future holdoutでは結果公開前に保存したsnapshotだけを使える

No-Go:

- 歴史programの時点を証明できないデータをconfirmatory future evaluationへ
  混ぜる
- 結果公開後の上書きや後知恵の特徴追加を検出できない

### Gate B — 確率モデル

Gate A / P通過後、protocolへ次の数値基準を固定して判定します。

- primary statisticは、各外側shadow raceの
  `log_loss_PL - log_loss_frequency_baseline`
- 開催日block bootstrapの95%区間の上限が `0` 未満
- `K >= 3` の外側foldのうち `ceil(2K / 3)` 以上でlog lossが改善方向
- pooled Brier差は `Brier_PL - Brier_baseline <= 0`
- 10個の等件数binで計算するECEはbaseline比 `+0.01` 以内
- 決定性、確率和、漏洩防止テストを満たす

ここでいう95%区間の方式、blockの定義、ECEのbin境界、欠測時の扱いは実行前に
protocolへ固定します。基準を満たさない場合、外側結果を見ながら特徴やモデルを
追加せず、「基準モデル改善を確認できず」と記録します。変更案は新しいprotocol
として次の試行へ分けます。

### Gate D — 購入可能オッズ

Go条件:

- 利用条件を確認できる、適法で安定した時刻付きオッズ源
- 予測時点と購入締切の順序を検証可能
- decision時点のsnapshotと実払戻を分離可能
- 取得失敗時のfail-closed

満たさない場合、EV・ROIは探索的な歴史研究に限定し、E2、UI、当日分析へ
進みません。

### Gate E1 — 真の未来における確率品質

開始条件:

- Gate A / P / Bを通過
- primaryモデル、baseline、特徴、係数、protocolを凍結
- 開始日、必要標本数、目標CI幅、最大12暦月を固定
- 結果公開前の予測をappend-only保存

終了時は、最低300適格レースかつ3暦月を満たしたうえで、Gate Bと同じ
primary statistic、block bootstrap、Brier、ECEを一度だけ計算します。
95%区間の上限が `0` 未満なら主仮説をsupport、最大期間でも必要標本数や
目標CI幅へ達しなければ `INCONCLUSIVE`、それ以外はnot supportedとします。

### Gate E2 — 真の未来における経済評価

開始条件:

- Gate Dを通過
- 購入規則、decision cutoff、1点stake、最大race exposureを1組だけ固定
- 必要標本数または目標CI幅と、最大終了期間を固定
- 予測、選択、decision oddsを結果公開前にappend-only保存

回収率、購入数、最大連敗、最大ドローダウン、開催日block bootstrap区間、
最大払戻1件を除く感度分析を必ず報告します。頑健な正の経済成績を主張できる
条件は、`ROI - 1.0` の95%区間の下限が `0` を上回り、
最大払戻1件を除いても損益の符号が正のままであることです。満たさない場合も
結果を保存し、閾値やtop NをE2上で選び直しません。

### Product Gate — UI・当日利用

再検討の必要条件:

- Gate E1を通過
- EV・買い目を表示する場合はGate D / E2も通過
- データ遅延・欠測時のfail-closedとリスク表示を設計済み
- 山田さんが別途、UI・当日利用の開始を承認

このゲートを通っても、自動投票・実資金操作は対象外です。

## 7. 方針を承認した場合の作業順

現時点では、どの作業packageも開始承認されていません。修正版Option Aを
選んだ場合でも、最初の承認範囲はWork package 0だけとし、その結果を見て
実装へ進むか再判断します。

### Work package 0 — 監査とresearch protocol

- Turnmarkの2連単構造を全期間監査
- program特徴のas-of可用性をfield単位で監査
- 主仮説、特徴、前処理、fold、選択基準、停止条件をprotocolへ固定
- 合法な時刻付きオッズ源を、収集開始せず調査
- `docs/DATA_CONTRACT.md` へ追記
- Gate A / Pの結果と、Gate B用protocolをレビュー

### Decision checkpoint — 実装するか

- Gate A / PがGoなら、賭式境界とモデル実装の開始可否を山田さんが判断
- いずれかがNo-Goなら、停止またはOption B / Cへの変更を判断
- 数値依存とCI追加をこの時点で承認

### Work package 1 — 賭式境界

- 現行3連単動作を壊さない賭式仕様を追加
- schema versionと互換方針を決定
- 2連単の取得、正規化、精算、text / JSON
- 例外系を含む自動テスト

### Work package 2 — 確率モデル

- 枠番Plackett–Luce
- program特徴Plackett–Luce
- 学習期間限定の前処理
- 係数、特徴、支持数、fingerprint
- 単勝・2連単・3連単の確率整合性

### Work package 3 — 事前固定nested walk-forward

- machine-readable experiment manifest
- 内側validationと外側shadow foldを分けたexpanding monthly folds
- baseline、較正、全試行台帳
- 開催日block bootstrapによる予測品質
- 再現レポート
- Gate B判定

### Work package 4 — E1 probability holdout

- 開始日、必要標本数、CI幅、最大期間を固定
- 結果前の予測をappend-only保存
- 完了までモデルを凍結
- 完了時に一度だけ正式評価

### Work package 5 — E2 economic holdout

- Gate D通過後だけ開始
- 購入規則とdecision cutoffを1組だけ固定
- decision oddsと選択をappend-only保存
- 完了時に一度だけ経済評価

Work package 0のオッズ源調査は、候補と利用条件を読むところまでです。
データ源採用や継続収集は別承認とします。

## 8. 技術上の未決定

Plackett–Luceの安定した最適化には数値計算ライブラリが有力です。

候補:

1. `numpy` + `scipy`を明示的に追加し、versionを固定
2. 標準ライブラリだけで最小optimizerを実装

推奨は1です。既存コアは実行時依存なしですが、統計最適化を独自実装するより、
十分に検証された数値計算を使う方が正しさと再現性を高めやすいためです。
依存追加はDecision checkpointでの明示的な承認事項とします。

数値依存を追加する時点でGitHub Actionsを導入し、`pyproject.toml`で宣言する
最小Pythonと、その実装時の安定版Pythonのmatrixで、install、全unit test、
compile確認を実行します。現在はGitHub Actionsもopen PRもありません。

その他の未決定:

- feature interactionの固定集合
- calibration手法
- nested expanding-windowの具体的なfold境界
- Gate B / E1の目標CI幅と必要標本数
- E2の購入規則、目標CI幅、最大期間
- 時刻付きオッズ源
- 未来holdout開始日

## 9. 選択肢

### Option A — 監査先行の二本立て（草案内の暫定推奨）

- 最初は2連単・program as-of・オッズ源の監査とprotocol策定だけ
- Gate A / P後に、2連単primaryのPlackett–Luce実装を再判断
- Track Bの時刻付きオッズ源は別ゲートで調査
- 単勝は診断、3連単はsecondaryとして維持
- UI、当日予想、自動投票へは進まない

長所:

- 確率モデルの問題と価格時点の問題を分離できる
- 3連単より低次元でモデル妥当性を確認できる
- 将来データを待つ間に基礎研究を進められる

短所:

- 初期賭式3連単からのスコープ拡張
- 監査、schema、テストの追加が必要
- 監査後に実装しない判断となる可能性がある
- 厳格なprotocolと試行台帳が必要

### Option B — 3連単のままモデルだけ改善

- Plackett–Luceとprogram特徴だけを追加
- 賭式schemaを広げない
- 時刻付きオッズ源は別ゲート

長所:

- 初期スコープを維持
- 実装差分を小さくできる

短所:

- 120結果の分散が大きく、モデル差を検出しにくい
- モデルの基本能力を診断しにくい

### Option C — データ蓄積を優先

- 新モデル・新賭式を実装しない
- 時刻付きオッズ源と未来holdout設計だけを確立
- 十分な新規データ後にモデル開発を再開

長所:

- 最も強い不確実性へ直接対処
- 後付け最適化を増やさない

短所:

- 当面のモデル研究が進まない
- 時刻付きオッズ源が見つからない場合、停滞する

## 10. 月野へのレビュー依頼事項

この草案を月野へ渡す際は、少なくとも次を確認します。

1. 2連単を唯一のprimary confirmatory bet typeに固定する主仮説は妥当か
2. Gate A → P → B → D → E1 → E2 → Productの順序に抜けがないか
3. Plackett–Luceのtop-2 partial likelihood、L2、IIAの扱いは妥当か
4. program特徴のas-of契約で未来情報漏洩を防げるか
5. nested expanding-windowと開催日block bootstrapは適切か
6. Gate Bの95%区間、fold整合、Brier、ECE `+0.01`という基準は妥当か
7. E1 / E2の分離、最低300レース・3暦月・最大12暦月は妥当か
8. Work package 0だけをGo候補とし、schema・モデル実装をHoldする境界は
   妥当か
9. 見落としている停止条件、データ契約、倫理・プロダクト上の危険はないか

レビューでは、blocking issue、修正推奨、承認できる点を分け、根拠も記録して
もらいます。

## 11. 暫定推奨と決定待ち

この草案におけるCodexの暫定推奨は、
**監査先行のOption Aを条件付きで採用すること**です。これは月野の見解では
ありません。

Go / Hold / No-Goは次の通りです。

- Go候補: 2連単全期間監査、program as-of監査、research protocol策定、
  合法な時刻付きオッズ源の調査
- Hold: 賭式schema、Plackett–Luce、nested walk-forward、future holdoutの実装
- No-Go: UI、当日予想、収益性主張、自動投票・実資金操作

次に山田さんが決める事項:

1. 月野のレビュー結果を反映した後、Option A / B / Cのどれを採用するか
2. Option Aなら、Work package 0だけを開始してよいか
3. 2連単を唯一のprimary confirmatory bet typeとする主仮説でよいか
4. 合法な時刻付きオッズ源の調査を含めてよいか

`numpy` / `scipy`、schema、モデル実装は、Gate A / P後のDecision checkpointで
別途判断します。月野のレビューと山田さんの決定までは新しいマイルストーンを
開始しません。
