#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst-fixed-income-zhangjiqiang 信号计算脚本（screen.py）
============================================================
张继强（华泰证券固收首席）债市框架的可执行化实现。
依据：references/decision-rules.md 的 S1-S12 信号表（工程化编号系本技能设计）。

运行方式：
  python screen.py                      # 演示模式（合成数据，仅验证流程）
  python screen.py --data data.json     # 真实数据（字段见 REQUIRED_FIELDS）
  python screen.py --data data.json --json-out   # stdout 输出机器可读 JSON（--json-out 是布尔标志）
  python screen.py --selftest           # 自测：36 个月逐月复算，统计每信号触发覆盖
"""

import argparse
import json
import math as _m
import sys


# ============================================================
# 参数区（来源分级：✅ 原文 / ⚠️ 外推 / ❌ 推断 —— 与 decision-rules.md 图例一致）
# ------------------------------------------------------------
# 规则：所有阈值集中在此，函数体内不散落裸阈值；每条与 decision-rules.md 逐条对应。
# ------------------------------------------------------------
# 规则 3：年度点位区间锚（张继强《蛰伏反击——2026年债市展望》2025-11-03）
RANGE_HIGH = 2.10      # ✅ 原文：2026 年 10Y 国债上限 2.0-2.1%（取上沿 2.1）
RANGE_LOW = 1.60       # ✅ 原文：2026 年 10Y 国债下限 1.6-1.7%（取下沿 1.6）
RANGE_BAND = 0.10      # ✅ 原文动作分档沿用"上限-10BP/下限+10BP"（2026：上沿区≥2.00%、下沿区≤1.70%）
RANGE_MID_H2 = (1.70, 1.90)  # ✅ 原文：2026 下半年核心运行区间 1.70-1.90%（2026.05）
# 规则 1：五碗面计分
SCORE_TRIG = 3         # ❌ 推断：最小假设，可替换——净分 ≥+3 偏多 / ≤-3 偏空（原文未给分档）
# 规则 2：资金面松紧
DR_BAND = 0.10         # ❌ 推断：最小假设，可替换——DR007 相对 OMO 偏离带宽 10BP（月均口径）
SPREAD_FLOOR = 0.0     # ⚠️ 外推：存单-DR007 息差 ≤0 为套息空间压缩（周报常用口径，带宽以原文复核）
# 规则 4：超长端利差
ULTRA_SPREAD = 0.50    # ⚠️ 外推：30-10Y 利差走阔至 50BP 附近做超长端波段（2026.03 方向，以原文复核）
# 规则 6：股债性价比
EQB_PCT_HIGH = 80.0    # ✅ 原文：股息率/10Y 利率 >80% 历史分位 = 全仓股票（华泰资产配置月报回测规则）
EQB_PCT_LOW = 20.0     # ✅ 原文：<20% 分位 = 全仓债券
RANK_WIN = 36          # ❌ 推断：最小假设，可替换——分位滚动窗口 36 个月（原文未公布窗口长度）
# 规则 8：拥挤度
DUR_PCT_HIGH = 80.0    # ❌ 推断：最小假设，可替换——久期处于窗口 80% 分位以上
DISP_PCT_LOW = 20.0    # ❌ 推断：最小假设，可替换——分歧度处于窗口 20% 分位以下
# 规则 7：季节性（月份数字）
SUPPLY_MONTHS = (6, 7, 8)   # ✅ 原文：警惕 6-8 月供给压力共振（2026.05，三季度长债供给高峰）
TURN_MONTHS = (10,)         # ⚠️ 外推：10 月前后变盘风险窗口（周报反复提示，以原文复核）
QUARTER_END = (3, 6, 9, 12) # ⚠️ 外推：季末资金收敛
# ============================================================


REQUIRED_FIELDS = [
    "bond10y", "bond30y", "bond1y", "dr007", "omo7d", "ncd1y",
    "ngdp_yoy", "sf_yoy", "gov_supply", "div_yield_ratio",
]

# 可选字段（缺失时对应信号优雅降级为"缺字段"提示，不阻塞整体计算）：
#   fund_duration / fund_duration_disp —— 债基久期与分歧度（S11，westock 无此数据源）
OPTIONAL_FIELDS = ["fund_duration", "fund_duration_disp"]


# ----------------------------------------------------------------------------
# 工具函数（领域无关，通用实现）
# ----------------------------------------------------------------------------

def pct_rank(series, value):
    """value 在 series 中的百分位（0-100）；None 视为缺失剔除。"""
    s = _clean(series)
    if not s:
        return 50.0
    below = sum(1 for x in s if x < value)
    return below / len(s) * 100.0


def _clean(series):
    """剔除 None（当月数据未发布等），返回有效值序列。"""
    return [x for x in (series or []) if x is not None]


def trend_up(series, lookback=3):
    """最近 lookback 期是否整体上行（末值高于首值）；None 视为缺失剔除。"""
    s = _clean(series)
    if len(s) < 2:
        return False
    win = s[-lookback:]
    return win[-1] > win[0]


def recent_avg(series, lookback=3):
    """最近 lookback 期均值（剔除 None）；序列不足时取全部有效值。"""
    s = _clean(series)
    if not s:
        return 0.0
    win = s[-lookback:]
    return sum(win) / len(win)


def missing(h, fields):
    return [f for f in fields if f not in h or not h[f]]


def get(h, field):
    """取字段最近一个有效值（当月未发布则回溯上月）；全缺失返回 None。"""
    if field not in h or not h[field]:
        return None
    s = _clean(h[field])
    return s[-1] if s else None


# ----------------------------------------------------------------------------
# 信号计算函数（契约：输入 h / extras → 返回 dict：id/name/triggered/detail/strength）
# ----------------------------------------------------------------------------

def bowl_score(h, extras):
    """规则 1：五碗面净分（-5 至 +5）。利多债市 +1 / 利空 -1 / 中性 0。

    权重 ❌ 推断：等权（最小假设，可替换；"货币政策是所有债券分析的核心"✅原文，
    如需突出可设政策面权重 2 倍）。
    """
    items = []
    # 1) 基本面：名义 GDP + 社融方向（回落利多债市）
    ngdp, sf = h.get("ngdp_yoy", []), h.get("sf_yoy", [])
    fundamental = 0
    if ngdp:
        fundamental += -1 if trend_up(ngdp) else (1 if trend_down(ngdp) else 0)
    if sf:
        fundamental += -1 if trend_up(sf) else (1 if trend_down(sf) else 0)
    fundamental = max(-1, min(1, fundamental))
    items.append(("基本面", fundamental))
    # 2) 政策面：货币政策取向 + 央行预期管理
    stance = (extras or {}).get("policy_stance", "neutral")
    policy = {"supportive": 1, "neutral": 0, "multi_goal": 0, "hawkish": -1}.get(stance, 0)
    if (extras or {}).get("cb_guidance"):
        policy -= 1
    policy = max(-1, min(1, policy))
    items.append(("政策面", policy))
    # 3) 资金面：DR007 vs OMO
    dr, omo = get(h, "dr007"), get(h, "omo7d")
    liquidity = 0
    if dr is not None and omo is not None:
        if dr > omo + DR_BAND:
            liquidity = -1
        elif dr < omo - DR_BAND:
            liquidity = 1
    items.append(("资金面", liquidity))
    # 4) 供求面：资产荒状态 + 政府债供给放量
    shortage = (extras or {}).get("asset_shortage", "none")
    supply = {"full": 1, "structural": 0, "weakening": 0, "none": -1}.get(shortage, 0)
    gs = h.get("gov_supply", [])
    if gs and len(gs) >= 6:
        if recent_avg(gs, 3) > recent_avg(gs, 12) * 1.3:  # ❌ 推断：近 3 月均值超 12 月均值 1.3 倍 = 供给放量
            supply = max(-1, supply - 1)
    items.append(("供求面", supply))
    # 5) 情绪估值：10Y 在年度区间中的位置（高于中枢 = 债券便宜 = 利多）
    y10 = get(h, "bond10y")
    valuation = 0
    if y10 is not None:
        mid = (RANGE_LOW + RANGE_HIGH) / 2.0
        if y10 > mid:
            valuation = 1
        elif y10 < mid:
            valuation = -1
    items.append(("情绪估值", valuation))
    net = sum(v for _, v in items)
    return net, items


def trend_down(series, lookback=3):
    """最近 lookback 期是否整体下行（末值低于首值）；None 视为缺失剔除。"""
    s = _clean(series)
    if len(s) < 2:
        return False
    win = s[-lookback:]
    return win[-1] < win[0]


def calc_s1(h, extras=None):
    """S1 五碗面净分 ≥ +3 → 偏多，持有偏长久期。"""
    ms = missing(h, REQUIRED_FIELDS)
    if ms:
        return {"id": "S1", "name": "五碗面偏多", "triggered": False,
                "detail": f"缺字段：{', '.join(ms)}", "strength": "direction"}
    net, items = bowl_score(h, extras)
    trig = net >= SCORE_TRIG
    detail = " + ".join(f"{k}{v:+d}" for k, v in items)
    return {"id": "S1", "name": "五碗面偏多", "triggered": trig,
            "detail": f"五碗面净分 {net:+d}（{detail}）vs 阈值 ≥+{SCORE_TRIG} → {'触发：持有偏长久期' if trig else '未触发'}",
            "strength": "strong"}


def calc_s2(h, extras=None):
    """S2 五碗面净分 ≤ -3 → 偏空，缩短久期防守。"""
    ms = missing(h, REQUIRED_FIELDS)
    if ms:
        return {"id": "S2", "name": "五碗面偏空", "triggered": False,
                "detail": f"缺字段：{', '.join(ms)}", "strength": "direction"}
    net, items = bowl_score(h, extras)
    trig = net <= -SCORE_TRIG
    detail = " + ".join(f"{k}{v:+d}" for k, v in items)
    return {"id": "S2", "name": "五碗面偏空", "triggered": trig,
            "detail": f"五碗面净分 {net:+d}（{detail}）vs 阈值 ≤-{SCORE_TRIG} → {'触发：缩短久期、防守' if trig else '未触发'}",
            "strength": "strong"}


def calc_s3(h, extras=None):
    """S3 10Y ≥ 年度区间上限-10BP（2026：≥2.00%）→ 配置盘进场，拉长久期。"""
    y10 = get(h, "bond10y")
    if y10 is None:
        return {"id": "S3", "name": "区间上沿配置", "triggered": False,
                "detail": "缺字段 bond10y", "strength": "direction"}
    th = RANGE_HIGH - RANGE_BAND
    trig = y10 >= th
    return {"id": "S3", "name": "区间上沿配置", "triggered": trig,
            "detail": f"10Y 国债 {y10:.2f}% vs 上沿阈值 {th:.2f}%（区间 {RANGE_LOW:.2f}-{RANGE_HIGH:.2f}%，✅2026年度策略） → {'触发：配置盘进场、拉长久期' if trig else '未触发'}",
            "strength": "strong"}


def calc_s4(h, extras=None):
    """S4 10Y ≤ 年度区间下限+10BP（2026：≤1.70%）→ 止盈，缩短久期。"""
    y10 = get(h, "bond10y")
    if y10 is None:
        return {"id": "S4", "name": "区间下沿止盈", "triggered": False,
                "detail": "缺字段 bond10y", "strength": "direction"}
    th = RANGE_LOW + RANGE_BAND
    trig = y10 <= th
    return {"id": "S4", "name": "区间下沿止盈", "triggered": trig,
            "detail": f"10Y 国债 {y10:.2f}% vs 下沿阈值 {th:.2f}%（1.70% 为历史极值低位，✅2026.05） → {'触发：止盈、缩短久期' if trig else '未触发'}",
            "strength": "strong"}


def calc_s5(h, extras=None):
    """S5 资金面收敛：DR007 高于 OMO+带宽 或 存单-DR007 息差≤0 → 降杠杆。"""
    dr, omo, ncd = get(h, "dr007"), get(h, "omo7d"), get(h, "ncd1y")
    if dr is None or omo is None or ncd is None:
        return {"id": "S5", "name": "资金面收敛", "triggered": False,
                "detail": "缺字段 dr007/omo7d/ncd1y", "strength": "direction"}
    cond1 = dr > omo + DR_BAND
    spread = ncd - dr
    cond2 = spread <= SPREAD_FLOOR
    trig = cond1 or cond2
    reasons = []
    if cond1:
        reasons.append(f"DR007 {dr:.2f}% 高于 OMO {omo:.2f}%+{DR_BAND:.2f}% 带宽")
    if cond2:
        reasons.append(f"存单-DR007 息差 {spread * 100:.0f}BP ≤ {SPREAD_FLOOR * 100:.0f}BP")
    return {"id": "S5", "name": "资金面收敛", "triggered": trig,
            "detail": (f"{'；'.join(reasons)} → 触发：降杠杆" if trig
                       else f"DR007 {dr:.2f}% vs OMO {omo:.2f}%，息差 {spread * 100:.0f}BP → 未触发（资金面平稳）"),
            "strength": "mid"}


def calc_s6(h, extras=None):
    """S6 30-10Y 超长端利差 ≥50BP → 超长端波段机会。"""
    y30, y10 = get(h, "bond30y"), get(h, "bond10y")
    if y30 is None or y10 is None:
        return {"id": "S6", "name": "超长端波段", "triggered": False,
                "detail": "缺字段 bond30y/bond10y", "strength": "direction"}
    spread = y30 - y10
    trig = spread >= ULTRA_SPREAD
    return {"id": "S6", "name": "超长端波段", "triggered": trig,
            "detail": f"30-10Y 利差 {spread * 100:.0f}BP vs 阈值 {ULTRA_SPREAD * 100:.0f}BP（⚠️2026.03 方向） → {'触发：超长端波段机会（只做不重仓，需配合供给节奏）' if trig else '未触发'}",
            "strength": "mid"}


def _eqb_rank(h):
    ratio = h.get("div_yield_ratio", [])
    if len(ratio) < 2:
        return None, None
    win = ratio[-RANK_WIN:]
    latest = win[-1]
    return latest, pct_rank(win[:-1] if len(win) > 1 else win, latest)


def calc_s7(h, extras=None):
    """S7 股债性价比 <20% 分位 → 债券极贵（原回测规则：全仓债券）。"""
    latest, rank = _eqb_rank(h)
    if latest is None:
        return {"id": "S7", "name": "股债性价比·债贵", "triggered": False,
                "detail": "缺字段 div_yield_ratio", "strength": "direction"}
    trig = rank < EQB_PCT_LOW
    return {"id": "S7", "name": "股债性价比·债贵", "triggered": trig,
            "detail": f"股息率/10Y 比值 {latest:.2f}，分位 {rank:.0f}% vs 阈值 <{EQB_PCT_LOW:.0f}%（✅原文回测规则） → {'触发：债券性价比透支（激进档全仓债券）' if trig else '未触发'}",
            "strength": "strong"}


def calc_s8(h, extras=None):
    """S8 股债性价比 >80% 分位 → 股票极便宜（原回测规则：全仓股票，实务提权益暴露）。"""
    latest, rank = _eqb_rank(h)
    if latest is None:
        return {"id": "S8", "name": "股债性价比·股便宜", "triggered": False,
                "detail": "缺字段 div_yield_ratio", "strength": "direction"}
    trig = rank > EQB_PCT_HIGH
    return {"id": "S8", "name": "股债性价比·股便宜", "triggered": trig,
            "detail": f"股息率/10Y 比值 {latest:.2f}，分位 {rank:.0f}% vs 阈值 >{EQB_PCT_HIGH:.0f}%（✅原文回测规则） → {'触发：提高权益+转债暴露（激进档全仓股票）' if trig else '未触发'}",
            "strength": "strong"}


def calc_s9(h, extras=None, month=None):
    """S9 季节性/供给高峰窗口：6-8 月供给共振、10 月变盘、季末资金收敛 → 防波动。"""
    if month is None:
        return {"id": "S9", "name": "季节性窗口", "triggered": False,
                "detail": "缺月份信息（由 as_of 推断）", "strength": "direction"}
    reasons = []
    if month in SUPPLY_MONTHS:
        reasons.append(f"{month} 月为政府债供给高峰共振窗口（✅2026.05 警惕 6-8 月）")
    if month in TURN_MONTHS:
        reasons.append("10 月前后变盘风险窗口（⚠️周报反复提示）")
    if month in QUARTER_END:
        reasons.append("季末资金收敛时点（⚠️）")
    trig = bool(reasons)
    return {"id": "S9", "name": "季节性窗口", "triggered": trig,
            "detail": (f"{'；'.join(reasons)} → 触发：暂缓加仓、防波动" if trig else f"{month} 月无季节性风险窗口 → 未触发"),
            "strength": "direction"}


def calc_s10(h, extras=None):
    """S10 政策拐点：货币政策目标切换/央行预期管理发声 → 降久期、控杠杆。"""
    ex = extras or {}
    reasons = []
    if ex.get("policy_stance") == "multi_goal":
        reasons.append("货币政策目标切换为稳增长/防通胀/防空转多目标平衡（✅2026.05）")
    if ex.get("policy_stance") == "hawkish":
        reasons.append("货币政策取向收紧")
    if ex.get("cb_guidance"):
        reasons.append("央行就长债利率风险发声/预期管理（✅2024 多次）")
    trig = bool(reasons)
    return {"id": "S10", "name": "政策拐点", "triggered": trig,
            "detail": (f"{'；'.join(reasons)} → 触发：降久期、控杠杆（政策面定拐点 ✅）" if trig else "政策取向平稳 → 未触发"),
            "strength": "mid"}


def calc_s11(h, extras=None):
    """S11 交易拥挤：久期高分位 + 分歧度低分位 → 防负反馈。"""
    dur, disp = h.get("fund_duration", []), h.get("fund_duration_disp", [])
    if not dur or not disp:
        return {"id": "S11", "name": "交易拥挤", "triggered": False,
                "detail": "缺字段 fund_duration/fund_duration_disp", "strength": "direction"}
    wd, ws = dur[-RANK_WIN:], disp[-RANK_WIN:]
    d_rank = pct_rank(wd[:-1] if len(wd) > 1 else wd, wd[-1])
    s_rank = pct_rank(ws[:-1] if len(ws) > 1 else ws, ws[-1])
    trig = d_rank >= DUR_PCT_HIGH and s_rank <= DISP_PCT_LOW
    return {"id": "S11", "name": "交易拥挤", "triggered": trig,
            "detail": (f"债基久期 {wd[-1]:.1f} 年（{d_rank:.0f}% 分位，阈值≥{DUR_PCT_HIGH:.0f}%）+ 分歧度 {ws[-1]:.2f}（{s_rank:.0f}% 分位，阈值≤{DISP_PCT_LOW:.0f}%） → {'触发：降杠杆、增流动性好的品种，防负反馈' if trig else '未触发'}（❌分位阈值系推断）"),
            "strength": "mid"}


def calc_s12(h, extras=None):
    """S12 市场生态状态机：≥2 项确认进入"低利率+高波动"→ 切换策略排序。"""
    ex = extras or {}
    conds = []
    ngdp = h.get("ngdp_yoy", [])
    c1 = trend_up(ngdp)
    conds.append(("名义GDP回升", c1))
    c2 = ex.get("asset_shortage") in ("structural", "weakening", "none")
    conds.append(("资产荒弱化/结构化", c2))
    y10 = get(h, "bond10y")
    c3 = y10 is not None and (RANGE_LOW + 0.05) <= y10 <= (RANGE_HIGH - 0.05)
    conds.append(("区间有底有顶", c3))
    n_ok = sum(1 for _, ok in conds if ok)
    trig = n_ok >= 2
    detail = " + ".join(f"{k}{'✓' if ok else '✗'}" for k, ok in conds)
    return {"id": "S12", "name": "低利率高波动生态", "triggered": trig,
            "detail": (f"{detail}（{n_ok}/3，阈值≥2 ❌推断） → " +
                       ("触发：套用 2026 策略排序——波段操作+票息策略+权益暴露 > 品种选择 > 久期调节+杠杆 > 信用下沉（✅原文）" if trig
                        else "未触发：沿用上一生态的策略排序")),
            "strength": "strong"}


# ----------------------------------------------------------------------------
# 信号汇总 → 久期/杠杆/品种/股债配置建议（❌ 工程化设计，动作映射依据 decision-rules.md）
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    trig = {s["id"]: s for s in signals if s["triggered"]}
    strong = [s["id"] for s in signals if s["triggered"] and s.get("strength") == "strong"]
    mid = [s["id"] for s in signals if s["triggered"] and s.get("strength") == "mid"]
    weak = [s["id"] for s in signals if s["triggered"] and s.get("strength") == "direction"]

    # 久期评分（-5 至 +5）：S3 加久期、S4 减久期、S1 加、S2 减、S10 减
    dur_score = 0
    for sid, w in (("S3", +2), ("S1", +2), ("S4", -2), ("S2", -2), ("S10", -1)):
        if sid in trig:
            dur_score += w
    if dur_score >= 2:
        duration = "拉长久期（区间上沿/五碗面偏多，配置盘进场逻辑）"
    elif dur_score <= -2:
        duration = "缩短久期（区间下沿止盈/五碗面偏空/政策拐点）"
    else:
        duration = "中性久期（区间内震荡，票息+波段为主）"

    # 杠杆评分：S5/S11/S9 均指向降杠杆
    lev_hits = [s for s in ("S5", "S11", "S9") if s in trig]
    leverage = "降杠杆" if len(lev_hits) >= 2 else ("谨慎加杠杆（资金面平稳且不拥挤时）" if not lev_hits else "维持中性杠杆")

    # 曲线与品种
    curve = []
    if "S6" in trig:
        curve.append("30-10Y 利差走阔至阈值上方：超长端波段（只做不重仓）")
    if "S12" in trig:
        curve.append("低利率+高波动生态：曲线陡峭化趋势，短端确定性更高（✅原文）")
        curve.append("策略排序：波段+票息+权益暴露 > 品种 > 久期+杠杆 > 下沉（✅2026年度策略）")
    if not curve:
        curve.append("曲线与品种：维持现状，无极值信号")

    # 股债配置
    eqb = "股债均衡"
    if "S8" in trig:
        eqb = "债券性价比透支，提高权益+转债暴露（原文激进档：全仓股票）"
    elif "S7" in trig:
        eqb = "股票性价比透支，债券占优（原文激进档：全仓债券）"

    return {
        "久期": duration,
        "杠杆": leverage,
        "曲线与品种": curve,
        "股债配置": eqb,
        "strong_triggered": strong,
        "mid_triggered": mid,
        "weak_triggered": weak,
    }


# ----------------------------------------------------------------------------
# 报告渲染（领域无关骨架）
# ----------------------------------------------------------------------------

def render_report(signals, positions, data, n_triggered, total):
    as_of = data.get("as_of", "N/A")
    demo = not bool(data.get("_real", False))
    lines = []
    lines.append(f"# 张继强（华泰固收）框架 · 债市信号报告（截至 {as_of}）")
    if demo:
        lines.append("> ⚠️ 数据来源：**演示模式（合成数据）**，仅用于验证流程，非真实数据。请用 --data 传入真实数据。")
    lines.append("")
    lines.append(f"## 一、信号汇总（触发 {n_triggered}/{total}）")
    lines.append("")
    lines.append("| 信号 | 名称 | 状态 | 读数与动作 |")
    lines.append("|---|---|---|---|")
    for s in signals:
        status = "🔴 触发" if s["triggered"] else "—"
        lines.append(f"| {s['id']} | {s['name']} | {status} | {s['detail']} |")
    lines.append("")
    lines.append("## 二、配置建议")
    lines.append("")
    lines.append(f"- **久期**：{positions['久期']}（工程化估算，❌推断）")
    lines.append(f"- **杠杆**：{positions['杠杆']}（工程化估算，❌推断）")
    lines.append("- **曲线与品种**：")
    for t in positions["曲线与品种"]:
        lines.append(f"  - {t}")
    lines.append(f"- **股债配置**：{positions['股债配置']}")
    lines.append("")
    lines.append("## 三、风险提示")
    lines.append("")
    lines.append("- 本报告为分析参考，非投资建议；阈值来源标注见 references/decision-rules.md。")
    lines.append("- **区间锚逐年更新**：年度点位区间随新年度策略发布强制更新（2026：1.6-2.1%）。")
    lines.append("- **观点引用**：须注明'张继强（华泰证券）{日期}观点'，机构归属随任职变化。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 演示模式数据（合成，字段 = decision-rules.md 数据-规则映射附录）
# ----------------------------------------------------------------------------

def demo_data():
    """合成演示数据（36 个月，2023-09 至 2026-08）。

    形态参考真实走势（利率中枢逐年下移后 2026 年回升）但数值全部为合成——
    仅用于验证信号触发路径，不代表任何真实读数。
    """
    n = 36
    months = []
    y, m = 2023, 9
    for i in range(n):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    def curve(start, mid, mid_idx, end):
        """三段折线 + 轻微波动。"""
        out = []
        for i in range(n):
            if i <= mid_idx:
                v = start + (mid - start) * i / max(mid_idx, 1)
            else:
                v = mid + (end - mid) * (i - mid_idx) / max(n - 1 - mid_idx, 1)
            out.append(round(v + 0.02 * _m.sin(i / 3), 3))
        return out

    history = {
        # 利率（%）：2023-09 高位 → 2025 末低位 → 2026 回升至上沿
        "bond10y": curve(2.65, 1.62, 26, 2.02),
        "bond30y": curve(3.05, 1.95, 26, 2.54),
        "bond1y": curve(2.10, 0.95, 26, 1.45),
        # 资金面（%）：OMO 两轮下调；DR007 末端高于 OMO（资金收敛）
        "omo7d": [1.9] * 12 + [1.7] * 12 + [1.4] * 12,
        "dr007": curve(1.95, 1.55, 26, 1.62),
        "ncd1y": curve(2.35, 1.55, 26, 1.78),
        # 基本面（%）：名义 GDP 先落底后回升
        "ngdp_yoy": curve(4.8, 3.9, 20, 4.7),
        "sf_yoy": curve(9.2, 7.6, 20, 8.1),
        # 供给（万亿/月）：常态 0.8，三季度高峰脉冲
        "gov_supply": [round(0.6 + 0.5 * _m.sin(i / 5) + (0.7 if 28 <= i <= 30 else 0.0), 2) for i in range(n)],
        # 股债性价比（股息率/10Y 比值）：先升（10Y 下行更快）后快速回落（权益大涨压低股息率）
        "div_yield_ratio": curve(0.95, 1.70, 26, 1.02),
        # 情绪：久期拉长、分歧度压缩（拥挤）
        "fund_duration": curve(2.1, 3.0, 26, 3.4),
        "fund_duration_disp": curve(0.75, 0.35, 26, 0.18),
    }
    return {
        "as_of": f"{months[-1][0]}-{months[-1][1]:02d}-01",
        "history": history,
        "extras": {
            "policy_stance": "multi_goal",   # 货币政策多目标平衡（2026.05 ✅）
            "cb_guidance": True,             # 当月有央行预期管理发声（合成）
            "asset_shortage": "none",        # 资产荒弱化（2026 ✅方向，取值合成）
            "eco_stage": "II->III",          # 新旧动能 II→III 过渡期（✅2026.05）
        },
    }


# ----------------------------------------------------------------------------
# 自测：逐月复算，统计每信号触发覆盖（交付前必须每信号至少触发一次）
# ----------------------------------------------------------------------------

def selftest():
    data = demo_data()
    h = data["history"]
    extras = data["extras"]
    funcs = [calc_s1, calc_s2, calc_s3, calc_s4, calc_s5, calc_s6,
             calc_s7, calc_s8, calc_s10, calc_s11, calc_s12]
    coverage = {f.__name__: 0 for f in funcs}
    coverage["calc_s9"] = 0
    # 按月切片复算（history 为"字段→月份数组"转置结构，最新在末尾）。
    # extras 随窗口演化（⚠️ 按叙事推断）：早期政策支持性+资产荒全面 → 晚期多目标+资产荒弱化。
    def extras_at(idx):
        return {
            "policy_stance": "supportive" if idx <= 24 else "multi_goal",
            "cb_guidance": idx >= 27,
            "asset_shortage": "full" if idx <= 14 else ("structural" if idx <= 26 else "none"),
            "eco_stage": "II->III",
        }
    for idx in range(6, len(h["bond10y"]) + 1):
        h_slice = {k: v[:idx] for k, v in h.items()}
        extras = extras_at(idx)
        for fn in funcs:
            try:
                sig = fn(h_slice, extras)
                if sig["triggered"]:
                    coverage[fn.__name__] += 1
            except Exception:
                pass
        try:
            sig = calc_s9(h_slice, extras, month=((7 + idx) % 12) + 1)
            if sig["triggered"]:
                coverage["calc_s9"] += 1
        except Exception:
            pass
    print("== selftest：36 个月逐月复算，每信号触发次数（交付要求：全部 >0）==")
    all_ok = True
    for k, v in coverage.items():
        ok = "✅" if v > 0 else "❌"
        if v == 0:
            all_ok = False
        print(f"  {k}: {v} 次 {ok}")
    print("结果：", "全部信号覆盖触发路径" if all_ok else "存在未覆盖信号，需修 demo 数据")
    return 0 if all_ok else 1


# ----------------------------------------------------------------------------
# 主流程（领域无关，通用实现）
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="张继强（华泰固收）框架债市信号计算")
    ap.add_argument("--data", help="数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true", help="输出 JSON 格式结果（布尔标志，JSON 打到 stdout）")
    ap.add_argument("--selftest", action="store_true", help="自测：逐月复算统计信号触发覆盖")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if args.data:
        with open(args.data, encoding="utf-8") as f:
            data = json.load(f)
        data["_real"] = True
        h = data.get("history", {})
        ms = missing(h, REQUIRED_FIELDS)
        if ms:
            print(f"[数据校验错误] 缺少必需字段：{', '.join(ms)}", file=sys.stderr)
            print(f"必需字段清单：{REQUIRED_FIELDS}", file=sys.stderr)
            sys.exit(2)
    else:
        data = demo_data()
        data["_real"] = False
        h = data["history"]

    extras = data.get("extras", {})
    # 月份（季节性信号用）
    month = None
    as_of = data.get("as_of", "")
    if as_of and "-" in as_of:
        try:
            month = int(as_of.split("-")[1])
        except (ValueError, IndexError):
            month = None

    calc_funcs = [calc_s1, calc_s2, calc_s3, calc_s4, calc_s5, calc_s6,
                  calc_s7, calc_s8]
    signals = []
    for fn in calc_funcs:
        try:
            signals.append(fn(h, extras))
        except Exception as e:
            signals.append({"id": fn.__name__, "name": fn.__name__, "triggered": False,
                            "detail": f"计算异常：{e}", "strength": "direction"})
    try:
        signals.append(calc_s9(h, extras, month=month))
    except Exception as e:
        signals.append({"id": "S9", "name": "季节性窗口", "triggered": False,
                        "detail": f"计算异常：{e}", "strength": "direction"})
    for fn in (calc_s10, calc_s11, calc_s12):
        try:
            signals.append(fn(h, extras))
        except Exception as e:
            signals.append({"id": fn.__name__, "name": fn.__name__, "triggered": False,
                            "detail": f"计算异常：{e}", "strength": "direction"})

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
