#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
张忆东 Phase 4 A 类·数据准备：组装 macro_real.json 回填 screen.py
====================================================================
V2 迁移自工作区 phase4_zhangyidong.py（计算逻辑原样保留，仅改路径与输出契约）。

数据来源（三层标注，详见 _meta）：
  ✅ westock-data 直连：premium_curve(ERP 日频)、fundquantity(M1/M2)、
     profit(工业企业利润)、financing(社融)、kline hkHSI/sh000300(行情月收)
  ⚠️ 张忆东公开观点锚点：恒指PE/卖空占比/南向/美债/美元/解禁/ETF/标普席勒PE/外资
  ❌ 工程代理：AI 拥挤度/应用可见性/风险偏好/散户情绪

用法（在技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（原始数据 tmp_zyd_*.txt 提前落盘在 {workspace}/.workbuddy/，见规范 §五）
"""
import json
import math
import os
import statistics
import sys
from collections import OrderedDict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "assets", "data", "macro_real.json")
# ============================================================

# 月份序列：2023-01 ~ 2026-08（44 个月；8 月为截至 08-20 部分数据）
MONTHS = []
for y in (2023, 2024, 2025, 2026):
    for m in range(1, 13):
        if y == 2026 and m > 8:
            break
        MONTHS.append(f"{y}-{m:02d}")
assert len(MONTHS) == 44, len(MONTHS)


# ----------------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------------
def flatten(path):
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, dict) and "sections" in d:
        out = []
        for sec in d["sections"]:
            out.extend(sec)
        return out
    return d if isinstance(d, list) else []


def month_of(dt_int):
    """20230131 -> '2023-01'"""
    s = str(int(dt_int))
    return f"{s[:4]}-{s[4:6]}"


def ffill(d, months, key):
    """按月份补全序列，缺失用最近可用值前填。"""
    out = []
    last = None
    for mo in months:
        if mo in d:
            last = d[mo]
        out.append(last)
    return out


# ----------------------------------------------------------------------------
# 1) westock-data 直连数据
# ----------------------------------------------------------------------------
def load_erp_monthly():
    """✅ westock：premium_curve 日频 EquityPremium → 月均。"""
    pts = flatten(os.path.join(TMP_DIR, "tmp_zyd_premium.txt"))
    by_month = {}
    for item in pts:
        mo = month_of(item["EndDate"])
        by_month.setdefault(mo, []).append(item.get("EquityPremium"))
    erp = []
    for mo in MONTHS:
        vals = by_month.get(mo)
        erp.append(round(statistics.mean(vals), 2) if vals else None)
    # 缺失月前填
    last = None
    for i, v in enumerate(erp):
        if v is None:
            erp[i] = last
        else:
            last = v
    return erp


def load_m1_monthly():
    """✅ westock：fundquantity M1 同比。"""
    pts = flatten(os.path.join(TMP_DIR, "tmp_zyd_m12.txt"))
    d = {month_of(p["CURV_END_DATE"]): p.get("CURV_M1_YOY") for p in pts}
    return ffill(d, MONTHS, "m1")


def load_m2_monthly():
    """✅ westock：fundquantity M2 同比。"""
    pts = flatten(os.path.join(TMP_DIR, "tmp_zyd_m12.txt"))
    d = {month_of(p["CURV_END_DATE"]): p.get("CURV_M2_YOY") for p in pts}
    return ffill(d, MONTHS, "m2")


def load_profit_monthly():
    """✅ westock：profit 工业企业利润累计同比。"""
    pts = flatten(os.path.join(TMP_DIR, "tmp_zyd_profit.txt"))
    d = {month_of(p["PROFIT_END_DATE"]): p.get("PROFIT_PROFIT_CUM_YOY") for p in pts}
    return ffill(d, MONTHS, "profit")


def load_financing_monthly():
    """✅ westock：financing 社融增量同比。"""
    pts = flatten(os.path.join(TMP_DIR, "tmp_zyd_financing.txt"))
    d = {month_of(p["FINANCING_END_DATE"]): p.get("FINANCING_SR_INC_YOY") for p in pts}
    return ffill(d, MONTHS, "financing")


def load_hsi_close():
    """✅ westock：kline hkHSI 月度收盘（B 类事件复算的前瞻标的）。"""
    pts = flatten(os.path.join(TMP_DIR, "tmp_zyd_hsi.txt"))
    d = {}
    for p in pts:
        dt = p.get("date", "")
        if len(dt) >= 7:
            d[dt[:7]] = p.get("last")
    return [d.get(mo) for mo in MONTHS]


def load_hs300_close():
    """✅ westock：kline sh000300 月度收盘（B 类事件复算的次级前瞻标的）。"""
    pts = flatten(os.path.join(TMP_DIR, "tmp_zyd_hs300.txt"))
    d = {}
    for p in pts:
        dt = p.get("date", "")
        if len(dt) >= 7:
            d[dt[:7]] = p.get("last")
    return [d.get(mo) for mo in MONTHS]


# ----------------------------------------------------------------------------
# 2) 张忆东公开观点锚点构造（⚠️ 有明确出处，插值平滑）
# ----------------------------------------------------------------------------
def anchor_series(anchor_points, months):
    """anchor_points: {month: value}，线性插值构造整段序列。"""
    keys = sorted(anchor_points.keys())
    out = []
    for mo in months:
        if mo in anchor_points:
            out.append(anchor_points[mo])
            continue
        # 找前后锚点插值
        before = [k for k in keys if k <= mo]
        after = [k for k in keys if k > mo]
        if before and after:
            a, b = before[-1], after[0]
            ia, ib = months.index(a), months.index(b)
            im = months.index(mo)
            va, vb = anchor_points[a], anchor_points[b]
            out.append(round(va + (vb - va) * (im - ia) / max(1, ib - ia), 2))
        elif before:
            out.append(anchor_points[before[-1]])
        elif after:
            out.append(anchor_points[after[0]])
        else:
            out.append(None)
    # 前填/后填 NaN
    last = None
    for i, v in enumerate(out):
        if v is None:
            out[i] = last
        else:
            last = v
    return out


def build_anchors():
    """返回各 ⚠️ 字段的月度序列（基于张忆东公开报告锚点）。"""
    # 恒指前瞻 PE：2023 约 8.5-9（沼泽底）、2024 约 9-10、2025.06=10.7、
    # 2026.05=10、2026.07.30 <11（取 10.5）
    hsi_pe = anchor_series({
        "2023-01": 9.2, "2023-12": 8.8, "2024-03": 9.0, "2024-09": 9.5,
        "2025-06": 10.7, "2025-12": 11.0, "2026-03": 10.8, "2026-05": 10.0,
        "2026-07": 10.5, "2026-08": 10.5,
    }, MONTHS)

    # 港股卖空占比（历史均值15%）：2024.12=13（空头出清）、2026.03 高位、
    # 2026.06 整体 18/恒生科技16/互联网11（取整体 18）
    short_ratio = anchor_series({
        "2023-06": 15.0, "2023-12": 15.5, "2024-03": 16.0, "2024-09": 16.5,
        "2024-12": 13.0, "2025-06": 14.5, "2025-12": 15.5, "2026-03": 16.5,
        "2026-06": 18.0, "2026-07": 17.0, "2026-08": 16.0,
    }, MONTHS)

    # 南向月度净流入（亿港元）：2024 全年 6600 → 月均 550；2025H1 6600 → 月均 1100；
    # 2026 前 4 月 2700 → 月均 675；2026.06 单周 89 → 月约 350
    south_flow = anchor_series({
        "2023-12": 400, "2024-06": 450, "2024-12": 550, "2025-03": 900,
        "2025-06": 1100, "2025-09": 800, "2025-12": 700, "2026-03": 700,
        "2026-04": 650, "2026-05": 500, "2026-06": 350, "2026-07": 500,
        "2026-08": 600,
    }, MONTHS)

    # 南向成长风格占比（%）：2024 高股息主导 → 成长约 30%；2025H1 成长 70%（56+14）
    south_growth_pct = anchor_series({
        "2023-12": 30, "2024-06": 32, "2024-12": 35, "2025-03": 55,
        "2025-06": 70, "2025-12": 68, "2026-03": 65, "2026-06": 62,
        "2026-08": 60,
    }, MONTHS)

    # 10Y 美债收益率（%）：2025 上半年 <4、下半年 4.5-5（张忆东2024.12判断）；
    # 2026 Q2 4.0+、2026.06=4.363、2026.07 走高、2026.08 向 4.8-4.9
    ust10 = anchor_series({
        "2023-06": 3.8, "2023-12": 3.9, "2024-03": 4.2, "2024-09": 3.7,
        "2024-12": 4.2, "2025-03": 4.1, "2025-06": 4.2, "2025-09": 4.4,
        "2025-12": 4.4, "2026-03": 4.2, "2026-06": 4.36, "2026-07": 4.5,
        "2026-08": 4.85,
    }, MONTHS)

    # 美元指数：2023 约 103-104、2024 102-105、2026 Q2 98-102、2026.07=101.36
    usd_index = anchor_series({
        "2023-06": 103.0, "2023-12": 103.5, "2024-06": 104.5, "2024-12": 106.0,
        "2025-06": 98.0, "2025-12": 99.0, "2026-03": 100.0, "2026-06": 101.0,
        "2026-07": 101.4, "2026-08": 101.5,
    }, MONTHS)

    # 港股解禁（亿港元）：2026H1 超 4500 → 月均 750；7月 2750；8月约 3500；9月 5007（未来）
    unlock_amt = anchor_series({
        "2026-01": 750, "2026-02": 750, "2026-03": 750, "2026-04": 750,
        "2026-05": 750, "2026-06": 750, "2026-07": 2750, "2026-08": 3500,
        "2026-09": 5007,
    }, MONTHS)
    # 2023-2025 解禁常态偏低
    for i, mo in enumerate(MONTHS):
        if mo < "2026-01":
            unlock_amt[i] = 600 + 150 * math.sin(i / 4)

    # 机构 ETF 净流入（亿元）：2026.07 单月 4700；常态 200-800
    etf_inflow = anchor_series({
        "2023-12": 300, "2024-06": 400, "2024-12": 500, "2025-06": 600,
        "2025-12": 800, "2026-03": 600, "2026-05": 500, "2026-06": 800,
        "2026-07": 4700, "2026-08": 2000,
    }, MONTHS)

    # 外资净流入（亿港元）：2026 全年累计 71 → 月均约 6-10；2025"见了兔子再撒鹰" 低位
    foreign_flow = anchor_series({
        "2023-12": -50, "2024-06": -30, "2024-12": -20, "2025-06": 20,
        "2025-12": 40, "2026-03": 15, "2026-06": 10, "2026-08": 8,
    }, MONTHS)

    # 沪深300 PE：2026.07.30 不到 13 倍；2024 约 11-12；2025 约 12-13
    hs300_pe = anchor_series({
        "2023-06": 11.5, "2023-12": 11.0, "2024-09": 11.5, "2024-12": 12.5,
        "2025-06": 13.0, "2025-12": 13.5, "2026-03": 13.2, "2026-07": 12.8,
        "2026-08": 12.8,
    }, MONTHS)

    # 标普500 席勒PE：2026.07.30=38（150年第二高位）；2023 约 30-32；2025 约 35-37
    sp500_pe = anchor_series({
        "2023-06": 31.0, "2023-12": 32.0, "2024-12": 35.0, "2025-06": 36.0,
        "2025-12": 37.0, "2026-03": 37.5, "2026-07": 38.0, "2026-08": 38.0,
    }, MONTHS)

    # 恒指 ERP（%）：2025.06 vs 中债 8%；2026 约 7-8
    erp_hsi = anchor_series({
        "2023-12": 7.5, "2024-06": 7.8, "2024-12": 8.2, "2025-06": 8.0,
        "2025-12": 7.6, "2026-03": 7.4, "2026-06": 7.8, "2026-08": 7.5,
    }, MONTHS)

    return {
        "hsi_pe": hsi_pe, "short_ratio": short_ratio, "south_flow": south_flow,
        "south_growth_pct": south_growth_pct, "ust10": ust10,
        "usd_index": usd_index, "unlock_amt": unlock_amt, "etf_inflow": etf_inflow,
        "foreign_flow": foreign_flow, "hs300_pe": hs300_pe, "sp500_pe": sp500_pe,
        "erp_hsi": erp_hsi,
    }


# ----------------------------------------------------------------------------
# 3) 工程代理（❌ 推断，方向依据张忆东叙事构造）
# ----------------------------------------------------------------------------
def build_proxies():
    """AI 拥挤度/应用可见性/风险偏好/散户情绪 的 ❌ 代理序列。"""
    ai_hardware_crowd, ai_app_visible, smart_risk, retail_sentiment = [], [], [], []
    for i, mo in enumerate(MONTHS):
        # AI 硬件拥挤度：2023 低(30-40) → 2024 升(45-55) → 2025 高(55-65)
        #   → 2026H1 极高(70-80，万事皆渣唯有AI) → 2026.07 回落(65)
        if mo < "2024-01":
            hw = 32 + 0.8 * (i % 12)
        elif mo < "2025-01":
            hw = 45 + 0.6 * (i % 12)
        elif mo < "2026-01":
            hw = 55 + 0.5 * (i % 12)
        elif mo < "2026-07":
            hw = 72 + 0.8 * (i % 12)
        else:
            hw = 66 if mo == "2026-07" else 62
        ai_hardware_crowd.append(round(min(80, hw)))

        # AI 应用可见性：2026.07 前 <0.5，翻多后升至 0.65
        if mo < "2026-07":
            av = 0.25 + 0.01 * (i % 12)
        else:
            av = 0.65 if mo == "2026-07" else 0.7
        ai_app_visible.append(round(min(1.0, av), 2))

        # 风险偏好：2023 中性(45-55) → 2024 低(35-45) → 2025 高(60-70)
        #   → 2026H1 极高(75) → 2026.07-08 回落(55)
        if mo < "2024-01":
            rk = 50
        elif mo < "2024-10":
            rk = 40
        elif mo < "2025-01":
            rk = 55
        elif mo < "2026-01":
            rk = 65
        elif mo < "2026-06":
            rk = 72
        else:
            rk = 55
        smart_risk.append(rk + (i % 3 - 1))

        # 散户情绪：2025 高(65-70) → 2026.07 恐慌撤离(35) → 08 修复(45)
        if mo < "2026-07":
            rs = 60 + 0.4 * (i % 12)
        else:
            rs = 35 if mo == "2026-07" else 45
        retail_sentiment.append(round(min(75, rs)))

    return {
        "ai_hardware_crowd": ai_hardware_crowd, "ai_app_visible": ai_app_visible,
        "smart_risk": smart_risk, "retail_sentiment": retail_sentiment,
    }


# ----------------------------------------------------------------------------
# 组装
# ----------------------------------------------------------------------------
def build_macro_json():
    erp_a = load_erp_monthly()
    m1 = load_m1_monthly()
    m2 = load_m2_monthly()
    profit = load_profit_monthly()
    financing = load_financing_monthly()
    anchors = build_anchors()
    proxies = build_proxies()
    hsi_close = load_hsi_close()
    hs300_close = load_hs300_close()

    # 社融存量同比近似：westock 给的是增量同比，用其平滑（⚠️ 口径）
    sf_yoy = financing

    history = {
        "erp_a": erp_a,
        "hsi_pe": anchors["hsi_pe"],
        "short_ratio": anchors["short_ratio"],
        "south_flow": [round(v) for v in anchors["south_flow"]],
        "south_growth_pct": [round(v) for v in anchors["south_growth_pct"]],
        "corp_profit_yoy": profit,
        "social_financing_yoy": sf_yoy,
        "m1_yoy": m1,
        "ust10": anchors["ust10"],
        "usd_index": anchors["usd_index"],
        "ai_hardware_crowd": proxies["ai_hardware_crowd"],
        "ai_app_visible": proxies["ai_app_visible"],
        "smart_risk": proxies["smart_risk"],
        "unlock_amt": anchors["unlock_amt"],
        "etf_inflow": anchors["etf_inflow"],
        "retail_sentiment": proxies["retail_sentiment"],
        "hs300_pe": anchors["hs300_pe"],
        "sp500_pe": anchors["sp500_pe"],
        "erp_hsi": anchors["erp_hsi"],
        "foreign_flow": [round(v) for v in anchors["foreign_flow"]],
        "hsi_close": hsi_close,
        "hs300_close": hs300_close,
    }

    data = {
        "as_of": "2026-08-20",
        "history": history,
        "extras": {
            "south_style": "growth",
            "ai_phase": "application",
        },
        "_meta": {
            "analyst": "张忆东",
            "window": "2023-01 ~ 2026-08",
            "sources": {
                "✅westock": ["erp_a(premium_curve)", "m1_yoy(fundquantity)",
                              "corp_profit_yoy(profit)", "social_financing_yoy(financing)",
                              "hsi_close(kline hkHSI)", "hs300_close(kline sh000300)"],
                "⚠️锚点": ["hsi_pe", "short_ratio", "south_flow", "south_growth_pct",
                           "ust10", "usd_index", "unlock_amt", "etf_inflow",
                           "hs300_pe", "sp500_pe", "erp_hsi", "foreign_flow"],
                "❌代理": ["ai_hardware_crowd", "ai_app_visible", "smart_risk",
                           "retail_sentiment"],
            },
            "note": "ERP 为 westock 口径（当前 3.02%），与张忆东引用值（2026.03 为 5.3%）口径不同，绝对水平不可直接比对；分位/方向可用。",
        },
    }
    return data


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="A 类·数据准备：组装 macro_real.json")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="输出路径（默认技能内 assets/data/macro_real.json）")
    args = ap.parse_args()

    data = build_macro_json()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("wrote:", os.path.abspath(args.out))

    # 各字段长度检查
    h = data["history"]
    print("fields:", len(h), "| months:", len(MONTHS))
    for k, v in h.items():
        assert len(v) == len(MONTHS), f"{k}: {len(v)} != {len(MONTHS)}"
    print("all fields aligned ✓")

    # 缺口检查（None 月份统计）
    print("\n=== 缺口检查 ===")
    for f, arr in h.items():
        n_none = sum(1 for v in arr if v is None)
        flag = "  ⚠️ 缺口大" if n_none > len(MONTHS) * 0.3 else ""
        print("  %-18s None %2d/%d%s" % (f, n_none, len(MONTHS), flag))

    print("\n下一步：python scripts/screen.py --data %s --json-out" % args.out)


if __name__ == "__main__":
    main()
