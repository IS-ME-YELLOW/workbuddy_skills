#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst-fixed-income-huangweiping 信号计算脚本
============================================================
黄伟平（申万宏源固收）框架信号计算：核心矛盾定位 → 定价范式 → 结构 → 策略落地。
信号编号 S1-S13 系本技能工程化设计（见 references/decision-rules.md 规则 14）。

用法：
  python screen.py                          # 演示模式（合成数据）
  python screen.py --data data.json         # 真实数据（history: 字段→月份数组，最新在末尾）
  python screen.py --data data.json --json-out  # 输出 JSON
  python screen.py --schema                 # 输出输入契约
"""

import argparse
import json
import math as _m
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ============================================================
# 参数区（来源分级：✅ 原文 / ⚠️ 外推 / ❌ 推断 —— 与 decision-rules.md 图例一致）
# ------------------------------------------------------------
# S1 核心矛盾阶段
PPI_MOM_UP_N = 2        # ❌ 推断：最小假设，可替换——连续 N 月 PPI 环比改善判定物价阶段
SF_YOY_CHEAP = 11.0     # ❌ 推断：最小假设，可替换——社融同比低于此值视为信用收缩
# S2 物价斜率
PPI_TO_CPI_ON = True    # ❌ 推断：最小假设，可替换——PPI→CPI 传导是否启动（人工判定）
# S3 货币政策框架状态
DR_OMO_GAP_SMOOTH = 10  # ✅ 原文：DR001-OMO 绝对利差 2024-26 年降至 9/13/9BP（传导顺畅基准）
# S4 资金面松紧
DR7_OMO_BAND = 15       # ❌ 推断：最小假设，可替换——DR007-OMO 偏离带宽(BP)
# S5 存单利差脉冲
NCD_PCTILE_HIGH = 80    # ❌ 推断：最小假设，可替换——存单利差滚动 1 年高分位阈值
# S6 长债定价锚
ANCHOR_GAP = 0.0        # ⚠️ 外推：长债定价锚切换判定阈值（以原文复核）
# S7 期限利差
TS10_1_PCTILE = 70      # ❌ 推断：最小假设，可替换——10-1Y 期限利差分位阈值
TS30_10_PCTILE = 60     # ❌ 推断：最小假设，可替换——30-10Y 期限利差分位阈值
# S8/S9 二永债利差分位（✅ 原文 2026.8.3）
SPREAD_PCTILE_TOP = 70  # ✅ 原文：信用利差滚动 1 年分位 70% 附近接近见顶
SPREAD_PCTILE_BOT = 10  # ✅ 原文：信用利差滚动 1 年分位 10% 附近接近见底
# S10 布林带（❌ σ 倍数推断）
BB_SIGMA = 2.0          # ❌ 推断：最小假设，可替换——布林带 σ 倍数
# S11 品种利差（✅ 原文 2026.8.10）
SUB_2Y_HIGH = 15        # ✅ 原文：永续-二债利差 >15BP 积极超配（弹性 1.4-1.5 倍）
SUB_2Y_MID = 8          # ✅ 原文：永续-二债利差 8-15BP 适度超配
# S13 资产性价比排序（✅ 原文 2026.6.9）
RATE_10Y_Q2 = 0.0180    # ✅ 原文：6-7 月 10Y 区间上沿 1.80%
RATE_10Y_Q2L = 0.0170   # ✅ 原文：6-7 月 10Y 区间下沿 1.70%
RATE_10Y_Q3 = 0.0185    # ✅ 原文：8-9 月 10Y 区间上沿 1.85%
RATE_10Y_Q3L = 0.0175   # ✅ 原文：8-9 月 10Y 区间下沿 1.75%
RATE_10Y_Q4 = 0.0175    # ✅ 原文：Q4 10Y 区间上沿 1.75%
RATE_10Y_Q4L = 0.0165   # ✅ 原文：Q4 10Y 区间下沿 1.65%
# ============================================================


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------

def _clean(series):
    """剔除 None，保留数值。"""
    return [x for x in series if x is not None]


def get(series):
    """回溯最近有效值（窗口末端/次月数据未发布时为 None）。"""
    clean = _clean(series)
    return clean[-1] if clean else None


def pct_rank(series, value):
    """value 在 series 中的百分位（0-100）。"""
    clean = _clean(series)
    if not clean:
        return 50.0
    below = sum(1 for x in clean if x < value)
    return below / len(clean) * 100.0


def recent_avg(series, lookback=3):
    """最近 lookback 期均值。"""
    clean = _clean(series)
    if not clean:
        return 0.0
    win = clean[-lookback:]
    return sum(win) / len(win)


def trend_up(series, lookback=3):
    """最近 lookback 期是否整体上行。"""
    clean = _clean(series)
    if len(clean) < 2:
        return False
    win = clean[-lookback:]
    return win[-1] > win[0]


def mom_up_months(series, n):
    """最近连续环比改善月数（仅对月度 PPI 等环比可序列）。"""
    clean = _clean(series)
    if len(clean) < 2:
        return 0
    cnt = 0
    for i in range(len(clean) - 1, 0, -1):
        if clean[i] > clean[i - 1]:
            cnt += 1
        else:
            break
    return cnt


def bollinger(series, sigma=BB_SIGMA):
    """布林带：(upper, lower, latest)。"""
    clean = _clean(series)
    if len(clean) < 3:
        return None
    n = len(clean)
    mean = sum(clean) / n
    var = sum((x - mean) ** 2 for x in clean) / n
    sd = _m.sqrt(var)
    return (mean + sigma * sd, mean - sigma * sd, clean[-1])


# ----------------------------------------------------------------------------
# 信号计算函数
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 核心矛盾阶段定位（方向总开关）。"""
    sf = get(h.get("sf_yoy"))
    ppi = h.get("ppi_yoy")
    ppi_up = mom_up_months(ppi, PPI_MOM_UP_N) if ppi else 0
    if sf is None:
        return {"id": "S1", "name": "核心矛盾阶段", "triggered": False,
                "detail": "缺字段 sf_yoy（社融同比）", "strength": "direction"}
    if ppi_up >= PPI_MOM_UP_N and sf < SF_YOY_CHEAP:
        stage = "物价+资金流向（物价回升斜率确认）"
        trig, strength = True, "strong"
    elif sf < SF_YOY_CHEAP:
        stage = "信用收缩/资产配置再平衡"
        trig, strength = False, "mid"
    else:
        stage = "信用扩张"
        trig, strength = False, "direction"
    return {"id": "S1", "name": "核心矛盾阶段", "triggered": trig,
            "detail": f"社融同比 {sf*100:.1f}% + PPI 连续环比改善 {ppi_up} 月 → 阶段：{stage}",
            "strength": strength}


