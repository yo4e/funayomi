# 時点付きprogram・オッズ源調査

Updated: **2026-07-24**

Status: **Work package 0 complete — future Gate P candidate found / Gate D No-Go**

## 1. 結論

一次資料だけを対象に、結果公開前のprogram snapshotと購入締切前の2連単
オッズを、合法・安定・時点付きで保存できる経路を調査しました。

- Turnmarkのhistorical programは意味上program情報でも、snapshotが全件
  post-closeであり、確認的利用はNo-Go
- BOAT RACE公式からリンクされる翌日番組表LZHは、将来Gate Pの有力候補
- ただしLZHの自動取得・保存・派生利用の許可範囲は未確認で、収集は未開始
- `lawful + stable + timestamped + pre-close odds`を同時に満たす採用可能な
  オッズ源は0件
- Gate DはNo-Goとし、価格収集、E2、EV・買い目UIを開始しない

今夜行ったのは公開資料と単発のHTTP metadata確認までです。collector、定期
アクセス、データ保存、外部問い合わせは実施していません。

## 2. Turnmark programの時点

監査基準commitは
[`34a3b0a`](https://github.com/turnmark/api/commit/34a3b0a15c0e221a71464bcd86b572c4b28f90a7)
です。

- [同期workflow](https://github.com/turnmark/api/blob/34a3b0a15c0e221a71464bcd86b572c4b28f90a7/.github/workflows/sync.yml#L3-L6)
  は6時間cron
- [同期スクリプト](https://github.com/turnmark/api/blob/34a3b0a15c0e221a71464bcd86b572c4b28f90a7/bin/sync.php#L15-L27)
  はJSTの前日についてprogram、preview、odds、resultを同じ実行で取得
- [ProgramScraper](https://github.com/turnmark/scraper/blob/13e65bcb2213e56f86bb5b0b201b432cceb9cc72/src/Scrapers/ProgramScraper.php#L47-L57)
  は公式racelistページを原本とする
- [schema](https://github.com/turnmark/api/blob/34a3b0a15c0e221a71464bcd86b572c4b28f90a7/docs/v1/schema.md#L67-L113)
  にprogramの `observed_at`、scrape開始・終了、版時刻はない
- [Issue #3](https://github.com/turnmark/api/issues/3) と
  [修正commit](https://github.com/turnmark/api/commit/762822aee53b876a6bf456ea090354d910e8f505)
  は、過去program値が後日変更され得ることを示す

公式の[情報更新説明](https://www.boatrace.jp/owpc/pc/extra/about.html)は、
全国・当地・モーター・ボート率が今節成績を含まないこと、F/L回数の集計期間、
program体重がレース場で計測された最新値であることを説明しています。
したがって比率等は意味上の事前情報として有力です。

しかし、Turnmarkに保存されたその値自体がレース前に観測されたこと、結果後に
変化していないことは証明できません。分類を次に固定します。

```text
historical Turnmark program
= semantic_pre_race_but_snapshot_post_race_unverified
= retrospective development only
```

フィールド完全性の実測は
[`PROGRAM_AS_OF_AUDIT.md`](PROGRAM_AS_OF_AUDIT.md) を正本とします。

## 3. 将来program snapshot候補

BOAT RACE公式の[ダウンロードページ](https://www.boatrace.jp/owpc/pc/extra/data/download.html)
は、公式系配布サイトの
[全国番組表LZH](https://www1.mbrace.or.jp/od2/B/dindex.html)へ明示的に
リンクしています。

2026-07-24 21:33 JSTの単発確認では、翌日2026-07-25分
`b260725.lzh` が存在し、HTTP `Last-Modified` は
2026-07-24 20:59:28 JSTでした。翌日レース前に取得可能な実例です。

一方、当日分 `b260724.lzh` は同日13:58:28 JSTにも更新されていました。
固定URLを後日取得するだけではas-of証跡になりません。採用を検討する場合も、
次を満たすまではGate Pを通しません。

1. 自動取得、raw保管、派生値利用・公開の許可範囲を確認
2. 全レース開始前の固定cutoffで低頻度に取得
3. raw bytes、SHA-256、request開始・終了、`retrieved_at`、HTTP `Date`、
   `Last-Modified`、`ETag`をappend-only保存
4. LZHが候補特徴を全て持つと仮定せず、field単位で対応関係を監査
5. 同じURLの後日変更を上書きせず別revisionとして保存

この候補の採用と収集開始は、利用条件確認後の別owner decisionです。

## 4. pre-close odds候補

| 候補 | 時点 | 安定性・許可 | Gate D |
|---|---|---|---|
| Turnmark API | 前日を翌日取得、時刻なし | MITだがpre-closeでない | No-Go |
| Boatrace Open API | oddsなし | 対象外 | No-Go |
| BOAT RACE公式odds HTML | 更新時刻表示あり | 公開API・schema・機械取得許可なし | No-Go |
| 旧公式オッズ情報サービス | 提供終了 | 利用不可 | No-Go |

Turnmarkの[odds schema](https://github.com/turnmark/api/blob/34a3b0a15c0e221a71464bcd86b572c4b28f90a7/docs/v1/schema.md#L151-L173)
には時刻がありません。

[Boatrace Open API](https://github.com/boatraceopenapi/api/blob/27096a08ebf7d1ac84a4e981cabc6f8c4d0d88a7/README.md)
はprogram、preview、resultを提供しますが、oddsを含みません。

BOAT RACE公式の[情報更新説明](https://www.boatrace.jp/owpc/pc/extra/about.html)
は、公式HTMLにオッズ更新時間を表示し、締切後は締切時オッズと表示すると
説明しています。しかし[サイトポリシー](https://www.boatrace.jp/owpc/pc/extra/policy.html)
は、許諾のない私的利用範囲外の複製・頒布を認めず、大量アクセスを禁止し、
URLや内容の継続性も保証していません。公開API、SLA、schema、機械取得・
再利用許諾は確認できませんでした。

旧公式「オッズ情報・結果」は
[2025-03-05のお知らせ](https://www.boatrace.jp/owsp/sp/site/news/2025/03/41685/)
で提供終了が案内されています。

以上から、公式HTMLを無許可で収集する実装は作りません。次の外部判断候補は、
[BOAT RACE公式窓口](https://www.boatrace.jp/owpc/pc/support/opinion)へ、
芦屋2連単の低頻度な研究取得・保存・派生集計の許可、または正式feedの有無を
確認することです。問い合わせ自体も今夜は行っていません。

## 5. 将来のas-of契約案

snapshot単位:

```text
provider
intermediary
source_url
source_commit_sha
permission_or_license_reference
terms_checked_at
request_started_at
retrieved_at
provider_observed_at
provider_updated_at
http_date
last_modified
etag
raw_sha256
race_date
stadium_number
race_number
bet_type
scheduled_close_at
actual_close_at
prediction_cutoff
cutoff_margin_seconds
availability_class
```

field単位:

```text
normalized_field
source_path
semantic_period
snapshot_id
as_of_evidence
availability_class
allowed_use
```

時刻を推測で埋めず、存在しない値は `null` にします。許容クラスは次です。

- `prospective_preclose_verified`
- `historical_postclose_semantics_only`
- `timestamp_unknown`
- `postrace`

E1の確認的特徴は `prospective_preclose_verified` だけを許可します。価格は
少なくとも次を満たし、raw snapshotと予測を結果公開前にappend-only固定する
必要があります。

```text
provider_updated_at <= retrieved_at <= decision_at
decision_at < scheduled_close_at - safety_margin
```

`closed_at` は現状、締切予定時刻として扱い、実締切時刻と断定しません。

## 6. Gate判定

```text
Gate P historical Turnmark:
  NO_GO_HISTORICAL_CONFIRMATORY_USE

Gate P prospective official program file:
  HOLD_PENDING_PERMISSION_AND_FIELD_AUDIT

Gate D timestamped purchasable odds:
  NO_GO_NO_ADOPTABLE_SOURCE
```

確率経路ではprospective program契約の検討だけ継続候補とします。価格・収益
経路は、公式許可または契約済みfeedが得られるまで停止します。
