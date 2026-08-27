#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘晨明 Phase 4 B 类·事件复算：信号-观点-行情三方对照
=====================================================
V2 迁移自工作区 phase4_liuchenming.py 的验证部分：
对 9 个关键事件时点，用"截至该月"的数据窗口（无前视）复算 S1-S12
信号，与刘晨明同期公开观点 + 真实行情（全A/中证TMT/中证红利）
三方对照。重跑后已与存量 phase4_liuchenming_result.json 逐事件
对照验证一致（signals / fwd 6 字段 / readings / extras / snapshot，
2026-08-21 迁移时点）。

输出统一 signalcheck.json 格式；V1 事件表原字段（signals 列表、
readings、事件时点 extras、TMT/红利前瞻收益）作为扩展键保留。
V1 事件含分析师同期观点（view 文本）但无 ✅/⚠️ 分级与预期方向，
故 view_grade / expect 留空、align 填 "n/a"（诚实标注，不虚构）。

前瞻收益基准：fwd_1m/fwd_3m 用全A（qa_close）；TMT/红利另存扩展键。
2026-08 部分月收益（aug_partial_qa/tmt）：优先读 tmp_lcm K线文件，
缺失时用 V1 快照固化值（phase4_liuchenming_result.json 记录值）。

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
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
ANALYST = "liuchenming"
FWD_FIELD = "qa"               # 前瞻标的：全A（月收盘）
FWD_UNIT = "pct"               # 前瞻收益 %
# V1 快照固化的 2026-08 部分月收益（原始 tmp_lcm K线文件缺失时的回退值；
# 找回 tmp_lcm_qa/tmt.txt 后自动改由文件实时计算）
AUG_PARTIAL_QA_FALLBACK = 2.4161978722955
AUG_PARTIAL_TMT_FALLBACK = 1.287384206942721
# ============================================================

MONTHS = ["%d-%02d" % (y, m) for y in (2023, 2024, 2025, 2026) for m in range(1, 13) if not (y == 2026 and m > 7)]
assert len(MONTHS) == 43

# ---------------------------------------------------------------------------
# 事件定义（V2 迁移自 phase4_liuchenming.py；V1 无观点分级，view_grade/expect 留空）
# ---------------------------------------------------------------------------
EVENTS = [
    ("2024-01", "微盘股流动性危机", "跌破趋势线但属黑天鹅：'仅两次有效跌破均系黑天鹅'（2026.07富国演讲复盘所指第一例）"),
    ("2024-09", "924行情启动", "宽基ETF日均净流入371亿=第一高峰；牛市前提确立（全A站上MA100）"),
    ("2024-12", "年度策略：财政发力", "广义财政发力→PPI回升→ROE上行；目标≥5pct（实际2025仅+1.5pct）"),
    ("2025-02", "TMT拥挤度触及40%", "澎湃专访：达40%短期调整概率大；回落25-30%是较佳买点"),
    ("2025-04", "对等关税冲击", "宽基ETF日均净流入562亿=第二高峰；黑天鹅式跌破，V型修复"),
    ("2025-06", "红利现金替代", "大行1年定存利率下破1%（2025-05-20降至0.95）→红利优于定存"),
    ("2026-03", "ROE五年首次回升", "广义财政-PPI-ROE传导兑现：真实PPI于2026-02转正、连续回升"),
    ("2026-07", "AI进二退一·第二次胜负手", "主线回撤+宽基ETF日均净流入305亿=第三高峰；'跌到趋势线=再布局'"),
    ("2026-08", "景气拐点双经验值", "主线净利润增速降至30%下方→30%/-50%双阈值预警框架"),
]


def extras_at(ym):
    black = ym in ("2024-01", "2025-04")           # 微盘股流动性危机 / 对等关税
    bull = ym >= "2024-10"                          # 924 之后站稳趋势线
    if ym <= "2023-12":
        focus = "cycle"
    elif ym <= "2024-12":
        focus = "stable"
    else:
        focus = "growth"
    return {"bull_market": bull, "black_swan": black, "focus": focus}