def calc_s2(h, extras=None):
    """S2 物价回升斜率（逆风期开关）。"""
    ppi = h.get("ppi_yoy")
    cpi = h.get("cpi_yoy")
    if not ppi or not cpi:
        return {"id": "S2", "name": "物价回升斜率", "triggered": False,
                "detail": "缺字段 ppi_yoy / cpi_yoy", "strength": "direction"}
    ppi_up = mom_up_months(ppi, PPI_MOM_UP_N)
    cpi_up = mom_up_months(cpi, PPI_MOM_UP_N)
    slope = ppi_up >= PPI_MOM_UP_N and (cpi_up >= 1 or (extras or {}).get("ppi_to_cpi"))
    return {"id": "S2", "name": "物价回升斜率", "triggered": bool(slope),
            "detail": f"PPI 连续环比改善 {ppi_up} 月、CPI 连续 {cpi_up} 月 → 斜率{'确认' if slope else '未确认'}（2-3 季度为逆风重点）",
            "strength": "strong" if slope else "direction"}

def calc_s3(h, extras=None):
    """S3 货币政策框架状态（传导效率）。"""
    dr = get(h.get("dr001"))
    omo = get(h.get("omo7d"))
    if dr is None or omo is None:
        return {"id": "S3", "name": "货币政策框架状态", "triggered": False,
                "detail": "缺字段 dr001 / omo7d", "strength": "direction"}
    gap_bp = (dr - omo) * 10000
    smooth = abs(gap_bp) < DR_OMO_GAP_SMOOTH
    return {"id": "S3", "name": "货币政策框架状态", "triggered": smooth,
            "detail": f"DR001-OMO 利差 {gap_bp:.0f}BP vs 传导顺畅基准 {DR_OMO_GAP_SMOOTH}BP → {'传导顺畅' if smooth else '传导受阻'}",
            "strength": "mid" if smooth else "direction"}


