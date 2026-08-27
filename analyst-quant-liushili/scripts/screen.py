#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘胜利（长江证券金工首席）信号计算脚本 —— screen.py
============================================================
依据 references/decision-rules.md 实现 S1-S8 信号。
纯标准库；五函数结构；演示模式（合成数据）默认可运行。

用法：
  python scripts/screen.py                  # 演示模式（合成数据）
  python scripts/screen.py --schema         # 输出输入契约 JSON
  python scripts/screen.py --data macro.json   # 真实数据
  python scripts/screen.py --data macro.json --json-out  # 机器可读 JSON
"""

import argparse
import json
import math as _m
import statistics as _st
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ============================================================
# 参数区（来源分级：✅ 原文 / ⚠️ 外推 / ❌ 推断 —— 与 decision-rules.md 图例一致）
# ------------------------------------------------------------
# S1 风格周期三维判断
CYCLE_GROWTH_BASE = 36.0  # ✅ 原文：价值成长轮动周期约三年（36 个月）
S1_GROWTH_TH = 0.0        # ❌ 推断：成长得分 >0 偏成长 / <0 偏价值，最小假设可替换
S1_LARGE_TH = 0.0         # ❌ 推断：大盘得分 >0 偏大盘（机构化代理），最小假设可替换
# S2 风格轮动图谱（方向打分，无绝对阈值）
S2_DIR_TH = 0.0           # ❌ 推断：因子方向分 >0 利好后一组风格
# S3 因子风险分层（三层结构固定，✅ 原文）
F3_BETA_TARGET = 1.0      # ❌ 推断：Beta 约束目标（未公开，组合优化参数可替换）
# S4 日历效应（✅ 原文规则，月份-暴露映射）
CAL_Q2_HIGH = 2           # ✅ 原文：二季度（4-6 月）高风险因子加仓窗口
CAL_Q3Q4_LOW = 3          # ✅ 原文：三四季度（7-12 月）降风险暴露
# S5 分析师因子（✅ 原文定义，权重 ❌ 推断）
AN_SUPR_W = 0.5           # ❌ 推断：超预期因子权重（主），最小假设可替换
AN_GROW_W = 0.3           # ❌ 推断：预期增长因子权重（辅，时序稳定性弱）
AN_DRIVE_W = 0.2          # ❌ 推断：驱动因子权重（换手维度）
# S6 神经网络因子（研究口径参考）
CHIP_RANKIC_REF = 5.0     # ❌ 推断：RankIC>5% 视为有效因子窗口（参考 ✅ 原文 ~9.05%）
# S8 大类资产黄金配置
R_REAL_DOWN_TH = 0.0      # ❌ 推断：实际利率环比下行=黄金加配信号（✅ 原文规则方向）
GEO_RISK_TH = 50.0        # ❌ 推断：地缘风险分位 >50=对冲加配
# 仓位工程化（❌ 推断：分析师未公布仓位映射，最小假设可替换）
POS_BASE = 55.0
POS_S1_GROW = 8.0         # 偏成长加仓
POS_S1_VALUE = -5.0       # 偏价值（相对防御）
POS_CAL_LOW = -6.0        # 三四季度降风险暴露
POS_GOLD_UP = 5.0         # 黄金超配
POS_MIN, POS_MAX = 30.0, 85.0
# ============================================================


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------

def pct_rank(series, value):
    """value 在 series 中的百分位（0-100）。"""
    if not series:
        return 50.0
    below = sum(1 for x in series if x < value)
    return below / len(series) * 100.0


def trend_up(series, lookback=3):
    """最近 lookback 期是否整体上行（末值高于首值）。"""
    if len(series) < 2:
        return False
    win = series[-lookback:]
    return win[-1] > win[0]


def recent_avg(series, lookback=3):
    """最近 lookback 期均值；序列不足时取全部。"""
    if not series:
        return 0.0
    win = series[-lookback:]
    return sum(win) / len(win)


def _clean(series):
    """剔除 None（数据源窗口末端/未发布）后返回。"""
    return [x for x in series if x is not None]


def _z(series):
    """全序列 z-score（σ 为样本标准差；n<3 时退化为 0 序列）。"""
    c = _clean(series)
    if len(c) < 3:
        return [0.0] * len(series)
    mu = _st.mean(c)
    sd = _st.stdev(c)
    if sd == 0:
        return [0.0] * len(series)
    return [(x - mu) / sd for x in series]


def _month_of(months):
    """从 months 数组取最新月份（'YYYY-MM' 或 'YYYY-MM-DD'）→ (年, 月)。"""
    if not months:
        return None
    last = str(months[-1])
    parts = last.split("-")
    if len(parts) >= 2:
        return (int(parts[0]), int(parts[1]))
    return None


# ----------------------------------------------------------------------------
# 信号计算函数（契约：输入 h / extras → 返回 dict）
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 风格周期三维判断：周期时间 + 宏观基本面（流动性/景气） + 资金面 → 四象限风格。"""
    need = ["style_cycle_pos", "liq_env", "prosperity_env", "inst_fund"]
    if any(not h.get(f) or not _clean(h[f]) for f in need):
        return {"id": "S1", "name": "风格周期三维判断", "triggered": False,
                "detail": "缺字段 style_cycle_pos/liq_env/prosperity_env/inst_fund（风格三维代理）", "strength": "direction"}
    cycle_pos = _clean(h["style_cycle_pos"])[-1]     # 正值=成长期、负值=价值期（❌ 代理）
    liq = _clean(h["liq_env"])[-1]                    # 正值=高流动性
    pros = _clean(h["prosperity_env"])[-1]            # 正值=高景气
    inst = _clean(h["inst_fund"])[-1]                 # 正值=机构化推进（偏大盘）
    margin = _clean(h["margin_ratio"])[-1] if h.get("margin_ratio") and _clean(h["margin_ratio"]) else 0.0
    growth_score = (cycle_pos + liq + pros) / 3.0      # ❌ 等权最小假设
    large_score = inst + (0.1 if margin < 0 else 0.0)  # ❌ 融资占比低=杠杆提升空间=风险偏好上行
    if growth_score > S1_GROWTH_TH and large_score > S1_LARGE_TH:
        trig, level, strength = True, "偏大盘成长（✅ 2026 年度判断同向）", "mid"
    elif growth_score > S1_GROWTH_TH:
        trig, level, strength = True, "偏小盘成长", "mid"
    elif large_score > S1_LARGE_TH:
        trig, level, strength = True, "偏大盘价值", "mid"
    else:
        trig, level, strength = True, "偏小盘价值", "mid"
    return {"id": "S1", "name": "风格周期三维判断", "triggered": trig,
            "detail": f"成长得分 {growth_score:+.2f} / 大盘得分 {large_score:+.2f}（周期 {cycle_pos:+.2f}，流动性 {liq:+.2f}，景气 {pros:+.2f}，机构 {inst:+.2f}）→ {level}",
            "strength": strength}


