# FunaYomi Handoff

Updated: **2026-07-24**

## Current state

Issue #1 の完了条件に対応する **非UIコアが実装済み** です。

- Phase 1 / M1: データ監査とデータ契約 — complete
- Phase 2 / M2: 透明な基準確率モデル — complete
- Phase 3 / M3: 期待値ランキング — complete
- Phase 4 / M4: 固定期間の最小時系列バックテスト — core complete
- Web UI、当日予想、自動投票 — not started / scope外

実装は Python 3.9以上、実行時依存なしです。

次期方針は **internal sub-agent reviewed draft / Tsukino review pending /
owner decision required** です。草案では、2連単を唯一の主仮説とする
監査先行Option Aを暫定推奨していますが、新しい賭式、モデル、
future holdoutの実装は開始していません。

## Implemented files

### Core

- `pyproject.toml` — package、Python要件、`funayomi` CLI
- `src/funayomi/cache.py` — 原本・正規化キャッシュ、SHA検証、revision退避
- `src/funayomi/turnmark.py` — Turnmark取得、JSON・有限数検証
- `src/funayomi/normalize.py` — 芦屋抽出、120通り、例外・結果状態の正規化
- `src/funayomi/domain.py` — program / preview / odds / outcome の分離型
- `src/funayomi/model.py` — 対称Dirichlet平滑化付き枠番頻度モデル
- `src/funayomi/ranking.py` — EV計算、降順、`PASS` / `SKIP_DATA`
- `src/funayomi/backtest.py` — 固定期間評価、実払戻、F/L・不成立返還、
  log loss、Brier score、較正
- `src/funayomi/cli.py` — `fetch` / `rank` / `backtest`
- `scripts/threshold_holdout_study.py` — 事前固定した閾値選択とテストの再現

### Verification and documentation

- `tests/` — 標準ライブラリ `unittest` の自動テスト
- `docs/DATA_CONTRACT.md` — 実データ監査、型、時点、例外、漏洩境界
- `docs/THRESHOLD_HOLDOUT_STUDY.md` — 閾値3分割実験の設計、全結果、fingerprint
- `docs/NEXT_PHASE_PROPOSAL.md` — 月野レビュー前の次期方針草案、主仮説、
  判断ゲート、作業package、レビュー依頼事項
- `docs/SUBAGENT_DESIGN_REVIEW.md` — Codexサブエージェントによる内部設計
  レビュー。月野のレビューではない
- `README.md` — セットアップ、実行例、実測結果
- `docs/ROADMAP.md` — Phase 1〜3完了、Phase 4の残作業、次期方針の決定待ち

## Data audit

監査基準:

- Turnmark API commit:
  `34a3b0a15c0e221a71464bcd86b572c4b28f90a7`
- 期間: 2026-01-01〜2026-07-23
- 全国日次JSON: 204日、欠落・JSON構文エラー0
- 芦屋: 107開催日 × 12R = 1,284レース

主な観測:

- 全1,284レースに3連単120キー
- program / preview / odds / result は全件存在
- 欠場15レースで各60オッズが `0`
- F/Lは31レース
- 3連単払戻0件は3レース、複数払戻と1〜3着同着は観測0
- 通常1〜6着が一意に揃う clean cohort は1,183レース
- F/Lなしの勝ち3連単は、1,000倍未満で `odds == payout/100`、
  1,000倍以上の7件も整数表示への切捨てで説明可能

Turnmark は翌日に前日分を取得し、オッズの `observed_at` を保存しません。
したがってオッズは `historical_snapshot_time_unknown` です。開始、前夜、
締切、最終オッズとは断定しません。

APIの固定URLは不変ではなく、過去JSONが後日修正された実績があります。
FunaYomiは初回原本をSHA付きで保存し、明示的refresh時も旧版をrevisionへ
退避します。

詳細は `docs/DATA_CONTRACT.md` が正本です。

## Probability model

初期モデル:

```text
P(c) = (count(c) + α) / (N + 120α)
α = 1
```