def calc_s4(h, extras=None):
    """S4 资金面松紧（杠杆开关）。"""
    dr7 = h.get("dr007")
    omo = get(h.get("omo7d"))
    if not dr7 or omo is None:
        return {"id": "S4", "name": "资金面松紧", "triggered": False,
                "detail": "缺字段 dr007 / omo7d", "strength": "direction"}
    avg = recent_avg(dr7, 20) if len(_clean(dr7)) >= 20 else get(dr7)
    gap_bp = (avg - omo) * 10000
    tight = gap_bp > DR7_OMO_BAND
    return {"id": "S4", "name": "资金面松紧", "triggered": tight,
            "detail": f"DR007 均值 {avg:.3f}% vs OMO {omo:.3f}% → 偏离 {gap_bp:+.0f}BP（收敛阈值 {DR7_OMO_BAND}BP）→ {'资金收敛' if tight else '资金平稳/宽松'}",
            "strength": "strong" if tight else "direction"}


def calc_s5(h, extras=None):
    """S5 存单利差脉冲（负债压力→配置窗口）。"""
    ncd = h.get("ncd1y")
    omo = get(h.get("omo7d"))
    if not ncd or omo is None:
        return {"id": "S5", "name": "存单利差脉冲", "triggered": False,
                "detail": "缺字段 ncd1y / omo7d", "strength": "direction"}
    gaps = [(x - omo) * 10000 for x in _clean(ncd)]
    latest = gaps[-1]
    pct = pct_rank(gaps, latest)
    trig = pct >= NCD_PCTILE_HIGH
    return {"id": "S5", "name": "存单利差脉冲", "triggered": trig,
            "detail": f"存单-OMO 利差 {latest:.0f}BP（滚动 1 年分位 {pct:.0f}%）→ {'脉冲走阔=负债压力=配置窗口' if trig else '低中枢常态'}",
            "strength": "mid" if trig else "direction"}


def calc_s6(h, extras=None):
    """S6 长债定价锚切换（政策利率未动+资金利率实质下行→10Y 有支撑）。"""
    c10y = h.get("c10y")
    dr7 = h.get("dr007")
    omo = get(h.get("omo7d"))
    if not c10y or not dr7 or omo is None:
        return {"id": "S6", "name": "长债定价锚切换", "triggered": False,
                "detail": "缺字段 c10y / dr007 / omo7d", "strength": "direction"}
    dr_avg = recent_avg(dr7, 6)
    policy_view = c10y[-1] - omo
    money_view = c10y[-1] - dr_avg
    switched = policy_view > money_view and (dr_avg - omo) < 0.0005
    return {"id": "S6", "name": "长债定价锚切换", "triggered": switched,
            "detail": f"10Y {c10y[-1]*100:.2f}%：政策利率锚溢价 {policy_view*100:.2f}pp vs 资金利率锚溢价 {money_view*100:.2f}pp → 定价锚{'切换至资金利率' if switched else '仍以政策利率为主'}",
            "strength": "strong" if switched else "direction"}