def calc_s2(h, extras=None):
    """S2 风格轮动图谱：宏观因子库方向打分（消费/周期、金融/非金融、科技/传统）。"""
    need = ["cpi_yoy", "retail_yoy", "rate_level", "invest_yoy", "credit_flow", "export_yoy"]
    if any(not h.get(f) or not _clean(h[f]) for f in need):
        return {"id": "S2", "name": "风格轮动图谱", "triggered": False,
                "detail": "缺字段 cpi_yoy/retail_yoy/rate_level/invest_yoy/credit_flow/export_yoy（宏观因子库）", "strength": "direction"}
    cpi = _clean(h["cpi_yoy"])[-1]
    retail = _clean(h["retail_yoy"])[-1]
    rate = _clean(h["rate_level"])[-1]
    invest = _clean(h["invest_yoy"])[-1]
    credit = _clean(h["credit_flow"])[-1]
    export = _clean(h["export_yoy"])[-1]
    # ✅ 原文规则：消费价格越低+零售越好 → 后期周期股；利率越高+投资越多 → 后期金融股；流动性越高+外贸越好 → 后期科技股
    cyc_score = -cpi + retail * 0.1       # ❌ 量纲合并推断
    fin_score = rate + invest * 0.05      # ❌ 量纲合并推断
    tec_score = credit + export * 0.2     # ❌ 量纲合并推断
    detail = (f"消费/周期 {cyc_score:+.2f}（CPI {cpi:+.1f}%，零售 {retail:+.1f}%）；"
              f"金融/非金融 {fin_score:+.2f}（利率 {rate:.2f}%，投资 {invest:+.1f}%）；"
              f"科技/传统 {tec_score:+.2f}（社融 {credit:+.1f}%，出口 {export:+.1f}%）")
    trig = abs(cyc_score) > 0.1 or abs(fin_score) > 0.1 or abs(tec_score) > 0.1  # ❌ 触发阈值推断
    return {"id": "S2", "name": "风格轮动图谱", "triggered": trig,
            "detail": detail + " → 方向打分（✅ 原文规则，无绝对阈值）", "strength": "direction"}