- 対象: 芦屋の枠番3連単120カテゴリ
- 学習: clean cohort の勝ち組み合わせ
- 予測入力: `stadium_number`, `program.entry_numbers`
- 不使用: preview、odds、払戻、着順、決まり手、結果側ST
- 時系列境界: 学習日 `<` 予測日。同日の先行レース結果も使わない
- 各推定に組み合わせ観測数、全学習レース数、信頼性ラベルを付与
- 確率和は絶対誤差 `1e-12` 以内で1

個別選手差を使わない意図的に弱い基準モデルです。

## Ranking behavior

```text
期待回収率 = 推定的中確率 × オッズ
期待利益率 = 期待回収率 - 1
```

- 全120行を丸め前EVの降順で返す
- 同値は正規化組み合わせ順
- 閾値比較は `>=`
- 有効120オッズが揃わなければ `SKIP_DATA`
- 閾値以上が0件なら `PASS`
- text / JSON出力
- JSONに原本SHA、学習fingerprint、α、根拠、支持数、除外理由を含む

## Backtest ordering and settlement

未来情報漏洩を防ぐ処理順:

```text
過去期間だけでfit
-> programとoddsで購入候補を固定
-> 固定後にoutcomeを開く
-> 的中、実払戻、返還を精算
```

- ランダム分割なし
- 各選択組み合わせ100円
- 閾値以上の全組み合わせを購入
- F/L艇を含む選択だけ100円返還
- 一意な1〜3着がなく、明示的な空払戻と監査済み例外コードがある
  3連単不成立は全選択を返還
- スタート後の転覆・落水等は返還せず実払戻で精算
- 欠落・型不正・矛盾した結果を返還と推定せず、安全に停止
- 結果異常を購入候補確定前の事後除外条件にしない

返還規則は BOAT RACE 公式ガイドに基づく導出で、Turnmark の返還観測値では
ありません。

## Fixed-split verification result

評価結果を見て閾値を変更せず、次の1条件を実行しました。

- 学習: 2026-05-01〜2026-06-15
- 学習有効レース: 253
- 評価: 2026-06-16〜2026-07-23
- 評価レース: 264
- α: 1
- 閾値: 期待回収率 `>= 1.00`
- stake: 1組100円、該当全組購入

結果:

- 購入レース: 263
- データ除外: 1
- PASS: 0
- 購入組み合わせ: 21,269
- 的中レース: 54
- 投資: 2,126,900円
- 払戻（返還込）: 1,748,140円
- 返還: 217組 / 21,700円
- 損益: -378,760円
- 回収率: 0.8219
- 最大連敗: 16
- 最大ドローダウン: 825,540円

確率品質（価格と勝ち3連単を比較できる263レース）:

| 確率 | log loss | Brier |
|---|---:|---:|
| 平滑化枠番頻度 | 4.2975 | 0.9795 |
| 一様120通り | 4.7875 | 0.9917 |
| 正規化市場暗黙確率 | 3.8119 | 0.9579 |

枠番頻度モデルは一様分布より良いものの、市場より悪い結果です。
確率5〜10%帯は平均予測6.17%に対し実績4.56%で過大推定でした。

この結果は利益保証ではありません。現条件では損失であり、オッズ時点も
未確認です。実購入可能な戦略性能として扱ってはいけません。

## Retrospective threshold pseudo-holdout result

この実験より前に、2026-06-16〜07-23で27閾値を探索済みです。閾値8.00〜
17.12の見かけ上の黒字は、2026-07-06 5R `6-4-2` の319,360円払戻1件に
依存し、17.121では的中が消えました。この試行履歴は
`docs/THRESHOLD_HOLDOUT_STUDY.md` に全て列挙しています。

本実験の計算前に次を固定して1回実行しました。ただし固定テスト期間の
2026-05-01〜06-15は以前の別実験で学習データとして使用済みです。
本実験内では閾値選択に使っていませんが、完全未観測の将来期間ではないため
retrospective pseudo-holdout と呼びます。

