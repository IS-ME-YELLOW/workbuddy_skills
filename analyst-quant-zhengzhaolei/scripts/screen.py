#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
郑兆磊（兴业证券金工首席）信号计算脚本 —— screen.py
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
# S1 点位效率择时
PROB_BULL = 60.0      # ❌ 推断：长期上涨概率高于此看多（趋势模式），动态阈值未公布，最小假设可替换
PROB_BULL_MID = 55.0  # ❌ 推断：概率模式看多的下界（55<P_L<=60 且 P_M 同向），最小假设可替换
PROB_OPT = 50.0       # ❌ 推断：谨慎偏乐观上界（P_L 在 50-55），最小假设可替换
PROB_BEAR = 40.0      # ❌ 推断：长期上涨概率低于此看空（趋势模式），最小假设可替换
PROB_BEAR_MID = 45.0  # ❌ 推断：概率模式谨慎上界（P_L<=45 且 P_M 同向），最小假设可替换
PROB_MID_DIR = 50.0   # ❌ 推断：中期概率同向分界（P_M>50 同向看多 / <50 同向看空），最小假设可替换
# S2 股债性价比 ERP 3.0 仓位锚
ERP_Q_HIGH = 90.0     # ⚠️ 外推：滚动 4 年分位高于此=高性价比加仓档（✅原文"极端高位"表述，90 为脚本档位，以原文复核）
ERP_Q_MID_HI = 70.0   # ⚠️ 外推：中性偏多档下界（脚本分档）
ERP_Q_MID_LO = 30.0   # ⚠️ 外推：中性偏空档上界（脚本分档）
ERP_Q_LOW = 10.0      # ⚠️ 外推：滚动 4 年分位低于此=低性价比减仓档（✅原文"极端低位"，10 为脚本档位）
ERP_Q_WIN_YR = 4      # ✅ 原文：滚动 4 年分位窗口（《固收加系列之五》等）
# S3 成长-价值轮动
GV_SIGMA = 0.5        # ❌ 推断：风格得分 |z|>0.5σ 判定成长/价值占优，最小假设可替换
# S4 大小盘轮动
CAP_SIGMA = 0.5       # ❌ 推断：趋势得分 |z|>0.5σ 判定小盘/大盘占优，最小假设可替换
CAP_TURN_HI = 90.0    # ⚠️ 外推：大小盘相对换手率分位高于此=拥挤拐点修正（✅原文"极高分位"），90 为脚本档
# S5 行业轮动（分歧与共振）
IND_TOP_N = 5         # ❌ 推断：行业推荐前 N（对齐 2026-08 五行业口径），最小假设可替换
# S6 趋势与极端拐点风控
LP_BUBBLE_TH = 0.5    # ❌ 推断：|LPPLS 泡沫指标|>0.5 触发拐点，最小假设可替换
LP_LOOKBACK = 3       # ❌ 推断：拐点检测近 N 月窗口，最小假设可替换
# S7 换手率情绪
TURN_MED_YR = 24      # ✅ 原文：换手率与"过去 2 年"中位数比较（24 个月即 2 年）
TURN_OVERHEAT = 90.0  # ⚠️ 外推：换手率近 10 年分位高于此=情绪过热警惕（✅原文方向，阈值脚本化）
# S8 美债利率方向
R_US_DIR = 0.0        # ✅ 原文：美债上行利好价值、下行利好成长（"解释力极强"）
# 仓位工程化（❌ 推断：分析师未公布仓位映射，最小假设可替换）
POS_BASE = 55.0       # 中性仓位中枢（%）
POS_ERP_HIGH = 75.0   # ERP>90 分位仓位
POS_ERP_LOW = 40.0    # ERP<=10 分位仓位
POS_S1_BULL = 5.0     # S1 看多加仓
POS_S1_BEAR = -10.0   # S1 谨慎减仓
POS_LP_NEG = 8.0      # 负泡沫抄底加仓
POS_LP_POS = -8.0     # 正泡沫见顶减仓
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