def calc_s3(h, extras=None):
    """S3 因子风险分层配置：低风险底仓 + 非周期增强 + 高风险弹性。"""
    need = ["factor_lowrisk", "factor_noncycle", "factor_highrisk"]
    if any(not h.get(f) or not _clean(h[f]) for f in need):
        return {"id": "S3", "name": "因子风险分层", "triggered": False,
                "detail": "缺字段 factor_lowrisk/factor_noncycle/factor_highrisk（三类因子合成值）", "strength": "direction"}
    lr = _clean(h["factor_lowrisk"])[-1]
    nc = _clean(h["factor_noncycle"])[-1]
    hr = _clean(h["factor_highrisk"])[-1]
    # ✅ 原文三层结构：低风险底仓、非周期增强、Beta 约束；高风险仅在风险偏好高时提升
    if lr > 0 and hr < 0:
        trig, level, strength = True, "风险偏好回落：低风险底仓为主、高风险降档（绝对收益策略防御态）", "strong"
    elif lr > 0 and hr > 0:
        trig, level, strength = True, "三层结构齐备：低风险底仓+非周期增强+高风险弹性（绝对收益策略进攻态）", "strong"
    else:
        trig, level, strength = False, "因子分层信号中性", "direction"
    return {"id": "S3", "name": "因子风险分层", "triggered": trig,
            "detail": f"低风险 {lr:+.2f} / 非周期 {nc:+.2f} / 高风险 {hr:+.2f}（Beta 目标 {F3_BETA_TARGET:.1f} ❌）→ {level}",
            "strength": strength}


def calc_s4(h, extras=None):
    """S4 日历效应因子暴露：月份节奏 + 春节/国庆事件窗口。"""
    month = _month_of(h.get("months")) if h.get("months") else None
    if month is None:
        return {"id": "S4", "name": "日历效应", "triggered": False,
                "detail": "缺字段 months（月份标签数组，判断季度窗口）", "strength": "direction"}
    mo = month[1]
    spring = h.get("spring_effect") or 0  # 1=春节前窗口 / -1=节后窗口 / 0=非窗口
    natl = h.get("national_effect") or 0  # 1=国庆前后窗口 / 0=非窗口
    if spring == 1:
        trig, level, strength = True, "春节前：风险偏好高，保持高风险暴露（✅ 原文'冰火两重天'）", "mid"
    elif spring == -1:
        trig, level, strength = True, "春节后：风险偏好回落，降档（✅ 原文）", "mid"
    elif natl == 1:
        trig, level, strength = True, "国庆前后：所有因子策略减弱，降因子暴露（✅ 原文跨节效应）", "mid"
    elif 4 <= mo <= 6:
        trig, level, strength = True, "二季度：高风险因子（成长/动量）表现最佳，加仓窗口（✅ 原文）", "strong"
    elif mo >= 7:
        trig, level, strength = True, "三四季度：风险偏好缓慢下降，降风险暴露（✅ 原文）", "mid"
    else:
        trig, level, strength = False, "一季度（春季躁动期）：风险偏好逐步上升，中性偏高", "direction"
    return {"id": "S4", "name": "日历效应", "triggered": trig,
            "detail": f"当前月份 {month[0]}-{mo:02d} → {level}", "strength": strength}


