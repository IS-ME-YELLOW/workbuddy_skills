#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘富兵 Phase 4 B 类·事件复算：信号-观点-行情三方对照
====================================================================
依据 analyst-distill 规范（phase4-scripts-conventions.md）编写。
`import screen` 复用 calc_s1..calc_s10，禁止重写计算逻辑。

EVENTS 表（7 条）覆盖观点主线（views.md ✅）：
  2024-01 双底、2024-07 超配大盘质量、2024-10-27 浪结构（结束概率不足 15%）、
  2025-11-07 日线上涨临近尾声/中期牛市开始、2026-05 提防冲高回落、
  2026-07-19 大概率再次探底、2026-08 30 分钟级别调整+六面图-0.12+转债偏离度 12.28%
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
ANALYST = "刘富兵（国盛证券金融工程）"
START_MONTH = "2023-09"          # 与 A 类脚本 MONTHS 窗口起点一致
FWD_FIELD = "hs300_close"        # 前瞻标的：沪深300 月收盘
FWD_UNIT = "pct"                 # 权益口径 → pct
# ============================================================

EVENTS = [
    {"month": "2024-01", "event": "底部判断：市场构筑双底（2024-01 底 + 2024-09 上旬）",
     "view": "✅ views.md：2024-01『市场构筑双底』（价格分段框架：2024-01 底 + 2024-09 上旬）",
     "view_grade": "✅", "expect": "S1+S4"},
    {"month": "2024-07", "event": "七月配置建议：超配大盘质量",
     "view": "✅ views.md：2024-07《七月配置建议：超配大盘质量》——风格'赔率-趋势-拥挤度'三维图谱应用案例",
     "view_grade": "✅", "expect": "S9"},
    {"month": "2024-10", "event": "浪结构判断：日线上涨只走了 1 浪，结束概率不足 15%",
     "view": "✅ views.md：2024-10-27『日线上涨只走了 1 浪，结束概率不足 15%』（量价分段+浪结构框架）",
     "view_grade": "✅", "expect": "S1"},
    {"month": "2025-11", "event": "中期展望：超 2/3 行业超涨 → 日线上涨临近尾声、中期牛市刚刚开始",
     "view": "✅ views.md：2025-11-07『超 2/3 行业超涨，半数以上指数走出 9-15 浪 → 日线上涨临近尾声，中期牛市刚刚开始』；景气指数 20.91",
     "view_grade": "✅", "expect": "S1+S5+S7"},
    {"month": "2026-05", "event": "择时提示：提防冲高回落（高位行业超涨后的级别风险）",
     "view": "✅ views.md：2026-05『提防冲高回落』",
     "view_grade": "✅", "expect": "S3+S7"},
    {"month": "2026-07", "event": "市场结构观点：24 行业日线下跌 → 短暂反抽后大概率再次探底",
     "view": "✅ views.md：2026-07-19『24 个行业日线下跌、17 个周线下跌 → 短暂反抽后大概率再次探底』；景气指数 21.42",
     "view_grade": "✅", "expect": "S1+S7"},
    {"month": "2026-08", "event": "最新月报：30 分钟级别调整 + 六面图 -0.12 中性 + 转债偏离度 12.28%",
     "view": "✅ views.md：2026-08『市场或迎 30 分钟级别调整；六面图综合分 -0.12 中性；转债全市场定价偏离度 12.28%』",
     "view_grade": "✅", "expect": "S2+S10"},
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
    故返回 {}；观点叙事已编码在 history（liq_dir/style_* 等）。"""
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
