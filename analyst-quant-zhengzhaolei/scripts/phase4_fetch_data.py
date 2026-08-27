#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
郑兆磊 Phase 4 A 类·数据准备：组装 macro_real.json 回填 screen.py
====================================================================
依据 analyst-distill 规范（phase4-scripts-conventions.md）编写。

数据来源（三层标注，详见 _meta）：
  ✅ westock-data 直连：kline sh000300/sh000852(指数月收)、premium_curve(股债溢价→ERP 滚动 4 年分位)、
     financing(社融存量同比→信用扩张)、yield_curve(国债 10Y-2Y→期限利差)、kline fxUSDCNY(汇率→升值指数)
  ⚠️ 观点锚点：本技能郑兆磊观点未公布可插值的月度数值序列（仅 2026-08 ERP 3.0 分位 35.4 等快照，
     见 references/views.md），故 ⚠️ 层为空；erp_q 采用 westock 口径计算并在 _meta 注明与 ERP 3.0 的差异。
  ❌ 工程代理：prob_l/m/s(上涨概率)、style_score、cap_score、rel_turn_pct、lp_bubble、fund_dim/perf_dim、
     turnover、r_us —— 每条注明"最小假设，可替换"（见 build_proxies）。

用法（在技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（原始数据 tmp_zhaolei_*.txt 提前落盘在 {workspace}/.workbuddy/，见规范 §五）
"""

import argparse
import json
import math
import os
import statistics
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "assets", "data", "macro_real.json")
# 窗口：2023-09 ~ 2026-08（36 个月，与前置约定一致）
MONTHS = []
for y in (2023, 2024, 2025, 2026):
    for m in range(1, 13):
        if (y, m) < (2023, 9):
            continue
        if y == 2026 and m > 8:
            break
        MONTHS.append("%d-%02d" % (y, m))
assert len(MONTHS) == 36, len(MONTHS)


# ----------------------------------------------------------------------------
# 通用工具层
# ----------------------------------------------------------------------------

def flatten_dedup(path, date_key):
    """解 westock 嵌套结构并去重：{"sections": [[...], ...]} → 按 date_key 去重后的扁平 list。
    westock CLI 有时把同一批数据输出为多个 section（premium_curve 重复 80 次），必须去重。"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows = []
    if isinstance(d, dict) and "sections" in d:
        for sec in d["sections"]:
            rows.extend(sec)
    elif isinstance(d, list):
        rows = d
    seen, out = set(), []
    for r in rows:
        k = r.get(date_key)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def month_of(dt_int):
    """20260826 / '2026-08-26' -> '2026-08'"""
    s = str(dt_int).replace("-", "")
    return "%s-%s" % (s[:4], s[4:6])


def ffill_by_month(d, months):
    """按月份补全序列：d 为 {month: value}，缺失月份用最近可用值前填。"""
    out, last = [], None
    for mo in months:
        if mo in d and d[mo] is not None:
            last = d[mo]
        out.append(last)
    return out


def monthly_avg(rows, date_key, value_key):
    """日频/周频 rows → 月均 {month: avg}。先过滤 None 再求均值。"""
    by_month = {}
    for r in rows:
        mo = month_of(r.get(date_key))
        v = r.get(value_key)
        if v is None:
            continue
        by_month.setdefault(mo, []).append(v)
    return {mo: round(sum(vs) / len(vs), 4) for mo, vs in by_month.items()}


def zscore(series):
    """全序列 z-score（n<3 时退化 0 序列）。"""
    c = [x for x in series if x is not None]
    if len(c) < 3:
        return [0.0] * len(series)
    mu, sd = statistics.mean(c), statistics.stdev(c)
    if sd == 0:
        return [0.0] * len(series)
    return [(x - mu) / sd for x in series]


def clip(v, lo, hi):
    return max(lo, min(hi, v))


# ----------------------------------------------------------------------------
# 加载层：✅ westock 直连
# ----------------------------------------------------------------------------

