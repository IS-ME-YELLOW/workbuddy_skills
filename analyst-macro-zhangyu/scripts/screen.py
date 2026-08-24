#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
screen.py — 张瑜(华创宏观)框架选股/配置信号计算脚本
=====================================================

将张瑜的宏观框架转化为可执行信号（S1-S12），输出仓位/风格/行业建议。

用法：
    python screen.py                  # 演示模式（内置示例数据，验证流程）
    python screen.py --data macro.json  # 用真实宏观数据文件计算
    python screen.py --data macro.json --json-out  # 输出机器可读 JSON

数据文件字段（JSON，所有序列按月排列，最新值在末尾；as_of 为数据截止日）：
{
  "as_of": "2026-07-31",
  "history": {
    "enterprise_dep_yoy":    [..],  # 非金融企业存款同比(%)
    "resident_dep_yoy":     [..],  # 居民存款同比(%)
    "resident_dep_new_m2":  [..],  # 居民新增存款/新增M2(%)
    "nonbank_dep_yoy":      [..],  # 非银金融机构存款同比(%)
    "m1_yoy_old":           [..],  # M1同比旧口径(%)
    "stock_sharpe":         [..],  # 股票滚动夏普(万得全A)
    "bond_sharpe":          [..],  # 债券滚动夏普(中债总财富)
    "ten_y_yield":          [..],  # 10年期国债收益率(%)
    "div_yield":            [..],  # 万得全A股息率(%)
    "ppi_yoy":              [..],  # PPI同比(%)
    "ind_profit_yoy":       [..],  # 规上工业企业利润同比(%)
    "midstream_demand_yoy": [..],  # 中游需求同比(%)
    "midstream_invest_yoy": [..],  # 中游投资同比(%)
    "coal_price":           [..],  # 煤炭价格(秦皇岛动力煤,元/吨)
    "land_premium":         [..],  # 百城土地溢价率(%)
    "house_excess_return":  [..],  # 居民购房超额收益率(%)
    "gov_lev_growth":       [..],  # 政府杠杆率增速(%)
    "res_lev_growth":       [..],  # 居民杠杆率增速(%)
    "capacity_util":        [..],  # 工业产能利用率(%)
    "policy_bank_gdp_pct":  [..],  # 政策行超额投放/GDP(%)
    "first_tier_house_yoy": [..],  # 一线房价同比(%)
    "giori":                [..]   # GIORI残差
  },
  "extras": {
    "gold_rate_real_rate_decoupled": false  # 金价与美国实际利率是否脱钩
  }
}

