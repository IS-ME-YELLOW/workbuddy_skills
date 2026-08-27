#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
张瑜 Phase 4 B 类·事件复算：剪刀差-信号-行情对照
=================================================
V2 迁移自工作区 phase4_zhangyu.py 的验证部分（V1 范式：事件表 +
S1/S3/S7/S8 简化信号检查，不改写为 screen.py calc_sN 复用；计算逻辑
原样保留，重跑数字与存量 phase4_zhangyu_events.json 完全一致）。

  1) 企业居民存款剪刀差 vs 后续行情（事件表，中证全指前瞻 1M/3M）
  2) 关键时点 S1/S3/S7/S8 触发状态（原 signal_check 3 时点保留为扩展键）
  3) 每个事件时点的同款信号判定（统一 signalcheck 格式 triggers）

用法（在技能根目录）：
  python scripts/phase4_validate_events.py --data assets/data/macro_real.json --out assets/data/signalcheck.json
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区
# ------------------------------------------------------------
ANALYST = "zhangyu"
START_MONTH = "2023-01"        # 窗口起点（与 A 类脚本一致，43 个月）
FWD_FIELD = "csi"              # 前瞻标的：中证全指（月收盘，B 脚本内嵌）
FWD_UNIT = "pct"               # 前瞻收益 %
# ============================================================

# 中证全指月收盘（westock-data kline sh000985；与 A 类脚本同源硬编码）
CSI_CLOSE = {
    "2023-01": 5112.41, "2023-02": 5115.27, "2023-03": 5074.03,
    "2023-04": 4998.81, "2023-05": 4814.79, "2023-06": 4859.89,
    "2023-07": 4959.94, "2023-08": 4672.31, "2023-09": 4621.41,
    "2023-10": 4515.15, "2023-11": 4522.11, "2023-12": 4421.96,
    "2024-01": 3874.62, "2024-02": 4251.41, "2024-03": 4310.67,
    "2024-04": 4353.88, "2024-05": 4288.11, "2024-06": 4039.97,
    "2024-07": 4020.58, "2024-08": 3854.74, "2024-09": 4706.77,
    "2024-10": 4794.14, "2024-11": 4845.90, "2024-12": 4750.67,
    "2025-01": 4632.67, "2025-02": 4847.41, "2025-03": 4826.86,
    "2025-04": 4666.80, "2025-05": 4764.60, "2025-06": 4954.23,
    "2025-07": 5168.75, "2025-08": 5723.95, "2025-09": 5875.46,
    "2025-10": 5866.65, "2025-11": 5732.77, "2025-12": 5919.12,
    "2026-01": 6259.18, "2026-02": 6398.46, "2026-03": 5842.34,
    "2026-04": 6342.26, "2026-05": 6368.84, "2026-06": 6551.62,
    "2026-07": 5681.24,
}

# ----------------------------------------------------------------------------
# 事件表（V2 迁移自原 phase4_zhangyu.py；V1 无观点字段，view 留空）
# ----------------------------------------------------------------------------
EVENTS = [
    ("2023-08", "剪刀差下行中"),
    ("2024-04", "M1转负+PPI深跌"),
    ("2024-08", "剪刀差见底(924前夕)"),
    ("2024-09", "924行情启动"),
    ("2025-04", "关税冲击底"),
    ("2025-08", "M1回升+剪刀差修复"),
    ("2026-01", "非银存款大增+存款搬家"),
    ("2026-05", "剪刀差连续22月修复"),
    ("2026-07", "最新月"),
]