def calc_s5(h, extras=None):
    """S5 行业轮动分析师因子：超预期 + 预期增长 + 驱动 三维合成。"""
    need = ["analyst_surprise", "analyst_growth", "analyst_drive"]
    if any(not h.get(f) or not _clean(h[f]) for f in need):
        return {"id": "S5", "name": "行业轮动（分析师因子）", "triggered": False,
                "detail": "缺字段 analyst_surprise/analyst_growth/analyst_drive（一致预期代理 ❌）", "strength": "direction"}
    su = _clean(h["analyst_surprise"])[-1]
    gr = _clean(h["analyst_growth"])[-1]
    dr = _clean(h["analyst_drive"])[-1]
    comp = AN_SUPR_W * su + AN_GROW_W * gr + AN_DRIVE_W * dr  # ❌ 权重最小假设
    if comp > 0 and su > 0:
        trig, level, strength = True, "分析师因子共振（超预期为主+预期增长/驱动辅助）→ 行业/ETF 加配（✅ 原文三维定义）", "mid"
    elif comp > 0:
        trig, level, strength = False, "分析师因子合成转正但超预期未确认 → 观察", "direction"
    else:
        trig, level, strength = False, "分析师因子合成为负 → 行业轮动回避", "direction"
    return {"id": "S5", "name": "行业轮动（分析师因子）", "triggered": trig,
            "detail": f"超预期 {su:+.2f} / 预期增长 {gr:+.2f} / 驱动 {dr:+.2f} → 合成 {comp:+.2f}（权重 {AN_SUPR_W:g}/{AN_GROW_W:g}/{AN_DRIVE_W:g} ❌）→ {level}",
            "strength": strength}


def calc_s6(h, extras=None):
    """S6 神经网络因子指增：筹码 RankIC 有效性（研究口径，方向参考）。"""
    if not h.get("chip_rankic"):
        return {"id": "S6", "name": "神经网络因子", "triggered": False,
                "detail": "缺字段 chip_rankic（筹码因子 RankIC %，研究口径）", "strength": "direction"}
    ric = h["chip_rankic"]
    if isinstance(ric, (list, tuple)):
        ric = _clean(ric)[-1] if _clean(ric) else None
    if ric is None:
        return {"id": "S6", "name": "神经网络因子", "triggered": False,
                "detail": "chip_rankic 无效", "strength": "direction"}
    if ric > CHIP_RANKIC_REF:
        trig, level, strength = True, f"深度学习因子有效（RankIC {ric:.2f}% > {CHIP_RANKIC_REF:.0f}%）→ 指增方向有效（✅ 原文 ~9.05%，2019-2025-11）", "direction"
    else:
        trig, level, strength = False, f"RankIC {ric:.2f}% 未达参考阈值 → 因子弱化（✅ 原文 2025 后传统因子失效背景）", "direction"
    return {"id": "S6", "name": "神经网络因子", "triggered": trig,
            "detail": f"筹码因子 RankIC {ric:.2f}%（参考 >{CHIP_RANKIC_REF:.0f}%）→ {level}；真实筹码因子需 Level1 数据不落地，本信号仅方向参考",
            "strength": strength}


def calc_s7(h, extras=None):
    """S7 多因子组合构建：大盘 + 成长 + 非周期因子，按风格环境选子集。"""
    need = ["factor_largecap", "factor_growth", "factor_crowding", "factor_reversal"]
    if any(not h.get(f) or not _clean(h[f]) for f in need):
        return {"id": "S7", "name": "多因子组合", "triggered": False,
                "detail": "缺字段 factor_largecap/factor_growth/factor_crowding/factor_reversal（组合因子）", "strength": "direction"}
    lc = _clean(h["factor_largecap"])[-1]
    gt = _clean(h["factor_growth"])[-1]
    cd = _clean(h["factor_crowding"])[-1]
    rv = _clean(h["factor_reversal"])[-1]
    style_env = h.get("style_env") or extras.get("style_env") or 0.0  # S1 输出：正=成长风格环境
    if isinstance(style_env, (list, tuple)):  # 统一契约：字段→月份数组，取最新一期
        style_env = style_env[-1] if style_env else 0.0
    if style_env > 0:
        # ✅ 原文：成长风格下分析师预期/成长动量/质量因子有效
        if gt > 0 and cd < 0:
            trig, level, strength = True, "成长风格环境：成长因子有效+拥挤度回落 → 组合偏成长加仓（✅ 原文风格-因子映射）", "mid"
        else:
            trig, level, strength = False, "成长风格环境但成长因子/拥挤度未确认 → 均衡", "direction"
    else:
        # 大盘/价值环境：大盘因子 + 非周期因子降尾部风险
        if lc > 0 and (cd < 0 or rv > 0):
            trig, level, strength = True, "大盘/价值风格环境：大盘因子+非周期因子（拥挤度/反转）降尾部风险（✅ 原文）", "mid"
        else:
            trig, level, strength = False, "风格环境未确认 → 均衡组合", "direction"
    return {"id": "S7", "name": "多因子组合", "triggered": trig,
            "detail": f"大盘 {lc:+.2f} / 成长 {gt:+.2f} / 拥挤度 {cd:+.2f} / 反转 {rv:+.2f}（风格环境 {style_env:+.2f}）→ {level}",
            "strength": strength}