def calc_s7(h, extras=None):
    """S7 期限利差压缩空间（超长/长久期性价比）。"""
    ts101 = h.get("ts101")
    ts3010 = h.get("ts3010")
    # 缺省：由收益率派生（c10y-c1y / c30y-c10y）
    if not ts101 and h.get("c10y") and h.get("c1y"):
        ts101 = [(a - b) * 10000 for a, b in zip(h["c10y"], h["c1y"])]
    if not ts3010 and h.get("c30y") and h.get("c10y"):
        ts3010 = [(a - b) * 10000 for a, b in zip(h["c30y"], h["c10y"])]
    if not ts101 or not ts3010:
        return {"id": "S7", "name": "期限利差", "triggered": False,
                "detail": "缺字段 ts101 / ts3010（BP 序列）及 c1y/c30y", "strength": "direction"}
    p101 = pct_rank(_clean(ts101), ts101[-1])
    p3010 = pct_rank(_clean(ts3010), ts3010[-1])
    trig = p101 >= TS10_1_PCTILE and p3010 >= TS30_10_PCTILE
    return {"id": "S7", "name": "期限利差", "triggered": trig,
            "detail": f"10-1Y {ts101[-1]:.0f}BP（分位 {p101:.0f}%）、30-10Y {ts3010[-1]:.0f}BP（分位 {p3010:.0f}%）→ {'曲线偏陡，长端性价比抬升' if trig else '利差中性/偏窄'}",
            "strength": "mid" if trig else "direction"}


def calc_s8(h, extras=None):
    """S8 二永债信用利差分位高位（配置/参与信号）。"""
    sp = h.get("credit_spread")
    sp_pct = h.get("credit_spread_pctile")
    sp_clean = _clean(sp) if sp else []
    sp_pct_clean = _clean(sp_pct) if sp_pct else []
    if not sp_clean and not sp_pct_clean:
        return {"id": "S8", "name": "二永债利差高位", "triggered": False,
                "detail": "缺字段 credit_spread / credit_spread_pctile", "strength": "direction"}
    if sp_pct_clean:
        pct = sp_pct_clean[-1]
    else:
        pct = pct_rank(sp_clean, sp_clean[-1])
    trig = pct >= SPREAD_PCTILE_TOP
    return {"id": "S8", "name": "二永债利差高位", "triggered": trig,
            "detail": f"信用利差滚动 1 年分位 {pct:.0f}% vs 见顶阈值 {SPREAD_PCTILE_TOP}% → {'接近见顶，参与信号' if trig else '未达高位'}",
            "strength": "mid" if trig else "direction"}


def calc_s9(h, extras=None):
    """S9 二永债信用利差分位低位（获利了结信号）。"""
    sp = h.get("credit_spread")
    sp_pct = h.get("credit_spread_pctile")
    sp_clean = _clean(sp) if sp else []
    sp_pct_clean = _clean(sp_pct) if sp_pct else []
    if not sp_clean and not sp_pct_clean:
        return {"id": "S9", "name": "二永债利差低位", "triggered": False,
                "detail": "缺字段 credit_spread / credit_spread_pctile", "strength": "direction"}
    if sp_pct_clean:
        pct = sp_pct_clean[-1]
    else:
        pct = pct_rank(sp_clean, sp_clean[-1])
    trig = pct <= SPREAD_PCTILE_BOT
    return {"id": "S9", "name": "二永债利差低位", "triggered": trig,
            "detail": f"信用利差滚动 1 年分位 {pct:.0f}% vs 见底阈值 {SPREAD_PCTILE_BOT}% → {'接近见底，获利了结' if trig else '未达低位'}",
            "strength": "mid" if trig else "direction"}


def calc_s10(h, extras=None):
    """S10 布林带波段（上轨=参与信号）。"""
    sp = h.get("credit_spread")
    if not sp:
        return {"id": "S10", "name": "布林带波段", "triggered": False,
                "detail": "缺字段 credit_spread", "strength": "direction"}
    bb = bollinger(sp)
    if bb is None:
        return {"id": "S10", "name": "布林带波段", "triggered": False,
                "detail": "信用利差数据缺失/序列过短 → 降级未验证", "strength": "direction"}
    upper, lower, latest = bb
    trig = latest >= upper
    return {"id": "S10", "name": "布林带波段", "triggered": trig,
            "detail": f"信用利差 {latest:.0f}BP vs 上轨 {upper:.0f}BP → {'触上轨=超卖=参与信号' if trig else '未触上轨'}",
            "strength": "direction"}


