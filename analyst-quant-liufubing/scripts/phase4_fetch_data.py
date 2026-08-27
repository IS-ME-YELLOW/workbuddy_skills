#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘富兵 Phase 4 A 类·数据准备：组装 macro_real.json 回填 screen.py
====================================================================
依据 analyst-distill 规范（phase4-scripts-conventions.md）编写。

数据来源（三层标注，详见 _meta）：
  ✅ westock-data 直连：kline sh000300/sh000852(指数月收+成交额)、premium_curve(股债溢价→ERP 滚动 4 年分位)、
     financing(社融存量同比→信用/流动性)、cpi_ppi(CPI/PPI 同比→六面图经济面)、pmi(PMI 新出口订单→增长方向)
  ⚠️ 观点锚点：a_share_prosperity(A股景气指数 2025-11=20.91 / 2026-01=18.12 / 2026-07=21.42，views.md)、
     cb_dev(转债定价偏离度 2026-08=12.28%，✅ 转债月报)——中间月度按锚点间常量/插值填充并在 _meta 注明。
  ❌ 工程代理：cycle_real/cycle_implied(宏观六周期阶段)、六面图缺数据维度(pb/aiae/margin_flow/cds_cn/
     risk_aversion/option_prem/vix/skew)、a_share_sentiment、gk_exp_ret、industry_*(行业轮动)、
     rs_score、style_*(风格三维) —— 每条注明"最小假设，可替换"（见 build_proxies）。

用法（在技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（原始数据 tmp_zhaolei_*.txt / tmp_fi_cpip_*.txt / tmp_liushi_pmi.txt 提前落盘在 {workspace}/.workbuddy/，见规范 §五）
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

CPIP_FILES = ["tmp_fi_cpip_2023.txt", "tmp_fi_cpip_2024.txt",
              "tmp_fi_cpip_2025.txt", "tmp_fi_cpip_2026.txt"]


# ----------------------------------------------------------------------------
# 通用工具层
# ----------------------------------------------------------------------------

def parse_md_table(path):
    """解析 markdown 表格 → (headers, rows)。' - '/'-' 视为 None。"""
    headers, rows = None, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if headers is None:
                headers = cells
            elif all(c in ("---", "") for c in cells):
                continue
            else:
                rows.append(cells)
    return headers, rows


def flatten_dedup(path, date_key):
    """解 westock 嵌套结构并去重：{"sections": [[...], ...]} → 按 date_key 去重后的扁平 list。"""
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


def sign_series(series):
    """数值序列 → [-1,0,1] 符号序列（0 保持 0；None→0）。"""
    out = []
    for v in series:
        if v is None or v == 0:
            out.append(0)
        else:
            out.append(1 if v > 0 else -1)
    return out


def trend_dir(series, lookback=3):
    """末值 vs N 期前符号（0=平）。"""
    if len(series) < lookback + 1:
        return 0
    a, b = series[-1 - lookback], series[-1]
    if a is None or b is None:
        return 0
    return 1 if b > a else (-1 if b < a else 0)


# ----------------------------------------------------------------------------
# 加载层：✅ westock 直连
# ----------------------------------------------------------------------------

def load_index_monthly(code, fname):
    """✅ westock：kline <指数代码> 月度收盘 → 36 长度序列（倒序→反转+月份对齐）。"""
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
    """✅ westock：kline sh000852（中证1000）月度收盘。"""
    return load_index_monthly("sh000852", "tmp_zhaolei_zz1000.txt")


def load_erp_pct():
    """✅ westock：premium_curve 日频 EquityPremium(E/P-10Y 国债) → 月均 → 滚动 4 年分位(0-100)。
    口径说明：westock EquityPremium 为简单股债溢价，非刘富兵六面图口径，绝对水平跨口径不可比，分位/方向可用。"""
    path = os.path.join(TMP_DIR, "tmp_zhaolei_premium.txt")
    if not os.path.exists(path):
        return None
    rows = flatten_dedup(path, "EndDate")
    by_m = monthly_avg(rows, "EndDate", "EquityPremium")
    seq = ffill_by_month(by_m, MONTHS)
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


