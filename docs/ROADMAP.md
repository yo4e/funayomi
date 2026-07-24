# FunaYomi Roadmap

Updated: 2026-07-24

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

Status: **not started**

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

- Turnmarkのオッズを歴史的バックテストに使えると判断できるか
- 3連単を最初の対象にするか、2連単で確率モデルを先に検証するか

Exit condition:

- 同じ入力から同じ正規化データを作れる
- データの意味を断定できない箇所が明記されている
- 未来情報漏洩の境界が固定されている

## Phase 2 — Transparent probability baseline

Status: **blocked by Phase 1**

Goal: 芦屋の各着順組み合わせへ、説明可能な確率を割り当てる。

Work:

1. 一様分布ベースライン
2. 芦屋のコース別歴史頻度ベースライン
3. 平滑化された条件付き確率モデル
4. 120通りの確率和を1へ正規化
5. 各推定の根拠とサンプル数を保存
6. 時系列外データで較正を評価

Decision gate:

- 基準モデルが単純な歴史頻度より有意に良いか
- データ量がモデルの細分化に耐えるか

Exit condition:

- 同じ学習期間から同じ確率が再現される
- 実際の結果を使わず予測できる
- 較正指標と弱点が報告される

## Phase 3 — Expected-value ranking engine

Status: **blocked by Phase 2**

Goal: 予測確率とオッズから期待値を計算し、買い目または見送りを返す。

Work:

1. オッズとの結合
2. 期待回収率と期待利益率の計算
3. 期待値順ランキング
4. 閾値による選別
5. 欠損・異常値の除外
6. `PASS` 判定
7. 人間が読める根拠表示

Exit condition:

- 全買い目の計算結果を監査できる
- オッズだけから作った市場確率と独立モデルを区別している
- 条件を満たさないレースを正しく見送れる

## Phase 4 — Walk-forward backtest

Status: **blocked by Phase 3**

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

## Phase 5 — Web UI

Status: **blocked by Phase 4**

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

Status: **future**

Goal: 歴史的検証が成立した場合だけ、当日データで期待値を計算する可能性を調べる。

Possible sources:

- Boatrace Open API for same-day program and preview data
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

- 2連単、単勝など他賭式
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
