# FunaYomi Handoff

Updated: **2026-07-26**

## Current state

Issue #1 の完了条件に対応する **非UIコアが実装済み** です。

- Phase 1 / M1: データ監査とデータ契約 — complete
- Phase 2 / M2: 透明な基準確率モデル — complete
- Phase 3 / M3: 期待値ランキング — complete
- Phase 4 / M4: 固定期間の最小時系列バックテスト — core complete
- Issue #1 pre-merge hardening — complete
- Option A / Work package 0 — complete
- Web UI、当日予想、自動投票 — not started / scope外

実装は Python 3.9以上、実行時依存なしです。

月野はIssue #1研究コアを条件付き承認し、山田さんは2026-07-24に
pre-merge hardening、MIT、2連単を唯一の主仮説とするOption A、
Work package 0、合法な時点付きsource調査を承認しました。承認範囲は完了
しています。

2連単監査はGate A conditional Goでしたが、historical programのGate Pと
時点付きオッズのGate DがNo-Goです。そのため2連単schema、Plackett–Luce、
数値依存、nested evaluation、future holdout、定期収集は開始していません。

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
- `src/funayomi/safety.py` — research-only / non-actionable固定metadata
- `src/funayomi/cli.py` — `fetch` / `rank` / `backtest`
- `scripts/threshold_holdout_study.py` — 事前固定した閾値選択とテストの再現
- `scripts/audit_turnmark_exacta.py` — offlineの2連単全期間Gate A監査
- `scripts/audit_program_asof.py` — program完全性・as-of Gate P監査

### Verification and documentation

- `tests/` — 標準ライブラリ `unittest` の自動テスト
- `docs/DATA_CONTRACT.md` — 実データ監査、型、時点、例外、漏洩境界
- `docs/THRESHOLD_HOLDOUT_STUDY.md` — 閾値3分割実験の設計、全結果、fingerprint
- `docs/EXACTA_DATA_AUDIT.md` — 2連単30通り、払戻、例外、適格件数、Gate A
- `docs/PROGRAM_AS_OF_AUDIT.md` — program候補特徴の完全性とGate P
- `docs/TIMESTAMPED_SOURCE_RESEARCH.md` — prospective program候補とGate D調査
- `docs/RESEARCH_PROTOCOL.md` — 2連単Plackett–Luce v1事前設計の説明
- `protocols/ashiya_exacta_pl_v1.json` — 実行前に固定した機械可読protocol
- `docs/NEXT_PHASE_PROPOSAL.md` — 月野レビュー反映済みの次期方針、二経路の
  判断ゲート、完了したWork package 0、次のDecision checkpoint
- `docs/SUBAGENT_DESIGN_REVIEW.md` — Codexサブエージェントによる内部設計
  レビュー。月野のレビューではない
- `docs/TSUKINO_DESIGN_REVIEW.md` — 月野テンプレクスによるIssue #1と
  次期方針のレビュー要約。Issueコメントを正本とする
- `README.md` — セットアップ、実行例、実測結果
- `docs/ROADMAP.md` — Phase 1〜4 core、hardening、Work package 0の状態
- `.github/workflows/ci.yml` — Python 3.9 / 3.14のinstall、unit test、compile
- `LICENSE` — MIT License

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

## Work package 0 results

### Gate A — exacta contract

- raw期間: 2026-01-01〜2026-07-23、204日、芦屋1,284レース
- raw manifest SHA-256:
  `92ebd6271d04ff2a914986fb21bf62d6f7882822ed53d6c15ab1239468967b65`
- 2連単30 canonical key: 1,284 / 1,284レース
- 38,520値: 正38,364、`0` 156、null / 型不正 / 欠落 / 余分 / 重複0
- `0`: 欠場15艇由来150、原因未定義6値・4レース
- 2連単払戻: 全1,284レースで1件
- 不成立、1〜2着同着、複数払戻: 観測0
- F/L発生31レース、直接返還field 0、導出返還対象404通り
- 2連単固有clean probability cohort: 1,184
- strict full-order clean: 1,183
- 全30正値かつ歴史精算監査可能: 1,265
- 開催節: 20、complete 18、期間端partial 2、曖昧境界0
- 判定: `CONDITIONAL_GO_RETROSPECTIVE_EXACTA_CONTRACT`

Gate Aだけではschema・モデル実装へ進みません。未観測の不成立、top-2同着、
複数払戻は将来fail-closedです。正本は `docs/EXACTA_DATA_AUDIT.md` です。

### Gate P — program as-of

- program候補16特徴: 7,704艇行で欠損0、非数値0
- 6艇program: 1,284 / 1,284レース
- providerの公開・更新・観測timestamp: 0
- sidecar取得と締切を比較可能な1,284件: 全件締切後
- source SHA集合fingerprint:
  `12f45eba27872b505626c2447845d5d695315e8d01b5fe003b6bbf31d6137560`
- 判定: `NO_GO_HISTORICAL_CONFIRMATORY_USE`

公式の翌日番組LZHはprospective snapshot候補ですが、自動取得・保存・派生利用の
許可範囲とfield対応が未確認です。収集は開始していません。正本は
`docs/PROGRAM_AS_OF_AUDIT.md` と `docs/TIMESTAMPED_SOURCE_RESEARCH.md` です。