- 学習: 2026-01-01〜03-31
- 閾値選択: 2026-04-01〜04-30
- 固定テスト: 2026-05-01〜06-15
- 候補: `1.00, 1.25, 1.50, 2.00, 3.00, 5.00, 8.00, 10.00,
  12.00, 15.00, 20.00`
- 選択: 購入20レース・200点以上で検証回収率最大、同率は低い閾値

4月の選択結果:

- 選択閾値: 8.00
- 購入: 1,822点 / 182,200円
- 的中: 1
- 払戻: 189,190円
- 回収率: 1.0384
- 損益: +6,990円
- 最大連敗: 157
- 最大ドローダウン: 166,200円
- 唯一の的中: 2026-04-29 11R `4-3-2`、188,190円

固定テスト:

| 方式 | 購入点数 | 的中 | 回収率 | 損益 | 最大連敗 | 最大DD |
|---|---:|---:|---:|---:|---:|---:|
| 閾値8.00 | 1,573 | 0 | 0.0210 | -154,000円 | 168 | 154,000円 |
| 閾値1.00 | 19,289 | 66 | 0.6303 | -713,140円 | 16 | 738,900円 |

閾値8.00の払戻3,300円は全て返還です。高い閾値は投資額と絶対損失を
減らしましたが、選別能力は再現しませんでした。検証の黒字は高配当1件への
適合です。詳細とfingerprintは `docs/THRESHOLD_HOLDOUT_STUDY.md` が正本です。

この結果を見て同じテスト期間へ別の閾値選択規則を試し、正式改善として
扱ってはいけません。

## Verification status

実行コマンド:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

結果:

```text
Ran 72 tests
OK
```

GitHub状態:

- Issue #1: open
- open pull request: 0
- GitHub Actions / combined status: 未設定

実データ統合確認:

- 2026-01-01〜2026-07-23の204日をHTTP取得・キャッシュ
- 芦屋1,284レースを正規化
- 2026-07-23 1Rを学習開始2026-05-01でrank
- 120行、確率和 `0.9999999999999996`
- JSONと人間向け出力を確認
- 閾値10,000で `PASS` を確認
- 同キャッシュの `--offline` バックテストを確認
- 3分割閾値実験を同キャッシュから再実行し、文書値と一致

## Known limits

1. Turnmarkオッズの観測時刻と購入可能時点は不明
2. 1〜5月の一部は後日バックフィル
3. Turnmarkの過去ファイルは後日修正され得る
4. 1,000倍以上のオッズは小数精度を失う
5. 返還フィールドはなく、公式規則と結果コードから導出
6. 基準モデルは枠番だけで、個別選手・モーター差を表現しない
7. 約7か月のデータだけで収益性を断定できない
8. fixed splitとretrospective pseudo-holdoutまで実施。複数foldの
   rolling walk-forward、真に未使用の将来期間、bootstrap不確実性、
   複数試行管理は未実装
9. UI、当日データ、リアルタイムオッズ、自動投票は未実装
10. Turnmark program特徴は `pre_race_timestamp_unverified`
11. Turnmarkの2連単キーはsampleで存在確認しただけで、全期間の30通り、
    返還、不成立、同着、適格件数は未監査
12. Plackett–Luce、賭式schema、数値依存、CIは未実装・未承認

## Exact restart point

次の再開地点は、**実際のChatGPTの月野に
`docs/NEXT_PHASE_PROPOSAL.md` をレビューしてもらい、その回答をリポジトリへ
反映すること**です。Codexのサブエージェントを月野として扱ってはいけません。

月野のレビュー反映後、山田さんが監査先行Option A / 3連単維持Option B /
データ蓄積Option Cのどれを採用するか決めます。

草案内で暫定推奨するOption Aを選ぶ場合も、最初の判断はWork package 0
（2連単全期間監査、program as-of監査、research protocol策定、合法な
時刻付きオッズ源の調査）だけを開始してよいかです。

- Go候補: 上記4つの監査・設計作業
- Hold: 賭式schema、Plackett–Luce、nested walk-forward、future holdout
- No-Go: UI、当日予想、収益性主張、自動投票・実資金操作

この決定まではコードを変更せず、新しいマイルストーンを開始しません。
