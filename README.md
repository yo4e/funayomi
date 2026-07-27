# FunaYomi（舟読み）

芦屋ボートレースを対象に、過去のレースデータとオッズから各買い目の的中確率を透明な統計アルゴリズムで推定し、期待値順に並べる研究用プロジェクトです。

> 当たる買い目を大量に出すのではなく、推定上「価格に対して割に合う買い目」だけを見つけ、割に合わないレースを見送る。

## 現在地

**Issue #1 の非UIコアと、Turnmark限定の2連単retrospective strategy
sandboxを実装済みです。**

Python 3.9以上と標準ライブラリだけで動きます。ウェブUI、当日予想、
リアルタイムオッズ、自動投票はありません。現在のコアは、時点未確認の
歴史オッズで計算手順を検証するためのものです。出力は常に
`actionable: false` / `historical_research_only` で、実購入判断には使えません。

2連単を唯一の主仮説とする監査先行Option Aは、
[`docs/NEXT_PHASE_PROPOSAL.md`](docs/NEXT_PHASE_PROPOSAL.md) に記録しています。
Codexサブエージェントによる
[`内部レビュー`](docs/SUBAGENT_DESIGN_REVIEW.md) と、最初の設計者である
月野テンプレクスによる
[`実レビュー`](docs/TSUKINO_DESIGN_REVIEW.md) を反映済みです。
Issue #1研究コアは条件付き承認、Option A / Work package 0は支持されました。
山田さんの承認により、Issue #1の安全化とWork package 0の監査・事前設計を
実施しました。

さらに2026-07-27のGate X承認により、時点未確認のTurnmarkだけを使う
`retrospective / non-actionable`な別protocolとして、schema v3の2連単30通り、
program特徴Plackett–Luce、市場blend、同額固定予算のsingle / dutch
portfolioを実装・評価しました。programモデルは弱い頻度baselineより
4fold中3foldでlog lossを改善しましたが、市場暗黙確率には及ばず、購入した
2方式はいずれも大幅赤字でした。詳細は
[`Turnmark 2連単strategy sandbox`](docs/TURNMARK_STRATEGY_SANDBOX.md)です。

公式翌日番組LZHは廃案ではなく、将来prospective snapshotが必要になった場合の
候補としてHoldしています。収集は開始していません。UI、当日予想、
リアルタイムオッズ、自動投票も未実装です。

## 初期スコープ

初期スコープは、できるだけ狭く固定します。

- 対象場：芦屋（場コード `21`）
- 対象データ：前日までに取得可能な過去レースデータ、オッズ、結果
- 賭式：3連単
- 出力：全120通りについて、推定的中確率、オッズ、期待回収率、期待利益率を計算し、期待値順に表示
- 予測方式：有料AI API・LLM APIを使わない、再現可能で説明可能な統計アルゴリズム
- 検証方式：未来情報を混ぜない時系列バックテスト
- 初期運用：研究・検証のみ。自動投票は行わない

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

実行時依存パッケージはありません。インストールせずに使う場合は、各コマンドを
`PYTHONPATH=src python -m funayomi` で実行できます。

## CLI

### 1. データ取得

Turnmark の全国日次JSON原本と、そのSHA-256・取得時刻を保存し、芦屋だけを
別ファイルへ正規化します。

```bash
funayomi fetch \
  --start 2026-05-01 \
  --end 2026-07-23
```

既定キャッシュは `data/cache` です。原本は `raw/turnmark`、正規化後は
`normalized/ashiya` に分離します。通常は既存原本を再取得しません。
Turnmark の原本が後日修正され得るため、明示的な `--refresh` で変化した
原本を取得した場合は以前の版を `raw/turnmark/revisions` へ退避します。

### 2. 期待値ランキング

```bash
funayomi rank \
  --date 2026-07-23 \
  --race 1 \
  --train-start 2026-05-01 \
  --threshold 1.00
```

初回は指定期間の日次データを自動取得します。既存キャッシュだけで再現する
場合は `--offline` を付けます。人間向け出力は既定、機械可読JSONは
`--format json` です。JSONには全120通り、確率、オッズ、期待回収率、
期待利益率、根拠、支持数、除外理由、原本SHA、学習fingerprintを含みます。

JSON直下には `actionable: false`、`strategy_status:
"historical_research_only"`、`refund_probability_mode: "not_modeled"` を
必ず含みます。有効な120オッズが揃わないレースは `SKIP_DATA`、閾値以上の
組み合わせがなければ `PASS`、あれば `RESEARCH_CANDIDATES` を返します。
候補は研究上の分類で、購入推奨ではありません。

### 3. 固定期間バックテスト

