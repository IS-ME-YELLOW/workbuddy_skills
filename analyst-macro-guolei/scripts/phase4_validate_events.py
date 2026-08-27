#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
郭磊 Phase 4 B 类·事件复算：信号-行情对照 + 三因子回测
=====================================================
V2 迁移自工作区 phase4_validate.py 的验证部分（V1 范式：三因子得分与
E/P 赔率直接计算，不改写为 screen.py calc_sN 复用；计算逻辑原样保留，
重跑数字与存量 phase4_events.json 完全一致）。

  A. M1-BCI-PPI 三因子动量择时（规则1）
  B. 胜率×赔率组合（三因子 OR 股债性价比极端，规则2 决策矩阵思想）
  C. 买入持有基准（沪深300）
输出关键事件对照表（统一 signalcheck 格式）+ 回测段（保留在尾部，
作为 signalcheck.json 的 backtest 扩展键）。

用法（在技能根目录）：
  python scripts/phase4_validate_events.py --out assets/data/signalcheck.json
（依赖 A 类脚本同款硬编码序列 + tmp_premium_curve.txt 日频文件；
  事件前瞻基准为沪深300月收盘）
"""
import argparse
import json
import os
import statistics
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen import hp_filter, zscore  # 复用技能脚本，确保逻辑一致  # noqa: E402

# ============================================================
# 配置区
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
ANALYST = "guolei"
FWD_FIELD = "hs300"             # 前瞻标的：沪深300（月收盘，B 脚本内嵌）
FWD_UNIT = "pct"                # 前瞻收益 %
# ============================================================

# ---------------------------------------------------------------------------
# 月度序列（2021-01 ~ 2026-07，67 个月；与 A 类脚本同源硬编码）
# ---------------------------------------------------------------------------
MONTHS = []
for y in range(2021, 2027):
    for m in range(1, 13):
        if y == 2026 and m > 7:
            break
        MONTHS.append(f"{y}-{m:02d}")

M1_YOY = [
    14.7, 7.4, 7.1, 6.2, 6.1, 5.5, 4.9, 4.2, 3.7, 2.8, 3.0, 3.5,
    -1.9, 4.7, 4.7, 5.1, 4.6, 5.8, 6.7, 6.1, 6.4, 5.8, 4.6, 3.7,
    6.7, 5.8, 5.1, 5.3, 4.7, 3.1, 2.3, 2.2, 2.1, 1.9, 1.3, 1.3,
    3.3, 2.6, 2.3, 0.6, -0.8, -1.7, -2.6, -3.0, -3.3, -2.3, -0.7, 1.2,
    0.4, 0.1, 1.6, 1.5, 2.3, 4.6, 5.6, 6.0, 7.2, 6.2, 4.9, 3.8,
    4.9, 5.9, 5.1, 5.0, 5.5, 4.0, 4.0,
]

PPI_YOY = [
    0.3, 1.7, 4.4, 6.8, 9.0, 8.8, 9.0, 9.5, 10.7, 13.5, 12.9, 10.3,
    9.1, 8.8, 8.3, 8.0, 6.4, 6.1, 4.2, 2.3, 0.9, -1.3, -1.3, -0.7,
    -0.8, -1.4, -2.5, -3.6, -4.6, -5.4, -4.4, -3.0, -2.5, -2.6, -3.0, -2.7,
    -2.5, -2.7, -2.8, -2.5, -1.4, -0.8, -0.8, -1.0, -2.8, -2.9, -2.5, -2.3,
    -2.3, -2.2, -2.5, -2.7, -3.3, -3.6, -3.6, -2.9, -2.3, -2.1, -2.2, -1.9,
    -1.4, -0.9, 0.5, 2.8, 3.9, 4.1, 3.5,
]

BOOM_Q = {
    2021: [125.2, 123.8, 119.2, 119.2],
    2022: [112.7, 101.8, 100.6, 98.9],
    2023: [107.8, 105.9, 108.6, 109.0],
    2024: [109.1, 107.5, 108.1, 108.3],
    2025: [108.5, 108.5, 108.9, 108.4],
    2026: [109.3, 109.5],
}

def boom_monthly():
    out = []
    for y in range(2021, 2027):
        for m in range(1, 13):
            if y == 2026 and m > 7:
                break
            q = min((m - 1) // 3, len(BOOM_Q[y]) - 1)
            out.append(BOOM_Q[y][q])
    return out

BCI_PROXY = boom_monthly()

PMI_MANU = [
    50.1, 52.6, 51.9, 49.2, 48.8, 49.0, 49.3, 49.7, 50.2, 49.5, 49.4, 49.0,
    49.2, 49.1, 50.8, 50.4, 49.5, 49.5, 49.4, 49.1, 49.8, 50.1, 50.3, 50.1,
    49.1, 50.2, 50.5, 49.0, 49.5, 49.7, 49.3, 49.4, 49.8, 49.0, 49.2, 50.1,
    49.3, 49.0, 50.4, 50.3, 50.0, 50.3, 49.2,
]

# 沪深300 月收盘（westock-data kline 查询值；2026-08 为 8/19 收盘）
HS300_CLOSE = {
    "2023-08": 3765.27, "2023-09": 3689.52, "2023-10": 3572.51, "2023-11": 3496.20, "2023-12": 3431.11,
    "2024-01": 3215.35, "2024-02": 3516.08, "2024-03": 3537.48, "2024-04": 3604.39,
    "2024-05": 3579.92, "2024-06": 3461.66, "2024-07": 3442.08, "2024-08": 3321.43,
    "2024-09": 4017.85, "2024-10": 3891.04, "2024-11": 3916.58, "2024-12": 3934.91,
    "2025-01": 3817.08, "2025-02": 3890.05, "2025-03": 3887.31, "2025-04": 3770.57,
    "2025-05": 3840.23, "2025-06": 3936.08, "2025-07": 4075.59, "2025-08": 4496.76,
    "2025-09": 4640.69, "2025-10": 4640.67, "2025-11": 4526.66, "2025-12": 4629.94,
    "2026-01": 4706.34, "2026-02": 4710.65, "2026-03": 4450.05, "2026-04": 4807.31,
    "2026-05": 4892.12, "2026-06": 4979.43, "2026-07": 4588.20, "2026-08": 4588.70,
}

# ---------------------------------------------------------------------------
# 溢价率日频（E/P 分位计算）
# ---------------------------------------------------------------------------
def parse_premium_curve():
    dates, ep, dp = [], [], []
    with open(os.path.join(TMP_DIR, "tmp_premium_curve.txt"), encoding="utf-8") as f:
        for line in f:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[1].isdigit() and len(parts[1]) == 8:
                try:
                    dates.append(parts[1])
                    dp.append(float(parts[2]))
                    ep.append(float(parts[3]))
                except ValueError:
                    dates.pop()
                    continue
    return dates, ep, dp

PREM_DATES, PREM_EP, PREM_DP = parse_premium_curve()

def premium_percentile(iso_date, which="ep"):
    """该日 EquityPremium(或 DividendPremium) 在截至该日全部历史中的分位(0-100)。
    注意：文件按日期倒序排列，当前值必须精确匹配目标日期。"""
    target = iso_date.replace("-", "")
    vals, cur = [], None
    arr = PREM_EP if which == "ep" else PREM_DP
    for dt, v in zip(PREM_DATES, arr):
        if dt <= target:
            vals.append(v)
            if dt == target:
                cur = v
    if not vals or cur is None:
        # 目标日无数据（非交易日）：取目标日前最近一个交易日
        for dt, v in zip(PREM_DATES, arr):
            if dt <= target:
                cur = v
                break
    if not vals or cur is None:
        return 50.0, None
    below = sum(1 for v in vals if v <= cur)
    return 100.0 * below / len(vals), cur

# ---------------------------------------------------------------------------
# 三因子得分（扩展窗口，避免前视）
# ---------------------------------------------------------------------------
def slope3(seg):
    w = len(seg)
    xs = list(range(w))
    mx, my = statistics.mean(xs), statistics.mean(seg)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, seg))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0

def compute_scores():
    """逐月扩展窗口计算 M1-BCI-PPI 综合得分（与 screen.py 同逻辑：z-score + 3个月斜率）。"""
    scores = {}
    for t in range(len(MONTHS)):
        if t < 23:  # 需 ≥24 个月预热（z-score 与 HP 滤波）
            continue
        bci = BCI_PROXY[:t + 1]
        m1 = M1_YOY[:t + 1]
        ppi = PPI_YOY[:t + 1]
        _, ppi_cycle = hp_filter(ppi)
        z_b, z_m, z_p = zscore(bci), zscore(m1), zscore(ppi_cycle)
        score = slope3(z_b[-3:]) + slope3(z_m[-3:]) + slope3(z_p[-3:])
        scores[MONTHS[t]] = score
    return scores

SCORES = compute_scores()

# ---------------------------------------------------------------------------
# 回测：2023-08 ~ 2026-08（信号月末产生，作用于下月）
# ---------------------------------------------------------------------------
BT_MONTHS = [m for m in HS300_CLOSE]  # 2023-08..2026-08 有序

def backtest(use_odds=False):
    """use_odds=False: 纯三因子(得分>0持有)；True: 三因子 OR E/P分位>90(赔率极端) 持有。"""
    nav, curve, pos_months, trades = 1.0, [], 0, []
    for i, m in enumerate(BT_MONTHS[:-1]):
        nxt = BT_MONTHS[i + 1]
        signal_m = m  # 用当月末可得信息
        score = SCORES.get(signal_m)
        ep_pct, _ = premium_percentile(f"{signal_m}-28", "ep")
        if use_odds:
            pos = (score is not None and score > 0) or ep_pct > 90
        else:
            pos = score is not None and score > 0
        if score is None:
            pos = False
        if pos:
            pos_months += 1
        r = (HS300_CLOSE[nxt] / HS300_CLOSE[m] - 1.0) if pos else 0.0
        nav *= (1 + r)
        curve.append((nxt, nav, pos, score, ep_pct))
        trades.append((m, nxt, pos, r))
    return nav, curve, pos_months, trades

def max_drawdown(curve_vals):
    peak, mdd = curve_vals[0], 0.0
    for v in curve_vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return mdd

# ---------------------------------------------------------------------------
# 事件对照表（V2 迁移自原 phase4_events.json 生成逻辑）
# ---------------------------------------------------------------------------
EVENTS = [
    ("2024-08", "924政策底前夕", "2024-09", "2024-11"),
    ("2024-09", "924行情启动当月", "2024-10", "2024-12"),
    ("2025-04", "对等关税冲击底部", "2025-05", "2025-07"),
    ("2025-08", "M1回升+PPI见底", "2025-09", "2025-11"),
    ("2026-06", "指数年内高点(4979)", "2026-07", None),
    ("2026-07", "PMI回落+单月-7.8%", "2026-08", None),
]

def fwd_ret(m_from, m_to):
    if m_to not in HS300_CLOSE or m_from not in HS300_CLOSE:
        return None
    return HS300_CLOSE[m_to] / HS300_CLOSE[m_from] - 1.0

def event_table():
    rows = []
    for m, label, m1f, m3f in EVENTS:
        idx = MONTHS.index(m)
        score = SCORES.get(m)
        ep_pct, ep_val = premium_percentile(f"{m}-28", "ep")
        # 之后1个月/3个月涨幅
        next_m = BT_MONTHS[BT_MONTHS.index(m) + 1] if m in BT_MONTHS and BT_MONTHS.index(m) + 1 < len(BT_MONTHS) else None
        r1 = fwd_ret(m, next_m) if next_m else None
        r3 = None
        if m3f:
            r3 = fwd_ret(m, m3f)
        rows.append({
            "month": m, "event": label,
            "m1": M1_YOY[idx], "ppi": PPI_YOY[idx], "pmi": PMI_MANU[idx - 24],
            "score": score, "ep_pct": ep_pct,
            "r1": r1, "r3": r3,
            "signal": ("胜率+" if score and score > 0 else ("胜率−" if score is not None else "N/A")) +
                      ("|赔率极佳" if ep_pct > 90 else "|赔率中性" if ep_pct > 20 else "|赔率差"),
        })
    return rows

def signal_detail(row):
    """事件行 → 统一格式 trigger_details（WIN=三因子胜率，ODD=E/P赔率）。"""
    det = []
    sc, ep = row["score"], row["ep_pct"]
    det.append({"id": "WIN", "name": "三因子胜率(M1-BCI-PPI)",
                "detail": f"综合得分 {sc:+.2f}（>0 为胜率+）" if sc is not None else "得分 N/A（预热期）",
                "strength": "strong" if (sc is not None and sc > 0) else "direction"})
    det.append({"id": "ODD", "name": "E/P 赔率分位",
                "detail": f"E/P 分位 {ep:.0f}%（>90% 为赔率极佳）",
                "strength": "strong" if ep > 90 else ("mid" if ep > 20 else "direction")})
    return det


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="B 类·事件复算：信号-行情对照 + 回测")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "data", "signalcheck.json"),
        help="输出路径（默认技能内 assets/data/signalcheck.json）")
    args = ap.parse_args()

    print("=" * 88)
    print("Phase 4 信号验证 · 郭磊(广发宏观)框架 · 数据窗口 2023-08 ~ 2026-08")
    print("=" * 88)

    # 回测
    nav_a, curve_a, in_a, trades_a = backtest(use_odds=False)
    nav_b, curve_b, in_b, trades_b = backtest(use_odds=True)
    bh = HS300_CLOSE["2026-08"] / HS300_CLOSE["2023-08"]
    bh_curve = []
    v = 1.0
    for m in BT_MONTHS:
        if m == "2023-08":
            bh_curve.append(1.0); continue
        v *= HS300_CLOSE[m] / HS300_CLOSE[BT_MONTHS[BT_MONTHS.index(m) - 1]]
        bh_curve.append(v)

    print("\n[回测] 2023-08 → 2026-08（37个月），基准=沪深300，信号月末产生作用于下月：")
    def stats_line(name, nav, months_in, mdd):
        total_m = len(BT_MONTHS) - 1
        years = total_m / 12.0
        ann = (nav ** (1 / years) - 1) * 100
        return (f"{name:<22} 总收益 {nav-1:+8.1%}  年化 {ann:+7.1f}%  "
                f"最大回撤 {mdd:7.1%}  持仓 {months_in}/{total_m} 月")
    print("  " + stats_line("A 纯三因子动量", nav_a, in_a, max_drawdown([1.0] + [c[1] for c in curve_a])))
    print("  " + stats_line("B 三因子∪赔率极端", nav_b, in_b, max_drawdown([1.0] + [c[1] for c in curve_b])))
    print("  " + stats_line("C 买入持有沪深300", bh, len(BT_MONTHS) - 1, max_drawdown(bh_curve)))

    hits_a = [(t[0], t[3]) for t in trades_a if t[2]]
    win_a = sum(1 for _, r in hits_a if r > 0)
    hits_b = [(t[0], t[3]) for t in trades_b if t[2]]
    win_b = sum(1 for _, r in hits_b if r > 0)

    # 事件对照
    print("\n[事件对照] E/P分位>90 = 赔率极佳(权益便宜)；胜率+ = 三因子得分>0：")
    results = []
    for row in event_table():
        r1 = f"{row['r1']:+.1%}" if row["r1"] is not None else "  n/a"
        r3 = f"{row['r3']:+.1%}" if row["r3"] is not None else "  n/a"
        sc = f"{row['score']:+.2f}" if row["score"] is not None else "n/a"
        print(f"  {row['month']:<9}{row['event']:<18}{row['m1']:>+6.1f}{row['ppi']:>+6.1f}{sc:>8}"
              f"{row['ep_pct']:>7.0f}%  {row['signal']:<14}{r1:>8}{r3:>8}")
        det = signal_detail(row)
        trig = [d["id"] for d in det
                if (d["id"] == "WIN" and row["score"] is not None and row["score"] > 0)
                or (d["id"] == "ODD" and row["ep_pct"] > 90)]
        results.append({
            "event": row["event"], "month": row["month"],
            "view": "", "view_grade": "", "expect": "",
            "triggers": trig, "trigger_details": [d for d in det if d["id"] in trig],
            "align": "n/a",
            "fwd_1m": round(row["r1"] * 100, 1) if row["r1"] is not None else None,
            "fwd_3m": round(row["r3"] * 100, 1) if row["r3"] is not None else None,
            "fwd_unit": FWD_UNIT,
            # 扩展字段（V1 事件表原字段，保留）
            "m1": row["m1"], "ppi": row["ppi"], "pmi": row["pmi"],
            "score": row["score"], "ep_pct": row["ep_pct"], "signal": row["signal"],
        })

    # 最新月快照（2026-07：三因子胜率 + E/P 赔率）
    last_row = event_table()[-1]  # EVENTS 最后一行为最新月 2026-07
    det_last = signal_detail(last_row)
    trig_last = [d["id"] for d in det_last
                 if (d["id"] == "WIN" and last_row["score"] is not None and last_row["score"] > 0)
                 or (d["id"] == "ODD" and last_row["ep_pct"] > 90)]
    snap = [{"id": d["id"], "name": d["name"],
             "triggered": d["id"] in trig_last, "detail": d["detail"],
             "strength": d["strength"]} for d in det_last]

    out = {
        "analyst": ANALYST, "as_of": "2026-07", "fwd_field": FWD_FIELD,
        "fwd_unit": FWD_UNIT, "events": results, "latest_snapshot": snap,
        # 回测段（V1 保留，扩展键）
        "backtest": {
            "window": "2023-08 ~ 2026-08",
            "A_pure_timing": {"nav": nav_a, "months_in": in_a},
            "B_with_odds": {"nav": nav_b, "months_in": in_b},
            "C_buyhold": {"nav": bh},
            "win_rate_A": 100 * win_a / max(1, len(hits_a)),
            "win_rate_B": 100 * win_b / max(1, len(hits_b)),
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nwrote:", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