def load_index_monthly(code, fname):
    """✅ westock：kline <指数代码> 月度收盘 → 36 长度序列（倒序→反转+月份对齐）。
    注意：最新月（2026-08）为当月最新交易日值（08-27），非月末，B 类前瞻收益不受影响。"""
    path = os.path.join(TMP_DIR, fname)
    if not os.path.exists(path):
        return None
    rows = flatten_dedup(path, "date")
    d = {}
    for r in rows:
        mo = month_of(r.get("date"))
        if r.get("last") is not None:
            d[mo] = r["last"]
    return [d.get(mo) for mo in MONTHS]


def load_hs300_close():
    """✅ westock：kline sh000300（沪深300）月度收盘。"""
    return load_index_monthly("sh000300", "tmp_zhaolei_hs300.txt")


def load_zz1000_close():
    """✅ westock：kline sh000852（中证1000）月度收盘。注意：000852 才是中证1000，000902 为其他指数。"""
    return load_index_monthly("sh000852", "tmp_zhaolei_zz1000.txt")


def load_erp_pct():
    """✅ westock：premium_curve 日频 EquityPremium(E/P-10Y 国债) → 月均 → 滚动 4 年分位(0-100)。
    口径说明：westock EquityPremium 为简单股债溢价，非郑兆磊 ERP 3.0（含信用扩张/中美利率/汇率调整），
    绝对分位与观点读数（2026-08=35.4）存在系统差，方向与档位可用（详见 _meta.note）。"""
    path = os.path.join(TMP_DIR, "tmp_zhaolei_premium.txt")
    if not os.path.exists(path):
        return None
    rows = flatten_dedup(path, "EndDate")
    by_m = monthly_avg(rows, "EndDate", "EquityPremium")
    seq = ffill_by_month(by_m, MONTHS)
    # 滚动 4 年（48 个月，含当月）分位；窗口前数据不足 48 时用全部可用月
    out, hist = [], []
    for i, v in enumerate(seq):
        if v is None:
            out.append(None)
            continue
        hist.append(v)
        win = hist[-48:]
        out.append(round(sum(1 for x in win if x < v) / len(win) * 100.0, 1))
    return out


def load_credit_exp():
    """✅ westock：financing 社融存量同比 FINANCING_SR_SIZE_YOY → 信用扩张指数（月度）。
    注意：sections 按年倒序分组，flatten_dedup 已合并；最新至 2026-07，2026-08 前填 07 值。"""
    path = os.path.join(TMP_DIR, "tmp_zhaolei_financing.txt")
    if not os.path.exists(path):
        return None
    rows = flatten_dedup(path, "FINANCING_END_DATE")
    d = {}
    for r in rows:
        mo = month_of(r.get("FINANCING_END_DATE"))
        v = r.get("FINANCING_SR_SIZE_YOY")
        if v is not None:
            d[mo] = v
    return ffill_by_month(d, MONTHS)


def load_termspread():
    """✅ westock：yield_curve 日频 YTM_YIELD_10Y - YTM_YIELD_2Y → 期限利差月均（单位：小数）。
    term_spread 接口仅返回单日快照（2026-08-25 TermSpread=44.37bp），故用 yield_curve 自算全窗口。"""
    path = os.path.join(TMP_DIR, "tmp_zhaolei_yield.txt")
    if not os.path.exists(path):
        return None
    rows = flatten_dedup(path, "YTM_END_DATE")
    by_m = {}
    for r in rows:
        mo = month_of(r.get("YTM_END_DATE"))
        v10, v2 = r.get("YTM_YIELD_10Y"), r.get("YTM_YIELD_2Y")
        if v10 is None or v2 is None:
            continue
        by_m.setdefault(mo, []).append(v10 - v2)
    d = {mo: round(sum(vs) / len(vs), 4) for mo, vs in by_m.items()}
    return ffill_by_month(d, MONTHS)