```bash
funayomi backtest \
  --train-start 2026-05-01 \
  --train-end 2026-06-15 \
  --eval-start 2026-06-16 \
  --eval-end 2026-07-23 \
  --threshold 1.00 \
  --stake 100
```

学習終了日は評価開始日より前でなければ実行できません。閾値以上の全組合せを
各100円と仮定する歴史研究用の固定ルールです。仮想候補は出走表とオッズだけで
確定し、その後に結果を開いて、実払戻とF/L返還を精算します。ランダム分割や
評価期間内の再学習はしません。

### 4. Turnmark限定2連単strategy sandbox

固定cacheを使い、outer 4fold、inner L2 / blend選択、4つの固定予算方式、
開催節block bootstrapを一括再現します。

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

出力は常に `actionable: false` です。Turnmarkのprogram・オッズ時点を
証明できないため、実購入可能な成績や確認的検証として扱えません。

### 5. テスト

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 基準確率モデル

初期モデルは芦屋の枠番3連単を120カテゴリとして数える、対称Dirichlet
平滑化付き頻度モデルです。

```text
P(組み合わせ c) = (count(c) + α) / (N + 120α)
既定値 α = 1（各組み合わせ1件相当）
```

モデルの予測入力は `stadium_number` と6つの `program.entry_numbers` だけです。
直前情報、オッズ、着順、払戻、決まり手、結果側STは確率特徴に使いません。
同日を含め、予測日以後の結果を学習へ渡すとエラーにします。

これは意図的に弱い、説明可能な基準モデルです。個別選手・モーター差は
表現せず、各レースで同じ枠番分布を使います。全120確率の和は数値誤差
`1e-12` 以内で1になることを検証します。

## 実データでの確認結果

2026-07-24時点の Turnmark commit
`34a3b0a15c0e221a71464bcd86b572c4b28f90a7` を監査しました。

- 2026-01-01〜2026-07-23の連続204日
- 芦屋107開催日、1,284レース
- 全レースで3連単120キー
- 欠場15レースでは各60オッズが `0`
- F/L発生31レース、3連単不成立3レース
- 保守的な学習用 clean cohort は1,183レース