依赖：仅标准库。
"""

import argparse
import json
import math
import statistics
import sys

# ---------------------------------------------------------------------------
# 常量与阈值（源自 decision-rules.md）
#
# 参数来源分级（与 references/decision-rules.md 顶部图例一致）：
#   ✅ 原文  = 张瑜公开研究/报告中明确给出的数值或口径
#   ⚠️ 外推  = 有公开依据但具体数值/分档未经逐字核对，属合理近似
#   ❌ 推断  = 张瑜未公布，为实现"可脚本化"而作的假设（最小假设，可替换）
# ---------------------------------------------------------------------------
SCISSORS_SLOPE_WINDOW = 3          # ❌ 推断：剪刀差斜率确认窗口(月)，原文未公布
SCISSORS_CONFIRM_MONTHS = 3        # ❌ 推断："连续N>=3"中N=3为最小假设
THREE_ARROWS_FLOW_PCT = 30.0       # ❌ 推断：三支箭"花"阶段的分位阈值(%)
SHARPE_HIGH_PCT = 70.0             # ⚠️ 外推："高位"分位口径公开，具体70%为合理近似
YIELD_LOW_PCT = 30.0              # ⚠️ 外推："深负"分位口径公开，具体30%为合理近似
FIVE_SIGNAL_OFFENSIVE = 4         # ⚠️ 外推：五信号进攻档（原文方向，档位为设计）
FIVE_SIGNAL_DEFENSIVE = 1         # ⚠️ 外推：五信号防御档（同上）
GOLD_STRATEGIC_PCT = 5.0          # ❌ 推断：黄金战略仓位比例(%)
GOLD_HIGH_PCT = 80.0              # ⚠️ 外推：GIORI高位分位阈值
COAL_BREAKOUT_WINDOW = 6          # ❌ 推断：煤价新高回看窗口(月)
COAL_MOM_THRESHOLD = 3.0          # ❌ 推断：煤价环比异动阈值(%)，原文无量化口径
POLICY_BANK_GDP_THRESHOLD = 0.8   # ✅ 原文：政策行超额投放>0.8-1% GDP
HOUSE_STABLE_THRESHOLD = -1.0     # ⚠️ 外推：一线房价企稳阈值(同比>-1%)


# ---------------------------------------------------------------------------
# 基础工具函数
# ---------------------------------------------------------------------------
def _is_number(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def percentile_rank(value, series):
    """value 在历史序列中的分位(0-100)。"""
    vals = sorted(v for v in series if _is_number(v))
    if not vals:
        return 50.0
    below = sum(1 for v in vals if v <= value)
    return 100.0 * below / len(vals)


def linear_slope(series, window=3):
    """近 window 期线性回归斜率。"""
    seg = [v for v in series[-window:] if _is_number(v)]
    if len(seg) < 2:
        return 0.0
    xs = list(range(len(seg)))
    mx = statistics.mean(xs)
    my = statistics.mean(seg)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, seg))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def consecutive_direction(series, direction="up"):
    """从序列末尾起，连续向上/向下的月数。"""
    if len(series) < 2:
        return 0
    count = 0
    for i in range(len(series) - 1, 0, -1):
        a, b = series[i], series[i - 1]
        if direction == "up" and a >= b:
            count += 1
        elif direction == "down" and a <= b:
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# 规则 1：企业居民存款剪刀差择时（S1/S2）
# ---------------------------------------------------------------------------
def calc_scissors_diff(enterprise_dep_yoy, resident_dep_yoy):
    """
    剪刀差 = 企业存款同比 - 居民存款同比。
    领先 PMI ~6个月、万得全A净利润 ~12个月、PPI ~9-12个月（✅原文）。
    """
    scissors = [e - r for e, r in zip(enterprise_dep_yoy, resident_dep_yoy)]
    latest = scissors[-1]
    slope = linear_slope(scissors, SCISSORS_SLOPE_WINDOW)
    up_months = consecutive_direction(scissors, "up")
    down_months = consecutive_direction(scissors, "down")
    pct = percentile_rank(latest, scissors)

    if slope > 0 and up_months >= SCISSORS_CONFIRM_MONTHS:
        state = "rising_confirmed"
    elif slope > 0 and up_months > 0:
        state = "rising_pending"
    elif slope < 0 and down_months >= SCISSORS_CONFIRM_MONTHS:
        state = "falling_confirmed"
    elif slope < 0 and down_months > 0:
        state = "falling_pending"
    else:
        state = "sideways"

    return {
        "series": scissors, "latest": latest, "percentile": pct,
        "slope": slope, "up_months": up_months, "down_months": down_months,
        "state": state,
    }


# ---------------------------------------------------------------------------
# 规则 2：存款搬家三支箭（S10）
# ---------------------------------------------------------------------------
def calc_three_arrows(resident_dep_new_m2):
    """
    居民新增存款/新增M2 的阶段判断（✅原文，看股做债系列2025.6-7）。
    高位=超额存，回落中=正常存，低位=花。
    """
    latest = resident_dep_new_m2[-1]
    pct = percentile_rank(latest, resident_dep_new_m2)
    slope = linear_slope(resident_dep_new_m2, 3)

    if pct < THREE_ARROWS_FLOW_PCT and slope < 0:
        stage = "spend"
    elif slope < 0 and pct <= 70:
        stage = "normal_save"
    else:
        stage = "excess_save"

    stage_cn = {"excess_save": "超额存", "normal_save": "正常存", "spend": "花"}.get(stage, stage)
    return {"latest": latest, "percentile": pct, "slope": slope,
            "stage": stage, "stage_cn": stage_cn}


# ---------------------------------------------------------------------------
# 规则 3：股债配置天平（S5）
# ---------------------------------------------------------------------------
def calc_sharpe_yield_spread(stock_sharpe, bond_sharpe, ten_y_yield, div_yield):
    """
    夏普差 = 股票夏普 - 债券夏普；收益差 = 10Y国债 - 股息率（✅原文）。
    """
    sharpe_diff = [s - b for s, b in zip(stock_sharpe, bond_sharpe)]
    yield_diff = [t - d for t, d in zip(ten_y_yield, div_yield)]

    sharpe_latest = sharpe_diff[-1]
    yield_latest = yield_diff[-1]
    sharpe_pct = percentile_rank(sharpe_latest, sharpe_diff)
    yield_pct = percentile_rank(yield_latest, yield_diff)

    if sharpe_pct > SHARPE_HIGH_PCT and yield_pct < YIELD_LOW_PCT:
        quadrant = "awakening"
    elif sharpe_pct > SHARPE_HIGH_PCT:
        quadrant = "equity_advantage"
    elif sharpe_pct < YIELD_LOW_PCT and yield_pct > SHARPE_HIGH_PCT:
        quadrant = "bond_advantage"
    elif yield_pct < YIELD_LOW_PCT:
        quadrant = "equity_dip"
    else:
        quadrant = "balanced"

    return {
        "sharpe_diff": sharpe_latest, "sharpe_pct": sharpe_pct,
        "yield_diff": yield_latest, "yield_pct": yield_pct,
        "quadrant": quadrant,
    }


# ---------------------------------------------------------------------------
# 规则 4：三螺旋五信号计分板（S3/S4）
# ---------------------------------------------------------------------------
def calc_five_signals(scissors, m1_yoy_old, ppi_yoy, first_tier_house_yoy,
                      policy_bank_gdp_pct, capacity_util):
    """
    五大解套信号（✅原文，《解开三螺旋》2024.11）：
    ① 财政乘数回升 ② 剪刀差回升 ③ M1真实回升(旧口径)
    ④ 一线房价企稳 ⑤ PPI同比转正
    """
    details = {}

    # ① 财政（政策行投放/GDP 趋升且 >0.8% ✅原文阈值）
    pb_slope = linear_slope(policy_bank_gdp_pct, 3)
    pb_latest = policy_bank_gdp_pct[-1]
    sig1 = pb_slope > 0 and pb_latest > POLICY_BANK_GDP_THRESHOLD
    details["fiscal"] = {"triggered": sig1, "latest": pb_latest, "slope": pb_slope}

    # ② 剪刀差
    sig2 = scissors["state"] in ("rising_confirmed", "rising_pending")
    details["scissors"] = {"triggered": sig2, "state": scissors["state"]}

    # ③ M1 旧口径
    m1_slope = linear_slope(m1_yoy_old, 3)
    sig3 = m1_slope > 0
    details["m1"] = {"triggered": sig3, "latest": m1_yoy_old[-1], "slope": m1_slope}

    # ④ 一线房价企稳（⚠️外推：同比>-1%且斜率向上）
    house_latest = first_tier_house_yoy[-1]
    house_slope = linear_slope(first_tier_house_yoy, 3)
    sig4 = house_latest > HOUSE_STABLE_THRESHOLD and house_slope > 0
    details["house"] = {"triggered": sig4, "latest": house_latest, "slope": house_slope}

    # ⑤ PPI 转正
    ppi_latest = ppi_yoy[-1]
    sig5 = ppi_latest > 0
    details["ppi"] = {"triggered": sig5, "latest": ppi_latest}

    count = sum(1 for v in details.values() if v["triggered"])
    return {"count": count, "details": details}


# ---------------------------------------------------------------------------
# 规则 6：央行降息条件（S7）
# ---------------------------------------------------------------------------
def calc_rate_cut_condition(ppi_yoy, ind_profit_yoy):
    """
    降息必要条件（✅原文，2026.3金融数据点评）：
    PPI 同比回落 + 工业企业利润同比转负 同时满足。
    """
    ppi_latest = ppi_yoy[-1]
    ppi_prev = ppi_yoy[-2] if len(ppi_yoy) >= 2 else ppi_latest
    ppi_falling = ppi_latest < ppi_prev
    profit_negative = ind_profit_yoy[-1] < 0
    triggered = ppi_falling and profit_negative
    return {
        "ppi_latest": ppi_latest, "ppi_falling": ppi_falling,
        "profit_yoy": ind_profit_yoy[-1], "profit_negative": profit_negative,
        "triggered": triggered,
    }


# ---------------------------------------------------------------------------
# 规则 5：中游供需状态（S8）
# ---------------------------------------------------------------------------
def calc_midstream_balance(midstream_demand_yoy, midstream_invest_yoy):
    """
    中游供需状态 = 需求同比 - 投资同比（⚠️外推：构造思路✅原文，公式为合理近似）。
    持续为正 = 中游景气上行。
    """
    balance = [d - inv for d, inv in zip(midstream_demand_yoy, midstream_invest_yoy)]
    latest = balance[-1]
    recent = balance[-3:] if len(balance) >= 3 else balance
    all_positive = all(v > 0 for v in recent)
    return {
        "latest": latest, "all_positive_recent": all_positive,
        "triggered": all_positive and latest > 0,
    }


# ---------------------------------------------------------------------------
# 规则 9：煤价异动（S9）
# ---------------------------------------------------------------------------
def calc_coal_signal(coal_price):
    """
    煤价向上异动：近期新高 + 环比涨幅超阈值（❌推断：异动无量化口径）。
    煤价 = "吹哨人"，股债趋势切换最领先信号（✅原文角色）。
    """
    latest = coal_price[-1]
    window = min(COAL_BREAKOUT_WINDOW, len(coal_price))
    recent_max = max(coal_price[-window:])
    is_new_high = latest >= recent_max
    prev = coal_price[-2] if len(coal_price) >= 2 else latest
    mom_change = (latest - prev) / prev * 100 if prev else 0.0
    triggered = is_new_high and mom_change > COAL_MOM_THRESHOLD
    return {
        "latest": latest, "recent_max": recent_max,
        "is_new_high": is_new_high, "mom_change_pct": mom_change,
        "triggered": triggered,
    }


# ---------------------------------------------------------------------------
# 规则 7：地产双信心（S11）
# ---------------------------------------------------------------------------
def calc_real_estate_signal(land_premium, house_excess_return):
    """
    土地溢价率回升（开发商信心）+ 购房超额收益率转正（居民信心）
    双正 = 地产循环重启（✅原文，2023.9演讲）。
    """
    land_latest = land_premium[-1]
    land_slope = linear_slope(land_premium, 3)
    land_positive = land_latest > 0 and land_slope > 0

    house_latest = house_excess_return[-1]
    house_positive = house_latest > 0

    both_positive = land_positive and house_positive
    return {
        "land_premium": land_latest, "land_slope": land_slope,
        "land_positive": land_positive,
        "house_excess_return": house_latest, "house_positive": house_positive,
        "both_positive": both_positive,
    }


# ---------------------------------------------------------------------------
# 规则 8：黄金 GIORI（S12）
# ---------------------------------------------------------------------------
def calc_gold_signal(giori, extras):
    """
    GIORI = 金价 OLS 回归残差（R²=0.64 ✅原文）。
    高分位 + 金价与实际利率脱钩 → 十年战略看多（✅原文方向）。
    """
    latest = giori[-1]
    pct = percentile_rank(latest, giori)
    decoupled = extras.get("gold_rate_real_rate_decoupled", False)
    triggered = pct > GOLD_HIGH_PCT and decoupled
    return {
        "giori": latest, "percentile": pct,
        "decoupled": decoupled, "triggered": triggered,
    }


# ---------------------------------------------------------------------------
# 规则 10：杠杆率增速差（S6）
# ---------------------------------------------------------------------------
def calc_leverage_spread(gov_lev_growth, res_lev_growth):
    """
    政府杠杆率增速 - 居民杠杆率增速（✅原文）。
    转负之前，债券无趋势性大反转风险。
    """
    spread = [g - r for g, r in zip(gov_lev_growth, res_lev_growth)]
    latest = spread[-1]
    triggered = latest < 0
    return {"spread": latest, "triggered": triggered}


# ---------------------------------------------------------------------------
# 信号聚合（S1-S12）
# ---------------------------------------------------------------------------
def aggregate_signals(scissors, arrows, sharpe_yield, five_sigs, rate_cut,
                      midstream, coal, real_estate, gold, leverage):
    signals = []
    def s(sid, name, triggered, strength, action, detail):
        return {"id": sid, "name": name, "triggered": triggered,
                "strength": strength, "action": action, "detail": detail}

    signals.append(s("S1", "剪刀差回升确认",
                     scissors["state"] == "rising_confirmed", "strong",
                     "权益前瞻建仓（领先利润12月）",
                     f"剪刀差 {scissors['latest']:.2f}%，斜率{scissors['slope']:+.3f}，连续回升{scissors['up_months']}月"))

    signals.append(s("S2", "剪刀差见顶回落确认",
                     scissors["state"] == "falling_confirmed", "strong",
                     "权益减仓预警（领先利润顶12月）",
                     f"剪刀差 {scissors['latest']:.2f}%，斜率{scissors['slope']:+.3f}，连续回落{scissors['down_months']}月"))

    signals.append(s("S3", "三螺旋五信号>=4个",
                     five_sigs["count"] >= FIVE_SIGNAL_OFFENSIVE, "strong",
                     "权益仓位进攻档",
                     f"五信号兑现 {five_sigs['count']}/5"))

    signals.append(s("S4", "三螺旋五信号<=1个",
                     five_sigs["count"] <= FIVE_SIGNAL_DEFENSIVE, "strong",
                     "权益仓位防御档",
                     f"五信号兑现 {five_sigs['count']}/5"))

    signals.append(s("S5", "股债配置天平-觉醒象限",
                     sharpe_yield["quadrant"] == "awakening", "strong",
                     "超配股+红利/类固收+",
                     f"夏普差{sharpe_yield['sharpe_diff']:.2f}({sharpe_yield['sharpe_pct']:.0f}%分位)/收益差{sharpe_yield['yield_diff']:.2f}%({sharpe_yield['yield_pct']:.0f}%分位)"))

    signals.append(s("S6", "杠杆率增速差转负",
                     leverage["triggered"], "strong",
                     "债券趋势熊预警，撤久期防守",
                     f"增速差{leverage['spread']:+.2f}%"))

    signals.append(s("S7", "PPI回落+利润转负",
                     rate_cut["triggered"], "strong",
                     "债券久期进攻",
                     f"PPI{rate_cut['ppi_latest']:.1f}%(回落:{rate_cut['ppi_falling']})/利润{rate_cut['profit_yoy']:.1f}%"))

    signals.append(s("S8", "中游供需状态持续为正",
                     midstream["triggered"], "medium",
                     "超配中游装备制造",
                     f"供需差{midstream['latest']:.2f}%(近3月全正:{midstream['all_positive_recent']})"))

    signals.append(s("S9", "煤价向上异动",
                     coal["triggered"], "medium",
                     "周期进攻+股债趋势切换预警",
                     f"煤价{coal['latest']:.0f}(新高:{coal['is_new_high']})/环比{coal['mom_change_pct']:+.1f}%"))

    signals.append(s("S10", "三支箭进入'花'阶段",
                     arrows["stage"] == "spend", "medium",
                     "高beta成长/券商；债仓降档",
                     f"居民存款/M2 {arrows['latest']:.1f}%({arrows['percentile']:.0f}%分位)→{arrows['stage_cn']}"))

    signals.append(s("S11", "土地溢价率+购房超额收益率双正",
                     real_estate["both_positive"], "medium",
                     "地产链配置解锁",
                     f"土地溢价率{real_estate['land_premium']:.2f}%(正:{real_estate['land_positive']})/购房超额收益率{real_estate['house_excess_return']:.2f}%(正:{real_estate['house_positive']})"))

    signals.append(s("S12", "GIORI高分位+金价实际利率脱钩",
                     gold["triggered"], "medium",
                     f"黄金战略配置(~{GOLD_STRATEGIC_PCT}%)",
                     f"GIORI{gold['giori']:.2f}({gold['percentile']:.0f}%分位)/脱钩:{gold['decoupled']}"))

    return signals


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------
def render_report(data, scissors, arrows, sharpe_yield, five_sigs, rate_cut,
                  midstream, coal, real_estate, gold, leverage, signals, demo=False):
    lines = []
    lines.append(f"# 张瑜框架 · 宏观资金流信号报告（截至 {data.get('as_of', 'N/A')}）")
    if demo:
        lines.append("")
        lines.append("> ⚠️ 数据来源：**演示模式（合成数据）**，仅用于验证流程，非真实宏观数据。请用 --data 传入真实数据。")
    lines.append("")

    # 一、剪刀差
    lines.append("## 一、企业居民存款剪刀差（核心指标）")
    lines.append(f"- 剪刀差：**{scissors['latest']:.2f}%**，历史分位 {scissors['percentile']:.0f}%")
    lines.append(f"- 斜率（近{SCISSORS_SLOPE_WINDOW}月）：{scissors['slope']:+.3f}，连续回升 {scissors['up_months']} 月 / 连续回落 {scissors['down_months']} 月")
    state_map = {
        "rising_confirmed": "✅ 回升确认（权益前瞻建仓信号）",
        "rising_pending": "⏳ 回升中（未达3月确认窗口）",
        "falling_confirmed": "⚠️ 见顶回落确认（减仓预警）",
        "falling_pending": "⚠️ 回落中（未达确认窗口）",
        "sideways": "➡️ 低位徘徊/横盘",
    }
    lines.append(f"- 状态：**{state_map.get(scissors['state'], scissors['state'])}**")
    lines.append("- 领先性：领先 PMI ~6个月、万得全A净利润 ~12个月、PPI ~9-12个月（✅原文）")
    lines.append("")

    # 二、三支箭
    lines.append("## 二、存款搬家三支箭")
    lines.append(f"- 居民新增存款/新增M2：**{arrows['latest']:.1f}%**，历史分位 {arrows['percentile']:.0f}%")
    lines.append(f"- 阶段：**{arrows['stage_cn']}**（斜率 {arrows['slope']:+.3f}）")
    lines.append("")

    # 三、股债天平
    lines.append("## 三、股债配置天平")
    lines.append(f"- 股债夏普比率差：**{sharpe_yield['sharpe_diff']:.2f}**，十年分位 {sharpe_yield['sharpe_pct']:.0f}%")
    lines.append(f"- 债股收益差：**{sharpe_yield['yield_diff']:.2f}%**，十年分位 {sharpe_yield['yield_pct']:.0f}%")
    q_map = {
        "awakening": "★ 股权觉醒象限（超配股+红利/类固收+）",
        "equity_advantage": "股优于债",
        "bond_advantage": "债优于股",
        "equity_dip": "逢低布局权益",
        "balanced": "均衡配置",
    }
    lines.append(f"- 象限：**{q_map.get(sharpe_yield['quadrant'], sharpe_yield['quadrant'])}**")
    lines.append("")

    # 四、五信号
    lines.append("## 四、三螺旋五信号计分板")
    lines.append(f"- 兑现：**{five_sigs['count']}/5**")
    label_map = {"fiscal": "①财政乘数回升", "scissors": "②剪刀差回升",
                 "m1": "③M1真实回升(旧口径)", "house": "④一线房价企稳", "ppi": "⑤PPI同比转正"}
    for k, v in five_sigs["details"].items():
        mark = "✅" if v["triggered"] else "❌"
        extra = ""
        if "latest" in v:
            extra = f"（{v['latest']:.2f}）"
        lines.append(f"  - {mark} {label_map.get(k, k)} {extra}")
    lines.append("")

    # 五、中游
    lines.append("## 五、中游供需状态")
    lines.append(f"- 供需差（需求同比−投资同比）：**{midstream['latest']:.2f}%**")
    lines.append(f"- 近3月持续为正：{'是' if midstream['all_positive_recent'] else '否'}")
    lines.append("")

    # 六、其他
    lines.append("## 六、其他关键指标")
    lines.append(f"- 央行降息条件：PPI {rate_cut['ppi_latest']:.1f}%（回落:{rate_cut['ppi_falling']}）+ 利润 {rate_cut['profit_yoy']:.1f}%（转负:{rate_cut['profit_negative']}）→ {'**触发**' if rate_cut['triggered'] else '未触发'}")
    lines.append(f"- 杠杆率增速差：{leverage['spread']:+.2f}% → {'**转负（债熊预警）**' if leverage['triggered'] else '未转负（债无趋势熊风险）'}")
    lines.append(f"- 煤价：{coal['latest']:.0f}（近期新高:{coal['is_new_high']}，环比 {coal['mom_change_pct']:+.1f}%）→ {'**异动**' if coal['triggered'] else '无异动'}")
    lines.append(f"- 地产双信心：土地溢价率 {real_estate['land_premium']:.2f}% + 购房超额收益率 {real_estate['house_excess_return']:.2f}% → {'**双正（地产链解锁）**' if real_estate['both_positive'] else '未双正'}")
    lines.append(f"- GIORI：{gold['giori']:.2f}（{gold['percentile']:.0f}%分位），脱钩:{gold['decoupled']} → {'**战略配置**' if gold['triggered'] else '不触发'}")
    lines.append("")

    # 七、信号
    lines.append("## 七、信号汇总（S1-S12）")
    triggered = [sig for sig in signals if sig["triggered"]]
    lines.append(f"- 触发 {len(triggered)}/{len(signals)} 条：{', '.join(sig['id'] for sig in triggered) if triggered else '无'}")
    for sig in triggered:
        lines.append(f"  - **{sig['id']}** [{sig['strength']}] {sig['name']} → {sig['action']}（{sig['detail']}）")
    lines.append("")

    # 八、综合建议
    lines.append("## 八、综合建议")
    strong_bull = any(sig["id"] in ("S1", "S3", "S5") for sig in triggered)
    strong_bear = any(sig["id"] in ("S2", "S4", "S6") for sig in triggered)
    rate_cut_sig = any(sig["id"] == "S7" for sig in triggered)
    midstream_sig = any(sig["id"] == "S8" for sig in triggered)
    arrows_sig = any(sig["id"] == "S10" for sig in triggered)
    gold_sig = any(sig["id"] == "S12" for sig in triggered)

    if strong_bull and not strong_bear:
        lines.append("- 仓位：**进攻档**（剪刀差回升+五信号>=4/夏普背离 → 权益前瞻性建仓/进攻）")
    elif strong_bear and not strong_bull:
        lines.append("- 仓位：**防御档**（剪刀差回落/五信号<=1 → 权益降仓、债性资产/高股息防守）")
    elif strong_bull and strong_bear:
        lines.append("- 仓位：**分歧档**（信号矛盾，减仓观望，等待方向明确）")
    else:
        lines.append("- 仓位：**中性/标准**（~50%，均衡配置，等待信号强化）")

    if rate_cut_sig:
        lines.append("- 股债：降息条件触发 → **债券久期进攻**；若降息落地+剪刀差同步回升 → 减持债券转权益")
    elif arrows_sig:
        lines.append("- 股债：三支箭进入'花'阶段 → **不出现股债双牛，股牛债偏熊** → 债仓降至防守档")
    else:
        lines.append("- 股债：杠杆率增速差未转负 → 债券无趋势性熊市（只做波段不做空）")

    if midstream_sig:
        lines.append("- 行业：中游供需状态持续为正 → **超配中游装备制造**（机械/电力设备/汽车/电子制造）")
    else:
        lines.append("- 行业：中游>消费>上游（排序待信号确认）；上游过剩原材料规避")

    if scissors["state"] in ("rising_confirmed", "rising_pending"):
        lines.append("- 风格：**创业板>宽基**（新经济权重高，剪刀差回升利好成长）")
    else:
        lines.append("- 风格：均衡/价值防守")

    if gold_sig:
        lines.append(f"- 黄金：GIORI历史高分位+脱钩 → **战略配置（~{GOLD_STRATEGIC_PCT}%）**，十年维度看多")

    lines.append("")
    lines.append("> 说明：观点为时效信息，最新张瑜观点见 assets/views.md；信号与观点冲突时优先遵循信号并说明分歧。")
    lines.append("> 参数来源标注：✅原文 / ⚠️外推 / ❌推断，详见 references/decision-rules.md。")
    lines.append("> 本报告为分析参考，非投资建议。A 股惯例：涨红跌绿。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 演示数据（48个月，含 2024.8-2026.5 剪刀差回升叙事）
# ---------------------------------------------------------------------------
def demo_data():
    import random
    rng = random.Random(42)
    n = 48
    t = list(range(n))

    # 企业存款同比：t=24(2024.8)见底后回升
    ent_dep = [10.5 - 0.25 * min(x, 24) + 0.3 * max(0, x - 24) + rng.uniform(-0.4, 0.4) for x in t]
    # 居民存款同比：高位加速回落
    res_dep = [13.0 - 0.12 * min(x, 24) - 0.25 * max(0, x - 24) + rng.uniform(-0.3, 0.3) for x in t]
    # 居民存款/M2：高位回落至低位
    dep_m2 = [55 - 0.5 * x + rng.uniform(-2, 2) for x in t]
    # 非银存款
    nonbank = [8 + 0.4 * x + 3 * math.sin(x / 8) + rng.uniform(-1, 1) for x in t]
    # M1旧口径：低位震荡后回升
    m1_old = [2.0 + 0.05 * x + 1.2 * math.sin(x / 10) + rng.uniform(-0.3, 0.3) for x in t]
    # 夏普
    stock_sh = [0.2 + 0.03 * x + 0.5 * math.sin(x / 12) + rng.uniform(-0.1, 0.1) for x in t]
    bond_sh = [0.3 + 0.01 * x + 0.3 * math.sin(x / 14) + rng.uniform(-0.05, 0.05) for x in t]
    # 利率
    ten_y = [2.55 - 0.02 * x + rng.uniform(-0.05, 0.05) for x in t]
    div = [2.4 + 0.015 * x + rng.uniform(-0.06, 0.06) for x in t]
    # PPI
    ppi = [-3.0 + 0.1 * x + 1.5 * math.sin(x / 8) + rng.uniform(-0.3, 0.3) for x in t]
    # 工业利润
    profit = [-5 + 0.4 * x + 5 * math.sin(x / 10) + rng.uniform(-2, 2) for x in t]
    # 中游
    mid_dem = [6 + 0.05 * x + 2 * math.sin(x / 9) + rng.uniform(-0.5, 0.5) for x in t]
    mid_inv = [5 + 0.02 * x + 1.5 * math.sin(x / 11) + rng.uniform(-0.4, 0.4) for x in t]
    # 煤价
    coal = [750 + 30 * math.sin(x / 10) + 2 * x + rng.uniform(-15, 15) for x in t]
    # 土地溢价率
    land = [3.5 + 0.5 * math.sin(x / 8) - 0.05 * x + rng.uniform(-0.5, 0.5) for x in t]
    # 购房超额收益率
    house_ex = [-3.0 + 0.08 * x + 0.5 * math.sin(x / 9) + rng.uniform(-0.3, 0.3) for x in t]
    # 杠杆率增速
    gov_lev = [3.5 + 0.3 * math.sin(x / 12) + rng.uniform(-0.2, 0.2) for x in t]
    res_lev = [1.5 + 0.2 * math.sin(x / 14) + rng.uniform(-0.15, 0.15) for x in t]
    # 产能利用率
    cap = [74.5 + 0.5 * math.sin(x / 10) + 0.03 * x + rng.uniform(-0.3, 0.3) for x in t]
    # 政策行/GDP
    pb_gdp = [0.5 + 0.02 * x + 0.15 * math.sin(x / 8) + rng.uniform(-0.05, 0.05) for x in t]
    # 一线房价
    house_yoy = [-5.0 + 0.1 * x + 1.5 * math.sin(x / 9) + rng.uniform(-0.5, 0.5) for x in t]
    # GIORI
    giori = [0.5 + 0.04 * x + 0.3 * math.sin(x / 15) + rng.uniform(-0.1, 0.1) for x in t]

    return {
        "as_of": "2026-07-31",
        "history": {
            "enterprise_dep_yoy": ent_dep, "resident_dep_yoy": res_dep,
            "resident_dep_new_m2": dep_m2, "nonbank_dep_yoy": nonbank,
            "m1_yoy_old": m1_old, "stock_sharpe": stock_sh, "bond_sharpe": bond_sh,
            "ten_y_yield": ten_y, "div_yield": div, "ppi_yoy": ppi,
            "ind_profit_yoy": profit, "midstream_demand_yoy": mid_dem,
            "midstream_invest_yoy": mid_inv, "coal_price": coal,
            "land_premium": land, "house_excess_return": house_ex,
            "gov_lev_growth": gov_lev, "res_lev_growth": res_lev,
            "capacity_util": cap, "policy_bank_gdp_pct": pb_gdp,
            "first_tier_house_yoy": house_yoy, "giori": giori,
        },
        "extras": {"gold_rate_real_rate_decoupled": True},
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="张瑜框架宏观资金流信号计算")
    ap.add_argument("--data", help="宏观数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true", help="输出 JSON 格式结果")
    args = ap.parse_args()

    data = demo_data() if not args.data else json.load(open(args.data, encoding="utf-8"))
    h = data["history"]
    extras = data.get("extras", {})

    scissors = calc_scissors_diff(h["enterprise_dep_yoy"], h["resident_dep_yoy"])
    arrows = calc_three_arrows(h["resident_dep_new_m2"])
    sharpe_yield = calc_sharpe_yield_spread(h["stock_sharpe"], h["bond_sharpe"],
                                            h["ten_y_yield"], h["div_yield"])
    five_sigs = calc_five_signals(scissors, h["m1_yoy_old"], h["ppi_yoy"],
                                  h["first_tier_house_yoy"],
                                  h["policy_bank_gdp_pct"], h["capacity_util"])
    rate_cut = calc_rate_cut_condition(h["ppi_yoy"], h["ind_profit_yoy"])
    midstream = calc_midstream_balance(h["midstream_demand_yoy"], h["midstream_invest_yoy"])
    coal = calc_coal_signal(h["coal_price"])
    real_estate = calc_real_estate_signal(h["land_premium"], h["house_excess_return"])
    gold = calc_gold_signal(h["giori"], extras)
    leverage = calc_leverage_spread(h["gov_lev_growth"], h["res_lev_growth"])
    signals = aggregate_signals(scissors, arrows, sharpe_yield, five_sigs, rate_cut,
                                midstream, coal, real_estate, gold, leverage)

    if args.json_out:
        out = {
            "as_of": data.get("as_of"), "demo": not args.data,
            "scissors_diff": scissors, "three_arrows": arrows,
            "sharpe_yield": sharpe_yield, "five_signals": five_sigs,
            "rate_cut": rate_cut, "midstream": midstream, "coal": coal,
            "real_estate": real_estate, "gold": gold, "leverage": leverage,
            "signals": signals,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render_report(data, scissors, arrows, sharpe_yield, five_sigs, rate_cut,
                            midstream, coal, real_estate, gold, leverage, signals,
                            demo=not args.data))


if __name__ == "__main__":
    sys.exit(main())
