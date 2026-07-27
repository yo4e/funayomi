# FunaYomi Roadmap

Updated: 2026-07-27

このロードマップは、FunaYomiを「小さく検証し、結果が悪くても正直に止められる」順序で進めるためのものです。

## Phase 0 — Define before building

Status: **complete**

Goal: 会話履歴がなくても目的と次の作業を再構成できる状態にする。

Deliverables:

- `README.md`
- `AGENTS.md`
- `docs/PROJECT_PLAN.md`
- `docs/ROADMAP.md`
- `docs/HANDOFF.md`

Exit condition:

- 初期対象、データ源、制約、非目標、次の判断ゲートがリポジトリに記録されている

## Phase 1 — Data audit and canonical dataset

Status: **complete (2026-07-24)**

Goal: Turnmark APIの意味と品質を確認し、芦屋の過去レースを再現可能な形で正規化する。

Work:

1. 数日分のAPIレスポンスを保存して構造を確認
2. 芦屋 `stadium_number = 21` の抽出を確認
3. オッズと結果の意味、時刻、欠損を調査
4. 3連単120通りの正規化ルールを決定
5. 欠場、返還、不成立、同着、データ欠損の扱いを決定
6. 予測可能情報と結果情報を分離
7. データ辞書と検証ルールを文書化
8. 小さな検証用データセットを作成

Decision gate:

- Turnmarkのオッズは時点未確認の歴史スナップショットとして、計算核の
  探索的バックテストに限定して使用する
- 3連単を初期対象として確定。芦屋1,284レース、clean cohort 1,183レースを
  確認し、平滑化120カテゴリ基準モデルには十分と判断した

Exit condition:

- 同じ入力から同じ正規化データを作れる
- データの意味を断定できない箇所が明記されている
- 未来情報漏洩の境界が固定されている

## Phase 2 — Transparent probability baseline

Status: **complete (2026-07-24)**

Goal: 芦屋の各着順組み合わせへ、説明可能な確率を割り当てる。

Work:

1. 一様分布ベースライン
2. 芦屋のコース別歴史頻度ベースライン
3. 平滑化された条件付き確率モデル
4. 120通りの確率和を1へ正規化
5. 各推定の根拠とサンプル数を保存
6. 時系列外データで較正を評価

Decision gate:

- 平滑化枠番頻度モデルは評価263レースで一様分布より良いが、市場暗黙確率
  より悪かった
- 個別選手・モーター等への細分化は行わず、まず基準モデルの未使用期間評価を
  優先する

Exit condition:

- 同じ学習期間から同じ確率が再現される
- 実際の結果を使わず予測できる
- 較正指標と弱点が報告される

## Phase 3 — Expected-value ranking engine

Status: **complete (2026-07-24)**

Goal: 予測確率とオッズから期待値を計算し、買い目または見送りを返す。

Work:

1. オッズとの結合
2. 期待回収率と期待利益率の計算
3. 期待値順ランキング
4. 閾値による選別
5. 欠損・異常値の除外
6. `PASS` 判定
7. 人間が読める根拠表示
8. `RESEARCH_CANDIDATES`、`actionable: false`、返還確率未モデル化を明示

Exit condition:

- 全買い目の計算結果を監査できる
- オッズだけから作った市場確率と独立モデルを区別している
- 条件を満たさないレースを正しく見送れる

## Phase 4 — Walk-forward backtest

Status: **research core complete — confirmatory future holdout not started**

Goal: 未来情報なしで、期待値閾値ごとの過去成績と不確実性を測る。

Work:

1. 時系列の学習・検証・最終テスト期間を決める
2. 100円固定購入を実装
3. 複数の期待値閾値を比較
4. 回収率、的中率、購入数、最大連敗、最大ドローダウンを計算
5. 月別・オッズ帯別・期待値帯別に分解
6. 複数試行による過剰適合を記録
7. 信頼区間または再標本化による不確実性を表示

Decision gate:

- 正の成績が偶然や後付け調整ではないと判断できる証拠があるか
- UIへ進む価値があるか

Exit condition:

- 完全に未使用だった最終期間で評価が完了
- 悪い結果も含めてレポートが保存される
- 再現コマンドまたは手順が文書化される

Current evidence:

- 学習: 2026-05-01〜06-15、clean 253レース
- 評価: 2026-06-16〜07-23、264レース
- 事前固定した期待回収率閾値: 1.00
- 100円固定、閾値以上の全組合せ
- 21,269組購入、54的中、回収率0.8219、損益-378,760円
- 最大連敗16、最大ドローダウン825,540円
- これはオッズ時点未確認の探索的結果で、収益性や実購入可能性を示さない
- 3分割の閾値選択では4月に閾値8.00を選んだが、5月1日〜6月15日の
  固定テストは1,573点、的中0、回収率0.0210、損益-154,000円
- 検証期間の黒字は188,190円の高配当1件に依存し、次期間で再現しなかった
- 詳細: `docs/THRESHOLD_HOLDOUT_STUDY.md`
- 複数foldのrolling walk-forward、真に未使用の将来期間、不確実性評価は
  未実施

### Research hardening and Work package 0

Status: **complete (2026-07-24)**

月野レビュー後、山田さんはOption A、2連単primary、Work package 0、
Issue #1 hardening、MITを承認しました。

Completed:

- Issue #1の出力をresearch-only / non-actionable化
- 返還確率を含まないpoint estimateであることをcode / README / data contractへ
  明記
