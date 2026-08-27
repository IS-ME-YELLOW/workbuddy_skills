#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘富兵（国盛证券金工首席）信号计算脚本 —— screen.py
============================================================
依据 references/decision-rules.md 实现 S1-S10 信号。
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
# S1 价格分段择时
MA_FAST, MA_MID, MA_SLOW = 30, 120, 250  # ❌ 推断：均线窗口代理 30分钟/日线/周线级别，最小假设可替换
WAVE_EARLY, WAVE_LATE = 3, 7              # ⚠️ 外推：浪 1-3 趋势早期、≥7 临近尾声（原文案例归纳）
END_PROB_HI = 80.0                        # ❌ 推断：结束概率高于此=拐点临近，最小假设可替换
END_PROB_LO = 20.0                        # ❌ 推断：结束概率低于此=趋势延续，最小假设可替换
# S2 择时雷达六面图
RADAR_BIAS_POS = 0.2                      # ❌ 推断：综合分 >0.2 看多（原文区间 [-1,1]，分档阈值推断）
RADAR_BIAS_NEG = -0.2                     # ❌ 推断：综合分 <-0.2 看空
# S3 LPPL 极端拐点
LP_DEV_MA = 12                            # ❌ 推断：偏离 12 月均线倍数代理 LPPLS 拟合强度
LP_DEV_POS = 15.0                         # ❌ 推断：偏离 >+15% 正泡沫见顶预警
LP_DEV_NEG = -15.0                        # ❌ 推断：偏离 <-15% 负泡沫抄底参照
# S4 宏观六周期偏离
CYCLE_DEV_MIN = 2                         # ❌ 推断：隐含滞后真实周期 ≥2 档=高偏离
# S6 GK 预期收益与 ERP
ERP_Q_HI = 80.0                           # ❌ 推断：ERP 分位 >80% 高性价比超配
ERP_Q_LO = 20.0                           # ❌ 推断：ERP 分位 <20% 低性价比减配
# S7 行业轮动
IND_TREND_Z = 0.5                         # ❌ 推断：趋势 z>0.5 强趋势
IND_CROWD_HI = 50.0                       # ❌ 推断：拥挤度分位 <50 低拥挤
# S8 行业 RS 年度主线
RS_TH = 90.0                              # ✅ 原文：RS>90 = 年度主线候选（《如何寻找当年的领涨行业》）
# S10 转债定价偏离度轮动
CB_Z_TAIL = 1.5                           # ✅ 原文：偏离度 Z 值 ±1.5σ 截尾
CB_W_BASE = 50.0                          # ✅ 原文：转债权重 = 50% + 50%×分数
# 仓位工程化（❌ 推断：分析师未公布仓位映射，最小假设可替换）
POS_BASE = 55.0
POS_S1_BULL = 8.0
POS_S1_BEAR = -10.0
POS_S3_NEG = 6.0
POS_S3_POS = -6.0
POS_S4_BULL = 5.0
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


def _ma(series, window):
    """简单移动平均；窗口不足时返回 None。"""
    c = _clean(series)
    if len(c) < window:
        return None
    return sum(c[-window:]) / window


def _count_waves(series, window=12):
    """浪结构计数代理：近 window 月内价格运行方向切换次数+1（❌ 推断）。"""
    c = _clean(series)
    if len(c) < 3:
        return 1
    win = c[-window:]
    switches = 0
    for i in range(2, len(win)):
        if (win[i] - win[i - 1]) * (win[i - 1] - win[i - 2]) < 0:
            switches += 1
    return switches + 1