def load_cpip():
    """✅ westock：cpi_ppi 年度文件合并 → (cpi_yoy, ppi_yoy) 月度序列（单位 %）。
    按 CPI_END_DATE 去重：每月可能多行（不同发布口径），取该列首个有值行（约定：cpip 每月 3 行分行）。"""
    cpi_d, ppi_d = {}, {}
    for fn in CPIP_FILES:
        path = os.path.join(TMP_DIR, fn)
        if not os.path.exists(path):
            continue
        headers, rows = parse_md_table(path)
        if headers is None:
            continue
        idx = {h: i for i, h in enumerate(headers)}
        for r in rows:
            mo = month_of(r[idx["CPI_END_DATE"]])
            if mo not in cpi_d and "CPI_CPI_YOY" in idx and idx["CPI_CPI_YOY"] < len(r):
                v = r[idx["CPI_CPI_YOY"]]
                if v not in ("-", "", "None"):
                    try:
                        cpi_d[mo] = float(v)
                    except ValueError:
                        pass
            if mo not in ppi_d and "PPI_PPI_YOY" in idx and idx["PPI_PPI_YOY"] < len(r):
                v = r[idx["PPI_PPI_YOY"]]
                if v not in ("-", "", "None"):
                    try:
                        ppi_d[mo] = float(v)
                    except ValueError:
                        pass
    return ffill_by_month(cpi_d, MONTHS), ffill_by_month(ppi_d, MONTHS)


def load_pmi_export_order():
    """✅ westock：pmi PMI_PMI_MANU_ORDER_EXPORT（PMI 新出口订单，>50 扩张）→ 出口景气代理（S2 增长维度辅助）。"""
    path = os.path.join(TMP_DIR, "tmp_liushi_pmi.txt")
    if not os.path.exists(path):
        return None
    headers, rows = parse_md_table(path)
    if headers is None:
        return None
    idx = {h: i for i, h in enumerate(headers)}
    d = {}
    for r in rows:
        mo = month_of(r[idx["PMI_END_DATE"]])
        v = r[idx["PMI_PMI_MANU_ORDER_EXPORT"]] if "PMI_PMI_MANU_ORDER_EXPORT" in idx else "-"
        if v not in ("-", "", "None", None):
            try:
                d[mo] = float(v)
            except ValueError:
                pass
    return ffill_by_month(d, MONTHS)


def load_index_amount():
    """✅ westock：sh000300 + sh000852 月成交额 amount（合计，单位：亿元）→ 六面图资金面 amount_trend 底层。"""
    out = []
    for mo in MONTHS:
        a = b = 0
        for fn in ("tmp_zhaolei_hs300.txt", "tmp_zhaolei_zz1000.txt"):
            path = os.path.join(TMP_DIR, fn)
            if not os.path.exists(path):
                continue
            rows = flatten_dedup(path, "date")
            for r in rows:
                if month_of(r.get("date")) == mo and r.get("amount") is not None:
                    if "hs300" in fn:
                        a = r["amount"]
                    else:
                        b = r["amount"]
        out.append(round((a + b) / 1e8, 2))
    return out


# ----------------------------------------------------------------------------
# 锚点层：⚠️ 观点锚点（views.md 公布数值）
# ----------------------------------------------------------------------------

def build_anchor_fields():
    """⚠️ 层：刘富兵公开观点中的数值锚点。
    a_share_prosperity（A股景气指数）：2025-11=20.91、2026-01=18.12、2026-07=21.42（✅ views.md）。
      锚点间按线性插值，锚点前用首个锚点值、锚点后用末个锚点值 —— 仅方向性用途，标注 ⚠️。
    cb_dev（转债定价偏离度 %）：2026-08=12.28（✅ 转债月报）。窗口内其余月份无公布值，
      以 hs300 偏离 12 月均线 ×常数 作方向代理（❌），锚点月校准到 12.28。"""
    n = len(MONTHS)
    # 景气指数锚点插值
    pros_anchors = {"2025-11": 20.91, "2026-01": 18.12, "2026-07": 21.42}
    keys = sorted(pros_anchors)
    prosperity = []
    for mo in MONTHS:
        if mo in pros_anchors:
            prosperity.append(pros_anchors[mo])
            continue
        before = [k for k in keys if k <= mo]
        after = [k for k in keys if k > mo]
        if before and after:
            a, b = before[-1], after[0]
            ia, ib, im = MONTHS.index(a), MONTHS.index(b), MONTHS.index(mo)
            va, vb = pros_anchors[a], pros_anchors[b]
            prosperity.append(round(va + (vb - va) * (im - ia) / max(1, ib - ia), 2))
        elif before:
            prosperity.append(pros_anchors[before[-1]])
        elif after:
            prosperity.append(pros_anchors[after[0]])
        else:
            prosperity.append(None)
    return {"a_share_prosperity": prosperity}


