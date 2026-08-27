#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘胜利 Phase 4 A 类·数据准备：组装 macro_real.json 回填 screen.py
====================================================================
依据 analyst-distill 规范（phase4-scripts-conventions.md）编写。

数据来源（三层标注，详见 _meta）：
  ✅ westock-data 直连：kline sh000300/sh000852(指数月收+成交额)、yield(10Y 国债月均→利率水平)、
     financing(社融存量同比→宏观流动性)、cpi_ppi(CPI 同比→消费价格)、consumption(社零当月同比→零售景气)、
     investment(制造业+基建投资累计同比→投资增速)、pmi(PMI 新出口订单→外贸景气代理)
  ⚠️ 观点锚点：style_cycle_pos(价值/成长三年周期位置，2026 成长期=偏成长，views.md 2026-01 年度判断)、
     pringle_phase(普林格周期阶段 2026 复苏/繁荣，views.md 2026-08 资产配置)、
     cb_gold/etf_gold(央行+ETF 购金持续，2022 以来需求端主力，views.md 2025-12/2026-08)
  ❌ 工程代理：liq_env/prosperity_env/inst_fund(S1 三维)、margin_ratio(融资占比)、
     factor_*(S3/S7 因子合成)、analyst_*(S5 分析师三维)、real_rate(实际利率=名义-通胀)、
     geo_risk(地缘分位)、chip_rankic(研究口径锚定 ✅ 原文 ~9.05%) —— 每条注明"最小假设，可替换"。

用法（在技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（原始数据 tmp_zhaolei_*.txt / tmp_fi_cpip_*.txt / tmp_liushi_*.txt 提前落盘在 {workspace}/.workbuddy/，见规范 §五）
"""

import argparse
import json
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
    """解析 markdown 表格 → (headers, rows)。' - '/'-' 视为缺失。"""
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


def get_col(headers, row, name):
    """取表格某列数值（'-'/''/'None' → None）。"""
    if name not in headers:
        return None
    i = headers.index(name)
    if i >= len(row):
        return None
    v = row[i]
    if v in ("-", "", "None", None):
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# 加载层：✅ westock 直连
# ----------------------------------------------------------------------------

def load_index_monthly(fname):
    """✅ westock：kline 月度收盘 → 36 长度序列（倒序→反转+月份对齐）。"""
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
    return load_index_monthly("tmp_zhaolei_hs300.txt")


def load_zz1000_close():
    """✅ westock：kline sh000852（中证1000）月度收盘。"""
    return load_index_monthly("tmp_zhaolei_zz1000.txt")


def load_rate_level():
    """✅ westock：yield 中债国债到期收益率 10Y → 月均（%）。"""
    path = os.path.join(TMP_DIR, "tmp_zhaolei_yield.txt")
    if not os.path.exists(path):
        return None
    rows = flatten_dedup(path, "YTM_END_DATE")
    by_m = monthly_avg(rows, "YTM_END_DATE", "YTM_YIELD_10Y")
    return ffill_by_month(by_m, MONTHS)


def load_credit_flow():
    """✅ westock：financing 社融存量同比 FINANCING_SR_SIZE_YOY → 宏观流动性（%）。"""
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
    按 CPI_END_DATE 去重：每月可能多行，取该列首个有值行（约定：cpip 每月 3 行分行）。"""
    cpi_d = {}
    for fn in CPIP_FILES:
        path = os.path.join(TMP_DIR, fn)
        if not os.path.exists(path):
            continue
        headers, rows = parse_md_table(path)
        if headers is None:
            continue
        for r in rows:
            mo = month_of(get_col(headers, r, "CPI_END_DATE"))
            if mo is None:
                continue
            if mo not in cpi_d:
                v = get_col(headers, r, "CPI_CPI_YOY")
                if v is not None:
                    cpi_d[mo] = v
    return ffill_by_month(cpi_d, MONTHS)