# ----------------------------------------------------------------------------
# 信号计算函数（契约：输入 h / extras → 返回 dict）
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 价格分段择时：级别确认（30/120/250 均线代理）+ 浪结构位置 → 趋势状态。"""
    px = h.get("hs300_close") or h.get("zz500_close") or h.get("zz1000_close") or h.get("cyb_close")
    if not px or not _clean(px):
        return {"id": "S1", "name": "价格分段择时", "triggered": False,
                "detail": "缺指数价格字段（hs300_close/zz500_close/zz1000_close/cyb_close）", "strength": "direction"}
    c = _clean(px)
    ma_f, ma_m, ma_s = _ma(c, MA_FAST), _ma(c, MA_MID), _ma(c, MA_SLOW)
    if None in (ma_f, ma_m, ma_s):
        return {"id": "S1", "name": "价格分段择时", "triggered": False,
                "detail": f"均线样本不足（需 ≥{MA_SLOW} 期）", "strength": "direction"}
    last = c[-1]
    bull = last > ma_f > ma_m > ma_s          # 多头排列 = 上涨级别（❌ 推断实现）
    bear = last < ma_f < ma_m < ma_s          # 空头排列 = 下跌级别（❌ 推断实现）
    waves = _count_waves(c)
    if bull:
        if waves <= WAVE_EARLY:
            trig, level, strength = True, f"日线级别上涨确认，仅 {waves} 浪 → 趋势早期，结束概率低（✅ 原文<15% 案例）", "strong"
        elif waves >= WAVE_LATE:
            trig, level, strength = True, f"日线上涨已走 {waves} 浪（≥{WAVE_LATE}）→ 临近尾声（⚠️ 原文案例归纳）", "mid"
        else:
            trig, level, strength = True, f"日线上涨确认，{waves} 浪 → 趋势延续", "mid"
    elif bear:
        trig, level, strength = True, f"日线级别下跌确认（{waves} 浪）→ 短暂反抽后大概率再探底（✅ 2026-07 案例）", "strong"
    else:
        trig, level, strength = False, "均线纠缠，级别未确认 → 中性", "direction"
    return {"id": "S1", "name": "价格分段择时", "triggered": trig,
            "detail": f"30/120/250 均线 {ma_f:.0f}/{ma_m:.0f}/{ma_s:.0f}，浪数 {waves} → {level}", "strength": strength}


def calc_s2(h, extras=None):
    """S2 择时雷达六面图：六维度子信号等权合成综合分（[-1,1]）→ 分档。"""
    fields = ["liq_dir", "cred_dir", "growth_dir", "infl_dir", "shiller_erp", "pb", "aiae",
              "margin_flow", "amount_trend", "cds_cn", "risk_aversion", "option_prem", "vix", "skew", "cb_dev"]
    present = [f for f in fields if h.get(f) and _clean(h[f])]
    if len(present) < 5:
        return {"id": "S2", "name": "择时雷达六面图", "triggered": False,
                "detail": f"六面图子信号不足（需 ≥5 项，现有 {len(present)}）", "strength": "direction"}
    scores = []
    for f in present:
        v = _clean(h[f])[-1]
        scores.append(1.0 if v > 0 else (-1.0 if v < 0 else 0.0))  # ❌ 赋分推断：看多=+1/中性=0/看空=-1
    comp = sum(scores) / len(scores)
    if comp > RADAR_BIAS_POS:
        trig, level, strength = True, "看多（六面图综合分为正）", "mid"
    elif comp < RADAR_BIAS_NEG:
        trig, level, strength = True, "看空（六面图综合分为负）", "mid"
    else:
        trig, level, strength = False, "中性（六面图综合分接近 0，参考 2026-08=-0.12 案例）", "direction"
    return {"id": "S2", "name": "择时雷达六面图", "triggered": trig,
            "detail": f"六面图综合分 {comp:+.2f}（阈值 ±{RADAR_BIAS_POS:.1f}；参与子信号 {len(present)} 项）→ {level}",
            "strength": strength}


def calc_s3(h, extras=None):
    """S3 LPPL 极端拐点：价格偏离 12 月均线百分比 → 正/负泡沫。"""
    px = h.get("hs300_close") or h.get("zz500_close") or h.get("zz1000_close") or h.get("cyb_close")
    if not px or not _clean(px):
        return {"id": "S3", "name": "LPPL 极端拐点", "triggered": False,
                "detail": "缺指数价格字段", "strength": "direction"}
    c = _clean(px)
    ma = _ma(c, LP_DEV_MA)
    if ma is None or ma == 0:
        return {"id": "S3", "name": "LPPL 极端拐点", "triggered": False,
                "detail": f"12 月均线样本不足（需 ≥{LP_DEV_MA} 期）", "strength": "direction"}
    dev = (c[-1] - ma) / ma * 100.0
    if dev > LP_DEV_POS:
        trig, level, strength = True, "正泡沫预警 → 减仓锁定（LPPL 见顶信号）", "mid"
    elif dev < LP_DEV_NEG:
        trig, level, strength = True, "负泡沫触发 → 分批抄底参照（LPPL 抄底信号）", "mid"
    else:
        trig, level, strength = False, "无极端偏离，LPPL 无信号", "direction"
    return {"id": "S3", "name": "LPPL 极端拐点", "triggered": trig,
            "detail": f"价格偏离 12 月均线 {dev:+.1f}%（阈值 ±{LP_DEV_POS:.0f}%）→ {level}", "strength": strength}


def calc_s4(h, extras=None):
    """S4 宏观六周期偏离：隐含周期 vs 真实周期偏离 → 风险资产信号。"""
    if not h.get("cycle_real") or not h.get("cycle_implied"):
        return {"id": "S4", "name": "宏观六周期偏离", "triggered": False,
                "detail": "缺字段 cycle_real / cycle_implied（阶段 1-6）", "strength": "direction"}
    cr, ci = h["cycle_real"][-1], h["cycle_implied"][-1]
    dev = ci - cr
    if dev <= -CYCLE_DEV_MIN:
        trig, level, strength = True, "隐含周期大幅滞后真实周期（预期收缩+高偏离）→ 看多风险资产（✅ 2026-07-17 案例）", "mid"
    elif abs(dev) < CYCLE_DEV_MIN:
        trig, level, strength = False, "周期偏离小 → 中性偏空（✅ 2026-07-03 案例）", "direction"
    else:
        trig, level, strength = False, "隐含周期领先真实周期 → 中性", "direction"
    return {"id": "S4", "name": "宏观六周期偏离", "triggered": trig,
            "detail": f"真实周期 {cr} / 隐含周期 {ci}（偏离 {dev:+d} 档，阈值 |偏离|≥{CYCLE_DEV_MIN:.0f}）→ {level}",
            "strength": strength}


def calc_s5(h, extras=None):
    """S5 A股景气与情绪指数：景气 26 周趋势 + 情绪综合信号。"""
    if not h.get("a_share_prosperity") or not _clean(h["a_share_prosperity"]):
        return {"id": "S5", "name": "A股景气与情绪", "triggered": False,
                "detail": "缺字段 a_share_prosperity（A股景气指数）", "strength": "direction"}
    pros = _clean(h["a_share_prosperity"])
    pros_up = trend_up(pros, lookback=6)
    sent = h.get("a_share_sentiment") or 0.0
    sent_val = sent if isinstance(sent, (int, float)) else 0.0
    if pros_up and sent_val > 0:
        trig, level, strength = True, "景气向上+情绪综合多 → 强顺风（✅ 2025-11 景气 20.91 抬升案例）", "mid"
    elif not pros_up and sent_val < 0:
        trig, level, strength = True, "景气向下+情绪综合空 → 逆风", "mid"
    else:
        trig, level, strength = False, "景气/情绪信号中性", "direction"
    return {"id": "S5", "name": "A股景气与情绪", "triggered": trig,
            "detail": f"景气指数 {pros[-1]:.2f}（26 周趋势{'升' if pros_up else '降'}）/ 情绪 {sent_val:+.2f} → {level}",
            "strength": strength}


def calc_s6(h, extras=None):
    """S6 GK 模型预期收益与 ERP：ERP 分位 + GK 预期收益比价。"""
    if not h.get("erp_q") or not _clean(h["erp_q"]):
        return {"id": "S6", "name": "GK 预期收益/ERP", "triggered": False,
                "detail": "缺字段 erp_q（宽基 ERP 分位 0-100）", "strength": "direction"}
    q = _clean(h["erp_q"])[-1]
    gk = h.get("gk_exp_ret")
    gk_v = _clean(gk)[-1] if gk and _clean(gk) else None
    if q > ERP_Q_HI:
        trig, level, strength = True, "高性价比：超配权益（ERP 高分位）", "mid"
    elif q < ERP_Q_LO:
        trig, level, strength = True, "低性价比：减配权益（ERP 低分位）", "mid"
    elif gk_v is not None and gk_v < 0:
        trig, level, strength = True, f"GK 预期收益转负（{gk_v:.1f}%）→ 回避（⚠️ 2021 案例）", "mid"
    else:
        trig, level, strength = False, "ERP 中性 → 标配", "direction"
    extra = f"；GK 预期收益 {gk_v:.1f}%" if gk_v is not None else ""
    return {"id": "S6", "name": "GK 预期收益/ERP", "triggered": trig,
            "detail": f"ERP 分位 {q:.1f}（阈值 >{ERP_Q_HI:.0f} 超配 / <{ERP_Q_LO:.0f} 减配）{extra} → {level}",
            "strength": strength}


def calc_s7(h, extras=None):
    """S7 行业轮动（右侧景气趋势 + 左侧困境反转）：趋势 z + 拥挤度分位。"""
    if not h.get("industry_momentum") or not _clean(h["industry_momentum"]):
        return {"id": "S7", "name": "行业轮动（右/左）", "triggered": False,
                "detail": "缺字段 industry_momentum（行业动量数组，跨行业均值）", "strength": "direction"}
    mom = _clean(h["industry_momentum"])
    zs = _z(mom)
    z_last = zs[-1] if zs else 0.0
    crowd = h.get("industry_crowding")
    crowd_v = _clean(crowd)[-1] if crowd and _clean(crowd) else None
    if z_last > IND_TREND_Z and (crowd_v is None or crowd_v < IND_CROWD_HI):
        trig, level, strength = True, "右侧买入象限：强趋势+低拥挤（✅ 原文'强趋势+低拥挤'，2011 以来年化超额 ~13.2%）", "mid"
    elif z_last > IND_TREND_Z:
        trig, level, strength = False, "强趋势但拥挤度偏高 → 减配（高拥挤警示）", "direction"
    else:
        trig, level, strength = False, "趋势中性 → 行业均衡", "direction"
    extra = f"；拥挤度分位 {crowd_v:.0f}" if crowd_v is not None else ""
    return {"id": "S7", "name": "行业轮动（右/左）", "triggered": trig,
            "detail": f"行业动量 z={z_last:+.2f}（阈值 {IND_TREND_Z:+.1f}）{extra} → {level}", "strength": strength}


def calc_s8(h, extras=None):
    """S8 行业 RS 年度主线：RS>90 阈值（每年 4 月底更新口径）。"""
    if not h.get("rs_score") or not _clean(h["rs_score"]):
        return {"id": "S8", "name": "行业 RS 主线", "triggered": False,
                "detail": "缺字段 rs_score（行业相对强弱指标，4 月底更新口径）", "strength": "direction"}
    rs = _clean(h["rs_score"])
    latest = rs[-1]
    if latest > RS_TH:
        trig, level, strength = True, f"RS>{RS_TH:.0f}：年度主线候选（✅ 原文；与 S7 共振 → 年化超额 ~19.1%）", "strong"
    else:
        trig, level, strength = False, f"RS={latest:.1f} 未达 {RS_TH:.0f} 阈值 → 非年度主线", "direction"
    return {"id": "S8", "name": "行业 RS 主线", "triggered": trig,
            "detail": f"最新 RS {latest:.1f}（阈值 >{RS_TH:.0f}）→ {level}", "strength": strength}


def calc_s9(h, extras=None):
    """S9 风格赔率-趋势-拥挤度图谱：三维合成排名（质量/成长/红利/小盘）。"""
    odds = h.get("style_odds")
    trend = h.get("style_trend")
    crowd = h.get("style_crowd")
    if not odds or not _clean(odds) or not trend or not _clean(trend) or not crowd or not _clean(crowd):
        return {"id": "S9", "name": "风格三维图谱", "triggered": False,
                "detail": "缺字段 style_odds/style_trend/style_crowd（质量/成长/红利/小盘四风格数组）", "strength": "direction"}
    o, t, c = _clean(odds)[-1], _clean(trend)[-1], _clean(crowd)[-1]
    if o > 50 and t > 0 and c < 50:
        trig, level, strength = True, "高赔率+强趋势+低拥挤 → 超配该风格（✅ 2024-07 案例：超配大盘质量）", "mid"
    elif c > 90:
        trig, level, strength = True, "风格拥挤度极高 → 减配（✅ 2024-07 小盘超高拥挤案例）", "mid"
    else:
        trig, level, strength = False, "风格三维无极端 → 均衡", "direction"
    return {"id": "S9", "name": "风格三维图谱", "triggered": trig,
            "detail": f"赔率 {o:.0f} / 趋势 {t:+.2f} / 拥挤度 {c:.0f} → {level}", "strength": strength}


def calc_s10(h, extras=None):
    """S10 转债定价偏离度轮动：Z 截尾公式 → 转债权重 0-100%。"""
    if not h.get("cb_dev") or len(_clean(h["cb_dev"])) < 24:
        return {"id": "S10", "name": "转债偏离度轮动", "triggered": False,
                "detail": "缺字段 cb_dev（转债定价偏离度数组，需 ≥24 期计算 3 年滚动 σ）", "strength": "direction"}
    c = _clean(h["cb_dev"])
    dev = c[-1]
    sd3y = _st.stdev(c[-36:]) if len(c) >= 36 else _st.stdev(c)
    z = dev / sd3y if sd3y else 0.0
    zc = max(-CB_Z_TAIL, min(CB_Z_TAIL, z))          # ±1.5σ 截尾（✅ 原文）
    score = zc / (-CB_Z_TAIL)                        # 分数（✅ 原文公式）
    w = CB_W_BASE + CB_W_BASE * score                # 权重 = 50% + 50%×分数（✅ 原文）
    w = round(max(0.0, min(100.0, w)))
    if w <= 5:
        trig, level, strength = True, "转债定价高估 → 转债仓位 0（✅ 2026-08 案例：偏离度 12.28% 处 96% 分位）", "strong"
    elif w >= 95:
        trig, level, strength = True, "转债定价低估 → 转债仓位满档", "strong"
    else:
        trig, level, strength = False, "转债仓位中性", "direction"
    return {"id": "S10", "name": "转债偏离度轮动", "triggered": trig,
            "detail": f"偏离度 {dev:.2f}%，Z={z:+.2f}（±{CB_Z_TAIL:.1f}σ 截尾）→ 转债仓位 {w}%", "strength": strength}


# ----------------------------------------------------------------------------
# 信号汇总 → 仓位/结构建议（工程化设计，❌ 推断）
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    trig = [s for s in signals if s["triggered"]]
    equity = POS_BASE
    # S1 方向修正
    s1 = next((s for s in signals if s["id"] == "S1"), None)
    if s1 and s1["triggered"]:
        if "上涨" in s1["detail"] and "下跌" not in s1["detail"]:
            equity += POS_S1_BULL
        elif "下跌" in s1["detail"]:
            equity += POS_S1_BEAR
    # S3 LPPL 修正
    s3 = next((s for s in signals if s["id"] == "S3"), None)
    if s3 and s3["triggered"]:
        if "负泡沫" in s3["detail"]:
            equity += POS_S3_NEG
        elif "正泡沫" in s3["detail"]:
            equity += POS_S3_POS
    # S4 六周期修正
    s4 = next((s for s in signals if s["id"] == "S4"), None)
    if s4 and s4["triggered"] and "看多" in s4["detail"]:
        equity += POS_S4_BULL
    equity = round(max(POS_MIN, min(POS_MAX, equity)))

    structure = []
    if not trig:
        structure.append("无信号触发，均衡配置")
    for s in trig:
        structure.append(f"{s['id']} {s['name']}：{s['detail']}")
    # 转债权重独立输出
    s10 = next((s for s in signals if s["id"] == "S10"), None)
    if s10 and s10["triggered"]:
        structure.append("转债：以 S10 输出仓位为准（0-100%）")
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
    lines.append(f"# 刘富兵（国盛金工）框架 · 信号报告（截至 {as_of}）")
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
    lines.append("- **观点引用**：须注明'刘富兵（国盛证券金融工程）{日期}观点'，机构归属随任职变化。")
    lines.append("- **推断参数**：均线窗口 30/120/250、六面图 ±0.2、LPPL ±15% 等均为 ❌ 推断最小假设，非分析师公布值。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 输入契约（对应 decision-rules.md 数据-规则映射附录）
# ----------------------------------------------------------------------------

def schema():
    return {
        "description": "刘富兵（国盛金工）input schema —— 调用 python scripts/screen.py --schema 获取",
        "history": {
            "required": [
                {"field": "hs300_close", "description": "沪深300 收盘价（价格数组，S1/S3 用；至少一个指数价格字段）"},
                {"field": "erp_q", "description": "宽基 ERP 滚动分位（0-100），S6 估值性价比"},
                {"field": "cycle_real", "description": "经济真实周期阶段 1-6（S4）"},
                {"field": "cycle_implied", "description": "资产隐含周期阶段 1-6（S4）"},
                {"field": "a_share_prosperity", "description": "A股景气指数（S5，✅ 原文 2025-11=20.91）"},
                {"field": "cb_dev", "description": "转债定价偏离度 %（S10，需 ≥24 期；2026-08=12.28 ✅ 原文）"},
            ],
            "optional": [
                {"field": "zz500_close", "description": "中证500 收盘价（S1/S3 备选）"},
                {"field": "zz1000_close", "description": "中证1000 收盘价（S1/S3 备选）"},
                {"field": "cyb_close", "description": "创业板指收盘价（S1/S3 备选）"},
                {"field": "liq_dir", "description": "货币方向/强度（六面图流动性，正=多/负=空）"},
                {"field": "cred_dir", "description": "信用方向/强度（六面图流动性）"},
                {"field": "growth_dir", "description": "增长方向/强度（六面图经济面）"},
                {"field": "infl_dir", "description": "通胀方向/强度（六面图经济面）"},
                {"field": "shiller_erp", "description": "席勒 ERP（六面图估值面）"},
                {"field": "pb", "description": "市场 PB（六面图估值面）"},
                {"field": "aiae", "description": "资产隐含盈利预期（六面图估值面 ⚠️ 口径未公开）"},
                {"field": "margin_flow", "description": "两融增量（六面图资金面）"},
                {"field": "amount_trend", "description": "成交额趋势（六面图资金面）"},
                {"field": "cds_cn", "description": "中国主权 CDS 利差（六面图资金面，收窄=多）"},
                {"field": "risk_aversion", "description": "海外风险厌恶指数（六面图资金面，回落=多）"},
                {"field": "option_prem", "description": "期权隐含升贴水（六面图拥挤度）"},
                {"field": "vix", "description": "期权 VIX（六面图拥挤度）"},
                {"field": "skew", "description": "期权 SKEW（六面图拥挤度，高=空）"},
                {"field": "a_share_sentiment", "description": "A股情绪综合信号（S5，正=多/负=空）"},
                {"field": "gk_exp_ret", "description": "GK 模型未来一年预期收益 %（S6 比价）"},
                {"field": "industry_momentum", "description": "行业动量数组（跨行业均值 z 输入，S7）"},
                {"field": "industry_prosperity", "description": "行业景气度（S7 右侧三维输入）"},
                {"field": "industry_crowding", "description": "行业拥挤度分位 0-100（S7，<50 低拥挤）"},
                {"field": "rs_score", "description": "行业 RS 相对强弱（S8，>90 主线）"},
                {"field": "style_odds", "description": "风格赔率分位（S9，>50 高赔率）"},
                {"field": "style_trend", "description": "风格趋势得分（S9，>0 强趋势）"},
                {"field": "style_crowd", "description": "风格拥挤度分位（S9，<50 低拥挤）"},
                {"field": "months", "description": "月份标签数组（升序，最新在末尾）"},
            ],
            "format": "字段 -> 月份数组；月份升序，最新值在末尾",
        },
        "extras": {
            "required": [],
            "optional": [
                {"field": "view_note", "description": "当期观点备注（人工口径校准，不参与计算）"},
                {"field": "cb_note", "description": "转债口径备注（不参与计算）"}
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
        # S1：价格先跌后涨，末段多头排列（日线上涨确认）
        "hs300_close": series(3800.0, 6.0, 90.0, clip=(3300.0, 4600.0)),
        "zz500_close": series(6100.0, 8.0, 120.0, clip=(5200.0, 7200.0)),
        # S2：六面图 15 项子信号，末段综合分略负（中性偏空案例）
        "liq_dir": [0.6 if i % 3 else -0.4 for i in range(n)],
        "cred_dir": [-0.5 if i >= 18 else 0.4 for i in range(n)],
        "growth_dir": [0.4 if i < 24 else -0.3 for i in range(n)],
        "infl_dir": [0.3 if i < 12 else -0.2 for i in range(n)],
        "shiller_erp": series(0.9, 0.002, 0.05),
        "pb": series(1.6, 0.003, 0.05),
        "aiae": series(0.0, 0.002, 0.04),
        "margin_flow": series(50.0, 0.4, 8.0, clip=(10.0, 100.0)),
        "amount_trend": series(0.0, 0.01, 0.15),
        "cds_cn": series(60.0, -0.4, 5.0, clip=(30.0, 90.0)),
        "risk_aversion": series(0.5, -0.004, 0.06, clip=(-0.3, 1.0)),
        "option_prem": series(0.0, 0.001, 0.03),
        "vix": series(18.0, -0.05, 1.5, clip=(12.0, 28.0)),
        "skew": series(105.0, 0.05, 2.0, clip=(95.0, 120.0)),
        "cb_dev": series(6.0, 0.15, 0.8, clip=(-3.0, 15.0)),
        # S3：末段价格偏离 12 月均线进入负区（触发负泡沫抄底路径）
        # S4：真实周期 4 → 隐含周期 2（滞后 2 档，看多风险资产）
        "cycle_real": [4] * n,
        "cycle_implied": [2 if i >= n - 4 else 3 for i in range(n)],
        # S5：景气上行 + 情绪转正
        "a_share_prosperity": series(16.0, 0.15, 0.6),
        "a_share_sentiment": [-0.4 if i < 24 else 0.5 for i in range(n)],
        # S6：ERP 分位从 35 升至 85（高性价比）
        "erp_q": series(35.0, 1.4, 4.0, clip=(5.0, 99.0)),
        "gk_exp_ret": series(4.0, 0.03, 0.5, clip=(-2.0, 10.0)),
        # S7：行业动量末段走强、拥挤度回落
        "industry_momentum": series(-0.4, 0.025, 0.06),
        "industry_prosperity": series(50.0, 0.4, 4.0, clip=(20.0, 80.0)),
        "industry_crowding": series(70.0, -0.8, 6.0, clip=(20.0, 95.0)),
        # S8：RS 末段突破 90（年度主线）
        "rs_score": series(78.0, 0.4, 2.0, clip=(60.0, 99.0)),
        # S9：风格三维（质量/成长/红利/小盘均值口径）末段高赔率低拥挤
        "style_odds": series(40.0, 0.5, 3.0, clip=(10.0, 90.0)),
        "style_trend": series(-0.3, 0.02, 0.05),
        "style_crowd": series(65.0, -0.6, 5.0, clip=(10.0, 95.0)),
    }
    return {
        "as_of": "2026-08-01",
        "history": history,
        "extras": {
            "view_note": "合成：演示模式（真实观点见 views.md，2026-08 六面图 -0.12 中性）",
            "cb_note": "合成：演示模式（真实 2026-08 偏离度 12.28% ✅ 原文）",
        },
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="刘富兵（国盛金工）框架信号计算")
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

    calc_funcs = [calc_s1, calc_s2, calc_s3, calc_s4, calc_s5, calc_s6,
                  calc_s7, calc_s8, calc_s9, calc_s10]
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