def calc_s11(h, extras=None):
    """S11 品种利差轮动（永续-二债）。"""
    sub = h.get("spread_btn")
    if not sub:
        return {"id": "S11", "name": "品种利差轮动", "triggered": False,
                "detail": "缺字段 spread_btn（永续-二债利差 BP）", "strength": "direction"}
    latest = sub[-1]
    if latest >= SUB_2Y_HIGH:
        trig, act, strength = True, "积极超配永续（弹性 1.4-1.5 倍）", "direction"
    elif latest >= SUB_2Y_MID:
        trig, act, strength = True, "适度超配永续", "direction"
    else:
        trig, act, strength = False, "超额不显著，均衡配置", "direction"
    return {"id": "S11", "name": "品种利差轮动", "triggered": trig,
            "detail": f"永续-二债利差 {latest:.0f}BP → {act}（阈值：>15 积极 / 8-15 适度 / <8 均衡）",
            "strength": strength}


def calc_s12(h, extras=None):
    """S12 机构行为异动（基金净卖出+保险转强=压利差延续；赎回异动=负反馈）。"""
    fund = h.get("fund_netbuy")
    insur = h.get("insur_netbuy")
    if not fund or not insur:
        return {"id": "S12", "name": "机构行为异动", "triggered": False,
                "detail": "缺字段 fund_netbuy / insur_netbuy（亿元）→ 降级未验证", "strength": "direction"}
    fund_clean = _clean(fund)
    insur_last = get(insur)
    if not fund_clean or insur_last is None:
        return {"id": "S12", "name": "机构行为异动", "triggered": False,
                "detail": "机构净买入数据缺失 → 降级未验证", "strength": "direction"}
    fund_last3 = sum(fund_clean[-3:]) if len(fund_clean) >= 3 else sum(fund_clean)
    config_strong = fund_last3 < 0 and insur_last > 0
    redraw = fund_last3 < -500 and insur_last < 0
    if redraw:
        act, trig, strength = "赎回/止损异动 → 负反馈预警，降杠杆增流动性", True, "mid"
    elif config_strong:
        act, trig, strength = "配置盘接力（保险转强）→ 压利差延续，持有", True, "mid"
    else:
        act, trig, strength = "机构行为中性", False, "direction"
    return {"id": "S12", "name": "机构行为异动", "triggered": trig,
            "detail": f"基金近 3 期净买入 {fund_last3:.0f} 亿、保险 {insur_last:.0f} 亿 → {act}",
            "strength": strength}


def calc_s13(h, extras=None):
    """S13 资产性价比排序（10Y 在当前季度区间位置 + 排序）。"""
    c10y = h.get("c10y")
    if not c10y:
        return {"id": "S13", "name": "资产性价比排序", "triggered": False,
                "detail": "缺字段 c10y", "strength": "direction"}
    latest = c10y[-1]
    month = (extras or {}).get("month", 6)
    if month in (6, 7):
        lo, hi, tag = RATE_10Y_Q2L, RATE_10Y_Q2, "6-7 月区间 1.70-1.80%"
    elif month in (8, 9):
        lo, hi, tag = RATE_10Y_Q3L, RATE_10Y_Q3, "8-9 月区间 1.75-1.85%（防守）"
    else:
        lo, hi, tag = RATE_10Y_Q4L, RATE_10Y_Q4, "Q4 区间 1.65-1.75%"
    if latest <= lo + 0.001:
        act = "逼近区间下沿 → 止盈/防回调"
        trig, strength, bias = True, "strong", "short"
    elif latest >= hi - 0.001:
        act = "逼近区间上沿 → 超长/长久期配置价值显现"
        trig, strength, bias = True, "strong", "long"
    else:
        act = "区间中部 → 票息+波段，按排序配置：超长>长久期>普信二永>存单"
        trig, strength, bias = False, "direction", "neutral"
    return {"id": "S13", "name": "资产性价比排序", "triggered": trig,
            "detail": f"10Y {latest*100:.2f}% vs {tag} → {act}",
            "strength": strength, "bias": bias}


