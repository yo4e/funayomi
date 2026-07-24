# 次期方針 内部サブエージェントレビュー

Reviewed: **2026-07-24**

Target: `docs/NEXT_PHASE_PROPOSAL.md`

Reviewer: **Codex sub-agent (`tsukino_review`)**

Result: **conditional recommendation for revised Option A**

このレビューは、Codexが独立した観点を増やすために起動したサブエージェント
による内部レビューです。山田さんの相棒であり本プロジェクトの最初の設計者で
あるChatGPTの月野によるレビューではありません。コードやプロジェクトの
実装変更は行っていません。

## 1. 結論

Option Aの方向性は妥当ですが、そのまま全実装を開始するのは早いです。

2連単は「利益が出る賭式探し」ではなく、低次元で確率モデルの能力を検証する
唯一のprimary confirmatory bet typeとして固定します。単勝は1着周辺確率の
診断、3連単は同じ順位モデルから導くsecondary evaluationに限定し、
賭式間ROIを見て勝者を選びません。

## 2. 必須修正

### 2.1 主仮説

主仮説を次へ固定します。

> program特徴Plackett–Luceモデルは、真の未来データにおける2連単の
> log lossを、平滑化枠番頻度モデルより改善するか。

単勝・3連単・ROIは主モデル選択へ使いません。全試行を台帳へ残します。

### 2.2 program cutoff

名称だけで事前情報と見なしてはいけません。現在のTurnmark programは
`pre_race_timestamp_unverified` です。

各特徴について次を契約化します。

- source path / provider
- snapshot `acquired_at`
- provider `observed_at` の有無
- race closeとの時間差
- どのprediction cutoffで使用可能か

時点を証明できない歴史programはretrospective developmentに限定し、
真の未来holdoutでは結果公開前に取得したsnapshotだけを使います。

### 2.3 Plackett–Luce

- `s_i = exp(x_i β)`
- 2連単primaryに合わせたtop-2 partial likelihood
- L2正則化
- 特徴block、符号化、欠損処理、交互作用、正則化候補を実行前固定
- 単勝・2連単・3連単の周辺確率整合性をテスト
- IIA仮定を既知の限界として明記

### 2.4 nested walk-forward

内側validationで前処理、正則化、較正を選び、外側shadow foldはモデル選択へ
再利用しません。外側foldを見て仕様を変えた場合は、新しいprotocolとして
試行を分けます。

bootstrapは舟券や単一レースを独立と見なさず、開催または開催日blockで
行います。

### 2.5 二種類のfuture holdout

確率品質と経済成績を分離します。

1. E1 probability holdout: log loss、Brier、較正
2. E2 economic holdout: 時刻付き購入可能オッズがある場合だけEV・ROI

`300レース・3か月`はE1の最低線にすぎず、裾の重いROIの証拠としては
不足します。development dataから必要標本数またはCI幅を事前に決め、
最大終了条件も固定します。

### 2.6 オッズ

時刻付き購入可能オッズがなければ、未来holdoutで正式評価できるのは
確率品質までです。EV選択・ROIは正式評価しません。

E2では次を分離します。

- decision時点で観測したオッズ
- 実払戻
- decision後の価格変化
- 締切までに表示edgeが消えた割合

### 2.7 凍結と監査証跡

future holdout開始前に次を保存します。

- protocol hash
- experiment config hash
- code commit hash
- data / source hash
- model artifact / coefficient hash
- 結果公開前の予測と選択

予測はappend-onlyで保存し、上書きしません。

### 2.8 CI

現在GitHub Actionsはありません。数値依存を追加する時点で、宣言する最小
Pythonと実装時の安定版Pythonによるテストmatrixを追加します。

## 3. 判断ゲート

推奨順序:

1. Gate A: 2連単30通り、払戻、例外、返還の全期間監査
2. Gate P: program特徴のas-of可用性と取得時刻
3. Gate B: 固定nested walk-forwardで確率モデル比較
4. Gate D: 合法で安定した購入締切前オッズ源
5. Gate E1: 真の未来データで確率品質
6. Gate E2: 時刻付きオッズがある場合だけ、固定した1購入規則を経済評価
7. Product Gate: UI・当日利用を再検討

「改善」「重大に悪化しない」「次段階」は、paired log-loss差の区間や
較正許容幅など、対象と数値をprotocolで固定する必要があります。

## 4. Go / Hold / No-Go

### Go候補

- 2連単の全期間監査
- program特徴時点監査
- research protocol策定
- 合法な時刻付きオッズ源の調査

### Hold

- 賭式schemaの実装
- Plackett–Luce実装
- future holdout実装

上記は、Gate A / Pとprotocolの仕様凍結後に再判断します。

### No-Go

- 現時点でのUI
- 当日予想
- 収益性主張
- 自動投票・実資金操作

## 5. 最終推奨

修正版Option Aなら進める価値があります。ただし最初の作業単位は実装ではなく、
2連単・program時点・オッズ源の3監査とprotocol固定です。監査結果が悪い場合に
止められることを、次期計画の中心に置きます。
