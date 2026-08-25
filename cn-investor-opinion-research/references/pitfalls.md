# Known pitfalls (cn-investor-opinion-research)

Read before and during a collection run. Each caused real mistakes in the
reference case (鲍无可 2024–2026).

## 1. Successor misattribution (most dangerous)
Fund quarterly reports are signed by whoever manages the product *now*. After a
star manager leaves, platforms (理杏仁, 天天基金, etc.) often still surface the
product under the famous name, but the newer reports are written by the
**successor** (e.g. 邹立虎 took over 景顺长城价值驱动 after 鲍无可 left).
- Always check the report's signing manager name, not just the product name.
- If the person left public funds, ALL their "季报" after the departure date
  belong to someone else — exclude them and note it.

## 2. WeChat (sogou) time-filter padding
The `wechat-article-search` / `sogou_search.py` `--time-range` / `--days` filter
is unreliable for niche names: it frequently returns OLD articles to pad the
result count when few recent items exist.
- Treat WeChat results as LEADS, not as dated evidence.
- Verify the actual publish date on the source page before trusting the
  time-window.

## 3. WebSearch query_keyword_groups format
`query_keyword_groups` must be a JSON **array of strings**:
`["phrase one","phrase two","phrase three"]`.
A malformed structure (e.g. a string instead of array, or broken brackets)
either errors or returns garbage and wastes a call. Build it as a clean array.

## 4. "No report" ≠ "no data" — reshape, don't stall
For a manager who moved to 私募, fund reports vanish from public view. Do NOT
report "nothing found". Re-center on roadshow transcripts / interviews / media,
and document the gap ("私募运作报告依法不公开") as a boundary, not a failure.

## 5. Saturation vs. real gap
New searches returning only reposts/derivatives of already-captured sources =
saturation (stop). But a SILENT window (e.g. "7–8 月无新增发声") must be
explicitly stated as a documented boundary, not assumed.

## Stop signals (all must hold to finish)
1. Saturation — new angles hit the same core sources.
2. Tier coverage — ≥1 representative per requested tier.
3. Timeline closure — requested window continuous, no unexplained gaps.
4. Explicit boundaries — non-findable items documented (private reports, quiet
   months, successor reports excluded).