# ----------------------------------------------------------------------------
# 信号汇总 → 仓位/结构建议
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    """汇总触发信号 → 久期/杠杆/结构建议（❌ 推断工程化）。"""
    trig = [s for s in signals if s["triggered"]]
    strong = [s["id"] for s in trig if s.get("strength") == "strong"]
    mid = [s["id"] for s in trig if s.get("strength") == "mid"]
    weak = [s["id"] for s in trig if s.get("strength") == "direction"]

    duration = "中性"
    if "S1" in strong or "S2" in strong:
        duration = "缩短久期（防守）"
    elif "S6" in strong or "S13" in strong:
        s13 = [s for s in trig if s["id"] == "S13"]
        if s13 and s13[0].get("bias") == "short":
            duration = "缩短久期（10Y 逼近区间下沿，止盈/防回调）"
        else:
            duration = "拉长久期（配置/进攻）"
    leverage = "中性"
    if "S4" in strong:
        leverage = "降杠杆"
    elif "S3" in mid and "S4" not in strong:
        leverage = "可加杠杆套息"

    structure = []
    if "S13" in strong:
        structure.append("按排序配置：超长期国债 > 长久期国债/政金债 > 普信债/二永债 > 存单")
    if "S8" in mid or "S10" in weak:
        structure.append("二永债利差高位/触上轨 → 参与/配置信号")
    if "S9" in mid:
        structure.append("二永债利差低位 → 获利了结")
    if "S11" in weak:
        structure.append("关注永续-二债品种利差轮动")
    if "S5" in mid:
        structure.append("存单利差脉冲 → 短端配置窗口")
    if "S12" in mid:
        structure.append("机构行为异动（配置盘/赎回）→ 相应调整")

    return {
        "duration": duration,
        "leverage": leverage,
        "structure": structure if structure else ["无强信号，均衡配置"],
        "strong_triggered": strong,
        "mid_triggered": mid,
        "weak_triggered": weak,
    }


# ----------------------------------------------------------------------------
# 报告渲染
# ----------------------------------------------------------------------------