def calc_s8(h, extras=None):
    """S8 大类资产黄金配置：实际利率下行 + 地缘升温 + 购金持续 → 黄金超配。"""
    if not h.get("real_rate") or not _clean(h["real_rate"]):
        return {"id": "S8", "name": "大类资产黄金", "triggered": False,
                "detail": "缺字段 real_rate（实际利率）", "strength": "direction"}
    rr = _clean(h["real_rate"])
    rr_down = len(rr) >= 2 and rr[-1] < rr[-2]          # 实际利率下行（✅ 原文规则）
    geo = _clean(h["geo_risk"])[-1] if h.get("geo_risk") and _clean(h["geo_risk"]) else None
    gold_cb = _clean(h["cb_gold"])[-1] if h.get("cb_gold") and _clean(h["cb_gold"]) else None
    etf_gold = _clean(h["etf_gold"])[-1] if h.get("etf_gold") and _clean(h["etf_gold"]) else None
    pringle = h.get("pringle_phase") or 0               # ✅ 原文：复苏/繁荣=战略配置
    if isinstance(pringle, (list, tuple)):              # 统一契约：字段→月份数组，取最新一期
        pringle = pringle[-1] if pringle else 0
    score = 0.0
    notes = []
    if rr_down:
        score += 1
        notes.append("实际利率下行")
    if geo is not None and geo > GEO_RISK_TH:
        score += 1
        notes.append("地缘风险升温")
    if gold_cb is not None and gold_cb > 0:
        score += 1
        notes.append("央行购金持续")
    if etf_gold is not None and etf_gold > 0:
        score += 1
        notes.append("ETF 购金持续")
    if pringle in (1, 2):                               # 1=复苏 2=繁荣（❌ 阶段编号推断）
        score += 1
        notes.append("普林格周期复苏/繁荣")
    if score >= 3:
        trig, level, strength = True, "黄金战略配置：多项驱动共振 → 黄金超配（✅ 原文 2022 以来央行+ETF 购金主力）", "mid"
    elif score >= 2:
        trig, level, strength = True, "黄金配置增强：驱动信号 ≥2 → 标配偏超", "mid"
    else:
        trig, level, strength = False, "黄金驱动信号不足 → 标配（分散波动角色，✅ 原文）", "direction"
    return {"id": "S8", "name": "大类资产黄金", "triggered": trig,
            "detail": f"实际利率 {'↓' if rr_down else '↑'} / 地缘 {geo} / 央行购金 {gold_cb} / ETF购金 {etf_gold} / 普林格 {pringle} → {'+'.join(notes) if notes else '无强驱动'} → {level}",
            "strength": strength}