# ----------------------------------------------------------------------------
# 信号计算函数（契约：输入 h / extras → 返回 dict）
# 返回 dict 固定四键：id / name / triggered / detail / strength
#   strength ∈ "strong" / "mid" / "direction"（decision-rules 规则 0 分级）
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 点位效率择时：长期上涨概率 P_L（+中期 P_M 确认）→ 看多/谨慎偏乐观/谨慎/中性。"""
    if "prob_l" not in h or not h["prob_l"]:
        return {"id": "S1", "name": "点位效率择时", "triggered": False,
                "detail": "缺字段 prob_l（长期上涨概率，兴财富周报口径；无 API 时用趋势代理 ❌）",
                "strength": "direction"}
    p_l = h["prob_l"][-1]
    p_m = h["prob_m"][-1] if h.get("prob_m") else None
    pm_dir = (p_m > PROB_MID_DIR) if p_m is not None else True
    if p_l > PROB_BULL:
        trig, level, strength = True, "看多（单边趋势模式）", "strong"
    elif PROB_BULL_MID < p_l <= PROB_BULL and pm_dir:
        trig, level, strength = True, "看多（概率指标模式，中期同向）", "mid"
    elif PROB_OPT < p_l <= PROB_BULL_MID:
        trig, level, strength = True, "谨慎偏乐观", "mid"
    elif p_l < PROB_BEAR:
        trig, level, strength = True, "谨慎（单边趋势模式）", "strong"
    elif p_l <= PROB_BEAR_MID and (p_m is None or not pm_dir):
        trig, level, strength = True, "谨慎（概率指标模式，中期同向）", "mid"
    else:
        trig, level, strength = False, "中性观望（概率无明确方向）", "direction"
    return {"id": "S1", "name": "点位效率择时", "triggered": trig,
            "detail": f"长期上涨概率 {p_l:.1f}%（阈值 看多>{PROB_BULL:.0f}/谨慎<{PROB_BEAR:.0f}）→ {level}",
            "strength": strength}


def calc_s2(h, extras=None):
    """S2 股债性价比 ERP 3.0：滚动 4 年分位 Q → 权益仓位锚。"""
    if "erp_q" not in h or not h["erp_q"]:
        return {"id": "S2", "name": "ERP3.0 仓位锚", "triggered": False,
                "detail": "缺字段 erp_q（ERP 3.0 滚动 4 年分位 0-100）", "strength": "direction"}
    q = h["erp_q"][-1]
    if q > ERP_Q_HIGH:
        trig, level, strength = True, "高性价比：权益仓位上限档", "strong"
    elif q > ERP_Q_MID_HI:
        trig, level, strength = False, "中性偏多：标准配置档", "direction"
    elif q > ERP_Q_MID_LO:
        trig, level, strength = False, "中性偏空：标配偏谨慎档", "direction"
    elif q > ERP_Q_LOW:
        trig, level, strength = False, "低性价比：接近减仓档", "direction"
    else:
        trig, level, strength = True, "低性价比：权益减仓至下限档", "strong"
    return {"id": "S2", "name": "ERP3.0 仓位锚", "triggered": trig,
            "detail": f"ERP 3.0 滚动 {ERP_Q_WIN_YR:.0f} 年分位 {q:.1f}（参考读数 2026-08=35.4，以当期报告为准）→ {level}",
            "strength": strength}


def calc_s3(h, extras=None):
    """S3 成长-价值轮动：风格得分（等权 z-score 合成，❌ 权重最小假设）vs ±0.5σ。"""
    if "style_score" not in h or not h["style_score"]:
        return {"id": "S3", "name": "成长价值轮动", "triggered": False,
                "detail": "缺字段 style_score（成长-价值轮动合成得分，正=成长占优；由 6 因子四维度合成）",
                "strength": "direction"}
    zs = _z(h["style_score"])
    latest = zs[-1]
    if latest > GV_SIGMA:
        trig, level, strength = True, "成长占优", "mid"
    elif latest < -GV_SIGMA:
        trig, level, strength = True, "价值占优", "mid"
    else:
        trig, level, strength = False, "风格均衡", "direction"
    return {"id": "S3", "name": "成长价值轮动", "triggered": trig,
            "detail": f"风格得分 z={latest:+.2f}σ（阈值 ±{GV_SIGMA:.1f}σ）→ {level}",
            "strength": strength}


def calc_s4(h, extras=None):
    """S4 大小盘轮动：趋势得分 vs ±0.5σ；相对换手率分位>90 触发拐点修正。"""
    if "cap_score" not in h or not h["cap_score"]:
        return {"id": "S4", "name": "大小盘轮动", "triggered": False,
                "detail": "缺字段 cap_score（大小盘趋势得分，正=小盘占优）", "strength": "direction"}
    zs = _z(h["cap_score"])
    latest = zs[-1]
    turn_pct = h["rel_turn_pct"][-1] if h.get("rel_turn_pct") else None
    if latest > CAP_SIGMA:
        if turn_pct is not None and turn_pct > CAP_TURN_HI:
            trig, level, strength = True, "小盘占优但相对换手率拥挤 → 降级均衡（拐点修正）", "mid"
        else:
            trig, level, strength = True, "小盘占优", "mid"
    elif latest < -CAP_SIGMA:
        trig, level, strength = True, "大盘占优", "mid"
    else:
        trig, level, strength = False, "大小盘均衡", "direction"
    extra = f"；相对换手率分位 {turn_pct:.0f}" if turn_pct is not None else ""
    return {"id": "S4", "name": "大小盘轮动", "triggered": trig,
            "detail": f"趋势得分 z={latest:+.2f}σ（阈值 ±{CAP_SIGMA:.1f}σ）{extra} → {level}",
            "strength": strength}


def calc_s5(h, extras=None):
    """S5 行业轮动'分歧与共振'：资金维度×业绩维度同向为正=共振买入。"""
    if "fund_dim" not in h or not h["fund_dim"] or "perf_dim" not in h or not h["perf_dim"]:
        return {"id": "S5", "name": "行业轮动（分歧与共振）", "triggered": False,
                "detail": "缺字段 fund_dim（资金维度得分）或 perf_dim（业绩维度得分）", "strength": "direction"}
    f = h["fund_dim"][-1]
    p = h["perf_dim"][-1]
    if f > 0 and p > 0:
        trig, level, strength = True, f"高确信买入（共振）：资金+业绩同向，纳入前 {IND_TOP_N:.0f} 行业核心持仓", "mid"
    elif f > 0:
        trig, level, strength = False, "观察（仅资金流入，业绩未兑现）→ 不重仓", "direction"
    else:
        trig, level, strength = False, "回避（资金或业绩维度为负）→ 低配", "direction"
    return {"id": "S5", "name": "行业轮动（分歧与共振）", "triggered": trig,
            "detail": f"资金维度 {f:+.2f} / 业绩维度 {p:+.2f} → {level}", "strength": strength}


def calc_s6(h, extras=None):
    """S6 趋势与极端拐点风控：LPPLS 泡沫触发（强）+ 信用扩张/汇率趋势（方向）。"""
    if "lp_bubble" not in h or not h["lp_bubble"]:
        return {"id": "S6", "name": "趋势与极端拐点", "triggered": False,
                "detail": "缺字段 lp_bubble（LPPLS 泡沫指标，正=正泡沫/负=负泡沫）", "strength": "direction"}
    win = _clean(h["lp_bubble"])[-LP_LOOKBACK:]
    if not win:
        return {"id": "S6", "name": "趋势与极端拐点", "triggered": False,
                "detail": "lp_bubble 近窗口无有效值", "strength": "direction"}
    neg = min(win)
    pos = max(win)
    if neg < -LP_BUBBLE_TH:
        trig, level, strength = True, "负泡沫触发 → 分批抄底（参照 2022-04、2024-02 ✅ 原文）", "strong"
    elif pos > LP_BUBBLE_TH:
        trig, level, strength = True, "正泡沫触发 → 见顶预警，减仓锁定收益", "strong"
    else:
        # 趋势型指标：信用扩张上行 + 汇率升值 → 趋势偏多
        credit_up = trend_up(_clean(h["credit_exp"])) if h.get("credit_exp") else False
        fx_up = trend_up(_clean(h["fx_appr"])) if h.get("fx_appr") else False
        if credit_up and fx_up:
            trig, level, strength = True, "趋势偏多（信用扩张+汇率同向改善）", "direction"
        else:
            trig, level, strength = False, "无极端拐点，趋势信号中性", "direction"
    return {"id": "S6", "name": "趋势与极端拐点", "triggered": trig,
            "detail": f"LPPLS 近 {LP_LOOKBACK:.0f} 月范围 [{pos:+.2f}, {neg:+.2f}]（阈值 ±{LP_BUBBLE_TH:.2f}）→ {level}",
            "strength": strength}


def calc_s7(h, extras=None):
    """S7 换手率情绪：全 A 换手率 vs 过去 2 年中位数 → 利好成长。"""
    if "turnover" not in h or not h["turnover"]:
        return {"id": "S7", "name": "换手率情绪", "triggered": False,
                "detail": "缺字段 turnover（万得全 A 换手率 %）", "strength": "direction"}
    tv = _clean(h["turnover"])
    if len(tv) < 2:
        return {"id": "S7", "name": "换手率情绪", "triggered": False,
                "detail": "turnover 样本不足", "strength": "direction"}
    win = tv[-TURN_MED_YR:]
    med = _st.median(win)
    latest = tv[-1]
    trig = latest > med
    return {"id": "S7", "name": "换手率情绪", "triggered": trig,
            "detail": f"换手率 {latest:.2f}% vs 过去 2 年中位数 {med:.2f}% → {'活跃，利好成长' if trig else '平淡'}",
            "strength": "direction"}


def calc_s8(h, extras=None):
    """S8 美债利率方向：10Y 美债环比上行 → 利好价值。"""
    if "r_us" not in h or not h["r_us"]:
        return {"id": "S8", "name": "美债利率方向", "triggered": False,
                "detail": "缺字段 r_us（10Y 美债收益率 %）", "strength": "direction"}
    r = _clean(h["r_us"])
    if len(r) < 2:
        return {"id": "S8", "name": "美债利率方向", "triggered": False,
                "detail": "r_us 样本不足", "strength": "direction"}
    up = r[-1] > r[-2]
    return {"id": "S8", "name": "美债利率方向", "triggered": up,
            "detail": f"10Y 美债 {r[-2]:.2f}% → {r[-1]:.2f}% → {'上行，利好价值' if up else '下行，利好成长'}",
            "strength": "direction"}


# ----------------------------------------------------------------------------
# 信号汇总 → 仓位/风格/市值/行业建议（金工版工程化设计，❌ 推断）
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    """汇总触发信号 → 配置建议（仓位中枢 + 结构方向）。"""
    trig = [s for s in signals if s["triggered"]]

    # 仓位中枢：ERP 分位定锚 + S1/S6 修正
    equity = POS_BASE
    erp_q = h["erp_q"][-1] if h.get("erp_q") and h["erp_q"] else None
    if erp_q is not None:
        if erp_q > ERP_Q_HIGH:
            equity = POS_ERP_HIGH
        elif erp_q <= ERP_Q_LOW:
            equity = POS_ERP_LOW
    prob_l = h["prob_l"][-1] if h.get("prob_l") and h["prob_l"] else None
    if prob_l is not None:
        if prob_l > PROB_BULL:
            equity += POS_S1_BULL
        elif prob_l < PROB_BEAR:
            equity += POS_S1_BEAR
    if h.get("lp_bubble") and h["lp_bubble"]:
        win = _clean(h["lp_bubble"])[-LP_LOOKBACK:]
        if win and min(win) < -LP_BUBBLE_TH:
            equity += POS_LP_NEG
        elif win and max(win) > LP_BUBBLE_TH:
            equity += POS_LP_POS
    equity = round(max(POS_MIN, min(POS_MAX, equity)))

    structure = []
    if not trig:
        structure.append("无信号触发，均衡配置（仓位按 ERP 分位锚定）")
    for s in trig:
        structure.append(f"{s['id']} {s['name']}：{s['detail']}")

    # 风格/市值/行业独立建议（与 calc_* 同源，避免解析字符串）
    zs_gv = _z(h["style_score"]) if h.get("style_score") else []
    if zs_gv and zs_gv[-1] > GV_SIGMA:
        structure.append("风格：超配成长（成长-价值轮动）")
    elif zs_gv and zs_gv[-1] < -GV_SIGMA:
        structure.append("风格：超配价值（成长-价值轮动）")
    zs_cap = _z(h["cap_score"]) if h.get("cap_score") else []
    turn_pct = h["rel_turn_pct"][-1] if h.get("rel_turn_pct") else None
    if zs_cap and zs_cap[-1] > CAP_SIGMA:
        structure.append("市值：小盘占优" + ("，注意相对换手率拥挤、降级均衡" if turn_pct is not None and turn_pct > CAP_TURN_HI else ""))
    elif zs_cap and zs_cap[-1] < -CAP_SIGMA:
        structure.append("市值：大盘占优")
    fd = h["fund_dim"][-1] if h.get("fund_dim") else None
    pd = h["perf_dim"][-1] if h.get("perf_dim") else None
    if fd is not None and pd is not None:
        structure.append("行业：资金×业绩" + ("共振 → 核心持仓" if fd > 0 and pd > 0 else "分歧/未兑现 → 观察或回避"))

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
    lines.append(f"# 郑兆磊（兴业金工）框架 · 信号报告（截至 {as_of}）")
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
    lines.append("- **观点引用**：须注明'郑兆磊（兴业证券金融工程）{日期}观点'，机构归属随任职变化。")
    lines.append("- **推断参数**：动态阈值 60/40、±0.5σ、行业前 5 等均为 ❌ 推断最小假设，非分析师公布值。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 输入契约（对应 decision-rules.md 数据-规则映射附录）
# ----------------------------------------------------------------------------

def schema():
    """返回调用方准备 --data 所需的最小输入契约。"""
    return {
        "description": "郑兆磊（兴业金工）input schema —— 调用 python scripts/screen.py --schema 获取",
        "history": {
            "required": [
                {"field": "prob_l", "description": "宽基长期上涨概率（0-100），兴财富周报口径；无 API 时用趋势代理 ❌"},
                {"field": "prob_m", "description": "宽基中期上涨概率（0-100），S1 中期同向确认"},
                {"field": "erp_q", "description": "ERP 3.0 滚动 4 年分位（0-100），S2 仓位锚"},
                {"field": "style_score", "description": "成长-价值轮动合成得分（正=成长占优），6 因子四维度等权 z-score 合成"},
                {"field": "cap_score", "description": "大小盘趋势得分（正=小盘占优），期限利差+信用利差+地产投资+相对净值合成"},
            ],
            "optional": [
                {"field": "prob_s", "description": "宽基短期上涨概率（0-100），短线参考"},
                {"field": "rel_turn_pct", "description": "大小盘相对换手率历史分位（0-100），S4 拐点修正"},
                {"field": "lp_bubble", "description": "LPPLS 泡沫指标（正=正泡沫/负=负泡沫/近0=无），S6 拐点风控"},
                {"field": "credit_exp", "description": "信用扩张指数（社融/中长贷增速代理），S6 趋势方向"},
                {"field": "fx_appr", "description": "人民币汇率升值指数（升=上行），S6 趋势方向"},
                {"field": "fund_dim", "description": "行业资金维度得分（主力/北向/ETF 资金流），S5 分歧与共振"},
                {"field": "perf_dim", "description": "行业业绩维度得分（超预期程度），S5 分歧与共振"},
                {"field": "turnover", "description": "万得全 A 换手率（%），S7 情绪"},
                {"field": "r_us", "description": "10Y 美债收益率（%），S8 海外流动性"},
                {"field": "months", "description": "月份标签数组（升序，最新在末尾），事件复算与季节性信号用"},
            ],
            "format": "字段 -> 月份数组；月份升序，最新值在末尾",
        },
        "extras": {
            "required": [],
            "optional": [
                {"field": "style_note", "description": "风格判断备注（人工口径校准，不参与计算）"},
                {"field": "industry_note", "description": "行业推荐备注（当期报告口径，不参与计算）"}
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
        # S1：长期概率从谨慎区(38)升至看多区(66)
        "prob_l": series(38.0, 0.85, 3.0, clip=(30.0, 75.0)),
        "prob_m": series(42.0, 0.60, 4.0, clip=(30.0, 75.0)),
        "prob_s": series(50.0, 0.10, 5.0, clip=(30.0, 75.0)),
        # S2：ERP 分位从 45 升至 96（触发高性价比）
        "erp_q": series(45.0, 1.45, 4.0, clip=(5.0, 99.0)),
        # S3：风格得分从 -0.7（价值）升至 +0.7（成长）
        "style_score": series(-0.7, 0.041, 0.08),
        # S4：趋势得分从 -0.5（大盘）升至 +0.6（小盘）；相对换手率末段高位
        "cap_score": series(-0.5, 0.033, 0.07),
        "rel_turn_pct": series(55.0, 1.1, 8.0, clip=(20.0, 98.0)),
        # S6：末段出现负泡沫触发抄底；信用扩张与汇率缓慢改善
        "lp_bubble": [(-0.7 if i >= n - 3 else (0.8 if i == 20 else 0.05)) for i in range(n)],
        "credit_exp": series(95.0, 0.20, 1.5),
        "fx_appr": series(100.0, 0.15, 1.0),
        # S5：末段资金/业绩同向为正（共振）
        "fund_dim": [-0.3 if i < 15 else 0.4 for i in range(n)],
        "perf_dim": [-0.2 if i < 20 else 0.5 for i in range(n)],
        # S7：换手率高于过去 2 年中位数
        "turnover": series(2.6, 0.012, 0.25),
        # S8：美债缓慢上行（末月强制上行以覆盖触发路径）
        "r_us": series(4.20, 0.012, 0.08),
    }
    history["r_us"][-1] = round(history["r_us"][-2] + 0.15, 3)
    return {
        "as_of": "2026-08-01",
        "history": history,
        "extras": {
            "style_note": "合成：演示模式",
            "industry_note": "合成：演示模式（真实版见 2026-08 推荐 机械/电力设备/家电/有色/传媒）",
        },
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="郑兆磊（兴业金工）框架信号计算")
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