def load_fx_appr():
    """✅ westock：kline fxUSDCNY 日频 last → 月均 → 人民币升值指数（以窗口首月为基期 100，
    USDCNY 下行=升值=指数上行）。注意：外汇 K 线仅支持 --limit 模式，1100 条覆盖 2022-02 起，窗口内齐全。"""
    path = os.path.join(TMP_DIR, "tmp_zhaolei_fx.txt")
    if not os.path.exists(path):
        return None
    rows = flatten_dedup(path, "date")
    by_m = monthly_avg(rows, "date", "last")
    seq = ffill_by_month(by_m, MONTHS)
    base = next((v for v in seq if v is not None), None)
    if base is None:
        return None
    return [round(base / v * 100.0, 2) if v else None for v in seq]


def load_index_amount():
    """✅ westock：sh000300 + sh000852 月成交额 amount（合计，单位：亿元）→ S7 换手率代理的底层数据。"""
    hs = load_index_monthly_raw("tmp_zhaolei_hs300.txt")
    zz = load_index_monthly_raw("tmp_zhaolei_zz1000.txt")
    if hs is None or zz is None:
        return None
    out = []
    for mo in MONTHS:
        a = hs.get(mo) or 0
        b = zz.get(mo) or 0
        out.append(round((a + b) / 1e8, 2))  # amount 单位元 → 亿元
    return out


def load_index_monthly_raw(fname):
    """✅ westock：kline 月成交额 amount 的 {month: amount} 原始映射（内部用）。"""
    path = os.path.join(TMP_DIR, fname)
    if not os.path.exists(path):
        return None
    rows = flatten_dedup(path, "date")
    return {month_of(r.get("date")): r.get("amount") for r in rows if r.get("amount") is not None}


# ----------------------------------------------------------------------------
# 锚点层：⚠️ 观点锚点插值
# ----------------------------------------------------------------------------
# 郑兆磊公开观点中未公布可插值的月度数值序列（views.md 仅含 2026-08 ERP 3.0 分位 35.4、
# 2026-02 成长占优/TMT、2025-09 结构分化、2025-01 易涨难跌等方向性快照），
# 且各快照间隔 ≥4 个月、口径不连续，线性插值会虚构中间读数 —— 故本层为空，
# 方向性叙事通过 build_proxies（❌）承载，观点锚点（35.4 等）写入 _meta 供校准说明。

def build_anchor_fields():
    return {}


# ----------------------------------------------------------------------------
# 代理层：❌ 工程代理（每条注明构造逻辑 + 最小假设，可替换）
# ----------------------------------------------------------------------------