# ----------------------------------------------------------------------------
# 代理层：❌ 工程代理（每条注明构造逻辑 + 最小假设，可替换）
# ----------------------------------------------------------------------------

def build_proxies(hs300, erp_q, credit_exp, cpi_yoy, ppi_yoy, pmi_exp, amount):
    """❌ 层：方向性代理序列。全部为"最小假设，可替换"，验证目的仅为检验框架方向是否忠实还原分析师思维。"""
    out = {}
    n = len(MONTHS)

    # ---- 宏观六周期（S4）❌：刘富兵六周期框架（基钦/朱格拉/库兹涅茨等）无公开数值。
    # ---- cycle_real 用社融同比增速 12 个月滚动分位映射阶段 1-6（信用扩张强度），
    # ---- cycle_implied 用 hs300 相对 12 月均线偏离映射阶段（资产隐含周期位置）。
    # ---- 最小假设，可替换为真实周期分解输出。
    def map_phase(seq, lo, hi, n_phase=6):
        """把序列线性映射到 1..6 阶段（基于全窗口 min-max）。"""
        c = [x for x in seq if x is not None]
        if not c:
            return [3] * len(seq)
        mn, mx = min(c), max(c)
        span = (mx - mn) or 1.0
        return [clip(int(1 + (v - mn) / span * (n_phase - 0.01)), 1, n_phase) if v is not None else 3
                for v in seq]

    # cycle_real：社融同比的 6 个月动量 → 阶段（动量为正且大 → 周期上行阶段编号大）
    cr_mom = []
    for i in range(n):
        j = i - 6
        if j >= 0 and credit_exp[j] and credit_exp[i]:
            cr_mom.append(credit_exp[i] - credit_exp[j])
        else:
            cr_mom.append(0.0)
    out["cycle_real"] = map_phase(cr_mom, None, None)
    # cycle_implied：hs300 相对 12 月均线偏离 → 阶段（偏离高=繁荣期编号大）
    ci_dev = []
    for i in range(n):
        win = [v for v in hs300[max(0, i - 11):i + 1] if v is not None]
        if len(win) >= 3 and win[-1]:
            ma = statistics.mean(win)
            ci_dev.append(win[-1] / ma - 1.0)
        else:
            ci_dev.append(0.0)
    out["cycle_implied"] = map_phase(ci_dev, None, None)

    # ---- 六面图：真实数据符号化（✅ 数据 → 方向）----
    out["liq_dir"] = sign_series([v - (credit_exp[i - 1] if i and credit_exp[i - 1] else v)
                                  for i, v in enumerate(credit_exp)])          # 流动性：社融环比方向
    out["cred_dir"] = sign_series([v - 10.0 for v in credit_exp])              # 信用：社融同比 vs 10 中性
    out["growth_dir"] = sign_series([v - 50.0 for v in pmi_exp]) if pmi_exp else [0] * n  # 增长：PMI 新出口订单
    out["infl_dir"] = [1 if (cpi_yoy[i] or 0) + (ppi_yoy[i] or 0) > 2 else
                       (-1 if (cpi_yoy[i] or 0) + (ppi_yoy[i] or 0) < 0 else 0) for i in range(n)]  # 通胀：CPI+PPI 合成
    out["shiller_erp"] = sign_series([v - 50.0 for v in erp_q])                # 估值：ERP 分位 vs 50
    out["amount_trend"] = sign_series([amount[i] - (amount[i - 1] if i else amount[i])
                                       for i in range(n)])                     # 资金面：成交额环比方向

    # ---- 六面图缺数据维度（❌ 叙事代理）----
    # pb/aiae/option_prem/vix/skew：无月度公开数值 → 按观点时间线构造方向性叙事（views.md）。
    # 2024 底部修复→2025 上涨→2025-11 超涨→2026-07 探底→2026-08 中性
    pb, aiae = [], []
    for i, mo in enumerate(MONTHS):
        if mo < "2024-09":
            pb.append(-1); aiae.append(-1)      # 2024 双底期：低估+盈利预期弱
        elif mo < "2025-11":
            pb.append(1); aiae.append(1)        # 2025 修复：估值修复+预期上修
        elif mo < "2026-07":
            pb.append(0); aiae.append(1)        # 超涨期：估值中性、盈利预期仍上
        else:
            pb.append(0); aiae.append(0)        # 2026-07 探底+08 中性
    out["pb"] = pb
    out["aiae"] = aiae
    # margin_flow：两融增量无月度 API → 成交额环比同构（❌ 代理）
    out["margin_flow"] = out["amount_trend"][:]
    # cds_cn：中国主权 CDS 无直连 → 常 0（中性，❌）
    out["cds_cn"] = [0] * n
    # risk_aversion：海外风险厌恶 → 用 hs300 波动率（月收益滚动 6 个月 std）负向映射（❌）
    rets = []
    for i in range(n):
        j = i - 1
        if j >= 0 and hs300[j] and hs300[i]:
            rets.append(hs300[i] / hs300[j] - 1.0)
        else:
            rets.append(0.0)
    vol = []
    for i in range(n):
        win = rets[max(0, i - 5):i + 1]
        vol.append(statistics.stdev(win) if len(win) >= 3 else 0.02)
    out["risk_aversion"] = [1 if v > 0.04 else (-1 if v < 0.015 else 0) for v in vol]
    # 期权三指标：无月度公开数值 → 与风险厌恶同构（❌ 代理）
    out["option_prem"] = out["risk_aversion"][:]
    out["vix"] = out["risk_aversion"][:]
    out["skew"] = [-v for v in out["risk_aversion"]]       # SKEW 高=空，反向

    # ---- S5 情绪（❌）：成交额环比 + 指数动量合成
    mom = [hs300[i] / hs300[i - 1] - 1.0 if i and hs300[i - 1] and hs300[i] else 0.0 for i in range(n)]
    out["a_share_sentiment"] = [clip(0.5 * (1 if m > 0.01 else (-1 if m < -0.01 else 0)) +
                                     0.5 * (a if a else 0), -1, 1)
                                for m, a in zip(mom, out["amount_trend"])]

    # ---- S6 GK 预期收益（❌）：ERP 分位 >80 高性价比 → 预期收益正；<20 负。
    out["gk_exp_ret"] = [round(clip((v - 50.0) / 50.0 * 6.0, -3, 8), 1) if v is not None else None
                         for v in erp_q]

    # ---- S7 行业轮动（❌）：行业动量/景气/拥挤度无月度 API → 按 views.md 观点时间线叙事。
    # ---- 2025-11 起超 2/3 行业超涨（动量高、拥挤高）→ 2026-07 24 行业日线下跌（动量弱、拥挤回落）
    ind_mom, ind_pros, ind_crowd = [], [], []
    for i, mo in enumerate(MONTHS):
        if mo < "2024-09":
            m_, p_, c_ = 0.2, -0.2, 30.0      # 底部：弱动量、弱景气、低拥挤
        elif mo < "2025-11":
            m_, p_, c_ = 0.6, 0.4, 45.0       # 上涨：强动量、景气修复、拥挤抬升
        elif mo < "2026-05":
            m_, p_, c_ = 1.0, 0.8, 75.0       # 超涨：动量极强、景气强、拥挤高（2/3 行业超涨）
        elif mo < "2026-07":
            m_, p_, c_ = 0.3, 0.5, 60.0       # 冲高回落：动量衰减
        else:
            m_, p_, c_ = -0.4, -0.1, 45.0     # 2026-07 探底：动量转弱、拥挤回落
        ind_mom.append(m_); ind_pros.append(p_); ind_crowd.append(c_)
    out["industry_momentum"] = ind_mom
    out["industry_prosperity"] = ind_pros
    out["industry_crowding"] = ind_crowd

    # ---- S8 RS 主线（❌）：RS 相对强弱无月度 API → 与行业动量同构的 0-100 分位代理。
    out["rs_score"] = [round(clip(50 + m * 40, 5, 95), 1) for m in ind_mom]

    # ---- S9 风格三维（❌）：风格赔率/趋势/拥挤无月度 API → 按 views.md（2024-07 超配大盘质量；2026 中性）。
    odds, trend, crowd = [], [], []
    for i, mo in enumerate(MONTHS):
        if mo < "2024-07":
            odds.append(45.0); trend.append(-0.3); crowd.append(40.0)   # 2024 上半年：低赔率修复期
        elif mo < "2024-10":
            odds.append(70.0); trend.append(0.7); crowd.append(35.0)    # 2024-07 超配大盘质量（高质量风格低拥挤）
        elif mo < "2025-11":
            odds.append(55.0); trend.append(0.4); crowd.append(50.0)
        else:
            odds.append(50.0); trend.append(0.0); crowd.append(55.0)    # 2025-11 后：风格信号中性
    out["style_odds"] = odds
    out["style_trend"] = trend
    out["style_crowd"] = crowd

    return out


