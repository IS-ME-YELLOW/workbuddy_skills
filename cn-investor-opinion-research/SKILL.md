---
name: cn-investor-opinion-research
description: "Research and archive the public opinions of a Chinese public fund manager, analyst, or investor on the A-share market, macro economy, or specific sectors. Collect authoritative sources via web and WeChat search, fetch full text, grade reliability by source type, and save original-source markdown files to the workspace. Use when a user asks to gather, organize, or archive a named Chinese market figure's views (e.g. 'XX 的观点 / 公开信息 / 研究报告 / 路演纪要 / 访谈'), or to trace how that person's views evolved over time."
agent_created: true
---

# CN Investor Opinion Research

## Overview

A repeatable pipeline for researching a named Chinese public-figure investor
(fund manager / strategist / analyst) and archiving their public market views
as graded, source-attributed markdown. The pipeline enforces an authority-first
collection order and a saturation-based stop rule so the result is
reproducible and defensible.

## When to use

- "收集/整理 XX 202X 年关于 A 股/宏观的公开观点"
- "把 XX 的研究报告、路演、访谈存成 markdown"
- "追溯 XX 对 AI / 出海 / 地产 的看法演变"
- Any task that names a Chinese market figure + asks for public opinions with
  an implied (or explicit) authority preference: 定期报告 > 路演/纪要 > 媒体 >
  社媒.

If the figure is overseas or the request is about a company/event (not a
person's opinions), this skill does not apply.

## Workflow

### Phase 0 — Derive the plan from user constraints

Do NOT invent a plan. Extract two constraints from the request and turn them
into a tracked task list (`TaskCreate`):

1. **Time window** — single year? range (e.g. "2024 至今")?
2. **Authority priority** — default order if unspecified:
   定期报告/官方纪要 (A) → 路演/会议实录 (B) → 权威媒体 (C) → 个人社媒/二次解读 (D).
   See `references/grading.md` for the full rubric.

Create one task per pipeline stage: 检索 → (分级)抓取原文 → 归档+索引. Mark
`in_progress` on the first before searching.

**Adaptive planning (critical):** The very first search often reveals a
biographical fact that reshapes the plan. For a fund manager, check current
employment status early — if they have left public funds / moved to private
(私募), the highest-priority tier (fund quarterly reports) will be EMPTY for
recent years. Re-center the plan on the next available tier (roadshow
transcripts, interviews) and record the gap as an explicit exclusion rather
than a failure.

### Phase 1 — Search

Run searches in PARALLEL where independent. Two channels:

**A. WebSearch** — primary channel. Always pass BOTH `query` and
`query_keyword_groups` (an array of 3–4 short phrase strings covering different
angles: e.g. "{name} {year} 季报 展望", "{name} 路演 纪要", "{name} 访谈 实录",
"{name} {topic} 观点"). The `query_keyword_groups` field drives the多角度
fan-out; never send only a single bare query.

> ⚠️ FORMAT TRAP: `query_keyword_groups` MUST be a JSON array of strings, e.g.
> `["a","b","c"]`. A malformed structure (nested/missing brackets) fails
> silently or returns garbage. Build it carefully.

**B. WeChat articles** — invoke the `wechat-article-search` skill (deep-research
plugin). It runs `scripts/sogou_search.py` under the hood. Typical call:
`Skill skill: wechat-article-search` with args like "{name} {year} 观点", then
the underlying Bash `sogou_search.py "{name}" --count 10 --time-range
YYYY-MM-DD YYYY-MM-DD`. WeChat is best for 纪要/转载/雪球-like reposts.

Search-sequence pattern that worked well:
1. Broad "name + year + 市场观点" → surfaces the figure's status & top sources.
2. "name + 离任/现状/私募/新东家" → confirms employment (reshapes plan).
3. "name + 访谈实录/路演" → finds transcripts.
4. "name + 具体议题 (AI/出海/地产)" → deepens topical coverage.
5. A final "name + 权威媒体名 (聪明投资者/中国证券报/钛媒体)" search to catch
   high-tier interviews missed above.

### Phase 2 — Fetch full text

For each promising URL, use `WebFetch` with a prompt that demands VERBATIM
extraction: "完整提取全文原文，包括标题/发布时间/来源/全部正文，逐字保留，不要摘要".
For dialogue transcripts, ask to preserve every Q&A turn. If WebFetch returns a
paywall/truncated page, try an alternate mirror URL from the same source or a
different aggregator (toutiao / qq / eastmoney / xueqiu often mirror each
other).

### Phase 3 — Grade & archive

Assign each captured source a tier (A–D) per `references/grading.md`. Write one
markdown file per source into a dated folder, e.g.
`{workspace}/XX公开观点资料/`. Filename convention:
`NN_来源_主题.md` where NN is a zero-padded ordinal keeping chronological order
(e.g. `01_中金财富云会客厅_官方纪要.md`, `11_2024Q1_一季报观点.md`). Prefix
quarterly-report files with the year-quarter so they sort before later years.

Always write an `00_索引与信源可靠性说明.md` index file containing:
- A timeline of the figure's status changes (employment, key dates).
- The full graded source list with URLs + dates + tier.
- Explicit exclusions / pitfalls found (see `references/pitfalls.md`).

### Phase 4 — Stop / sufficiency check

Stop searching only when ALL hold (see `references/pitfalls.md` "Stop signals"):
1. **Saturation** — new keyword groups keep returning the same core sources
   (only reposts/derivatives of already-captured material).
2. **Tier coverage** — at least one representative in each requested tier.
3. **Timeline closure** — the requested window is continuous (e.g. every
   quarterly report present; no unexplained gaps).
4. **Explicit boundaries** — state what is NOT findable (e.g. "私募运作报告不
   公开", "7–8 月无新增发声") so silence is documented, not hidden.

## Reliability tiers (summary)

A — 一手/亲述: 基金定期报告经理展望、持牌机构官方路演纪要、本人署名文章.
B — 逐字实录: 80 分钟级对话全文、会议实录.
C — 权威媒体: 新华社系/中国证券报/财联社/钛媒体/东方财富等记者稿.
D — 社媒/二次解读: 雪球/公众号个人文、含作者评论的摘编 — 引用时必须区分
"本人原话" vs "作者解读".

Full rubric + worked examples: `references/grading.md`.
Known traps (successor misattribution, WeChat time-filter padding, JSON
mistakes): `references/pitfalls.md`.

## Output structure

```
{workspace}/XX公开观点资料/
├── 00_索引与信源可靠性说明.md
├── 01_...md  (A/B tier, chronological)
├── ...
└── NN_...md  (D tier last)
```

Present the index + key files with `present_files` at the end; in the summary
call out (a) the reshaped plan if employment changed, (b) the top-tier source
for the year, (c) cross-year view evolution, (d) excluded pitfalls.
