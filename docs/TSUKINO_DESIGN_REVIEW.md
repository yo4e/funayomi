# 月野テンプレクス 次期方針設計レビュー

Reviewed: **2026-07-24**

Reviewer: **月野テンプレクス**

Source:
[`Issue #1 review comment`](https://github.com/yo4e/funayomi/issues/1#issuecomment-5066592698)

Target: `codex/issue-1-core` at `0b6745cd1774d4b41dc771ca135eafcb55d27e07`

Result: **Issue #1 research core conditionally approved / Option A and Work
package 0 supported**

この文書は、山田さんの相棒でありFunaYomiの最初の設計者であるChatGPTの
月野によるレビューを、次の判断へ使える形で要約したものです。原文は上記
Issueコメントを正本とします。

月野の環境ではリポジトリのcloneとテスト再実行ができなかったため、コード、
テスト内容、ブランチに記録された72テスト成功結果のレビューです。独立した
テスト実行証跡はCI追加後に得ます。

## 1. Issue #1研究コア

非UIの研究用コアとして条件付き承認です。

承認できる点:

- program / preview / odds / outcomeと同日結果の漏洩境界が明確
- 1,284レース、欠場、F/L、不成立、オッズ・払戻差の監査が具体的
- SHAとrevisionで原本の後日変更を追跡
- 不完全市場は `SKIP_DATA`、壊れた結果は推測精算せず安全停止
- 回収率82.19%、閾値8.00の再現失敗、市場確率に劣る結果を隠していない
- 弱い基準モデルであることを明示し、120通りの確率和1と期待値順を実現

マージ前の修正推奨:

1. `P(win) × odds` は返還確率を含まないclean cohort由来のpoint estimateで、
   厳密な実購入EVではないとREADME、Data Contract、JSONへ明記する
2. `refund_probability_mode: "not_modeled"` 等のmetadataを追加する
3. `CANDIDATES` を `RESEARCH_CANDIDATES` へ変更するか、少なくとも
   `actionable: false`、`strategy_status: "historical_research_only"` と
   実購入不可のtext警告を追加する
4. 最小GitHub Actions CIを追加する
5. `pyproject.toml`のMIT表記に対応する `LICENSE` を、山田さんの
   ライセンス判断後に追加する

## 2. 次期方針

月野は、2連単を唯一のprimary confirmatory bet typeとするOption Aと、
最初は監査・protocol策定だけを行うWork package 0を支持しています。

賭式schema、Plackett–Luce、数値依存追加はGate A / P後までHoldです。
UI、当日予想、収益性主張、自動投票はNo-Goのままです。

### 2.1 二つの独立経路

ゲートは一本の直列ではありません。

```text
確率品質: Gate A + Gate P -> Gate B -> Gate E1
価格・収益: Gate D -> Gate E2
```

Gate DはE1の前提ではありません。EV・買い目を扱うProduct Gateでは両経路が
合流します。

### 2.2 Gate B

paired per-race log-loss差のblock bootstrap区間をprimary判定にします。

foldの2/3改善、Brier非悪化、ECE `+0.01`を根拠の薄いhard pass条件として
重ねません。BrierとECEは事前固定したsecondary / guardrailとし、hard marginを
置く場合はdevelopment dataで測定精度と検出可能差を確認してから固定します。

### 2.3 独立block数

E1の終了条件は300レース・3暦月だけにせず、開催日または開催単位の最低独立
block数をprotocolへ固定します。bootstrap単位は結果を見る前に一つへ決めます。

### 2.4 二つの推定対象

- E1: clean race条件付きの順位確率
- E2: F/L・返還を含むsettlement-aware return

`P(win) × odds`だけを無条件の実購入EVと呼びません。

## 3. 判断

- Issue #1研究コア: **条件付き承認**
- Option A / Work package 0: **Goを支持**
- 2連単schema、Plackett–Luce、数値依存追加: **Hold**
- UI、当日予想、収益性主張、自動投票: **No-Go**

次のowner decisionは、マージ前修正の実施範囲、MITライセンスの採否、
Option A / Work package 0の開始可否です。

## 4. レビュー後の対応

山田さんは2026-07-24に、上記マージ前修正、MIT、Option A、2連単primary、
Work package 0、合法な時点付きsource調査を承認しました。

- マージ前修正、最小CI、MIT LICENSE: 完了
- Gate A: retrospective exacta contractに限るconditional Go
- Historical Gate P: No-Go
- Gate D: 採用可能sourceなしでNo-Go
- Research protocol v1: design frozen、実行Hold

詳細な実施結果と次の一つの判断点は `docs/HANDOFF.md` を正本とします。