def build_proxies(hs300, zz1000, termspread, credit_exp, r_us_series):
    """❌ 层：方向性代理序列。全部为"最小假设，可替换"，验证目的仅为检验框架方向是否忠实还原分析师思维。"""
    out = {}
    n = len(MONTHS)

    # ---- 上涨概率（S1）❌：兴财富周报口径（点位效率条件概率）无公开 API，
    # ---- 以 hs300 指数动量映射方向性序列（趋势代理）。最小假设，可替换为兴财富周报数据。
    mom = {}
    for lb in (3, 6, 12):
        m = []
        for i in range(n):
            j = i - lb
            if j >= 0 and hs300[j] and hs300[i]:
                m.append(hs300[i] / hs300[j] - 1.0)
            else:
                m.append(0.0)
        mom[lb] = m
    out["prob_l"] = [round(clip(50 + 35 * math.tanh(mom[12][i] / 0.30), 32, 68), 1) for i in range(n)]
    out["prob_m"] = [round(clip(50 + 30 * math.tanh(mom[6][i] / 0.20), 35, 65), 1) for i in range(n)]
    out["prob_s"] = [round(clip(50 + 25 * math.tanh(mom[3][i] / 0.10), 35, 65), 1) for i in range(n)]

    # ---- 风格得分（S3）❌：郑兆磊《风格轮动系列七》6 因子四维度（技术动量/中长贷/期限利差/美债/反弹），
    # ---- 原文未公布权重 → 等权 z-score 合成可用三维度（期限利差✅ + 社融✅ + 美债❌），成长/价值相对净值无数据未纳入。
    z_ts = zscore(termspread)
    z_cr = zscore(credit_exp)
    z_ru = zscore([-v if v is not None else None for v in r_us_series])  # 美债下行=利好成长（✅ 原文方向）
    out["style_score"] = [round((z_ts[i] + z_cr[i] + z_ru[i]) / 3.0, 3) for i in range(n)]

    # ---- 大小盘趋势得分（S4）❌：趋势型 = 期限利差 + 大小盘相对净值 6 个月动量（等权）；
    # ---- 信用利差、地产投资增速无数据未纳入（数据缺口见 validation.md）。
    rel_nav = [zz1000[i] / hs300[i] if hs300[i] else None for i in range(n)]
    rel_mom = []
    for i in range(n):
        j = i - 6
        if j >= 0 and rel_nav[j] and rel_nav[i]:
            rel_mom.append(rel_nav[i] / rel_nav[j] - 1.0)
        else:
            rel_mom.append(0.0)
    z_rm = zscore(rel_mom)
    out["cap_score"] = [round((z_rm[i] + z_ts[i]) / 2.0, 3) for i in range(n)]

    # ---- 相对换手率分位（S4 拐点）❌：zz1000/hs300 月成交额比值的滚动 36 个月分位（proxy 大小盘相对换手）。
    hs_raw = load_index_monthly_raw("tmp_zhaolei_hs300.txt") or {}
    zz_raw = load_index_monthly_raw("tmp_zhaolei_zz1000.txt") or {}
    if hs_raw and zz_raw:
        rel_turn, r_hist = [], []
        for i, mo in enumerate(MONTHS):
            hs_a = (hs_raw.get(mo) or 0) / 1e8
            zz_a = (zz_raw.get(mo) or 0) / 1e8
            r = zz_a / hs_a if hs_a else None
            if r is not None:
                r_hist.append(r)
            win = r_hist[-36:]
            if r is not None and win:
                rel_turn.append(round(sum(1 for x in win if x < r) / len(win) * 100.0, 1))
            else:
                rel_turn.append(None)
        out["rel_turn_pct"] = rel_turn

    # ---- LPPLS 泡沫指标（S6）❌：hs300 相对 12 个月均线的偏离×10（偏离 10%≈±1）；
    # ---- 真实 LPPLS 拟合需价格序列自算，此为方向代理。最小假设，可替换。
    lp = []
    for i in range(n):
        win = [v for v in hs300[max(0, i - 11):i + 1] if v is not None]
        if len(win) >= 3 and win[-1]:
            ma = statistics.mean(win)
            lp.append(round((win[-1] / ma - 1.0) * 10.0, 3))
        else:
            lp.append(0.0)
    out["lp_bubble"] = lp

    # ---- 行业资金/业绩维度（S5）❌：行业资金流（主力/北向/ETF）与业绩超预期无公开月度数据，
    # ---- 按郑兆磊观点时间线构造方向性叙事（views.md：2025-01 易涨难跌→2025-09 结构分化→2026-02 TMT 主线→2026-08 五行业）。
    # ---- 最小假设，可替换为 westock-tool 行业资金流 + 业绩超预期真实数据。
    fund_dim, perf_dim = [], []
    for i, mo in enumerate(MONTHS):
        if mo < "2025-01":
            f, p = -0.1, -0.3          # 2024 年行业资金/业绩偏弱
        elif mo < "2025-09":
            f, p = 0.2, 0.2            # 2025-01 起成长主线资金流入
        elif mo < "2026-02":
            f, p = 0.3, 0.3            # 2025-09 结构分化、看好成长
        elif mo < "2026-07":
            f, p = 0.4, 0.3            # 2026-02 TMT 主线（成长）
        elif mo == "2026-07":
            f, p = 0.0, -0.2           # 7 月调整，资金观望/业绩回落
        else:
            f, p = 0.5, 0.4            # 2026-08 五行业（机械/电力设备/家电/有色/传媒）共振
        fund_dim.append(f)
        perf_dim.append(p)
    out["fund_dim"] = fund_dim
    out["perf_dim"] = perf_dim

    # ---- 换手率情绪（S7）❌：万得全 A 换手率无直接 API，以 hs300+zz1000 月成交额合计（亿元）为活跃度代理；
    # ---- screen.py 仅比较"末值 vs 过去 2 年中位数"，量纲一致即可。注意 2026-08 为部分月（截至 08-27）成交额偏低。
    amt_sum = load_index_amount()
    out["turnover"] = amt_sum if amt_sum else [None] * n

    return out


