#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘胜利 Phase 4 B 类·事件复算：信号-观点-行情三方对照
====================================================================
依据 analyst-distill 规范（phase4-scripts-conventions.md）编写。
`import screen` 复用 calc_s1..calc_s8，禁止重写计算逻辑。

EVENTS 表（5 条）覆盖观点主线（views.md ✅）：
  2025-02（⚠️ 月份代理：2025 年度策略《风格切换下的因子投资》）、
  2025-12 黄金年度观点、2026-01-28 年度风格判断（三维框架→偏大盘成长）、
  2026-05-07 行业轮动（十二）分析师因子、2026-08-19 资产配置（四）绝对收益+黄金
fwd 标的：hs300_close（沪深300 月收盘，权益口径 pct）。

用法（在技能根目录）：
  python scripts/phase4_validate_events.py --data assets/data/macro_real.json --out assets/data/signalcheck.json
"""

import argparse
import json
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区（按目标分析师修改）
# ------------------------------------------------------------
ANALYST = "刘胜利（长江证券金融工程）"
START_MONTH = "2023-09"          # 与 A 类脚本 MONTHS 窗口起点一致
FWD_FIELD = "hs300_close"        # 前瞻标的：沪深300 月收盘
FWD_UNIT = "pct"                 # 权益口径 → pct
# ============================================================

EVENTS = [
    {"month": "2025-02", "event": "2025 年度策略《风格切换下的因子投资》：传统因子失效、价值/成长约 3 年周期、2026 偏大盘成长",
     "view": "✅ views.md：2025 年度策略『传统因子失效；价值/成长轮动周期约 3 年；2026 预判偏大盘成长』（⚠️ 事件月取 2025-02 代理，views.md 未给具体月）",
     "view_grade": "⚠️", "expect": "S1"},
    {"month": "2025-12", "event": "黄金年度观点：央行购金+ETF 购金为定价主力（2022 以来）",
     "view": "✅ views.md：2025-12『黄金战略配置价值延续——央行购金+ETF 购金为定价主力，实际利率下行支撑』",
     "view_grade": "✅", "expect": "S8"},
    {"month": "2026-01", "event": "年度风格判断（复旦 FICC）：周期时间+宏观基本面+资金面三维 → 2026 大概率偏大盘成长",
     "view": "✅ views.md：2026-01-28『跳出单一因子视角，转向风格周期维度；判断 2026 年大概率偏向大盘成长』",
     "view_grade": "✅", "expect": "S1+S7"},
    {"month": "2026-05", "event": "行业轮动（十二）：分析师因子三维定义（超预期/预期增长/驱动）",
     "view": "✅ views.md：2026-05-07『行业轮动分析师因子三维——超预期（一致预期相对年报同比）、预期增长（一致预期环比）、分析师驱动（首次覆盖后量价表现）；成长方向占优』",
     "view_grade": "✅", "expect": "S5"},
    {"month": "2026-08", "event": "资产配置（四）：权益绝对收益策略（低风险底仓+非周期增强+Beta 约束）+ 黄金战略配置",
     "view": "✅ views.md：2026-08-19『权益绝对收益策略主导——风险分层防御态；黄金战略配置延续——实际利率下行+地缘风险升温+央行/ETF 购金持续』",
     "view_grade": "✅", "expect": "S3+S8"},
]


# ----------------------------------------------------------------------------
# 通用函数（领域无关，勿改）
# ----------------------------------------------------------------------------

def build_months(start, n):
    """从 start 起构造 n 个月份序列（"YYYY-MM" 升序）。"""
    y, m = int(start[:4]), int(start[5:7])
    out = []
    for _ in range(n):
        out.append("%d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def window_at(macro, months, month):
    """截至 month 的无前视切片：{field: arr[:idx+1]}。事件月含当月（决策时点可得）。"""
    idx = months.index(month)
    return {f: list(arr[: idx + 1]) for f, arr in macro["history"].items()}


def run_signals(screen, h, extras):
    """动态发现并遍历 calc_s1..calc_sN（要求信号连续编号、统一签名 fn(h, extras)）。"""
    sigs, i = [], 1
    while True:
        fn = getattr(screen, "calc_s%d" % i, None)
        if fn is None:
            break
        try:
            r = fn(h, extras)
        except Exception as e:  # 单信号出错不阻塞整体
            r = {"id": "S%d" % i, "name": "S%d" % i, "triggered": False,
                 "detail": "计算异常：%s" % e, "strength": "direction"}
        if r:
            sigs.append(r)
        i += 1
    return sigs


def fwd_ret(values, idx, n, unit):
    """事件月之后 n 个月的标的变动（次月起算），越界返回 None。"""
    if values is None or idx + n >= len(values):
        return None
    a, b = values[idx], values[idx + n]
    if a is None or b is None:
        return None
    if unit == "bp":
        return round((b - a) * 10000, 1)
    return round((b - a) / a * 100, 1)


def align_grade(trig_ids, all_sigs, expect):
    """预期信号 vs 实际响应的对齐判定（❌ 推断：粗粒度匹配，validation.md 中披露）。"""
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


def fmt(v, unit):
    if v is None:
        return "N/A"
    return ("%+.1f%%" % v) if unit == "pct" else ("%+.1fBP" % v)


# ----------------------------------------------------------------------------
# 需按分析师修改：时点 extras 推断（screen.py 计算不消费 extras，返回 {} 即可）
# ----------------------------------------------------------------------------

def infer_extras(month):
    """事件时点的 extras 推断：screen.py 的 calc_sN 不读取 extras（仅作报告备注），
    故返回 {}；观点叙事已编码在 history（style_cycle_pos/factor_* 等）。"""
    return {}


# ----------------------------------------------------------------------------
# 主流程（领域无关，勿改）
# ----------------------------------------------------------------------------

def resolve_screen(demo):
    """demo=True 用同目录 screen_template 自测；正式运行 import 同目录成品 screen。"""
    if demo:
        import screen_template as screen
        return screen
    try:
        import screen
        return screen
    except ImportError:
        sys.exit("错误：未找到 screen 模块。本脚本应与 screen.py 同住技能 scripts/ 目录，"
                 "或加 --demo 用模板自测。")


def load_macro(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="B 类·事件复算：信号-观点-行情三方对照")
    ap.add_argument("--data", help="macro_real.json 路径（技能内为 assets/data/macro_real.json）")
    ap.add_argument("--out", default="signalcheck.json", help="输出路径")
    ap.add_argument("--demo", action="store_true", help="模板自测：用 screen_template 演示数据")
    args = ap.parse_args()

    screen = resolve_screen(args.demo)

    if args.demo:
        macro = screen.demo_data()
        macro = dict(macro)
        macro["_real"] = False
    elif args.data:
        macro = load_macro(args.data)
    else:
        sys.exit("需要 --data <macro_real.json>（或 --demo 自测）")

    # 月份轴：取首个字段长度（与 A 类 MONTHS 一致）
    n = len(next(iter(macro["history"].values())))
    months = build_months(START_MONTH, n)
    if args.demo:  # 演示数据窗口短，事件月对齐到末月
        EVENTS[0]["month"] = months[-1]

    fwd_values = macro["history"].get(FWD_FIELD)
    if fwd_values is None:  # 模板自测：演示数据可能无该字段，退回首字段
        fwd_values = next(iter(macro["history"].values()))

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
        sigs = run_signals(screen, h, extras)
        trig_ids = [s["id"] for s in sigs if s["triggered"]]
        f1 = fwd_ret(fwd_values, idx, 1, FWD_UNIT)
        f3 = fwd_ret(fwd_values, idx, 3, FWD_UNIT)
        grade = align_grade(trig_ids, sigs, ev.get("expect", ""))

        print("\n▶ %s  (%s)" % (ev.get("event", ""), month))
        print("  观点[%s]: %s" % (ev.get("view_grade", "?"), ev.get("view", "-")))
        print("  预期: %s" % ev.get("expect", "-"))
        print("  信号触发 (%d/%d): %s  [对齐 %s]" % (len(trig_ids), len(sigs), trig_ids, grade))
        for s in sigs:
            if s["triggered"]:
                print("    · %s %s: %s" % (s["id"], s["name"], s["detail"]))
        print("  前瞻(%s): 1M %s / 3M %s" % (FWD_FIELD, fmt(f1, FWD_UNIT), fmt(f3, FWD_UNIT)))

        results.append({
            "event": ev.get("event", ""), "month": month,
            "view": ev.get("view", ""), "view_grade": ev.get("view_grade", ""),
            "expect": ev.get("expect", ""), "triggers": trig_ids,
            "trigger_details": [{"id": s["id"], "name": s["name"], "detail": s["detail"],
                                 "strength": s.get("strength")} for s in sigs if s["triggered"]],
            "align": grade, "fwd_1m": f1, "fwd_3m": f3, "fwd_unit": FWD_UNIT,
        })

    # 最新月全信号快照（对应 validation.md "实时快照"节）
    h_latest = window_at(macro, months, months[-1])
    sigs_latest = run_signals(screen, h_latest, infer_extras(months[-1]))
    snap = [{"id": s["id"], "name": s["name"], "triggered": s["triggered"],
             "detail": s["detail"], "strength": s.get("strength", "")} for s in sigs_latest]

    out = {"analyst": ANALYST, "as_of": months[-1], "fwd_field": FWD_FIELD,
           "fwd_unit": FWD_UNIT, "events": results, "latest_snapshot": snap}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    n_align = sum(1 for r in results if r["align"] == "align")
    print("\n" + "=" * 96)
    print("对齐统计：align %d / partial %d / conflict %d / n-a %d（共 %d 事件）" % (
        n_align, sum(1 for r in results if r["align"] == "partial"),
        sum(1 for r in results if r["align"] == "conflict"),
        sum(1 for r in results if r["align"] == "n/a"), len(results)))
    print("最新月快照触发：%s" % [s["id"] for s in snap if s["triggered"]])
    print("wrote:", args.out)


if __name__ == "__main__":
    main()