def render_report(signals, positions, data, n_triggered, total):
    as_of = data.get("as_of", "N/A")
    demo = not bool(data.get("_real", False))
    lines = []
    lines.append(f"# 黄伟平框架 · 债市信号报告（截至 {as_of}）")
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
    lines.append(f"- **久期**：{positions['duration']}")
    lines.append(f"- **杠杆**：{positions['leverage']}")
    lines.append("- **结构/品种**：")
    for t in positions["structure"]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("## 三、风险提示")
    lines.append("")
    lines.append("- 本报告为分析参考，非投资建议；阈值来源标注见 references/decision-rules.md。")
    lines.append("- **观点引用**：须注明'截至 {日期} 黄伟平（{任职机构}）观点'；2023.8-2024 属兴业证券、2024 至今属申万宏源。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 输入契约
# ----------------------------------------------------------------------------

def schema():
    return {
        "description": "analyst-fixed-income-huangweiping input schema",
        "history": {
            "required": [
                {"field": "dr001", "description": "DR001 月度均值，最新在末尾"},
                {"field": "dr007", "description": "DR007 月度序列"},
                {"field": "omo7d", "description": "OMO 7 天政策利率序列"},
                {"field": "ncd1y", "description": "1Y AAA 存单利率月度序列"},
                {"field": "c10y", "description": "10Y 国债收益率月度序列"},
                {"field": "c30y", "description": "30Y 国债收益率月度序列"},
                {"field": "credit_spread", "description": "二永债/信用债信用利差（BP）月度序列"},
                {"field": "credit_spread_pctile", "description": "信用利差滚动 1 年分位数（0-100），可选（缺省按序列内分位计算）"},
                {"field": "spread_btn", "description": "永续-二债品种利差（BP）月度序列"},
                {"field": "fund_netbuy", "description": "基金二级净买入（亿元）月度序列"},
                {"field": "insur_netbuy", "description": "保险二级净买入（亿元）月度序列"},
                {"field": "ppi_yoy", "description": "PPI 同比月度序列"},
                {"field": "cpi_yoy", "description": "CPI 同比月度序列"},
                {"field": "sf_yoy", "description": "社融存量同比月度序列"},
            ],
            "optional": [
                {"field": "ts101", "description": "10-1Y 期限利差（BP），缺省由 c10y-c1y 计算"},
                {"field": "ts3010", "description": "30-10Y 期限利差（BP），缺省由 c30y-c10y 计算"},
                {"field": "c1y", "description": "1Y 国债收益率，供期限利差计算"},
            ],
            "format": "字段 -> 月份数组；月份升序，最新值在末尾",
        },
        "extras": {
            "required": [],
            "optional": [
                {"field": "month", "description": "当前月份（1-12），用于 S13 季度区间判断"},
                {"field": "ppi_to_cpi", "description": "PPI→CPI 传导是否启动（bool，人工判定）"},
                {"field": "core_stage", "description": "核心矛盾阶段人工判定（信用收缩/再平衡/物价）"},
            ],
        },
        "_meta": "可选；记录每个字段的数据来源、口径差异和降级方式",
    }


# ----------------------------------------------------------------------------
# 演示模式数据（合成）
# ----------------------------------------------------------------------------

def demo_data():
    """合成演示数据：覆盖每个信号触发/未触发路径。"""
    n = 36
    months = [f"{2023 + (7 + i) // 12}-{(7 + i) % 12 + 1:02d}" for i in range(n)]
    base = {"months": months}

    def wave(freq, phase, amp, trend):
        return [round(trend * i + amp * _m.sin(i / freq + phase), 4) for i in range(n)]

    history = {
        "dr001": wave(6, 0, 0.0004, 0.0008),      # 缓步下行
        "dr007": wave(6, 0.5, 0.0005, 0.0009),
        "omo7d": [0.0150] * n,
        "ncd1y": [round(0.0170 + 0.0012 * _m.sin(i / 5), 4) for i in range(n)],
        "c10y":  [round(0.0190 - 0.0016 * _m.sin(i / 6), 4) for i in range(n)],
        "c30y":  [round(0.0240 - 0.0015 * _m.sin(i / 6), 4) for i in range(n)],
        "c1y":   [round(0.0145 + 0.0005 * _m.sin(i / 5), 4) for i in range(n)],
        "credit_spread": [round(50 + 14 * _m.sin(i / 4 + 1), 1) for i in range(n)],   # 模拟高位区间
        "spread_btn": [round(12 + 6 * _m.sin(i / 3 + 2), 1) for i in range(n)],
        "fund_netbuy": [round(80 * _m.sin(i / 3) - 100, 1) for i in range(n)],
        "insur_netbuy": [round(60 + 30 * _m.sin(i / 4), 1) for i in range(n)],
        "ppi_yoy": [round(-0.012 + 0.0015 * i, 4) for i in range(n)],   # 触底回升
        "cpi_yoy": [round(0.002 + 0.0004 * i, 4) for i in range(n)],
        "sf_yoy": [round(0.105 - 0.0012 * i, 4) for i in range(n)],     # 社融回落
    }
    # 期限利差由收益率派生
    history["ts101"] = [round((a - b) * 10000, 1) for a, b in zip(history["c10y"], history["c1y"])]
    history["ts3010"] = [round((a - b) * 10000, 1) for a, b in zip(history["c30y"], history["c10y"])]
    history["credit_spread_pctile"] = [round(pct_rank(history["credit_spread"][:i + 1], history["credit_spread"][i]), 1) for i in range(n)]

    return {
        "as_of": months[-1] + "-01",
        "history": history,
        "extras": {"month": 8, "ppi_to_cpi": True},
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="黄伟平固收框架信号计算")
    ap.add_argument("--data", help="数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true", help="输出 JSON 格式结果（布尔标志）")
    ap.add_argument("--schema", action="store_true", help="输出输入契约 JSON（布尔标志）")
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
                  calc_s7, calc_s8, calc_s9, calc_s10, calc_s11, calc_s12, calc_s13]
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