# ---------------------------------------------------------------------------
# K线（2026-08 部分月收益用；与 A 类脚本同款解析）
# ---------------------------------------------------------------------------
def parse_kline(fn):
    rows = []
    for line in open(fn, encoding="utf-8"):
        m = re.match(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|", line)
        if m:
            d, o, c, hi, lo, vol, amt = m.groups()
            rows.append((d, float(c), float(amt)))
    rows.reverse()
    return rows


def load_aug_partial(qa_close, tmt_close):
    """2026-08 部分月收益（%）：tmp_lcm K线文件可用则实时计算，否则用固化值。"""
    try:
        qa_aug = {}
        tmt_aug = {}
        for d, c, a in parse_kline(os.path.join(TMP_DIR, "tmp_lcm_qa.txt")):
            qa_aug[d[:7]] = c
        for d, c, a in parse_kline(os.path.join(TMP_DIR, "tmp_lcm_tmt.txt")):
            tmt_aug[d[:7]] = c
        if "2026-08" in qa_aug and "2026-08" in tmt_aug:
            return ((qa_aug["2026-08"] / qa_close["2026-07"] - 1) * 100,
                    (tmt_aug["2026-08"] / tmt_close["2026-07"] - 1) * 100)
    except FileNotFoundError:
        pass
    return AUG_PARTIAL_QA_FALLBACK, AUG_PARTIAL_TMT_FALLBACK


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="B 类·事件复算：信号-观点-行情对照")
    ap.add_argument("--data", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "data", "macro_real.json"),
        help="A 类脚本输出的 macro_real.json 路径")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "data", "signalcheck.json"),
        help="输出路径（默认技能内 assets/data/signalcheck.json）")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        macro = json.load(f)
    history = macro["history"]
    for f_name, arr in history.items():
        assert len(arr) == len(MONTHS), f"{f_name}: {len(arr)} != {len(MONTHS)}"

    # 前瞻收益基准（westock K线收盘 2 位小数，round 无损）
    qa_close = dict(zip(MONTHS, history["qa_close"]))
    tmt_close = dict(zip(MONTHS, history["tmt_index"]))
    div_close = dict(zip(MONTHS, history["div_close"]))

    def window_at(ym):
        if ym not in MONTHS:  # 2026-08 等未入库月份：用截至最新可得月（2026-07）的全窗口
            return {k: list(v) for k, v in history.items()}
        i = MONTHS.index(ym)
        return {k: list(v[: i + 1]) for k, v in history.items()}

    def fwd(ym, closes, n):
        if ym not in MONTHS:
            return None  # 2026-08：前瞻收益不可得，用 8 月部分月收益（aug_partial_*）替代
        i = MONTHS.index(ym)
        if i + n >= len(MONTHS):
            return None
        return (closes[MONTHS[i + n]] / closes[ym] - 1) * 100

    aug_qa, aug_tmt = load_aug_partial(qa_close, tmt_close)

    CALCS = [(i, getattr(screen, "calc_s%d" % i)) for i in range(1, 13)]

    print("=" * 88)
    print("Phase 4 事件时点复算 · 刘晨明(广发策略)框架 · 数据窗口 2023-01 ~ 2026-07")
    print("=" * 88)
    print("\n%-8s %-16s %-26s %7s %7s %7s %7s" % ("月份", "事件", "信号", "全A1M", "全A3M", "TMT1M", "TMT3M"))

    results = []
    for ym, name, view in EVENTS:
        h = window_at(ym)
        ex = extras_at(ym)
        sigs = []
        sig_details = []
        for i, fn in CALCS:
            try:
                r = fn(h, ex)
                sig_details.append(r)
                if r.get("triggered"):
                    sigs.append("S%d" % i)
            except Exception:
                sigs.append("S%d(ERR)" % i)
        fwd_qa_1m, fwd_qa_3m = fwd(ym, qa_close, 1), fwd(ym, qa_close, 3)
        fwd_tmt_1m, fwd_tmt_3m = fwd(ym, tmt_close, 1), fwd(ym, tmt_close, 3)
        fwd_div_1m, fwd_div_3m = fwd(ym, div_close, 1), fwd(ym, div_close, 3)

        def fmt(x):
            return ("%+.1f" % x) if x is not None else "—"
        print("%-8s %-16s %-26s %7s %7s %7s %7s" % (
            ym, name[:8], ",".join(sigs)[:26],
            fmt(fwd_qa_1m), fmt(fwd_qa_3m), fmt(fwd_tmt_1m), fmt(fwd_tmt_3m)))

        results.append({
            "event": name, "month": ym,
            "view": view, "view_grade": "", "expect": "",
            "triggers": sigs,
            "trigger_details": [
                {"id": s["id"], "name": s["name"], "detail": s["detail"],
                 "strength": s["strength"]}
                for s in sig_details
                if s.get("id") in [t.replace("(ERR)", "") for t in sigs]
            ],
            "align": "n/a",
            "fwd_1m": round(fwd_qa_1m, 1) if fwd_qa_1m is not None else None,
            "fwd_3m": round(fwd_qa_3m, 1) if fwd_qa_3m is not None else None,
            "fwd_unit": FWD_UNIT,
            # 扩展字段（V1 事件表原字段，保留）
            "extras": ex,
            "readings": {
                "ratio_ma100": h["ratio_ma100"][-1], "ratio_ma20": h["ratio_ma20"][-1],
                "tmt_share_anchor": h["tmt_turnout_pct"][-1], "tmt_share_proxy": h["tmt_share_proxy"][-1],
                "ppi_yoy": h["ppi_yoy"][-1], "etf": h["etf_inflow_daily_bn"][-1],
                "g_tmt": h["profit_growth_tmt"][-1], "gap": h["profit_growth_gap"][-1],
                "deposit": h["deposit_1y"][-1], "fiscal": h["fiscal_impulse"][-1],
            },
            "fwd_tmt_1m": fwd_tmt_1m, "fwd_tmt_3m": fwd_tmt_3m,
            "fwd_div_1m": fwd_div_1m, "fwd_div_3m": fwd_div_3m,
        })

    # 2026-07末/8月部分月信号快照（h_now + ex_now 全窗口）
    h_now = {k: list(v) for k, v in history.items()}
    ex_now = {"bull_market": True, "black_swan": False, "focus": "growth"}
    snap_sigs = []
    for i, fn in CALCS:
        r = fn(h_now, ex_now)
        snap_sigs.append(r)

    # 最新月快照（统一格式：S1-S12 全量触发状态）
    latest_snapshot = [{"id": s["id"], "name": s["name"], "triggered": s["triggered"],
                        "detail": s["detail"], "strength": s["strength"]} for s in snap_sigs]

    # V1 snapshot（aug_partial 部分月收益 + 关键读数，扩展键保留）
    tmt_peak = max(tmt_close[m] for m in MONTHS if m <= "2026-07")
    v1_snapshot = {
        "month": "2026-07", "aug_partial_qa": aug_qa, "aug_partial_tmt": aug_tmt,
        "signals_now": [s["id"] for s in snap_sigs if s["triggered"]],
        "readings_now": {"ratio_ma100": history["ratio_ma100"][-1],
                         "tmt_dd_pct": round((tmt_close["2026-07"] / tmt_peak - 1) * 100, 1),
                         "ppi_yoy": history["ppi_yoy"][-1]},
    }
    print("\n快照（2026-07末/8月部分）:", json.dumps(v1_snapshot, ensure_ascii=False))

    out = {
        "analyst": ANALYST, "as_of": "2026-07", "fwd_field": FWD_FIELD,
        "fwd_unit": FWD_UNIT, "events": results, "latest_snapshot": latest_snapshot,
        # V1 snapshot 扩展键（aug_partial 来源：tmp_lcm 文件缺失时为固化值）
        "snapshot": v1_snapshot,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nwrote:", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