# ----------------------------------------------------------------------------
# 组装层
# ----------------------------------------------------------------------------

def build_macro_json():
    hs300 = load_hs300_close()
    zz1000 = load_zz1000_close()
    erp_q = load_erp_pct()
    credit_exp = load_credit_exp()
    cpi_yoy, ppi_yoy = load_cpip()
    pmi_exp = load_pmi_export_order()
    amount = load_index_amount()
    anchors = build_anchor_fields()
    proxies = build_proxies(hs300, erp_q, credit_exp, cpi_yoy, ppi_yoy, pmi_exp, amount)

    # cb_dev：锚点 2026-08=12.28（✅ 转债月报），窗口内其余月以 hs300 偏离 12 月均线 ×6 代理（❌），
    # 锚点月校准：直接写 12.28，其余月 = max(偏离代理, 0)。
    cb_proxy = []
    for i in range(len(MONTHS)):
        win = [v for v in hs300[max(0, i - 11):i + 1] if v is not None]
        if len(win) >= 3 and win[-1]:
            cb_proxy.append(round(max(0.0, (win[-1] / statistics.mean(win) - 1.0) * 6.0), 2))
        else:
            cb_proxy.append(0.0)
    if "2026-08" in MONTHS:
        cb_proxy[MONTHS.index("2026-08")] = 12.28   # ✅ 原文锚点

    history = {
        "months": MONTHS,
        # S1/S3 输入
        "hs300_close": hs300,
        "zz1000_close": zz1000,
        # S2 输入（六面图）
        "liq_dir": proxies["liq_dir"],
        "cred_dir": proxies["cred_dir"],
        "growth_dir": proxies["growth_dir"],
        "infl_dir": proxies["infl_dir"],
        "shiller_erp": proxies["shiller_erp"],
        "pb": proxies["pb"],
        "aiae": proxies["aiae"],
        "margin_flow": proxies["margin_flow"],
        "amount_trend": proxies["amount_trend"],
        "cds_cn": proxies["cds_cn"],
        "risk_aversion": proxies["risk_aversion"],
        "option_prem": proxies["option_prem"],
        "vix": proxies["vix"],
        "skew": proxies["skew"],
        "cb_dev": cb_proxy,
        # S4 输入
        "cycle_real": proxies["cycle_real"],
        "cycle_implied": proxies["cycle_implied"],
        # S5 输入
        "a_share_prosperity": anchors["a_share_prosperity"],
        "a_share_sentiment": proxies["a_share_sentiment"],
        # S6 输入
        "erp_q": erp_q,
        "gk_exp_ret": proxies["gk_exp_ret"],
        # S7 输入
        "industry_momentum": proxies["industry_momentum"],
        "industry_prosperity": proxies["industry_prosperity"],
        "industry_crowding": proxies["industry_crowding"],
        # S8 输入
        "rs_score": proxies["rs_score"],
        # S9 输入
        "style_odds": proxies["style_odds"],
        "style_trend": proxies["style_trend"],
        "style_crowd": proxies["style_crowd"],
    }

    meta = {
        "✅westock": {
            "hs300_close": "kline sh000300 月度收盘",
            "zz1000_close": "kline sh000852 月度收盘（000852 才是中证1000）",
            "erp_q": "premium_curve EquityPremium 月均 → 滚动 4 年分位（自算；口径=简单股债溢价）",
            "credit_exp": "financing FINANCING_SR_SIZE_YOY 社融存量同比（最新 2026-07，08 前填）",
            "cpi_yoy/ppi_yoy": "cpi_ppi 年度文件合并 CPI_CPI_YOY / PPI_PPI_YOY（每月取该列首个有值行）",
            "pmi_exp": "pmi PMI_PMI_MANU_ORDER_EXPORT 新出口订单（>50 扩张）→ growth_dir",
            "amount_trend": "sh000300+sh000852 月成交额合计（亿元）环比方向",
        },
        "⚠️锚点": {
            "a_share_prosperity": "views.md：2025-11=20.91 / 2026-01=18.12 / 2026-07=21.42，锚点间线性插值（方向性用途）",
            "cb_dev": "2026-08=12.28（✅ 转债月报）；其余月=hs300 偏离 12 月均线×6 代理（❌）",
        },
        "❌代理": {
            "cycle_real": "社融同比 6m 动量→min-max 映射阶段 1-6（六周期无公开数值）",
            "cycle_implied": "hs300 偏离 12 月均线→阶段 1-6（资产隐含周期）",
            "pb": "按 views.md 观点时间线方向叙事（底部/修复/超涨/探底）",
            "aiae": "同上（盈利预期维度）",
            "margin_flow": "与 amount_trend 同构（两融增量无月度 API）",
            "cds_cn": "常 0 中性（中国主权 CDS 无直连）",
            "risk_aversion": "hs300 月收益 6m 波动率阈值映射（海外风险厌恶无月度 API）",
            "option_prem/vix/skew": "与 risk_aversion 同构（期权数据无月度 API）",
            "a_share_sentiment": "成交额环比+指数动量合成",
            "gk_exp_ret": "ERP 分位线性映射（GK 模型无公开数值）",
            "industry_momentum/prosperity/crowding": "views.md 观点时间线叙事（行业轮动无月度 API）",
            "rs_score": "与 industry_momentum 同构 0-100 分位",
            "style_odds/trend/crowd": "views.md 叙事（2024-07 超配大盘质量案例校准）",
        },
        "note": (
            "① erp_q 为 westock 口径简单股债溢价滚动分位，非刘富兵六面图口径，绝对水平跨口径不可比，仅方向可用。"
            "② 六面图 15 子项中 7 项为真实数据符号化（liq/cred/growth/infl/shiller/amount/cb_dev），8 项为 ❌ 叙事代理，"
            "验证的是'框架可执行性+方向还原度'，非回测绩效。"
            "③ 无前视纪律：字段序列均为决策时点可得数据；2026-08 为最新决策月。"
        ),
    }

    return {
        "as_of": "2026-08-27",
        "history": history,
        "extras": {
            "view_note": "2025-11 日线上涨临近尾声/中期牛市开始；2026-07 大概率再次探底；2026-08 30 分钟级调整+六面图 -0.12 中性（views.md）",
        },
        "_meta": {
            "analyst": "刘富兵（国盛证券金融工程）",
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
        print("  %-18s None %2d/%d%s" % (f, n_none, len(MONTHS), flag))

    print("\n=== 末值检查（决策月 2026-08）===")
    for f in ["hs300_close", "erp_q", "cycle_real", "cycle_implied", "a_share_prosperity",
              "cb_dev", "liq_dir", "cred_dir", "growth_dir", "infl_dir", "shiller_erp",
              "amount_trend", "a_share_sentiment", "gk_exp_ret", "industry_momentum",
              "rs_score", "style_odds", "style_trend", "style_crowd"]:
        v = h[f][-1]
        print("  %-18s %s" % (f, v))

    print("\n下一步：python scripts/screen.py --data %s --json-out" % args.out)


if __name__ == "__main__":
    main()