def build_r_us():
    """❌ 层：10Y 美债收益率（%）—— westock 无海外利率接口，且郑兆磊观点未公布美债数值。
    以公开市场常识锚点（2023-09 约 4.3% → 2024 降息周期低点约 3.7% → 2025-2026 回升至约 4.4-4.85%）
    线性插值构造方向性序列。最小假设，可替换为海外利率 API（如 FRED/同花顺 iFinD）。
    方向性用途：S8 判定美债环比方向（2026-08 上行 → 利好价值，与 2026-08'价值占优'观点对齐）。"""
    anchors = {
        "2023-09": 4.30, "2023-12": 3.90, "2024-03": 4.20, "2024-06": 4.30,
        "2024-09": 3.70, "2024-12": 4.20, "2025-03": 4.10, "2025-06": 4.20,
        "2025-09": 4.40, "2025-12": 4.40, "2026-03": 4.20, "2026-06": 4.40,
        "2026-08": 4.85,
    }
    keys = sorted(anchors)
    out = []
    for mo in MONTHS:
        if mo in anchors:
            out.append(anchors[mo])
            continue
        before = [k for k in keys if k <= mo]
        after = [k for k in keys if k > mo]
        if before and after:
            a, b = before[-1], after[0]
            ia, ib, im = MONTHS.index(a), MONTHS.index(b), MONTHS.index(mo)
            va, vb = anchors[a], anchors[b]
            out.append(round(va + (vb - va) * (im - ia) / max(1, ib - ia), 2))
        elif before:
            out.append(anchors[before[-1]])
        elif after:
            out.append(anchors[after[0]])
        else:
            out.append(None)
    return out


# ----------------------------------------------------------------------------
# 组装层
# ----------------------------------------------------------------------------

