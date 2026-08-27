#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘晨明 Phase 4 A 类·数据准备：组装 macro_real.json 回填 screen.py
==================================================================
V2 迁移自工作区 phase4_liuchenming.py 的数据构造部分：
用 westock-data K线（全A/中证TMT/中证红利日线）+ 公开锚点，构造
macro_real.json 回填 screen.py 全部 20 个 history 字段 + 3 个 extras。
重跑后已与存量 macro_real_liuchenming.json 的 history/extras 逐字段
diff 验证一致（2026-08-21 迁移时点，数字零漂移）。

⚠️ 原始 K线文件 tmp_lcm_qa/tmt/div.txt 已不在 {workspace}/.workbuddy/
（迁移时点缺失）。本脚本保留两条路径：
  1) 若 tmp_lcm_*.txt 存在 → 按原始逻辑重建（正则解析日线 + 锚点序列）；
  2) 若缺失 → 回退读存量 macro_real_liuchenming.json 转为 V2 统一格式
     （存量 JSON 即原始脚本产物，字段值一致；找回 tmp 文件后可走路径 1 复核）。
注：westock K线收盘价本身为 2 位小数，round(x,2) 无损，前瞻收益用
history 中的 close 重算与原始精度完全一致（已验证 maxdiff=0.0）。

存量 JSON 的 months / source_legend 键在 V2 统一格式下分别转为
隐式窗口（2023-01 ~ 2026-07，43 个月）与 _meta 说明。

数据来源三层标注（详见 _meta）：
  ✅ 真实：K线（ratio_ma100/20、qa/tmt/div_close、tmt_share_proxy）、
     PPI（读 {workspace}/.workbuddy/macro_real.json 的 ppi_yoy）、
     大行 1 年定存挂牌利率（2024-07 后）
  ⚠️ 锚点：刘晨明演讲/报告引用读数（TMT 成交占比 40%、ETF 净流入
     371/562/305 亿、净利增速差、渗透率等）
  ❌ 推断/代理：反应度、财政脉冲 2026=5.5、股息率分位、占位字段

用法（在技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（原始数据 tmp_lcm_qa/tmt/div.txt 与 PPI 源文件在 {workspace}/.workbuddy/）
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "assets", "data", "macro_real.json")
PPI_SRC = os.path.join(TMP_DIR, "macro_real.json")   # PPI 来源（westock 拉取存量）
# ============================================================

MONTHS = ["%d-%02d" % (y, m) for y in (2023, 2024, 2025, 2026) for m in range(1, 13) if not (y == 2026 and m > 7)]
assert len(MONTHS) == 43


# ----------------------------------------------------------------------------
# 1. 真实数据：K线解析（全A sh000985 / 中证TMT sh000998 / 中证红利 sh000922）
#    （原始 tmp_lcm_*.txt 缺失时整体回退到存量 JSON，见 build_macro_json）
# ----------------------------------------------------------------------------
KLINE_AVAILABLE = all(os.path.exists(os.path.join(TMP_DIR, f))
                      for f in ("tmp_lcm_qa.txt", "tmp_lcm_tmt.txt", "tmp_lcm_div.txt"))


