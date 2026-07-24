# FunaYomi Project Plan

Updated: 2026-07-24

## 1. Purpose

FunaYomiは、芦屋ボートレースを対象に、過去のレースデータとオッズから各買い目の的中確率を推定し、オッズとの比較によって期待値の高い買い目を抽出する研究用ウェブアプリを目指します。

このプロジェクトは「当てる予想」を大量に出すことではなく、次の問いを検証します。

> 芦屋の公開過去データだけを使った透明な統計アルゴリズムで、市場オッズに対して一貫した価格差を見つけられるか。

結果が「見つからない」でも、研究として有効です。

## 2. Initial scope

### Included

- 芦屋のみ（場コード `21`）
- 過去レースの出走表、直前情報、オッズ、結果
- 3連単を最初の対象候補とする
- 全120通りの確率推定と期待値計算
- 時系列バックテスト
- モバイルフレンドリーな閲覧・検証UI
- 無料・低コストで再現可能なローカル計算

### Excluded from the initial version

- 当日リアルタイム運用
- 自動投票
- 購入アカウント連携
- 有料AI API、LLM API、予想文章生成
- 複数場への拡張
- すべての賭式への同時対応
- 利益を保証する表示

## 3. Terminology

### 推定的中確率

アルゴリズムが、予測時点で利用可能だった特徴だけを使って見積もる確率です。

### 市場暗黙確率

単純には `1 / odds` で表せます。ただし、控除や市場全体の歪みが含まれ、全買い目の合計は通常1になりません。市場の基準比較には使えますが、これだけを独立予測として使ってはいけません。

### 期待回収率

```text
expected_return = predicted_probability × odds
```

- `1.00`：損益分岐の推定
- `1.10`：1円あたり1.10円の期待回収、期待利益率10%の推定
- `0.80`：期待利益率-20%の推定

### Value bet

設定した期待回収率の閾値を超える買い目です。高配当という意味ではありません。

## 4. Data sources

### 4.1 Turnmark API

Initial source of historical data.

- Repository: `https://github.com/turnmark/api`
- Endpoint: `https://turnmark.github.io/api/v1/YYYY/YYYYMMDD.json`
- Available from: current README and observed files start at 2026-01-01
- Data: programs, preview, odds, results
- License: MIT
- Status: unofficial, delayed, no accuracy/completeness guarantee

The 2026-07-24 audit recorded the following in `docs/DATA_CONTRACT.md`:

- オッズ値がどの取得時点を表すか
- 同一日の途中更新履歴が残るか、最終スナップショットだけか
- 欠場、返還、取消、不成立、同着の表現
- 欠損フィールドと型の揺れ
- 芦屋開催日の抽出方法
- 払戻とオッズの整合性

1〜5月の一部は後日バックフィルです。オッズには観測時刻がなく、翌日に
過去データとして取得されます。通常レースでは払戻と整合しますが、
開始・前夜・締切・最終のいずれとも断定せず
`historical_snapshot_time_unknown` とします。

### 4.2 Boatrace Open API

Potential future source for current-day program and preview data.

- Repository: `https://github.com/boatraceopenapi/api`
- Historical endpoint: `https://boatraceopenapi.github.io/api/v1/YYYY/YYYYMMDD.json`
- Current-day endpoint: `https://boatraceopenapi.github.io/api/v1/today.json`
- Approximate update interval: 3 minutes
- Data: programs, preview, results; no odds
- License: MIT

Not required for the first historical backtest.

## 5. Data contract defined in M1

正本は `docs/DATA_CONTRACT.md` です。正規化レースは少なくとも次を分離します。

### Race identity

- date
- stadium_number
- race_number
- closed_at
- grade_number
- day_number

### Entry features available before the race

- entry_number
- racer_number
- rank_number
- age
- weight
- flying_count
- late_count
- average_start_timing
- national_win_rate
- national_top_2_percent
- national_top_3_percent
- local_win_rate
- local_top_2_percent
- local_top_3_percent
- motor_number
- motor_top_2_percent
- motor_top_3_percent
- boat_number
- boat_top_2_percent
- boat_top_3_percent

### Preview features, only if their timestamp is available before the prediction cutoff

- course_number
- start_timing
- exhibition_time
- tilt_adjustment
- weight_adjustment
- wind_speed
- wind_direction_number
- wave_height
- weather_number
- air_temperature
- water_temperature

### Odds

- bet_type
- combination
- odds
- observed_at, if available
- source

### Outcome

- place_number by entry
- winning trifecta combination
- payout
- invalidation/refund flags

Prediction features and outcome fields must be stored separately to reduce accidental leakage.

## 6. First probability model

The first model should be deliberately transparent and weak enough to understand.

### Recommended baseline: smoothed empirical conditional model

For each race, estimate the probability of a 3-boat order as:

```text
P(a-b-c | x)
= P(a is first | x)
× P(b is second | a first, x)
× P(c is third | a first, b second, x)
```

Here `x` begins with a very small set of features, such as:

- 芦屋
- entry number / actual course number
- racer class
- recent or published win-rate bands
- motor performance band

The initial implementation may use frequency tables with Bayesian/Dirichlet-style smoothing so that rare combinations never receive unstable zero or extreme probabilities.

The 120 trifecta probabilities must be normalized to sum to 1 for each race.

### Required baselines

The model must be compared against simple references.

1. Uniform 120-way probability
2. Historical Ashiya trifecta frequency by course/order
3. Market-implied probability normalized across available odds
4. A simple lane/course-only model

