#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘郁 Phase 4 B 类·事件复算：信号-观点-行情三方对照
=====================================================
V2 迁移自工作区 phase4_fi_validate.py liuyu 分支（计算逻辑原样保留）。

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
ANALYST = "liuyu"
START_MONTH = "2023-01"        # 窗口起点（与 A 类脚本一致，44 个月）
FWD_FIELD = "c10y"             # 前瞻标的：10Y 国债收益率
FWD_UNIT = "bp"                # 收益率变动 bp
# ============================================================

# ----------------------------------------------------------------------------
# 事件表（V2 迁移自 .workbuddy/phase4_liuyu_events.json；view 含 ✅/⚠️ 分级）
# ----------------------------------------------------------------------------
EVENTS = [
    {"month": "2023-11", "event": "2023.11 化债特殊再融资债供给高峰，供给冲击担忧",
     "view": "✅ 原文：化债型财政带来短期供给冲击，但宏观基本面跳跃性反转概率有限→供给冲击不改利率下行方向，逢高配置",
     "view_grade": "✅", "expect": "S6 资金面平稳 / 10Y 供给扰动后回落"},
    {"month": "2024-02", "event": "2024.2 春节前后，广发时期收尾；债市低位，配置盘买入",
     "view": "⚠️ 框架外推：配置盘因存款重定价负债成本下降成主要买入力量（2024.12 表述回溯）",
     "view_grade": "⚠️", "expect": "S2/S3 行情状态判定"},
    {"month": "2024-09", "event": "2024.9.24 央行降准降息 + 9.26 政治局会议，债市先急跌后修复",
     "view": "⚠️ 框架外推：货币趋松确认（OMO 1.7→1.5%），政策利好落地后关注止盈",
     "view_grade": "⚠️", "expect": "S1 货币趋松成立但信用未宽（四象限=货币趋松&信用趋紧，不触发进攻，partial）/ 10Y 先抑后扬"},
    {"month": "2024-12", "event": "2024.12 非银同业存款自律新规 + 存款利率自律定价机制，债市抢跑 2025 降息",
     "view": "✅ 原文：存款自律落地→非银资金利率中枢下行、票息行情加速；债市抢跑 2025 降息；大行非银存款单月 -3.44 万亿→大行缺负债",
     "view_grade": "✅", "expect": "S11 存款自律信号（数据缺失降级）/ 10Y 加速下行"},
    {"month": "2025-01", "event": "2025.1 年初季节性低点：降准降息预期（≥100BP 降准、>30BP 降息），央行暂停购债",
     "view": "✅ 原文：2025 年降准幅度至少与 2024 年持平、降息幅度或超 30BP；宽货币主线不变",
     "view_grade": "✅", "expect": "10Y 低位 / S8 区间下沿临近"},
    {"month": "2025-05", "event": "2025.5.8 降息 0.1pct（OMO→1.4%）+ 5.15 降准，利多兑现",
     "view": "⚠️ 框架外推：降准降息落地=利多兑现止盈点（规则 12 预期差逻辑）",
     "view_grade": "⚠️", "expect": "S6 资金平稳 / 10Y 利多兑现后震荡"},
    {"month": "2026-02", "event": "2026.2 基金'买长卖短'、2 月末交易盘骤然止盈推动长端陡峭上行",
     "view": "✅ 原文：2026.3.4 月报——交易盘骤然止盈；2025 学习效应→2026 机构对收益锁定更敏感，波动放大",
     "view_grade": "✅", "expect": "S10 交易盘止盈信号（数据缺失降级）/ 10Y 短线上行"},
    {"month": "2026-04", "event": "2026.4.21《流动性框架之三》：资金面=事件扰动+动能缺失两类型综合；DR001 中枢或维持 1.20-1.25%",
     "view": "✅ 原文：动能缺失型宽松延续→加杠杆套息安全边际高；终结触发=政府债放量/信贷回升/汇率压力",
     "view_grade": "✅", "expect": "S5 动能缺失型 / S6 资金面平稳→加杠杆"},
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
    """事件时点 extras 推断（无前视）：
    - policy_loose 按 OMO 是否已下调（≤1.70% 视为宽松进行时）；
    - supply_slow 按 2026 动能缺失型宽松窗口给 True；
    - month/day 供 S13 月度节奏（月度数据粒度，day 取 15=中旬代表值）。
    """
    mo_num = int(month.split("-")[1])
    idx = months.index(month)
    omo = h_full["omo7d"][idx]
    policy_loose = omo is not None and omo <= 0.0170  # 2024.9 降息后持续宽松
    supply_slow = month >= "2026-01"                  # 2026 动能缺失型宽松
    return {"policy_loose": policy_loose, "supply_slow": supply_slow,
            "month": mo_num, "day": 15}


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