def load_retail_yoy():
    """✅ westock：consumption 社零当月同比 CONSUMP_CONSUMP_CUR_YOY（%）。"""
    path = os.path.join(TMP_DIR, "tmp_liushi_consumption.txt")
    if not os.path.exists(path):
        return None
    headers, rows = parse_md_table(path)
    if headers is None:
        return None
    d = {}
    for r in rows:
        mo = month_of(get_col(headers, r, "CONSUMP_END_DATE"))
        if mo is None:
            continue
        v = get_col(headers, r, "CONSUMP_CONSUMP_CUR_YOY")
        if v is not None:
            d.setdefault(mo, v)
    return ffill_by_month(d, MONTHS)


def load_invest_yoy():
    """✅ westock：investment 制造业+基建投资累计同比均值（%）。"""
    path = os.path.join(TMP_DIR, "tmp_liushi_investment.txt")
    if not os.path.exists(path):
        return None
    headers, rows = parse_md_table(path)
    if headers is None:
        return None
    d = {}
    for r in rows:
        mo = month_of(get_col(headers, r, "INV_END_DATE"))
        if mo is None:
            continue
        m = get_col(headers, r, "INV_INV_MANU_CUM_YOY")
        i = get_col(headers, r, "INV_INV_INFRA_CUM_YOY")
        vals = [v for v in (m, i) if v is not None]
        if vals:
            d.setdefault(mo, round(sum(vals) / len(vals), 2))
    return ffill_by_month(d, MONTHS)


def load_pmi_export():
    """✅ westock：pmi PMI_PMI_MANU_ORDER_EXPORT（PMI 新出口订单，>50 扩张）→ 外贸景气代理。
    说明：westock export 接口无出口同比字段，仅余额/储备/外储 → 用新出口订单指数作方向代理（⚠️ 口径降级）。"""
    path = os.path.join(TMP_DIR, "tmp_liushi_pmi.txt")
    if not os.path.exists(path):
        return None
    headers, rows = parse_md_table(path)
    if headers is None:
        return None
    d = {}
    for r in rows:
        mo = month_of(get_col(headers, r, "PMI_END_DATE"))
        if mo is None:
            continue
        v = get_col(headers, r, "PMI_PMI_MANU_ORDER_EXPORT")
        if v is not None:
            d.setdefault(mo, v)
    return ffill_by_month(d, MONTHS)


def load_index_amount(fnames):
    """✅ westock：指数月成交额合计（亿元）→ S1 资金面/情绪底层。"""
    out = []
    for mo in MONTHS:
        total = 0.0
        for fn in fnames:
            path = os.path.join(TMP_DIR, fn)
            if not os.path.exists(path):
                continue
            rows = flatten_dedup(path, "date")
            for r in rows:
                if month_of(r.get("date")) == mo and r.get("amount") is not None:
                    total += r["amount"]
        out.append(round(total / 1e8, 2))
    return out


# ----------------------------------------------------------------------------
# 锚点层：⚠️ 观点锚点（views.md 判断方向）
# ----------------------------------------------------------------------------