- Python 3.9 / 3.14の最小GitHub Actions CI
- MIT `LICENSE`
- 2連単全期間監査:
  Gate A conditional Go、2連単固有clean 1,184レース
- program as-of監査:
  16特徴は完全、historical Gate P No-Go
- source調査:
  prospective program候補はHold、Gate D No-Go
- machine-readable research protocol:
  仮説、特徴、fold、開催節bootstrap、停止条件を固定

Boundary at completion of Work package 0:

- Conditional Go: retrospectiveな2連単probability contract
- Hold: 賭式schema、Plackett–Luce、数値依存、nested evaluation、E1
- No-Go: historical programによる確認的評価、価格収集、E2、UI、当日予想、
  収益性主張、自動投票・実資金操作

この時点では、次の判断を公式翌日番組LZHの確認としていました。その後、
山田さんはLZHを将来候補としてHoldし、次の別packageを承認しました。

### Turnmark exacta strategy sandbox

Status: **complete (2026-07-27)**

Authorization:

- Turnmarkだけを使う
- retrospective hypothesis generationだけに使う
- 全出力をnon-actionableにする
- Gate P / D、確認的protocol、UI、当日予想、自動投票へ拡張しない
- 公式翌日番組LZHは廃案にせず、将来prospectiveの候補としてHoldする

Completed:

- schema v3: 2連単30通り、払戻、結果状態、学習・評価・精算適格性
- program特徴Plackett–Luceとα=1枠番2連単頻度baseline
- expanding inner validationによるL2選択とouter 4fold
- 正規化市場確率と `λ ∈ {0, 0.25, 0.5, 1}` の幾何blend
- 同一1,000円race budgetのprogram / blend × single / dutch 4方式
- 開催節共通resample、20,000 bootstrap
- 全候補、失敗、月別・開催節別結果、fingerprintのcompact ledger

Evidence:

- program log loss 2.6906、頻度baseline 2.8001
- 4fold中3fold改善、pooled差 -0.1095:
  Gate S `PASS_RETROSPECTIVE_SIGNAL_CANDIDATE`
- 市場log loss 2.4999でprogramより良く、blendは全fold `λ=0`
- `program_single`: 回収率0.3112、損益-506,300円、最大DD 524,000円
- `program_dutch`: 回収率0.6081、損益-288,070円、最大DD 307,920円
- blend 2方式: 735レース全PASS、購入0
- dutchはsingleより下方リスクを改善したが、回収率bootstrap 95%区間
  0.4590〜0.7719で、収益候補ではない

Current boundary:

- Gate P / DはNo-Goのまま
- Gate Rはdescriptive Paretoだけで、scalar winnerなし
- Gate U locked future Turnmark replicationは未承認
- 同じouter期間へ結果を見た救済調整をしない
- LZHの利用条件・field監査・収集は、将来必要になった場合だけ別判断

Details:

- `docs/TURNMARK_STRATEGY_SANDBOX.md`
- `protocols/turnmark_exacta_strategy_sandbox_v1.json`
- `experiments/turnmark_exacta_strategy_sandbox_v1.json`

## Phase 5 — Web UI

Status: **blocked by Product Gate**

Goal: モバイルで期待値ランキングとバックテストを読める研究用UIを作る。

Candidate screens:

- Project explanation and limitations
- Date / race selector
- Expected-value ranking
- Probability, odds, sample support, expected return
- PASS result
- Threshold backtest explorer
- Equity curve and drawdown
- Data-source and timestamp notice

Decision gate:

- 個人用か一般公開か
- 静的生成で足りるか、サーバー処理が必要か
- 予想表示が射幸性を過度に煽らない設計になっているか

Exit condition:

- スマートフォンで主要操作ができる
- 数値の根拠とリスクが同じ画面で確認できる
- 秘密情報や有料AIサービスが不要

## Phase 6 — Current-day analysis

Status: **blocked by Gate P / Gate D**

Goal: 歴史的検証が成立した場合だけ、当日データで期待値を計算する可能性を調べる。

Possible sources:

- Boatrace Open API for same-day program and preview data
- 公式翌日番組LZH（利用許可とfield監査後だけ）
- A separately reviewed, lawful and stable source for current odds

Required work:

- 予測締切時点を固定
- 過去モデルと当日特徴の一致を確認
- オッズの取得時刻と変動を表示
- 期待値が購入時まで維持されたか記録
- データ遅延時は予想を出さない

Not included automatically:

- automated betting
- account login
- payment or bankroll transfer
- aggressive scraping

## Phase 7 — Expansion only if evidence supports it

Status: **optional future**

Possible directions:

- 単勝など、2連単以外の賭式
- 他場への展開
- 水面・風・展示情報を含むモデル
- rolling-window or venue-specific adaptation
- transparent regression or ranking models
- public research reports

Expansion rule:

芦屋の単純モデルが成立しない場合、場や特徴を増やして結果を良く見せるためだけの拡張はしません。拡張には、事前に仮説と評価条件を記録します。

## Project stop conditions

次の場合、実装を止めるか研究結果として終了できます。

- オッズの意味や時点を十分に特定できない
- データ欠損が多く再現可能なバックテストを作れない
- 芦屋だけではサンプルが足りない
- 未使用期間で市場基準を上回る証拠がない
- UI化しても誤解を招く可能性が高い
- 維持コストが研究価値を上回る

「勝てないとわかった」は失敗ではなく、このプロジェクトの有効な結論です。