# 原 signal_check 时点（结果保留为 signalcheck.json 扩展键，与存量一致）
SIGNAL_CHECK_MONTHS = [
    ("2024-08", "924底"), ("2025-08", "M1回升"), ("2026-05", "最新信号"),
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


def check_at(month, months, h):
    """关键时点 S1/S3/S7/S8 触发状态（V1 简化判定，原 signal_check 逻辑参数化）：
    - S1: 剪刀差回升确认（连续3月向上）
    - S3: 五信号（M1回升/PPI转正/剪刀差回升/财政/房价企稳，≥4 触发）
    - S7: 央行降息条件（PPI回落 且 利润为负）
    - S8: 中游供需（需求-投资 > 0）
    """
    sc = [e - r for e, r in zip(h["enterprise_dep_yoy"], h["resident_dep_yoy"])]
    idx = months.index(month)
    # S1: 剪刀差回升确认（连续3月向上）
    if idx >= 3:
        up_count = sum(1 for i in range(idx, max(idx-4, -1), -1)
                       if i > 0 and sc[i] >= sc[i-1])
    else:
        up_count = 0
    s1 = up_count >= 3
    # S3: 五信号（简化判断）
    five_count = 0
    if h["m1_yoy_old"][idx] > 0 and idx > 0 and h["m1_yoy_old"][idx] > h["m1_yoy_old"][idx-1]:
        five_count += 1  # M1回升
    if h["ppi_yoy"][idx] > 0:
        five_count += 1  # PPI转正
    if sc[idx] > sc[max(idx-3, 0)]:
        five_count += 1  # 剪刀差回升
    if h["policy_bank_gdp_pct"][idx] > 0.8:
        five_count += 1  # 财政
    if h["first_tier_house_yoy"][idx] > -1.0:
        five_count += 1  # 房价企稳
    # S8: 中游供需
    midstream = h["midstream_demand_yoy"][idx] - h["midstream_invest_yoy"][idx]
    s8 = midstream > 0
    # S7: 央行降息条件
    ppi_falling = idx > 0 and h["ppi_yoy"][idx] < h["ppi_yoy"][idx-1]
    profit_neg = h["ind_profit_yoy"][idx] < 0
    s7 = ppi_falling and profit_neg
    return {
        "month": month,
        "scissors": round(sc[idx], 2),
        "scissors_up_count": up_count,
        "S1_triggered": s1,
        "five_count": five_count,
        "S3_triggered": five_count >= 4,
        "midstream_balance": round(midstream, 2),
        "S8_triggered": s8,
        "S7_triggered": s7,
        "ppi": h["ppi_yoy"][idx], "profit": h["ind_profit_yoy"][idx],
    }


SIG_DETAIL = {
    "S1": lambda c: ("剪刀差连续回升 %d 月（≥3 确认）" % c["scissors_up_count"]),
    "S3": lambda c: ("五信号 %d/5（M1回升/PPI转正/剪刀差回升/财政/房价企稳，≥4 触发）" % c["five_count"]),
    "S7": lambda c: ("PPI 回落且利润为负 → 降息条件成立（PPI %+.1f%%、利润 %+.1f%%）" % (c["ppi"], c["profit"])),
    "S8": lambda c: ("中游供需差 %+.2f%%（需求-投资>0）" % c["midstream_balance"]),
}


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="B 类·事件复算：剪刀差-信号-行情对照")
    ap.add_argument("--data", default="assets/data/macro_real.json",
                    help="macro_real.json 路径")
    ap.add_argument("--out", default="assets/data/signalcheck.json",
                    help="输出路径")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        macro = json.load(f)
    h = macro["history"]

    n = len(next(iter(h.values())))
    months = build_months(START_MONTH, n)
    sc = [e - r for e, r in zip(h["enterprise_dep_yoy"], h["resident_dep_yoy"])]

    print("=" * 96)
    print("%s Phase 4 剪刀差-信号-行情三方对照（%d 个关键事件时点）" % (ANALYST, len(EVENTS)))
    print("=" * 96)

    # 事件对照（原 event_table 逻辑原样）
    results = []
    for m, label in EVENTS:
        idx = months.index(m)
        c = check_at(m, months, h)
        fwd_1m = None
        fwd_3m = None
        if idx + 1 < n:
            fwd_1m = round((CSI_CLOSE[months[idx + 1]] / CSI_CLOSE[m] - 1.0) * 100, 1)
        if idx + 3 < n:
            fwd_3m = round((CSI_CLOSE[months[idx + 3]] / CSI_CLOSE[m] - 1.0) * 100, 1)
        trig = [s for s in ("S1", "S3", "S7", "S8") if c[f"{s}_triggered"]]
        det = [{"id": s, "name": {"S1": "剪刀差回升确认", "S3": "五信号共振",
                                  "S7": "央行降息条件", "S8": "中游供需"}[s],
                "detail": SIG_DETAIL[s](c), "strength": "strong"} for s in trig]
        r1 = f"{fwd_1m:+.1f}%" if fwd_1m is not None else "  n/a"
        r3 = f"{fwd_3m:+.1f}%" if fwd_3m is not None else "  n/a"
        print(f"  {m:<9}{label:<16}剪刀差{sc[idx]:>+8.2f}"
              f"{h['enterprise_dep_yoy'][idx]:>+7.1f}{h['resident_dep_yoy'][idx]:>+7.1f}"
              f"{h['m1_yoy_old'][idx]:>+6.1f}{h['ppi_yoy'][idx]:>+6.1f}"
              f"{h['ind_profit_yoy'][idx]:>+7.1f}  触发{trig or '无'}  {r1:>8}{r3:>8}")
        results.append({
            "event": label, "month": m,
            "view": "", "view_grade": "", "expect": "",
            "triggers": trig, "trigger_details": det,
            "align": "n/a",
            "fwd_1m": fwd_1m, "fwd_3m": fwd_3m, "fwd_unit": FWD_UNIT,
            # 扩展字段（V1 事件表原字段，保留）
            "scissors": round(sc[idx], 2),
            "ent_dep": h["enterprise_dep_yoy"][idx],
            "res_dep": h["resident_dep_yoy"][idx],
            "m1": h["m1_yoy_old"][idx], "ppi": h["ppi_yoy"][idx],
            "profit": h["ind_profit_yoy"][idx],
            "csi": CSI_CLOSE[m],
        })

    # 原 signal_check 3 时点（保留为扩展键）
    sig_checks = []
    print("\n[信号检查] 关键时点 S1/S3/S7/S8 触发状态：")
    for m, label in SIGNAL_CHECK_MONTHS:
        c = check_at(m, months, h)
        c["label"] = label
        sig_checks.append(c)
        print(f"  {c['month']} ({label}): 剪刀差{c['scissors']:+.2f}% 连续回升{c['scissors_up_count']}月"
              f" → S1={'✅' if c['S1_triggered'] else '❌'}"
              f" | 五信号{c['five_count']}/5 → S3={'✅' if c['S3_triggered'] else '❌'}"
              f" | 中游供需差{c['midstream_balance']:+.2f}% → S8={'✅' if c['S8_triggered'] else '❌'}"
              f" | 降息条件 → S7={'✅' if c['S7_triggered'] else '❌'}")

    # 最新月快照（S1/S3/S7/S8）
    c_last = check_at(months[-1], months, h)
    snap = [{"id": s, "name": {"S1": "剪刀差回升确认", "S3": "五信号共振",
                               "S7": "央行降息条件", "S8": "中游供需"}[s],
             "triggered": c_last[f"{s}_triggered"],
             "detail": SIG_DETAIL[s](c_last),
             "strength": "strong" if c_last[f"{s}_triggered"] else "direction"}
            for s in ("S1", "S3", "S7", "S8")]

    out = {"analyst": ANALYST, "as_of": months[-1], "fwd_field": FWD_FIELD,
           "fwd_unit": FWD_UNIT, "events": results, "latest_snapshot": snap,
           # 原 signal_check 3 时点结果（V1 保留，扩展键）
           "signal_check": sig_checks}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n最新月（%s）快照触发：%s" % (months[-1], [s["id"] for s in snap if s["triggered"]]))
    print("wrote:", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