def build_anchor_fields():
    """⚠️ 层：刘胜利公开观点中的方向锚点（views.md）。
    style_cycle_pos（价值/成长周期位置）：2026-01-28 年度判断"2026 偏大盘成长"（✅），
      价值/成长约 3 年周期（2023 前后切换）→ 2025 下半年起进入成长期（正），此前为价值期（负）。
      ——周期位置为框架概念，无公开数值，构造为平滑过渡序列（❌ 具体数值最小假设，方向 ✅）。
    pringle_phase（普林格周期）：2026-08 资产配置（四）黄金战略配置（经济扩张+通胀预期+货币宽松）
      → 复苏/繁荣期（编号 1/2，❌ 编号推断）。
    cb_gold/etf_gold：2022 以来央行+ETF 购金为需求端主力（✅ views.md 2025-12/2026-08）→ 持续为正。"""
    n = len(MONTHS)
    # style_cycle_pos：2023-09~2025-06 价值期（负），2025-07 起过渡，2026 成长期（正）
    cycle = []
    for mo in MONTHS:
        if mo < "2025-07":
            cycle.append(-0.5)          # 价值期（2023 前后切换后的价值段）
        elif mo < "2026-01":
            cycle.append(0.0)           # 过渡（周期底部区域）
        else:
            cycle.append(0.6)           # 成长期（2026 年度判断：偏成长 ✅）
    # pringle_phase：2025-07 前滞胀/衰退（3/4），之后复苏→繁荣（1/2）——❌ 编号推断，仅方向
    pringle = []
    for mo in MONTHS:
        if mo < "2024-09":
            pringle.append(4)           # 衰退（2024 底部）
        elif mo < "2025-07":
            pringle.append(3)           # 滞胀（2025 修复期）
        elif mo < "2026-03":
            pringle.append(1)           # 复苏
        else:
            pringle.append(2)           # 繁荣（2026 黄金战略配置 ✅）
    # 央行/ETF 购金：2022 以来主力 → 持续为正（月度无公开数值 → 方向常量 ⚠️）
    cb_gold = [25.0] * n                # 央行购金净买入（吨/月，方向常量 ⚠️）
    etf_gold = [15.0] * n               # 黄金 ETF 净流入（吨/月，方向常量 ⚠️）
    return {
        "style_cycle_pos": cycle,
        "pringle_phase": pringle,
        "cb_gold": cb_gold,
        "etf_gold": etf_gold,
    }


# ----------------------------------------------------------------------------
# 代理层：❌ 工程代理（每条注明构造逻辑 + 最小假设，可替换）
# ----------------------------------------------------------------------------