### Gate D — timestamped purchasable odds

Turnmarkはpost-close・時刻なし、Boatrace Open APIはoddsなし、公式HTMLは
公開API・安定schema・機械取得許可がなく、旧公式サービスは終了済みでした。

```text
Gate D = NO_GO_NO_ADOPTABLE_SOURCE
```

価格collector、E2、EV・買い目UIは開始していません。公式許可または契約済み
feedなしに公式HTMLを収集しません。

### Research protocol v1

`protocols/ashiya_exacta_pl_v1.json` のSHA-256:

```text
5c0f160d0aec74407fd82e05e826cbfdaa920cedcd22a51092926f24814cb24a
```

固定した主な設計:

- primary: program特徴Plackett–Luce対α=1の枠番2連単頻度baseline
- primary metric: race単位log-loss差の平均
- outer shadow: 2026年4月、5月、6月、7月1〜23日
- training-only median補完、欠損indicator、標準化
- L2: `0.01, 0.1, 1, 10, 100`
- 開催節block、outer層別、20,000 bootstrap、PCG64 seed `20260724`
- Gate B hard pass: paired差95%区間の上限 `< 0`
- Brier、ECE、較正、fold別差はsecondary
- E1最低線: 300適格レース、3暦月、12開催節、最大12暦月

protocolはdesign frozenですが `execution_status = HOLD_GATE_P_NO_GO` です。
モデルやnested評価は実装・実行していません。

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
- 閾値以上があれば `RESEARCH_CANDIDATES`。購入推奨ではない
- text / JSON出力
- JSONに原本SHA、学習fingerprint、α、根拠、支持数、除外理由を含む
- JSON直下に `actionable: false`、
  `strategy_status: historical_research_only`、
  `refund_probability_mode: not_modeled`
- text冒頭に歴史研究専用・実購入判断不可を表示

現行の期待回収率はclean cohort由来の `P(win) × odds` point estimateで、
`P(refund)`を含む厳密な実購入EVではありません。バックテストの総払戻には、
候補確定後に結果から判明した実現返還だけを加算します。

## Backtest ordering and settlement

未来情報漏洩を防ぐ処理順:

```text
過去期間だけでfit
-> programとoddsで仮想候補を固定
-> 固定後にoutcomeを開く
-> 的中、実払戻、返還を精算
```

- ランダム分割なし
- 各選択組み合わせ100円
- 閾値以上の全組み合わせを仮想購入
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
Ran 89 tests
OK
```

GitHub状態:

- Issue #1: open
- 月野テンプレクスの条件付き承認レビュー:
  `https://github.com/yo4e/funayomi/issues/1#issuecomment-5066592698`
- open pull request: 0
- GitHub Actions: Python 3.9 / 3.14 matrixがcommit `8bfc4a9`に対して成功
  - `https://github.com/yo4e/funayomi/actions/runs/30180483790`

ローカルでは全89テスト、`compileall`、`git diff --check`が成功しています。
月野の環境ではcloneと再実行ができなかったため、独立実行証跡はGitHub
Actionsで確認しました。

ローカルCI順序の再現では、macOS付属Python 3.9の初期pip 21.2.4が
`pyproject.toml`のeditable installに未対応で最初のinstallに失敗しました。
workflowどおりpip 26.0.1へ更新後、`pip install -e .`、全89テスト、
`compileall`は成功しました。CIがpip upgradeを先に行う理由として記録します。

実データ統合確認:

- 2026-01-01〜2026-07-23の204日をHTTP取得・キャッシュ
- 芦屋1,284レースを正規化
- 2026-07-23 1Rを学習開始2026-05-01でrank
- 120行、確率和 `0.9999999999999996`
- JSONと人間向け出力を確認
- 閾値10,000で `PASS` を確認
- 同キャッシュの `--offline` バックテストを確認
- 3分割閾値実験を同キャッシュから再実行し、文書値と一致
- 同固定cacheから2連単Gate A監査とprogram Gate P監査を再実行し、文書値と一致

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
10. Turnmark program特徴は値が完全でも
    `pre_race_timestamp_unverified`。historical confirmatory利用はNo-Go
11. 2連単不成立、1〜2着同着、複数払戻は実例0で、将来は契約追加まで停止
12. 2連単の原因未定義`0`が6値・4レースあり、補完しない
13. Plackett–Luce、賭式schema、数値依存、nested評価は未実装・未承認
14. 現行の期待回収率は返還確率を含まないclean cohort由来のpoint estimate
15. 公式翌日番組LZHは利用許可・field対応未確認で、収集未開始
16. 採用可能な時点付きpre-close odds源がなく、Gate D / E2はNo-Go

## Exact restart point

次の再開地点は一つです。

> **山田さんが、公式翌日番組LZHについて利用許可とfield契約を確認し、
> 結果公開前のprospective program snapshot収集だけを次の作業packageとして
> 設計するか判断する。**

この判断までは、外部問い合わせ、定期収集、2連単schema、NumPy / SciPy、
Plackett–Luce、nested evaluation、E1、E2、UIを開始しません。
