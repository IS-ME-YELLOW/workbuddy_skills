#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄伟平 Phase 4 B 类·事件复算：信号-观点-行情三方对照
=====================================================
V2 迁移自工作区 phase4_fi_validate.py huangweiping 分支（计算逻辑原样保留）。

对每个关键事件时点：
  1) 用"截至该月"的数据窗口复算 S1-S13 信号（screen.py 各 calc_sN）
  2) 与分析师同期观点（✅/⚠️ 来源分级）对照
  3) 计算前瞻行情（事件月之后 1M/3M 的 10Y 收益率变动，bp）

用法（在技能根目录）：
  python scripts/phase4_validate_events.py --data assets/data/macro_real.json --out assets/data/signalcheck.json
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen  # noqa: E402

# ============================================================
# 配置区
# ------------------------------------------------------------
ANALYST = "huangweiping"
START_MONTH = "2023-01"        # 窗口起点（与 A 类脚本一致，44 个月）
FWD_FIELD = "c10y"             # 前瞻标的：10Y 国债收益率
FWD_UNIT = "bp"                # 收益率变动 bp
# ============================================================

# ----------------------------------------------------------------------------
# 事件表（V2 迁移自 .workbuddy/phase4_huangweiping_events.json；view 含 ✅/⚠️ 分级）
# ----------------------------------------------------------------------------
EVENTS = [
    {"month": "2024-09", "event": "2024.9.24 央行降准降息组合拳 + 9.26 政治局会议，债市先急跌后修复，长端利率快速下行",
     "view": "⚠️ 框架外推：政策利率下调（OMO 1.7→1.5%、MLF 2.3→2.0%）打开广谱利率下行空间，利率中枢随政策利率逐级下移",
     "view_grade": "⚠️", "expect": "S3 传导顺畅 / S6 定价锚向资金利率切换 / 10Y 中枢下移"},
    {"month": "2025-01", "event": "2025.1 资金面阶段性收紧（跨年+政府债供给），央行暂停购债预期升温，长端小幅调整",
     "view": "⚠️ 框架外推：资金面扰动不改宽货币方向；暂停购债=相机抉择，短端承压、长端影响有限",
     "view_grade": "⚠️", "expect": "S4 资金收敛触发或接近 / S6 未切换"},
    {"month": "2025-05", "event": "2025.5.8 央行降息（OMO 1.5%→1.4%）+ 5.15 降准 0.5pct，利多落地",
     "view": "⚠️ 框架外推：降准降息落地=利多兑现；政策利率下移→DR 中枢下移→10Y 定价锚溢价被动走阔",
     "view_grade": "⚠️", "expect": "S3 传导顺畅 / S4 资金平稳 / 10Y 缓步下行"},
    {"month": "2025-08", "event": "2025.8 债市进入 8-9 月防守窗口（黄伟平框架：政策观察期，久期偏防御）",
     "view": "✅ 原文：2026.6.9 中期策略延续 8-9 月防守思路（政策部署习惯+银行信贷投放规律）",
     "view_grade": "✅", "expect": "S13 防守信号（10Y 1.71% < 8-9 月下沿 1.75%，止盈/防回调）/ S4 资金偏紧"},
    {"month": "2026-06", "event": "2026.6 中期策略发布：10Y 区间 1.70-1.80%（6-7 月）、8-9 月 1.75-1.85% 防守",
     "view": "✅ 原文：2026.6.9 中期策略（10Y 6-7 月区间上沿 1.80%、8-9 月防守）",
     "view_grade": "✅", "expect": "10Y 运行于区间内 / S13 逼近下沿止盈（1.70% 恰为下沿）"},
    {"month": "2026-08", "event": "2026.8.3 二永债三位一体定价框架 + 2026.8.17 存单报告：信用利差 70%/10% 分位极值、永续-二债利差>15BP 积极超配",
     "view": "✅ 原文：2026.8.3 二永债框架（分位 70% 顶/10% 底）；2026.8.10 品种利差（>15BP 积极超配永续）",
     "view_grade": "✅", "expect": "S8/S9 分位极值判定、S11 品种利差轮动、S13 逼近区间下沿止盈"},
]


