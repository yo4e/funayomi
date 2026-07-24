# FunaYomi Handoff

Updated: **2026-07-24**

## Current state

FunaYomi is at **Phase 0: project definition complete**.

The repository currently contains planning documents only. There is no application code, dependency file, downloaded dataset, model, web UI, automated workflow, issue backlog, or deployment.

Files created:

- `README.md` — public project overview, initial scope, APIs, milestones
- `AGENTS.md` — cold-start and collaboration rules for AI workers
- `docs/PROJECT_PLAN.md` — statistical, data, validation, and product plan
- `docs/ROADMAP.md` — phased roadmap and decision gates
- `docs/HANDOFF.md` — this exact restart point

## Owner intent

山田さんの現在の意図は次の通りです。

- 地元である芦屋ボートレースにまず限定する
- 前日までに利用可能な過去オッズを使う
- オッズと独立した確率推定を行い、期待値順に買い目を並べる
- 予測に高コストなAI APIやLLM APIを使わない
- Turnmark APIなどの公開APIは利用する
- 将来的にはモバイルフレンドリーなウェブUIを作る
- UIでは「期待値がこの閾値以上を買った場合、過去成績がどうなるか」をバックテストできるようにする
- 現時点では実装しない
- 次にこのリポジトリを見たAIが、会話を知らなくても再開できる状態にする

## Accepted initial scope

- Venue: Ashiya
- Stadium number: `21`
- Historical API: Turnmark API
- First wager candidate: trifecta / 3連単
- Prediction: deterministic or classical statistical algorithm, locally executable
- Ranking: predicted probability × odds
- Validation: chronological out-of-sample backtest
- First stake policy: hypothetical fixed 100 yen per selected combination
- First-class output: `PASS` when no qualifying value exists
- No live betting or automated account operation

## Important distinction about odds

Turnmark API provides odds for races available up to the previous day, but the repository documentation inspected so far does not establish that the value is specifically a “race-day previous-evening odds snapshot.”

Until Phase 1 data audit determines otherwise, use this careful wording:

> historical odds available from previous-day-or-earlier race data

Do not silently label the field as opening odds, previous-evening odds, closing odds, or final odds.

## Data sources currently identified

### Turnmark API

- `https://github.com/turnmark/api`
- `https://turnmark.github.io/api/v1/YYYY/YYYYMMDD.json`
- History begins 2026-05-01
- Includes programs, preview, odds, results
- MIT license
- Unofficial; accuracy and completeness not guaranteed

### Boatrace Open API

- `https://github.com/boatraceopenapi/api`
- `https://boatraceopenapi.github.io/api/v1/YYYY/YYYYMMDD.json`
- `https://boatraceopenapi.github.io/api/v1/today.json`
- Approximate 3-minute updates
- Includes programs, preview, results; no odds
- Candidate for a later current-day phase, not required now

## Current unresolved decisions

These decisions remain intentionally open.

1. Confirm whether the first wager type is 3連単 or whether 2連単 should be used as a simpler probability-model baseline.
2. Determine what timestamp or collection stage the Turnmark odds represent.
3. Determine whether the available Ashiya history is sufficient for 120-way estimation.
4. Decide the first prediction cutoff: program-only or preview-available.
5. Decide whether initial probabilities are based on entry number, actual course number, or both.
6. Define how to handle missing preview, fewer than six valid entries, refund, cancellation, no-contest, and dead heat.
7. Set the minimum sample support required before a high expected-value estimate is displayable.
8. Choose implementation and deployment frameworks only after the data audit.

## Exact restart gate

**Stop here until 山田さん explicitly authorizes implementation.**

Do not create code merely because Phase 0 is complete.

When implementation is authorized, begin **Phase 1 / M1: data audit and data contract**. Do not begin the probability model or UI first.

## First bounded work package after authorization

The next worker should:

1. Read `AGENTS.md`, `README.md`, `docs/PROJECT_PLAN.md`, and `docs/ROADMAP.md`.
2. Inspect current Issues and Pull Requests.
3. Fetch a small sample of Turnmark JSON files containing Ashiya races.
4. Confirm the path and type of `stadium_number`, race identifiers, odds, preview, and results.
5. Flatten only the Ashiya records into a temporary analysis table.
6. List every missing, malformed, cancelled, refunded, or exceptional case observed.
7. Compare odds fields with result payout fields for consistency without assuming their timestamp.
8. Draft `docs/DATA_CONTRACT.md` describing normalized records and leakage boundaries.
9. Report findings and ask for the 3連単-versus-2連単 gate if the data makes that choice material.
10. Update this handoff with the exact observed state.

## Explicitly prohibited in the first work package

- No predictive model fitting
- No expected-value claims
- No public prediction page
- No automatic betting
- No official-site scraper
- No paid service
- No LLM API
- No large historical download before the sample audit
- No framework selection merely for momentum

## Definition of the next successful checkpoint

Phase 1 has not started successfully because code exists. It has started successfully when the project can answer:

- What exactly does one Turnmark Ashiya race record contain?
- What exactly does its odds field mean, and what remains unknown?
- Which fields were available at the chosen prediction cutoff?
- Which records must be excluded or specially handled?
- Can a chronological, reproducible dataset be built without future leakage?

Only after those answers are recorded should probability modeling begin.