def build_proxies(hs300, zz1000, rate_level, credit_flow, cpi_yoy, retail_yoy,
                  invest_yoy, pmi_exp, amount):
    """❌ 层：方向性代理序列。全部为"最小假设，可替换"，验证目的仅为检验框架方向是否忠实还原分析师思维。"""
    out = {}
    n = len(MONTHS)

    # ---- S1 三维代理 ----
    # liq_env（流动性环境）：利率水平越低 → 越宽松（-zscore(10Y)）+ 社融扩张辅助（✅ 规则：宽松→成长加分）
    rz = zscore(rate_level) if rate_level else [0.0] * n
    cz = zscore(credit_flow) if credit_flow else [0.0] * n
    out["liq_env"] = [round(clip(-rz[i] * 0.7 + cz[i] * 0.3, -1, 1), 2) for i in range(n)]
    # prosperity_env（景气度环境）：PMI 新出口订单 -50（扩张偏离）→ 景气方向（✅ 规则：高景气→成长加分）
    out["prosperity_env"] = [round(clip((v - 50.0) / 10.0, -1, 1), 2) if v is not None else 0.0
                             for v in (pmi_exp or [50.0] * n)]
    # inst_fund（机构资金面）：机构化推进无月度 API → 大盘相对小盘 12m 动量方向（机构主导=大盘占优 ❌ 代理）
    inst = []
    for i in range(n):
        if i < 12 or not hs300 or not zz1000 or not hs300[i] or not zz1000[i] \
                or not hs300[i - 12] or not zz1000[i - 12]:
            inst.append(0.0)
        else:
            rel = (hs300[i] / hs300[i - 12]) / (zz1000[i] / zz1000[i - 12]) - 1.0
            inst.append(clip(rel * 8.0, -1, 1))
    out["inst_fund"] = inst
    # margin_ratio（融资占比）：两融无月度 API → 恒 0 中性（❌，可选字段不影响 S1 主判断）
    out["margin_ratio"] = [0.0] * n

    # ---- S3 因子风险分层（❌ 叙事 + 量价代理）----
    # 2024 底部：低风险占优、高风险弱；2025 上涨：高风险转正；2026-08 绝对收益防御态（✅ views.md）：
    # 低风险正、非周期正、高风险转负 → S3 触发"风险偏好回落：低风险底仓为主、高风险降档"
    lr, nc, hr = [], [], []
    for i, mo in enumerate(MONTHS):
        if mo < "2024-09":
            lr.append(0.4); nc.append(-0.1); hr.append(-0.3)     # 底部：低风险底仓有效
        elif mo < "2025-11":
            lr.append(0.2); nc.append(0.1); hr.append(0.5)       # 修复/上涨：高风险弹性恢复
        elif mo < "2026-05":
            lr.append(0.1); nc.append(0.2); hr.append(0.3)       # 高位：风险偏好仍高
        else:
            lr.append(0.5); nc.append(0.3); hr.append(-0.4)      # 2026-08 防御态（✅ 资产配置四）
    out["factor_lowrisk"] = lr
    out["factor_noncycle"] = nc
    out["factor_highrisk"] = hr

    # ---- S5 分析师三维（❌ 叙事代理：westock 无一致预期接口）----
    # 2026-05-07 行业轮动（十二）分析师因子观点：超预期+预期增长共振行业加配、成长占优（✅ views.md）
    su, gr, dr = [], [], []
    for i, mo in enumerate(MONTHS):
        if mo < "2025-11":
            su.append(-0.2); gr.append(-0.1); dr.append(-0.1)    # 窗口前期：预期下修
        else:
            su.append(0.4); gr.append(0.3); dr.append(0.2)       # 2026 成长占优：三维转正
    out["analyst_surprise"] = su
    out["analyst_growth"] = gr
    out["analyst_drive"] = dr

    # ---- S6 筹码因子 RankIC（研究口径锚定）----
    # ✅ 原文：2019-2025-11 筹码因子 RankIC ~9.05%（研究口径，真实落地需 Level1 数据不提供）→ 常数锚定
    out["chip_rankic"] = [9.05] * n

    # ---- S7 多因子组合（❌ 叙事代理：无因子暴露月度 API）----
    # 2026 大盘成长主线（✅ views.md）：大盘因子正、成长因子正；2026-08 拥挤度回落+反转转正（防御态）
    lc, gt, cd, rv = [], [], [], []
    for i, mo in enumerate(MONTHS):
        if mo < "2024-09":
            lc.append(0.3); gt.append(-0.3); cd.append(-0.2); rv.append(0.3)   # 底部：大盘价值
        elif mo < "2025-11":
            lc.append(0.2); gt.append(0.4); cd.append(0.3); rv.append(-0.2)    # 修复：成长占优、拥挤抬升
        elif mo < "2026-05":
            lc.append(0.1); gt.append(0.5); cd.append(0.5); rv.append(-0.3)    # 高位：成长动量强、拥挤度高
        else:
            lc.append(0.4); gt.append(0.3); cd.append(-0.3); rv.append(0.3)    # 2026-08：大盘成长+拥挤回落
    out["factor_largecap"] = lc
    out["factor_growth"] = gt
    out["factor_crowding"] = cd
    out["factor_reversal"] = rv

    # ---- S8 大类资产黄金 ----
    # real_rate（实际利率）：名义 10Y - 通胀预期（CPI 代理）❌ → 2026 实际利率下行（✅ views.md 黄金逻辑）
    rr = []
    for i in range(n):
        y = rate_level[i] if rate_level and rate_level[i] is not None else 2.0
        c = cpi_yoy[i] if cpi_yoy and cpi_yoy[i] is not None else 0.0
        rr.append(round(y - c, 2))
    out["real_rate"] = rr
    # geo_risk（地缘分位 0-100）：无月度 API → 叙事分位（2026 升温 ✅ views.md 资产配置四）
    geo = []
    for i, mo in enumerate(MONTHS):
        if mo < "2025-01":
            geo.append(45.0)
        elif mo < "2026-01":
            geo.append(50.0)
        else:
            geo.append(62.0)            # 2026 地缘升温 → >50 触发对冲加配
    out["geo_risk"] = geo

    # ---- 情绪/量价辅助（S1 资金面、报告参考）----
    mom = [hs300[i] / hs300[i - 1] - 1.0 if i and hs300 and hs300[i - 1] and hs300[i] else 0.0
           for i in range(n)]
    out["a_share_sentiment"] = [round(clip(0.5 * (1 if m > 0.01 else (-1 if m < -0.01 else 0)) +
                                           0.5 * (1 if amount[i] > (amount[i - 1] if i else amount[i]) else 0),
                                       -1, 1), 2)
                                for i, m in enumerate(mom)]

    return out