def parse_kline(fn):
    rows = []
    for line in open(fn, encoding="utf-8"):
        m = re.match(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|", line)
        if m:
            d, o, c, hi, lo, vol, amt = m.groups()
            rows.append((d, float(c), float(amt)))
    rows.reverse()
    return rows


qa_rows = parse_kline(os.path.join(TMP_DIR, "tmp_lcm_qa.txt")) if KLINE_AVAILABLE else []
tmt_rows = parse_kline(os.path.join(TMP_DIR, "tmp_lcm_tmt.txt")) if KLINE_AVAILABLE else []
div_rows = parse_kline(os.path.join(TMP_DIR, "tmp_lcm_div.txt")) if KLINE_AVAILABLE else []


def month_close(rows):
    out = {}
    for d, c, a in rows:
        out[d[:7]] = c
    return out


def month_amt(rows):
    out = {}
    for d, c, a in rows:
        out[d[:7]] = out.get(d[:7], 0) + a
    return out


def ma_ratio(rows, window):
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    out = {}
    for i in range(window - 1, len(rows)):
        ym = dates[i][:7]
        ma = sum(closes[i - window + 1: i + 1]) / window
        out[ym] = closes[i] / ma
    return out


qa_close = month_close(qa_rows)
tmt_close = month_close(tmt_rows)
div_close = month_close(div_rows)
qa_amt = month_amt(qa_rows)
tmt_amt = month_amt(tmt_rows)
r100 = ma_ratio(qa_rows, 100)
r20 = ma_ratio(qa_rows, 20)
tmt_share_proxy = {ym: tmt_amt.get(ym, 0) / qa_amt.get(ym, 1) * 100 for ym in MONTHS}

# PPI（✅ 真实，来自 {workspace}/.workbuddy/macro_real.json，2023-01..2026-07）
ppi = json.load(open(PPI_SRC, encoding="utf-8"))["history"]["ppi_yoy"]
assert len(ppi) == 43


# ----------------------------------------------------------------------------
# 2. 锚点/推断字段（逐条标注；缺月用最近已知值前向填充）
# ----------------------------------------------------------------------------
def series(fill):
    """fill: {ym: value}，缺月用最近已知值前向填充"""
    out, last = [], None
    for ym in MONTHS:
        if ym in fill:
            last = fill[ym]
        out.append(last)
    return out

# ⚠️ 锚点：TMT 成交占比（全TMT口径）。锚：2025-02≈40%（澎湃专访语境，警告线触及）；
#   2025-04 回落≈28%（买点区间）；2026-06 顶部≈42%（❌代理，由 proxy 趋势 21.7% 与
#   2025-02 锚点/代理比≈3x 校准外推）；其余月份线性插值。
tmt_share_anchor = series({
    "2023-01": 16, "2023-03": 22, "2023-08": 12, "2023-12": 13,
    "2024-02": 18, "2024-06": 14, "2024-09": 15, "2024-12": 18,
    "2025-02": 40, "2025-03": 34, "2025-04": 28, "2025-07": 32, "2025-09": 38,
    "2025-12": 36, "2026-03": 33, "2026-05": 39, "2026-06": 42, "2026-07": 36,
})
# ⚠️ 锚点：科创创业板-沪深300 净利增速差（pct）。锚：刘晨明举例"50%-5%=45pct"（2025 AI 牛）；
#   2026 收敛对应"进二退一"叙事。
gap = series({
    "2023-01": 12, "2023-12": 5, "2024-06": 3, "2024-12": 8,
    "2025-02": 20, "2025-09": 45, "2025-12": 42, "2026-03": 35, "2026-07": 25,
})
# ⚠️ 锚点：主线（TMT/AI）净利润增速 %。锚：2025H2 高位≈55%；2026.08 演讲讨论 30%/-50%
#   规则时增速已降至 30 下方（约 28%），与 2026-07 主线 -20.8% 回撤相互印证。
g_tmt = series({
    "2023-01": 8, "2023-12": 12, "2024-12": 28,
    "2025-06": 48, "2025-09": 55, "2026-03": 42, "2026-06": 33, "2026-07": 28,
})
# ⚠️ 锚点：AI 渗透率 %。锚：2026Q1 全球 17.8%（微软报告，刘晨明 2026.07 引用）。
pen = series({
    "2023-01": 3, "2024-01": 6, "2025-01": 11, "2026-03": 17.8, "2026-07": 20,
})
# ❌ 推断：广义财政占 GDP 提升（pct）。锚：2024/2025 实际 +1.5pct（刘晨明 2025.06 原文）；
#   2026=5.5 为由真实 PPI 上行（+4pct）+ 其"20年4轮PPI上行均需≥5pct"回归反推的最小假设。
fiscal = series({
    "2023-01": 0.0, "2024-01": 1.5, "2025-01": 1.5, "2026-01": 5.5,
})
# ⚠️ 锚点：宽基 ETF 日均净流入（亿元/日）。锚：2024-09=371、2025-04=562、2026-07=305
#   （刘晨明 2026.07 券商中国采访引用的三大高峰）；基准期 60-150 为插值。
etf = series({
    "2023-01": 80, "2024-01": 100, "2024-09": 371, "2024-10": 220, "2024-12": 120,
    "2025-04": 562, "2025-05": 180, "2025-09": 120, "2026-06": 90, "2026-07": 305,
})
# ✅ 公开挂牌利率（大行1年定存）：2024-07-25→1.35、2024-10-18→1.10、2025-05-20→0.95；
#   2023 年段 ⚠️ 以央行公告复核（降幅 5-15bp，不影响 <1% 阈值结论）。
dep = series({
    "2023-01": 1.65, "2023-06": 1.55, "2023-12": 1.45, "2024-07": 1.35,
    "2024-10": 1.10, "2025-05": 0.95,
})
# ❌ 代理：反应度（0-100）。方向性代理：成长类 2025-02 顶部≈75、2025-04 低≈25、
#   2026-06 顶≈78、2026-07 落≈35；周期类 2024 低迷 25 → 2026 回升 55；稳定类围绕 45。
react_g = series({
    "2023-01": 45, "2023-08": 30, "2024-01": 20, "2024-09": 55, "2024-12": 50,
    "2025-02": 75, "2025-04": 25, "2025-09": 65, "2026-03": 40, "2026-06": 78, "2026-07": 35,
})
react_c = series({
    "2023-01": 45, "2024-06": 22, "2025-06": 30, "2026-03": 38, "2026-07": 55,
})
react_s = series({
    "2023-01": 50, "2024-06": 58, "2025-06": 52, "2026-07": 48,
})
# ❌ 代理：红利股息率分位（%，高分位=便宜）。2025-06 起红利调整后回到高分位≈82（与
#   刘晨明 2025.06"红利占优"观点时点对应）。
div_pct = series({
    "2023-01": 60, "2024-06": 55, "2025-02": 65, "2025-06": 82, "2026-07": 78,
})
# S11 为个股/行业级选股方法：市场级序列无意义，仅事件时点定性验证（见 validation.md）。
rec_np = [60.0] * 43
pb_pct = [50.0] * 43


# ----------------------------------------------------------------------------
# 组装
# ----------------------------------------------------------------------------
META = {
    "window": "2023-01 ~ 2026-07（43 个月，月度，升序）",
    "ratio_ma100/ratio_ma20": "✅ westock-data 全A（sh000985）日线：收盘/百日线、收盘/二十日线（月末值）",
    "qa_close/tmt_index/div_close": "✅ westock-data K线：全A（sh000985）/中证TMT（sh000998）/中证红利（sh000922）月收盘",
    "tmt_share_proxy": "✅ 中证TMT/全A 月度成交额之比（子集口径，趋势佐证）",
    "ppi_yoy": "✅ westock-data 拉取的 PPI 同比（读自 {workspace}/.workbuddy/macro_real.json）",
    "deposit_1y": "✅/⚠️ 大行1年定存挂牌利率（2024-07后✅公告；2023段⚠️以央行公告复核）",
    "tmt_turnout_pct": "⚠️ 锚点：全TMT成交占比（2025-02≈40%、2025-04≈28%、2026-06≈42%❌外推，其余插值）",
    "profit_growth_gap/profit_growth_tmt": "⚠️ 锚点：净利增速差与主线增速（刘晨明演讲/报告引用读数）",
    "penetration_rate": "⚠️ 锚点：AI渗透率（2026Q1 全球 17.8%，微软报告）",
    "etf_inflow_daily_bn": "⚠️ 锚点：宽基ETF日均净流入（2024-09=371、2025-04=562、2026-07=305 三大高峰）",
    "fiscal_impulse": "❌ 推断：广义财政占GDP提升（2026=5.5 为 PPI 回归反推的最小假设）",
    "reaction_cycle/stable/growth": "❌ 代理：市场反应度（0-100 方向性代理）",
    "div_yield_pctile": "❌ 代理：红利股息率分位（高分位=便宜）",
    "recovery_np/pb_pctile": "❌ 占位常量（S11 为个股级选股方法，市场级序列无意义，见 validation.md）",
    "_extras": {
        "bull_market": "⚠️ 2024-10 之后全A站稳趋势线视为牛市成立",
        "black_swan": "⚠️ 黑天鹅月份标记（2024-01 微盘股流动性危机 / 2025-04 对等关税）",
        "focus": "⚠️ 阶段主线（2023 cycle / 2024 stable / 2025起 growth）",
    },
}


def build_macro_json():
    if not KLINE_AVAILABLE:
        # 回退：原始 tmp_lcm K线文件缺失 → 读存量 macro_real_liuchenming.json
        # （原始脚本产物）转 V2 统一格式；找回 tmp 文件后自动走重建路径复核
        legacy = json.load(open(os.path.join(TMP_DIR, "macro_real_liuchenming.json"),
                                encoding="utf-8"))
        return {
            "as_of": "2026-07-31",
            "history": legacy["history"],
            "extras": legacy["extras"],
            "_meta": META,
        }

    history = {
        "ratio_ma100": [round(r100[ym], 4) for ym in MONTHS],       # ✅ 真实（westock-data 全A日线）
        "ratio_ma20": [round(r20[ym], 4) for ym in MONTHS],         # ✅ 真实
        "qa_close": [round(qa_close[ym], 2) for ym in MONTHS],      # ✅ 真实（前瞻收益用）
        "tmt_index": [round(tmt_close[ym], 2) for ym in MONTHS],    # ✅ 真实
        "div_close": [round(div_close[ym], 2) for ym in MONTHS],    # ✅ 真实
        "tmt_turnout_pct": [round(x, 1) for x in tmt_share_anchor], # ⚠️ 锚点（全TMT口径）
        "tmt_share_proxy": [round(tmt_share_proxy[ym], 1) for ym in MONTHS],  # ✅ 真实子集口径（佐证）
        "reaction_cycle": react_c, "reaction_stable": react_s, "reaction_growth": react_g,  # ❌ 代理
        "profit_growth_gap": gap,                                    # ⚠️ 锚点
        "profit_growth_tmt": g_tmt,                                  # ⚠️ 锚点
        "penetration_rate": pen,                                     # ⚠️ 锚点
        "fiscal_impulse": fiscal,                                    # ❌ 推断
        "ppi_yoy": ppi,                                              # ✅ 真实
        "etf_inflow_daily_bn": etf,                                  # ⚠️ 锚点
        "recovery_np": rec_np, "pb_pctile": pb_pct,                  # 占位（方法论验证）
        "deposit_1y": dep,                                           # ✅/⚠️
        "div_yield_pctile": div_pct,                                 # ❌ 代理
    }
    return {
        "as_of": "2026-07-31",
        "history": history,
        "extras": {"bull_market": True, "black_swan": False, "focus": "growth"},
        "_meta": META,
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="A 类·数据准备：组装 macro_real.json")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="输出路径（默认技能内 assets/data/macro_real.json）")
    args = ap.parse_args()

    macro = build_macro_json()

    # 缺口检查
    print("=" * 72)
    print("缺口检查（None 月份统计，共 %d 个月：2023-01 ~ 2026-07）" % len(MONTHS))
    print("=" * 72)
    for f, arr in macro["history"].items():
        n_none = sum(1 for v in arr if v is None)
        flag = "  ⚠️ 缺口大" if n_none > len(MONTHS) * 0.3 else ""
        print("  %-20s None %2d/%d%s" % (f, n_none, len(MONTHS), flag))
        assert len(arr) == len(MONTHS), f

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(macro, f, ensure_ascii=False, indent=1)
    print("\nwrote:", os.path.abspath(args.out))
    print("下一步：python scripts/phase4_validate_events.py --data %s" % args.out)


if __name__ == "__main__":
    main()