# ----------------------------------------------------------------------------
# 信号汇总 → 仓位/结构建议（工程化设计，❌ 推断）
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    trig = [s for s in signals if s["triggered"]]
    equity = POS_BASE
    # S1 风格方向修正
    s1 = next((s for s in signals if s["id"] == "S1"), None)
    if s1 and s1["triggered"]:
        if "成长" in s1["detail"]:
            equity += POS_S1_GROW
        elif "价值" in s1["detail"]:
            equity += POS_S1_VALUE
    # S4 日历效应修正
    s4 = next((s for s in signals if s["id"] == "S4"), None)
    if s4 and s4["triggered"] and ("三四季度" in s4["detail"] or "国庆" in s4["detail"] or "春节后" in s4["detail"]):
        equity += POS_CAL_LOW
    # S8 黄金超配修正
    s8 = next((s for s in signals if s["id"] == "S8"), None)
    if s8 and s8["triggered"] and "黄金超配" in s8["detail"]:
        equity += POS_GOLD_UP
    equity = round(max(POS_MIN, min(POS_MAX, equity)))

    structure = []
    if not trig:
        structure.append("无信号触发，均衡配置")
    for s in trig:
        structure.append(f"{s['id']} {s['name']}：{s['detail']}")
    # 因子分层与多因子组合联动
    s3 = next((s for s in signals if s["id"] == "S3"), None)
    if s3 and s3["triggered"]:
        structure.append("配置结构：低风险底仓 + 非周期增强 + Beta 约束（绝对收益三层结构 ✅ 原文）")
    return {
        "equity": equity,
        "structure": structure,
        "strong_triggered": [s["id"] for s in trig if s.get("strength") == "strong"],
        "mid_triggered": [s["id"] for s in trig if s.get("strength") == "mid"],
        "weak_triggered": [s["id"] for s in trig if s.get("strength") == "direction"],
    }


# ----------------------------------------------------------------------------
# 报告渲染
# ----------------------------------------------------------------------------