A more complex model is useful only if it improves out-of-sample calibration or return over these baselines.

### Later optional models

Only after the baseline is understood:

- transparent multinomial or conditional logistic regression
- Plackett–Luce ranking model
- gradient boosting with explainability and fixed reproducibility

These are classical statistical/machine-learning techniques run locally, not paid generative-AI APIs. They are optional and must not replace the transparent baseline without comparison.

## 7. Expectation ranking

For each valid 3連単 combination:

1. Read the model probability `p`
2. Read odds `o`
3. Compute `expected_return = p × o`
4. Compute `expected_profit_rate = expected_return - 1`
5. Record probability confidence / sample support
6. Sort descending by expected return
7. Apply a configurable minimum threshold
8. Return `PASS` when no combination qualifies

The display should not rank tiny-sample estimates as trustworthy without warning. A high point estimate with little support must be visibly different from a stable estimate.

## 8. Backtest design

### Time split

Never randomly mix earlier and later races.

Example structure:

- Training window: earliest available period
- Validation window: subsequent period used for model/threshold choices
- Test window: final untouched period used once for final assessment

Because the available Turnmark history begins in 2026, the initial sample may be small. If the sample is insufficient, the correct result is to report insufficient evidence, not to tune until profitable.

### Walk-forward evaluation

Preferred later method:

1. Train only on data before date D
2. Predict races on date D
3. Record hypothetical bets and outcomes
4. Advance D
5. Refit or update using only newly past data

### Default betting simulation

- 100 yen fixed stake per selected combination
- No martingale
- No loss chasing
- No bankroll-dependent stake sizing in the first baseline
- Multiple qualifying combinations may be allowed, but total race exposure must be reported

### Threshold experiments

UI may later compare:

- expected return ≥ 1.00
- ≥ 1.05
- ≥ 1.10
- ≥ 1.20
- custom threshold
- top N per race
- maximum total stake per race

Every threshold tested creates multiple-testing risk. The number of tried strategies must be recorded.

## 9. Evaluation metrics

### Prediction quality

- Log loss
- Brier score
- Calibration curve
- Top-choice hit rate
- Probability mass assigned to the actual result

### Betting simulation

- Total stake
- Total payout
- Net profit/loss
- Return on investment
- Number of races considered
- Number of races bet
- Number of combinations purchased
- Hit rate
- Maximum losing streak
- Maximum drawdown
- Profit distribution by month, odds range, expected-value band, and race number

### Uncertainty

Where practical, report bootstrap confidence intervals or resampling-based ranges. A positive historical ROI with a wide interval spanning large losses is not evidence of a reliable edge.

## 10. Web application direction

The core should remain separate from the UI.

Possible eventual structure:

```text
Data ingestion -> normalized local store -> probability model
-> expectation engine -> backtest engine -> web UI
```

Recommended separation:

- deterministic Python core for ingestion, modeling, ranking, and backtest
- local SQLite or columnar files for reproducible data snapshots
- thin web layer that calls the core or reads generated artifacts
- responsive frontend for phone use

The exact framework is intentionally undecided until M1–M4 clarify the data volume and deployment needs.

## 11. Safety and product boundaries

- This is an analysis and research tool, not financial advice or a guaranteed-profit system.
- No automatic betting in the initial roadmap.
- No design intended to increase betting frequency; `PASS` is a first-class result.
- Default backtests use fixed low hypothetical stakes.
- The UI should show sample size, uncertainty, and historical drawdown near expected-value rankings.
- Data provider limitations and timestamps must remain visible.
- No credentials, payment data, or betting account access should enter the repository.

## 12. Design decisions and remaining questions

Issue #1で固定した事項:

1. 初期賭式は3連単
2. 芦屋1,284レース、clean cohort 1,183レースを確認し、平滑化120カテゴリ
   基準モデルを実装
3. 初期モデルはentry numberだけを使い、previewは観測時刻不明のため不使用
4. 予測締切はprogram cutoff
5. preview欠損はnullのまま保存し、resultから補完しない
6. 6艇未満または120オッズ不完備は `SKIP_DATA`
7. 支持数は各推定に表示し、α=1で平滑化
8. 固定期間モデルを実装し、rollingは次段階
9. 11候補から検証回収率で閾値8.00を選んだ3分割pseudo-holdoutは、
   次期間で的中0・回収率0.0210となり、高配当1件への適合と判断

次期方針案:

- `docs/NEXT_PHASE_PROPOSAL.md` に、2連単を唯一のprimary confirmatory
  bet typeとする監査先行案を草案として記録
- `docs/SUBAGENT_DESIGN_REVIEW.md` のCodex内部レビューを草案へ反映済み
- 草案内の暫定推奨はOption Aだが、月野の実レビューと山田さんの決定は未了
- 2連単、数値依存、モデル、future holdoutの実装は未承認
- 最初に進める候補は2連単・program as-of・オッズ源の監査とprotocol策定だけ

未解決で、暗黙に仮定してはいけない事項:

1. Turnmarkオッズの厳密な観測時刻と購入可能時点
2. Turnmark program特徴のas-of可用性
3. 月野の実レビュー、Option A / B / C、監査packageの開始可否
4. nested expanding-windowのfold、複数試行管理、block bootstrap
5. 個別選手・モーター特徴を追加する事前仮説と停止条件
6. future probability / economic holdoutの開始・終了条件
7. UIへ進む最低性能・較正条件
8. 不安定な推定を利益保証と誤解させない公開・deployment形態