データ構造、型、返還・不成立、オッズと払戻の照合、キャッシュ契約は
[`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md) に記録しています。

### 2連単Work package 0とstrategy sandbox

山田さんの承認後、2連単を唯一のprimary仮説とする前提監査だけを実施しました。

- [2連単全期間監査](docs/EXACTA_DATA_AUDIT.md):
  Gate A `CONDITIONAL_GO`、30キーは1,284 / 1,284レース、
  2連単固有clean cohortは1,184レース
- [program完全性・as-of監査](docs/PROGRAM_AS_OF_AUDIT.md):
  候補16特徴は7,704艇行で欠損0だが、過去snapshotの時点証明がなく
  Gate P `NO_GO_HISTORICAL_CONFIRMATORY_USE`
- [時点付きsource調査](docs/TIMESTAMPED_SOURCE_RESEARCH.md):
  将来program候補はHold、採用可能なpre-close odds源がなく
  Gate D `NO_GO_NO_ADOPTABLE_SOURCE`
- [研究protocol v1](docs/RESEARCH_PROTOCOL.md):
  仮説、特徴、fold、開催節bootstrap、停止条件を固定したが、実行はHold

この監査結果だけでは確認的protocolを開始せず、Gate P / DはNo-Goのままです。
その後、山田さんが別のGate Xとして、Turnmark限定・retrospective・
non-actionableな仮説生成sandboxだけを承認しました。

正式sandbox結果:

| 指標 | program single | program dutch | blend single / dutch |
|---|---:|---:|---:|
| 購入レース | 735 | 735 | 0 |
| 点数 / 的中レース | 735 / 6 | 6,804 / 144 | 0 / 0 |
| 回収率 | 0.3112 | 0.6081 | —（全PASS） |
| 損益 | -506,300円 | -288,070円 | 0円 |
| 最大連敗 | 109 | 22 | 0 |
| 最大ドローダウン | 524,000円 | 307,920円 | 0円 |

programのpooled log lossは2.6906、枠番頻度baselineは2.8001で、
Gate Sは3 / 4 fold改善によりretrospective signal候補を通過しました。
一方、市場暗黙確率は2.4999とさらに良く、inner validationは全foldで
`λ=0`（市場100%）を選択しました。そのためblendは期待回収率1.10以上の
候補を一つも出さず、全PASSでした。

dutchは単点より下方リスクと払戻集中を改善しましたが、開催節bootstrapの
回収率95%区間も0.4590〜0.7719で1を下回りました。収益候補ではありません。
全L2 / λ試行、月別・開催節別結果、fingerprintは
[`正式ledger`](experiments/turnmark_exacta_strategy_sandbox_v1.json)へ保存
しています。future locked replication（Gate U）は未承認です。

固定閾値1.00を後から調整せず、学習2026-05-01〜06-15、評価
2026-06-16〜07-23で一度実行した最小バックテストは次の結果でした。

| 指標 | 値 |
|---|---:|
| 学習有効レース | 253 |
| 評価レース | 264 |
| 購入レース / データ除外 | 263 / 1 |
| 購入組合せ | 21,269 |
| 的中レース | 54 |
| 投資 / 払戻 | 2,126,900円 / 1,748,140円 |
| 回収率 | 0.8219 |
| 損益 | -378,760円 |
| 最大連敗 / 最大ドローダウン | 16 / 825,540円 |

同じ評価期間のうち価格と勝ち3連単を比較できる263レースで、確率品質も
確認しました（log loss / Brier score は小さい方が良い）。

| 確率 | log loss | Brier score |
|---|---:|---:|
| 平滑化枠番頻度モデル | 4.2975 | 0.9795 |
| 一様120通り | 4.7875 | 0.9917 |
| 正規化した市場暗黙確率 | 3.8119 | 0.9579 |

基準モデルは一様分布より良いものの、市場暗黙確率より悪い結果でした。
予測確率5〜10%の帯は平均6.17%に対して実績4.56%で、過大推定でした。

これは収益性を示す結果ではありません。むしろ、現基準モデルと閾値1.00では
評価期間に損失だったことを記録します。Turnmark オッズの購入可能時点も
確認できないため、実行可能な売買戦略の成績として扱えません。

### 閾値を上げた3分割 retrospective pseudo-holdout

本実験の収支を計算する前に規則を固定しました。ただし固定テスト期間の
2026-05-01〜06-15は、以前の別実験で学習データとして使用済みです。
本実験内では閾値選択に使っていませんが、人間にとって完全未観測の将来期間
ではないため retrospective pseudo-holdout と呼びます。

学習を2026-01-01〜03-31、閾値選択を04-01〜04-30、固定テストを
05-01〜06-15とし、11候補から検証回収率最大の閾値を選びました。
最低標本は購入20レース・200点です。

4月は閾値8.00が回収率103.84%で選ばれましたが、その利益は
2026-04-29芦屋11Rの188,190円払戻1件に依存していました。閾値を固定した
次期間では1,573点購入して的中0、返還込み回収率2.10%、損益-154,000円でした。
最大連敗は168、最大ドローダウンは154,000円です。比較用の閾値1.00も
回収率63.03%、損益-713,140円、最大連敗16、最大ドローダウン738,900円でした。

高い足切りの収益性は再現せず、検証期間の高配当へ適合した結果でした。
事前設計、全候補、再現コマンド、データfingerprintは
[`docs/THRESHOLD_HOLDOUT_STUDY.md`](docs/THRESHOLD_HOLDOUT_STUDY.md) に
悪い結果を含めて保存しています。

## 中心となる計算

ある買い目のclean cohort条件付き推定的中確率を `p`、時点未確認の歴史
オッズを `o` とすると、現行出力のpoint estimateは次の通りです。

```text
期待回収率 = p × o
期待利益率 = p × o - 1
```

例：推定的中確率10%、オッズ12.0倍なら、期待回収率は1.20、期待利益率は20%です。

ただし、これは返還確率を含む厳密な実購入EVではありません。settlement-aware
returnには少なくとも `P(win) × odds + P(refund) × refunded_stake` が必要で、
現行モデルは `P(refund)` を推定しません。バックテストの総払戻には、結果から
判明した実現返還だけを加算します。

難しいのは掛け算ではなく `p` の推定です。オッズから逆算した確率だけを
使っても市場価格を言い換えるだけなので、独立した確率モデルが必要です。

## データ源

### Turnmark API — 初期開発の主データ源

- Repository: `turnmark/api`
- Endpoint: `https://turnmark.github.io/api/v1/YYYY/YYYYMMDD.json`
- 対応期間：現行READMEと実データでは2026年1月1日以降
- 含まれるもの：出走表、直前情報、オッズ、結果
- ライセンス：MIT
- 非公式APIであり、正確性・完全性は保証されない

注意：監査により、Turnmark は翌日に前日分を取得し、オッズの観測時刻を
保存していないことが分かりました。通常レースの勝ちオッズは払戻÷100と
一致し、締切・確定相当である可能性は高いものの、開始、前夜、締切、最終の
どれとも断定しません。`historical_snapshot_time_unknown` として扱います。

### Boatrace Open API — 将来の当日情報候補

- Repository: `boatraceopenapi/api`
- Endpoint: `https://boatraceopenapi.github.io/api/v1/YYYY/YYYYMMDD.json`
- 当日用: `https://boatraceopenapi.github.io/api/v1/today.json`
- 約3分間隔で更新
- 含まれるもの：出走表、直前情報、結果（オッズなし）
- ライセンス：MIT

当日運用を検討する段階で使用します。初期版では必須ではありません。

## 設計原則

1. **AIに予想させない**  
   有料LLM APIやブラックボックスな文章生成モデルを予測器にしません。

2. **説明可能であること**  
   なぜその買い目の推定確率が高くなったか、使った特徴と計算手順を追跡できるようにします。

3. **期待値と的中率を混同しない**  
   よく当たる買い目と、価格に対して割安な買い目は別です。

4. **未来情報を混ぜない**  
   学習・集計期間より後のレースだけで検証します。ランダム分割による情報漏洩を避けます。

5. **買わない結果を正解として扱う**  
   条件を満たす買い目がなければ「見送り」を正式な出力にします。

6. **利益を保証しない**  
   推定誤差、オッズ変動、控除、データ欠損があり、正の期待値表示は利益を保証しません。

7. **自動投票を初期スコープに入れない**  
   まずはデータ取得、確率推定、期待値計算、バックテスト、CLI出力までを扱います。

## マイルストーン

### M0 — 企画と再開可能性

- [x] 目的と初期スコープを記録
- [x] データ源候補を記録
- [x] 制約と非目標を記録
- [x] ロードマップと正確な再開地点を作成

### M1 — データ監査とデータ契約

- [x] Turnmark APIの実データを数日分から全期間へ拡大して確認
- [x] 芦屋の場コード `21` で正しく抽出できることを確認
- [x] オッズの取得時点・欠損・取消・不成立・同着の扱いを確認
- [x] 3連単120通りのキーを正規化する仕様を決定
- [x] 予測時点で利用可能だった情報だけを列挙
- [x] 入力・中間データ・出力のスキーマを文書化

### M2 — 透明な基準確率モデル

- [x] 芦屋の枠番3連単成績を集計
- [x] 少数データを暴れさせない平滑化方法を決定
- [x] 全3連単の確率合計が1になる基準モデルを実装
- [x] 根拠と支持数を表示できる形で確率を保存
- [x] 一様分布・市場暗黙確率との時系列外比較を実施

### M3 — 期待値ランキング

- [x] 推定確率とオッズを結合
- [x] 期待回収率・期待利益率を計算
- [x] レースごとに全買い目を期待値順で出力
- [x] 閾値未満なら見送りと判定
- [x] 欠損・異常オッズを安全に除外

### M4 — 時系列バックテスト

- [x] 過去期間でモデルを作り、その後の期間だけで検証
- [x] 100円固定購入を基準戦略にする
- [x] 期待値閾値を変更して収支を比較
- [x] 回収率、的中率、購入数、最大連敗、最大ドローダウンを表示
- [x] 最小評価期間で推定確率の較正、log loss、Brier scoreを確認
- [x] 手数の少ない戦略が偶然に勝っただけでないか確認
- [x] 2連単sandboxでnested選択、4 outer fold、開催節bootstrapを実施
- [x] 同じ固定予算でsingle / dutchとprogram / market blendを比較
- [ ] 設計固定後に新しく蓄積した将来期間で再確認

### M5 — モバイルフレンドリーなウェブUI

- [ ] 日付・レースを選択
- [ ] 期待値ランキングを表示
- [ ] 閾値スライダーでバックテスト結果を更新
- [ ] 見送りを含む判断履歴を表示
- [ ] スマートフォンで読みやすく操作できる画面にする

### M6 — 当日利用の検討

- [ ] Boatrace Open APIから当日出走表・直前情報を取得
- [ ] 当日オッズを正当に安定取得できる方法を別途検討
- [ ] 過去モデルと当日入力の特徴定義を一致させる
- [ ] オッズ変動による期待値崩れを表示

## 非目標

- 「必勝」「数学的に必ず勝てる」と宣伝すること
- LLMの勘や文章による買い目生成
- 利益が出るように過去条件を後付けで調整すること
- 未来の結果を予測入力へ混ぜること
- 初期段階での自動購入、資金移動、外部アカウント操作
- BOATRACE公式サイトへの無許可の高頻度スクレイピング

## 再開方法

AI共同作業者は、次の順で読んでください。

1. `AGENTS.md`
2. `README.md`
3. `docs/PROJECT_PLAN.md`
4. `docs/ROADMAP.md`
5. `docs/HANDOFF.md`

現在の正確な再開地点は `docs/HANDOFF.md` にあります。

## ライセンス

[MIT License](LICENSE) です。