# ----------------------------------------------------------------------------
# 通用函数
# ----------------------------------------------------------------------------
def build_months(start, n):
    y, m = int(start[:4]), int(start[5:7])
    out = []
    for _ in range(n):
        out.append("%d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def window_at(macro, months, month):
    """截至 month 的数据窗口 h（与 screen.py --data 契约一致：字段→月份数组）。"""
    idx = months.index(month)
    return {f: list(arr[: idx + 1]) for f, arr in macro["history"].items()}


def run_signals(h, extras):
    sigs = []
    for i in range(1, 14):
        fn = getattr(screen, f"calc_s{i}")
        sigs.append(fn(h, extras))
    return sigs


def fwd_bp(values, idx, n):
    """事件月之后 n 个月的 10Y 收益率变动（bp），越界返回 None。"""
    if values is None or idx + n >= len(values):
        return None
    if values[idx] is None or values[idx + n] is None:
        return None
    return round((values[idx + n] - values[idx]) * 10000, 1)


def align_grade(trig_ids, all_sigs, expect):
    """预期信号 vs 实际响应的对齐判定（❌ 推断：粗粒度匹配，validation.md 中披露）：
    - expect 为空 → n/a
    - 预期含"降级/缺失"且对应信号 detail 含"缺字段/N/A" → align（数据缺失降级符合预期）
    - trig 命中 expect 信号 → align
    - expect 信号存在（未触发，判定成立但未达阈值）→ partial
    - 其余 → conflict
    """
    if not expect:
        return "n/a"
    expect_ids = set(re.findall(r"S\d+", expect))
    if not expect_ids:
        return "n/a"
    if "降级" in expect or "缺失" in expect:
        for s in all_sigs:
            if s["id"] in expect_ids and ("缺字段" in s["detail"] or "N/A" in s["detail"]):
                return "align"
    if [t for t in trig_ids if t in expect_ids]:
        return "align"
    if [s["id"] for s in all_sigs if s["id"] in expect_ids]:
        return "partial"
    return "conflict"


# ----------------------------------------------------------------------------
# 时点 extras 推断（⚠️ 推断，validation.md 中披露）
# ----------------------------------------------------------------------------
def infer_extras(month, h_full, months):
    """事件时点 extras 推断（无前视）：month 供 S13 按季度区间选参
    （6-7 月 Q2 / 8-9 月 Q3 / Q4）。"""
    mo_num = int(month.split("-")[1])
    return {"month": mo_num}


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="B 类·事件复算：信号-观点-行情三方对照")
    ap.add_argument("--data", default="assets/data/macro_real.json",
                    help="macro_real.json 路径")
    ap.add_argument("--out", default="assets/data/signalcheck.json",
                    help="输出路径")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        macro = json.load(f)
    h_full = macro["history"]

    n = len(next(iter(h_full.values())))
    months = build_months(START_MONTH, n)
    fwd_values = h_full.get(FWD_FIELD)

    print("=" * 96)
    print("%s Phase 4 信号-观点-行情三方对照（%d 个关键事件时点）" % (ANALYST, len(EVENTS)))
    print("=" * 96)

    results = []
    for ev in EVENTS:
        month = ev["month"]
        if month not in months:
            print("\n⚠️ 跳过（月份不在窗口内）：%s %s" % (ev.get("event", ""), month))
            continue
        idx = months.index(month)
        h = window_at(macro, months, month)
        extras = infer_extras(month, h_full, months)
        sigs = run_signals(h, extras)
        trig = [s for s in sigs if s["triggered"]]
        trig_ids = [s["id"] for s in trig]
        f1, f3 = fwd_bp(fwd_values, idx, 1), fwd_bp(fwd_values, idx, 3)
        grade = align_grade(trig_ids, sigs, ev.get("expect", ""))

        print(f"\n▶ {ev['event']}  ({month})")
        print(f"  观点[{ev.get('view_grade', '?')}]: {ev.get('view', '-')}")
        print(f"  预期: {ev.get('expect', '-')}")
        print(f"  信号触发 ({len(trig)}/{len(sigs)}): {trig_ids}  [对齐 {grade}]")
        for s in trig:
            print(f"    · {s['id']} {s['name']}: {s['detail']}")
        print(f"  前瞻 10Y: 1M {f1}BP / 3M {f3}BP")

        results.append({
            "event": ev["event"], "month": month,
            "view": ev.get("view", ""), "view_grade": ev.get("view_grade", ""),
            "expect": ev.get("expect", ""), "triggers": trig_ids,
            "trigger_details": [{"id": s["id"], "name": s["name"],
                                 "detail": s["detail"], "strength": s.get("strength")} for s in trig],
            "align": grade, "fwd_1m": f1, "fwd_3m": f3, "fwd_unit": FWD_UNIT,
        })

    # 最新月完整信号快照
    h_latest = window_at(macro, months, months[-1])
    sigs_latest = run_signals(h_latest, infer_extras(months[-1], h_full, months))
    snap = [{"id": s["id"], "name": s["name"], "triggered": s["triggered"],
             "detail": s["detail"], "strength": s.get("strength", "")} for s in sigs_latest]

    out = {"analyst": ANALYST, "as_of": months[-1], "fwd_field": FWD_FIELD,
           "fwd_unit": FWD_UNIT, "events": results, "latest_snapshot": snap}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    n_align = sum(1 for r in results if r["align"] == "align")
    print("\n" + "=" * 96)
    print("对齐统计：align %d / partial %d / conflict %d / n-a %d（共 %d 事件）" % (
        n_align, sum(1 for r in results if r["align"] == "partial"),
        sum(1 for r in results if r["align"] == "conflict"),
        sum(1 for r in results if r["align"] == "n/a"), len(results)))
    print("最新月快照触发：%s" % [s["id"] for s in snap if s["triggered"]])
    print("wrote:", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