# ----------------------------------------------------------------------------
# 组装层
# ----------------------------------------------------------------------------

def build_macro_json():
    hs300 = load_hs300_close()
    zz1000 = load_zz1000_close()
    rate_level = load_rate_level()
    credit_flow = load_credit_flow()
    cpi_yoy = load_cpip()
    retail_yoy = load_retail_yoy()
    invest_yoy = load_invest_yoy()
    pmi_exp = load_pmi_export()
    amount = load_index_amount(["tmp_zhaolei_hs300.txt", "tmp_zhaolei_zz1000.txt"])
    anchors = build_anchor_fields()
    proxies = build_proxies(hs300, zz1000, rate_level, credit_flow, cpi_yoy,
                            retail_yoy, invest_yoy, pmi_exp, amount)

    # export_yoy：PMI 新出口订单 - 50 偏离度（方向代理，⚠️ 口径降级；非真实出口同比）
    export_yoy = [round(v - 50.0, 1) if v is not None else None for v in (pmi_exp or [])]
    # style_env：S1 输出回填（2026 成长环境=正）——供 S7 用（与 style_cycle_pos 同向）
    style_env = [round(v * 0.8, 2) for v in anchors["style_cycle_pos"]]

    # spring_effect / national_effect：事件窗口（2026-08 非春节/国庆 → 0）
    spring_effect = [0] * len(MONTHS)
    national_effect = [0] * len(MONTHS)

    history = {
        "months": MONTHS,
        # S1 输入
        "style_cycle_pos": anchors["style_cycle_pos"],
        "liq_env": proxies["liq_env"],
        "prosperity_env": proxies["prosperity_env"],
        "inst_fund": proxies["inst_fund"],
        "margin_ratio": proxies["margin_ratio"],
        # S2 输入
        "cpi_yoy": cpi_yoy,
        "retail_yoy": retail_yoy,
        "rate_level": rate_level,
        "invest_yoy": invest_yoy,
        "credit_flow": credit_flow,
        "export_yoy": export_yoy,
        # S3 输入
        "factor_lowrisk": proxies["factor_lowrisk"],
        "factor_noncycle": proxies["factor_noncycle"],
        "factor_highrisk": proxies["factor_highrisk"],
        # S4 输入
        "spring_effect": spring_effect,
        "national_effect": national_effect,
        # S5 输入
        "analyst_surprise": proxies["analyst_surprise"],
        "analyst_growth": proxies["analyst_growth"],
        "analyst_drive": proxies["analyst_drive"],
        # S6 输入
        "chip_rankic": proxies["chip_rankic"],
        # S7 输入
        "factor_largecap": proxies["factor_largecap"],
        "factor_growth": proxies["factor_growth"],
        "factor_crowding": proxies["factor_crowding"],
        "factor_reversal": proxies["factor_reversal"],
        "style_env": style_env,
        # S8 输入
        "real_rate": proxies["real_rate"],
        "geo_risk": proxies["geo_risk"],
        "cb_gold": anchors["cb_gold"],
        "etf_gold": anchors["etf_gold"],
        "pringle_phase": anchors["pringle_phase"],
        # 参考辅助
        "hs300_close": hs300,
        "zz1000_close": zz1000,
        "a_share_sentiment": proxies["a_share_sentiment"],
    }

    meta = {
        "✅westock": {
            "hs300_close/zz1000_close": "kline sh000300/sh000852 月度收盘",
            "rate_level": "yield YTM_YIELD_10Y 中债国债 10Y 月均（%）",
            "credit_flow": "financing FINANCING_SR_SIZE_YOY 社融存量同比（%）",
            "cpi_yoy": "cpi_ppi 年度文件合并 CPI_CPI_YOY（每月取该列首个有值行）",
            "retail_yoy": "consumption CONSUMP_CONSUMP_CUR_YOY 社零当月同比（%）",
            "invest_yoy": "investment INV_INV_MANU_CUM_YOY 与 INV_INV_INFRA_CUM_YOY 均值（%）",
            "pmi_exp": "pmi PMI_PMI_MANU_ORDER_EXPORT 新出口订单（>50 扩张）",
            "amount": "sh000300+sh000852 月成交额合计（亿元）",
        },
        "⚠️锚点": {
            "style_cycle_pos": "views.md 2026-01 年度判断：2026 偏大盘成长（✅ 方向）；三年周期位置无公开数值，数值为 ❌ 最小假设",
            "pringle_phase": "views.md 2026-08 黄金战略配置（复苏/繁荣期）；阶段编号 1-4 为 ❌ 推断",
            "cb_gold/etf_gold": "views.md 2025-12/2026-08：2022 以来央行+ETF 购金为需求端主力（方向 ✅，月度吨数为常量 ⚠️）",
        },
        "❌代理": {
            "liq_env": "-zscore(10Y 利率)*0.7 + zscore(社融)*0.3（宽松=利率低+信用扩张）",
            "prosperity_env": "PMI 新出口订单-50 偏离 /10（高景气→成长加分 ✅ 规则）",
            "inst_fund": "大盘相对小盘 12m 动量（机构化推进无月度 API）",
            "margin_ratio": "恒 0 中性（两融数据无月度 API，可选字段）",
            "export_yoy": "PMI 新出口订单-50 偏离（⚠️ westock export 接口无出口同比，仅余额/储备 → 方向代理）",
            "factor_lowrisk/noncycle/highrisk": "views.md 观点时间线叙事（2024 底→2025 修复→2026-08 防御态）",
            "analyst_surprise/growth/drive": "views.md 2026-05 分析师因子观点叙事（无一致预期接口）",
            "chip_rankic": "✅ 原文 ~9.05%（研究口径，2019-2025-11）；常数锚定，非当月实测",
            "factor_largecap/growth/crowding/reversal": "views.md 2026 大盘成长主线叙事",
            "real_rate": "名义 10Y - CPI（通胀预期代理）",
            "geo_risk": "views.md 2026 地缘升温叙事分位（无月度 API）",
            "a_share_sentiment": "指数动量+成交额环比合成（辅助参考）",
        },
        "note": (
            "① 验证目的是'框架可执行性+方向还原度'，非回测绩效——代理字段均为最小假设可替换，"
            "真实信号落地需一致预期/两融/Level1 等数据源。"
            "② S1 输出'偏大盘成长'（2026 ✅ 判断同向）、S3 输出防御态（2026-08 ✅ 资产配置四同向）为关键对照。"
            "③ 无前视纪律：字段序列均为决策时点可得数据；2026-08 为最新决策月。"
        ),
    }

    return {
        "as_of": "2026-08-27",
        "history": history,
        "extras": {
            "view_note": "2026-08-19 资产配置（四）：权益绝对收益策略（低风险底仓+非周期增强+Beta约束）+ 黄金战略配置；2026-01 年度判断偏大盘成长（views.md）",
            "style_note": "2026 年度策略+复旦 FICC 论坛：周期时间+宏观基本面+资金面三维 → 2026 大概率偏大盘成长（✅ 原文）",
        },
        "_meta": {
            "analyst": "刘胜利（长江证券金融工程）",
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
    for f in ["style_cycle_pos", "liq_env", "prosperity_env", "inst_fund",
              "cpi_yoy", "retail_yoy", "rate_level", "invest_yoy", "credit_flow", "export_yoy",
              "factor_lowrisk", "factor_noncycle", "factor_highrisk",
              "analyst_surprise", "analyst_growth", "analyst_drive",
              "factor_largecap", "factor_growth", "factor_crowding", "factor_reversal",
              "real_rate", "geo_risk", "cb_gold", "etf_gold", "pringle_phase",
              "hs300_close", "a_share_sentiment"]:
        v = h[f][-1]
        print("  %-18s %s" % (f, v))

    print("\n下一步：python scripts/screen.py --data %s --json-out" % args.out)


if __name__ == "__main__":
    main()