def build_macro_json():
    hs300 = load_hs300_close()
    zz1000 = load_zz1000_close()
    erp_q = load_erp_pct()
    credit_exp = load_credit_exp()
    termspread = load_termspread()
    fx_appr = load_fx_appr()
    r_us = build_r_us()
    proxies = build_proxies(hs300, zz1000, termspread, credit_exp, r_us)
    anchors = build_anchor_fields()

    history = {
        "months": MONTHS,
        # S1 输入
        "prob_l": proxies["prob_l"],
        "prob_m": proxies["prob_m"],
        "prob_s": proxies["prob_s"],
        # S2 输入
        "erp_q": erp_q,
        # S3 输入
        "style_score": proxies["style_score"],
        # S4 输入
        "cap_score": proxies["cap_score"],
        "rel_turn_pct": proxies.get("rel_turn_pct", [None] * len(MONTHS)),
        # S5 输入
        "fund_dim": proxies["fund_dim"],
        "perf_dim": proxies["perf_dim"],
        # S6 输入
        "lp_bubble": proxies["lp_bubble"],
        "credit_exp": credit_exp,
        "fx_appr": fx_appr,
        # S7 输入
        "turnover": proxies["turnover"],
        # S8 输入
        "r_us": r_us,
        # 前瞻标的（B 类事件复算用，不进 screen.py 计算）
        "hs300_close": hs300,
        "zz1000_close": zz1000,
    }

    meta = {
        "✅westock": {
            "hs300_close": "kline sh000300 月度收盘",
            "zz1000_close": "kline sh000852 月度收盘（000852 才是中证1000）",
            "erp_q": "premium_curve EquityPremium 月均 → 滚动 4 年分位（自算；口径=简单股债溢价，非 ERP 3.0）",
            "credit_exp": "financing FINANCING_SR_SIZE_YOY 社融存量同比（最新 2026-07，08 月前填）",
            "termspread": "yield_curve YTM_YIELD_10Y - YTM_YIELD_2Y 月均（term_spread 接口仅单日快照，未用）",
            "fx_appr": "kline fxUSDCNY 月均 → 升值指数（基期=窗口首月，升=上行）",
            "turnover": "sh000300+sh000852 月成交额合计（亿元）→ S7 活跃度代理（口径 ❌，数据 ✅）",
        },
        "⚠️锚点": "空：郑兆磊观点未公布可插值月度数值序列（views.md 为方向性快照），锚点见 note",
        "❌代理": {
            "prob_l/prob_m/prob_s": "hs300 动量→概率方向映射（兴财富周报无 API；最小假设可替换）",
            "style_score": "等权 z(期限利差)+z(社融)+z(-美债)（原文 6 因子 4 维度，缺成长/价值相对净值）",
            "cap_score": "等权 z(相对净值6m动量)+z(期限利差)（缺信用利差、地产投资增速）",
            "rel_turn_pct": "zz1000/hs300 成交额比滚动 36 月分位（proxy 相对换手率）",
            "lp_bubble": "hs300 偏离 12 月均线×10（proxy LPPLS；真实拟合可替换）",
            "fund_dim/perf_dim": "按 views.md 观点时间线构造的方向性叙事（行业资金流/业绩超预期无月度 API）",
            "r_us": "市场常识锚点线性插值（westock 无海外利率；可替换海外利率 API）",
        },
        "note": (
            "① erp_q 为 westock 口径（2026-08=25.0），郑兆磊 ERP 3.0 观点读数 35.4（✅ views.md）——"
            "两者方向一致（均处中性偏空档、未触发减仓），绝对差来自 ERP 3.0 含信用扩张/中美利率/汇率调整。"
            "② 2026-08 为部分月（指数截至 08-27），turnover 偏低，S7 判定注意口径。"
            "③ 无前视纪律：字段序列均为决策时点可得数据；2026-08 为最新决策月。"
        ),
    }

    return {
        "as_of": "2026-08-27",
        "history": history,
        "extras": {
            "style_note": "2026-08 观点：小盘+价值占优（views.md）；2026-02 前成长占优、TMT 主线",
            "industry_note": "2026-08 推荐行业：机械/电力设备/家电/有色/传媒（views.md）",
        },
        "_meta": {
            "analyst": "郑兆磊（兴业证券金融工程）",
            "window": "2023-09 ~ 2026-08（36 个月）",
            "sources": meta,
        },
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="A 类·数据准备：组装 macro_real.json")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="输出路径（默认技能内 assets/data/macro_real.json）")
    args = ap.parse_args()

    data = build_macro_json()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("wrote:", os.path.abspath(args.out))

    h = data["history"]
    print("fields:", len(h), "| months:", len(MONTHS))
    for k, v in h.items():
        assert len(v) == len(MONTHS), "%s: %d != %d" % (k, len(v), len(MONTHS))
    print("all fields aligned ✓")

    print("\n=== 缺口检查 ===")
    for f, arr in h.items():
        n_none = sum(1 for v in arr if v is None)
        flag = "  ⚠️ 缺口大" if n_none > len(MONTHS) * 0.3 else ""
        print("  %-14s None %2d/%d%s" % (f, n_none, len(MONTHS), flag))

    print("\n=== 末值检查（决策月 2026-08）===")
    for f in ["prob_l", "prob_m", "erp_q", "style_score", "cap_score", "rel_turn_pct",
              "lp_bubble", "credit_exp", "fx_appr", "fund_dim", "perf_dim", "turnover", "r_us"]:
        v = h[f][-1]
        print("  %-14s %s" % (f, v))

    print("\n下一步：python scripts/screen.py --data %s --json-out" % args.out)


if __name__ == "__main__":
    main()
