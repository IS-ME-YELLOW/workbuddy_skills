#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
张忆东 Phase 4 B 类·事件复算：信号-观点-行情三方对照
=====================================================
V2 迁移自工作区 phase4_validate_zhangyidong.py（计算逻辑原样保留：
run_signals 用显式函数清单——本技能 calc 函数为混合签名
fn(h) / fn(h, extras)，非 calc_sN 统一签名，故不能套用模板的动态发现）。

前瞻收益：从 macro_real.json 的 hsi_close / hs300_close 月度收盘计算
（V2 迁移时将原 A 类事件表的两指数收盘升格进 history）。

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
ANALYST = "zhangyidong"
START_MONTH = "2023-01"        # 窗口起点（与 A 类脚本一致，44 个月）
FWD_FIELD = "hsi_close"        # 前瞻主标的：恒指月收（次级 hs300_close）
FWD_FIELD2 = "hs300_close"
FWD_UNIT = "pct"
# ============================================================

# ----------------------------------------------------------------------------
# 事件表（V2 迁移自 .workbuddy/phase4_zhangyidong_events.json；观点为蒸馏时
# 从公开报告摘录。原表无 ✅/⚠️ 分级与预期信号，故 view_grade 留空、align 为 n/a）
# ----------------------------------------------------------------------------
EVENTS = [
    {"month": "2023-08", "event": "2023H2 平衡市",
     "view": "A股平衡市'螺蛳壳里做道场'、数字经济主线；港股'沼泽底'宜当债配"},
    {"month": "2024-03", "event": "2024.03 港股的春天",
     "view": "看多港股：美债利率见顶+内地低利率+经济企稳，高胜率投资"},
    {"month": "2024-09", "event": "2024.09 924反转前",
     "view": "反转逻辑：风险溢价5%→0（高性价比）+政策组合拳+财富再配置"},
    {"month": "2025-04", "event": "2025.04 关税战",
     "view": "'特朗普是纸老虎'，积极防御、布局黄金坑"},
    {"month": "2025-06", "event": "2025.06 港股长牛",
     "view": "恒指ERP 8%、南向6600亿定价权，港股牛市风雨无阻"},
    {"month": "2026-03", "event": "2026.03 SMART机遇期",
     "view": "A股ERP 5.3%（47.7%分位），年初震荡是蓄力"},
    {"month": "2026-05", "event": "2026.05 夏季策略",
     "view": "N型走势（5冲高/6-7寒风/8走强）；三重共振；逢低超配A+H"},
    {"month": "2026-07", "event": "2026.07.30 翻多",
     "view": "'老乡别再割肉'：=1998纳斯达克，AI应用下半场启动；机构ETF+4700亿/散户撤离"},
    {"month": "2026-08", "event": "2026.08 底部确认",
     "view": "'空间到了时间没到'：8月逆势布局不追高；美债或摸5%（灰犀牛）"},
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
    """截至 month 的无前视切片（事件月含当月）。"""
    idx = months.index(month)
    return {f: list(arr[: idx + 1]) for f, arr in macro["history"].items()}


def run_signals(h, extras):
    """显式遍历本技能 calc 函数（混合签名：大部分 fn(h)，calc_south_style fn(h, extras)）。"""
    sigs = []
    for fn in (screen.calc_erp_signal, screen.calc_hk_resonance,
               screen.calc_short_ratio, screen.calc_credit_expansion,
               screen.calc_ust_chain, screen.calc_ai_clock,
               screen.calc_smart_rotation, screen.calc_south_style,
               screen.calc_unlock, screen.calc_bottom_feature):
        r = fn(h) if fn is not screen.calc_south_style else fn(h, extras)
        if isinstance(r, tuple):
            sigs.extend(r)
        else:
            sigs.append(r)
    return [s for s in sigs if s]


def fwd_ret(values, idx, n):
    """事件月之后 n 个月的收盘涨跌幅（%），越界/缺失返回 None。"""
    if values is None or idx + n >= len(values):
        return None
    a, b = values[idx], values[idx + n]
    if a is None or b is None:
        return None
    return round((b - a) / a * 100, 1)


def align_grade(trig_ids, all_sigs, expect):
    """预期信号 vs 实际响应的对齐判定（expect 为空 → n/a）。"""
    if not expect:
        return "n/a"
    expect_ids = set(re.findall(r"S\d+", expect))
    if not expect_ids:
        return "n/a"
    if [t for t in trig_ids if t in expect_ids]:
        return "align"
    if [s["id"] for s in all_sigs if s["id"] in expect_ids]:
        return "partial"
    return "conflict"


def fmt(v):
    return "N/A" if v is None else "%+.1f%%" % v


# ----------------------------------------------------------------------------
# 时点 extras 推断（⚠️ 推断，validation.md 中披露）
# ----------------------------------------------------------------------------
def infer_extras(month):
    """该时点的 extras 推断（无前视）：
    - ai_phase: 张忆东 2026.07.30 翻多宣布 AI 应用下半场启动 → 2026-07 起 application
    - south_style: 南向成长化叙事 2026 年成为主线 → 2026-01 起 growth
    """
    ai_phase = "application" if month >= "2026-07" else "hardware"
    south_style = "growth" if month >= "2026-01" else "dividend"
    return {"ai_phase": ai_phase, "south_style": south_style}


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

    n = len(next(iter(macro["history"].values())))
    months = build_months(START_MONTH, n)
    fwd_values = macro["history"].get(FWD_FIELD)
    fwd2_values = macro["history"].get(FWD_FIELD2)

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
        extras = infer_extras(month)
        sigs = run_signals(h, extras)
        trig_ids = [s["id"] for s in sigs if s["triggered"]]
        f1, f3 = fwd_ret(fwd_values, idx, 1), fwd_ret(fwd_values, idx, 3)
        g1, g3 = fwd_ret(fwd2_values, idx, 1), fwd_ret(fwd2_values, idx, 3)
        grade = align_grade(trig_ids, sigs, ev.get("expect", ""))

        print("\n▶ %s  (%s)" % (ev.get("event", ""), month))
        print("  观点: %s" % ev.get("view", "-"))
        print("  信号触发 (%d/%d): %s  [对齐 %s]" % (len(trig_ids), len(sigs), trig_ids, grade))
        for s in sigs:
            if s["triggered"]:
                print("    · %s %s: %s" % (s["id"], s["name"], s["detail"]))
        print("  前瞻: 恒指 1M %s / 3M %s | 沪深300 1M %s / 3M %s"
              % (fmt(f1), fmt(f3), fmt(g1), fmt(g3)))

        results.append({
            "event": ev.get("event", ""), "month": month,
            "view": ev.get("view", ""), "view_grade": ev.get("view_grade", ""),
            "expect": ev.get("expect", ""), "triggers": trig_ids,
            "trigger_details": [{"id": s["id"], "name": s["name"], "detail": s["detail"],
                                 "strength": s.get("strength")} for s in sigs if s["triggered"]],
            "align": grade,
            "fwd_1m": f1, "fwd_3m": f3, "fwd_unit": FWD_UNIT, "fwd_field": FWD_FIELD,
            "fwd_hs300_1m": g1, "fwd_hs300_3m": g3,
        })

    # 最新月全信号快照（对应 validation.md "实时快照"节）
    h_latest = window_at(macro, months, months[-1])
    sigs_latest = run_signals(h_latest, infer_extras(months[-1]))
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