def render_report(signals, positions, data, n_triggered, total):
    as_of = data.get("as_of", "N/A")
    demo = not bool(data.get("_real", False))
    lines = []
    lines.append(f"# 刘胜利（长江金工）框架 · 信号报告（截至 {as_of}）")
    if demo:
        lines.append("> ⚠️ 数据来源：**演示模式（合成数据）**，仅用于验证流程，非真实数据。请用 --data 传入真实数据。")
    lines.append("")
    lines.append(f"## 一、信号汇总（触发 {n_triggered}/{total}）")
    lines.append("")
    lines.append("| 信号 | 名称 | 状态 | 读数与动作 |")
    lines.append("|---|---|---|---|")
    for s in signals:
        status = "✅ 触发" if s["triggered"] else "—"
        lines.append(f"| {s['id']} | {s['name']} | {status} | {s['detail']} |")
    lines.append("")
    lines.append("## 二、配置建议")
    lines.append("")
    lines.append(f"- **权益仓位**：约 **{positions['equity']}%**（工程化估算，❌ 推断）")
    lines.append("- **结构/主线**：")
    for t in positions["structure"]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("## 三、风险提示")
    lines.append("")
    lines.append("- 本报告为分析参考，非投资建议；阈值来源标注见 references/decision-rules.md。")
    lines.append("- **观点引用**：须注明'刘胜利（长江证券金融工程）{日期}观点'，机构归属随任职变化。")
    lines.append("- **推断参数**：风格得分阈值 0、分析师因子权重 0.5/0.3/0.2、黄金阈值等均为 ❌ 推断最小假设，非分析师公布值。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 输入契约（对应 decision-rules.md 数据-规则映射附录）
# ----------------------------------------------------------------------------

def schema():
    return {
        "description": "刘胜利（长江金工）input schema —— 调用 python scripts/screen.py --schema 获取",
        "history": {
            "required": [
                {"field": "style_cycle_pos", "description": "价值成长周期位置（正=成长期/负=价值期，S1；三年周期 ✅ 原文）"},
                {"field": "liq_env", "description": "流动性环境（正=宽松，S1；利率/M2 代理 ❌）"},
                {"field": "prosperity_env", "description": "景气度环境（正=高景气，S1；PMI/盈利预期代理 ❌）"},
                {"field": "inst_fund", "description": "机构资金面（正=机构化推进偏大盘，S1；机构增量代理 ❌）"},
                {"field": "cpi_yoy", "description": "CPI 同比 %（S2 消费/周期）"},
                {"field": "retail_yoy", "description": "社会消费品零售同比 %（S2 消费/周期）"},
                {"field": "rate_level", "description": "无风险利率 %（S2 金融/非金融）"},
                {"field": "invest_yoy", "description": "固定资产投资同比 %（S2 金融/非金融）"},
                {"field": "credit_flow", "description": "社融/M2 增速（S2 科技/传统）"},
                {"field": "export_yoy", "description": "出口同比 %（S2 科技/传统）"},
                {"field": "factor_lowrisk", "description": "低风险因子合成值（S3，价格稳定/成交稳定/价值合成）"},
                {"field": "factor_noncycle", "description": "非周期因子合成值（S3，拥挤度/反转合成）"},
                {"field": "factor_highrisk", "description": "高风险因子合成值（S3，成长/动量合成）"},
                {"field": "analyst_surprise", "description": "分析师超预期（S5，一致预期相对年报同比，代理 ❌）"},
                {"field": "analyst_growth", "description": "分析师预期增长（S5，一致预期环比，代理 ❌）"},
                {"field": "analyst_drive", "description": "分析师驱动（S5，首次覆盖后换手维度，代理 ❌）"},
                {"field": "factor_largecap", "description": "大盘因子（S7）"},
                {"field": "factor_growth", "description": "成长因子（S7）"},
                {"field": "factor_crowding", "description": "拥挤度因子（S7，非周期）"},
                {"field": "factor_reversal", "description": "反转因子（S7，非周期）"},
                {"field": "real_rate", "description": "实际利率（S8，名义利率-通胀预期）"},
                {"field": "months", "description": "月份标签数组（升序，最新在末尾，S4 日历效应用）"},
            ],
            "optional": [
                {"field": "margin_ratio", "description": "融资余额占流通市值比例（S1 资金面，占比低=杠杆提升空间）"},
                {"field": "chip_rankic", "description": "筹码因子 RankIC %（S6，研究口径单值或数组）"},
                {"field": "geo_risk", "description": "地缘风险分位 0-100（S8）"},
                {"field": "cb_gold", "description": "央行购金净买入（正=持续，S8）"},
                {"field": "etf_gold", "description": "黄金 ETF 净流入（正=持续，S8）"},
                {"field": "pringle_phase", "description": "普林格周期阶段（1=复苏 2=繁荣 3=滞胀 4=衰退，❌ 编号推断，S8）"},
                {"field": "style_env", "description": "风格环境（S1 输出回填：正=成长环境，S7 用）"},
                {"field": "spring_effect", "description": "春节窗口（1=节前 / -1=节后 / 0=非窗口，S4）"},
                {"field": "national_effect", "description": "国庆窗口（1=国庆前后 / 0=非窗口，S4）"},
            ],
            "format": "字段 -> 月份数组；月份升序，最新值在末尾",
        },
        "extras": {
            "required": [],
            "optional": [
                {"field": "view_note", "description": "当期观点备注（人工口径校准，不参与计算）"},
                {"field": "style_note", "description": "风格判断备注（2026 大盘成长口径，不参与计算）"}
            ],
        },
        "_meta": "可选；记录每个字段的数据来源、口径差异和降级方式（Phase 4 回填）",
    }


# ----------------------------------------------------------------------------
# 演示模式数据（合成）
# ----------------------------------------------------------------------------

def demo_data():
    """生成合成演示数据（36 个月，2023-09 ~ 2026-08，覆盖触发/未触发双路径）。"""
    n = 36
    months = []
    y, m = 2023, 9
    for _ in range(n):
        months.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    def series(base, slope, amp, phase=0.0, clip=None):
        out = []
        for i in range(n):
            v = base + slope * i + amp * _m.sin(i / 4.0 + phase)
            if clip:
                v = max(clip[0], min(clip[1], v))
            out.append(round(v, 3))
        return out

    history = {
        "months": months,
        # S1：周期转成长（三年周期）+ 流动性宽松 + 景气上行 + 机构化 → 大盘成长
        "style_cycle_pos": series(-0.5, 0.03, 0.05),
        "liq_env": series(-0.3, 0.02, 0.06),
        "prosperity_env": series(-0.2, 0.018, 0.05),
        "inst_fund": series(0.1, 0.008, 0.03),
        "margin_ratio": series(9.5, -0.02, 0.2),
        # S2：CPI 低+零售回暖+利率平稳+社融扩张+出口回升 → 周期/科技加分
        "cpi_yoy": series(1.2, -0.015, 0.1, clip=(0.0, 3.0)),
        "retail_yoy": series(3.0, 0.08, 0.3, clip=(0.0, 8.0)),
        "rate_level": series(2.3, -0.01, 0.05, clip=(1.5, 3.0)),
        "invest_yoy": series(3.5, 0.05, 0.2, clip=(0.0, 8.0)),
        "credit_flow": series(9.0, 0.06, 0.3, clip=(5.0, 15.0)),
        "export_yoy": series(2.0, 0.09, 0.4, clip=(-5.0, 10.0)),
        # S3：末段低风险为正、高风险转负（防御态）
        "factor_lowrisk": [0.3 if i >= n - 8 else 0.1 for i in range(n)],
        "factor_noncycle": [0.2 if i >= n - 6 else -0.1 for i in range(n)],
        "factor_highrisk": [-0.4 if i >= n - 8 else 0.3 for i in range(n)],
        # S4：末月 2026-08 = 三四季度降风险窗口
        # S5：分析师超预期/预期增长/驱动末段转正
        "analyst_surprise": series(-0.3, 0.02, 0.05),
        "analyst_growth": series(-0.2, 0.015, 0.04),
        "analyst_drive": series(-0.1, 0.01, 0.03),
        # S6：RankIC 末段回升至有效区
        "chip_rankic": series(3.0, 0.2, 0.5, clip=(0.0, 12.0)),
        # S7：大盘因子为正 + 成长转正 + 拥挤度回落
        "factor_largecap": series(0.1, 0.004, 0.02),
        "factor_growth": series(-0.2, 0.015, 0.03),
        "factor_crowding": series(0.3, -0.015, 0.04),
        "factor_reversal": series(-0.1, 0.01, 0.03),
        # S8：实际利率下行 + 购金持续 + 普林格复苏
        "real_rate": series(1.8, -0.012, 0.06, clip=(0.5, 3.0)),
        "geo_risk": series(45.0, 0.4, 4.0, clip=(10.0, 90.0)),
        "cb_gold": series(20.0, 0.6, 3.0, clip=(0.0, 60.0)),
        "etf_gold": series(10.0, 0.4, 2.0, clip=(-10.0, 40.0)),
        "pringle_phase": [2 if i >= n - 6 else 3 for i in range(n)],
    }
    return {
        "as_of": "2026-08-01",
        "history": history,
        "extras": {
            "view_note": "合成：演示模式（真实观点见 views.md，2026 大盘成长判断）",
            "style_note": "合成：演示模式（2026 年度策略结论：偏大盘成长 ✅ 原文）",
        },
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="刘胜利（长江金工）框架信号计算")
    ap.add_argument("--data", help="数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true", help="输出 JSON 格式结果（布尔标志，JSON 打到 stdout）")
    ap.add_argument("--schema", action="store_true", help="输出输入契约 JSON（布尔标志，JSON 打到 stdout）")
    args = ap.parse_args()

    if args.schema:
        print(json.dumps(schema(), ensure_ascii=False, indent=1))
        return

    if args.data:
        with open(args.data, encoding="utf-8") as f:
            data = json.load(f)
        data["_real"] = True
    else:
        data = demo_data()
        data["_real"] = False

    h = data["history"]
    extras = data.get("extras", {})

    calc_funcs = [calc_s1, calc_s2, calc_s3, calc_s4, calc_s5, calc_s6, calc_s7, calc_s8]
    signals = []
    for fn in calc_funcs:
        try:
            sig = fn(h, extras)
        except Exception as e:
            sig = {"id": fn.__name__, "name": fn.__name__, "triggered": False,
                   "detail": f"计算异常：{e}", "strength": "direction"}
        if sig:
            signals.append(sig)

    n_trig = sum(1 for s in signals if s["triggered"])
    positions = aggregate_signals(signals, h, extras)

    if args.json_out:
        out = {
            "as_of": data.get("as_of"),
            "demo": not data.get("_real", False),
            "n_triggered": n_trig,
            "total": len(signals),
            "signals": signals,
            "positions": positions,
            "extras": extras,
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(render_report(signals, positions, data, n_trig, len(signals)))


if __name__ == "__main__":
    main()
