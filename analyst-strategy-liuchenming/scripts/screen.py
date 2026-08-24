#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst-strategy-liuchenming 信号计算脚本
============================================================
刘晨明（广发证券首席策略分析师）框架的工程化信号实现。
阈值与 references/decision-rules.md 逐条对应（双向核对）。

运行方式：
  python screen.py                       # 演示模式（合成数据）
  python screen.py --data data.json      # 真实数据
  python screen.py --data data.json --json-out   # stdout 输出 JSON（布尔标志）
"""

import argparse
import json
import math as _m


# ============================================================
# 参数区（来源分级：✅ 原文 / ⚠️ 外推 / ❌ 推断 —— 与 decision-rules.md 图例一致）
# ------------------------------------------------------------
# S1 百日趋势线再布局
MA100_TRIG = 1.00        # ✅ 原文：全A跌至100日均线附近/以下（比值≤1.0）= 再布局节点（2026.07 富国演讲）
# S2 二十日均线抄底
MA20_TRIG = 1.00         # ✅ 原文：牛市中跌破20日均线，99次复盘约1周、再跌1%-3%后企稳（2026.03 天玉访谈）
MA20_EXTRA_DD = 0.02     # ✅ 原文：跌破后预期再跌空间约1%-3%（取中值2%作展示）
# S3 成交额占比拥挤度
TMT_HIGH = 40.0          # ✅ 原文：TMT成交占比达40%短期调整概率大，不能再增配（2025.02 澎湃专访）
TMT_BUY_HIGH = 30.0      # ✅ 原文：回落至25%-30%为较佳买点（上沿）
TMT_BUY_LOW = 25.0       # ✅ 原文：买点下沿
# S4 市场反应度二七法则（分资产阈值，%）
REACT_BUY_CYCLE = 20.0   # ✅ 原文：经济周期类超卖买入阈值（二七法则，2024.08 广发策略报告）
REACT_SELL_CYCLE = 70.0  # ✅ 原文：经济周期类超买卖出阈值
REACT_BUY_STABLE = 30.0  # ✅ 原文：稳定价值类买入阈值（三七法则）
REACT_SELL_STABLE = 70.0 # ✅ 原文：稳定价值类卖出阈值
REACT_BUY_GROWTH = 20.0  # ✅ 原文：景气成长类买入阈值
REACT_SELL_GROWTH = 80.0 # ✅ 原文：景气成长类卖点上调至80%以减少踏空
# S5 风格研判
GAP_WIN = 3              # ❌ 推断：差值3个月MA窗口，最小假设，可替换（原文为方向逻辑无固定窗口）
# S6 景气拐点预警
GROWTH_FLOOR = 30.0      # ✅ 原文：增速由高位降至30%以下 → 市场表现显著变差（2026.08）
GROWTH_FALL = 50.0       # ✅ 原文：增速回落幅度超过50% → 显著变差
GROWTH_WIN = 12          # ❌ 推断：高位回看窗口12个月，最小假设，可替换
# S7 渗透率天花板
PEN_WARN = 40.0          # ✅ 原文：渗透率达40%后可能引发股价较长时间滞涨（2026.07）
PEN_ALARM = 50.0         # ✅ 原文：40%-50%区间上沿强警戒
# S8 财政-PPI-ROE 传导
FISCAL_TRIG = 5.0        # ✅ 原文：广义财政占GDP提升不少于5pct才可能带来PPI/ROE上行周期（2024.12/2025.06）
FISCAL_FLOOR = 1.0       # ❌ 推断：1-5pct判为"托底"下限，最小假设（原文案例：+1.5pct=托底）
PPI_CONFIRM_M = 2        # ❌ 推断：PPI连续回升确认窗口2个月，最小假设，可替换
# S9 宽基ETF净流入底部
ETF_INFLOW_TRIG = 300.0  # ✅ 原文：宽基ETF日均净流入300亿级=阶段性底部信号（2026.07 券商中国：305亿=第三高峰）
# S10 主线调整充分性
DD_PCT_TRIG = 19.0       # ✅ 原文：13个主线板块35次调整平均幅度19%（2026.07；另述20%，以原文复核）
DD_MONTH_TRIG = 1        # ✅ 原文：平均持续21个交易日 ≈ 1个月（月度数据近似换算，❌推断标注换算）
# S11 困境反转恢复率
REC_EXCELLENT = 120.0    # ✅ 原文：净利润恢复率优秀线120%（2005-2024分组统计，2025.09 报告）
REC_PASS = 70.0          # ✅ 原文：及格线70%
PB_PCTILE_BONUS = 30.0   # ✅ 原文：PB分位数（10年）<30%作为估值加成限定条件
# S12 红利现金替代
DEPOSIT_TRIG = 1.0       # ✅ 原文：大行1年定存利率破1% → 红利性价比优于现金/定存/理财（2025.06）
DIV_PCTILE_TRIG = 80.0   # ❌ 推断：红利股息率近3年分位≥80%视为低位（"趋势线下沿"定性表述的量化替代，最小假设可替换）
# ============================================================


# ----------------------------------------------------------------------------
# 工具函数（领域无关，通用实现）
# ----------------------------------------------------------------------------

def pct_rank(series, value):
    """value 在 series 中的百分位（0-100）。"""
    if not series:
        return 50.0
    below = sum(1 for x in series if x < value)
    return below / len(series) * 100.0


def trend_up(series, lookback=3):
    """最近 lookback 期是否整体上行。"""
    if len(series) < 2:
        return False
    win = series[-lookback:]
    return win[-1] > win[0]


def recent_avg(series, lookback=3):
    """最近 lookback 期均值。"""
    if not series:
        return 0.0
    win = series[-lookback:]
    return sum(win) / len(win)


def get(h, field):
    """安全取字段；缺失返回 None。"""
    if field in h and h[field]:
        return h[field]
    return None


# ----------------------------------------------------------------------------
# 信号计算函数（契约：输入 h / extras → 返回 dict 四键）
#   id/name/triggered/detail/strength（strength ∈ strong/mid/direction）
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 百日趋势线再布局。"""
    extras = extras or {}
    field = "ratio_ma100"
    s = get(h, field)
    if s is None:
        return {"id": "S1", "name": "百日趋势线再布局", "triggered": False,
                "detail": f"缺字段 {field}（按 decision-rules.md 映射附录补全）", "strength": "direction"}
    latest = s[-1]
    bull = bool(extras.get("bull_market", True))
    swan = bool(extras.get("black_swan", False))
    if latest <= MA100_TRIG:
        if bull and not swan:
            return {"id": "S1", "name": "百日趋势线再布局", "triggered": True,
                    "detail": f"全A/MA100 最新 {latest:.3f} ≤ {MA100_TRIG}（牛市前提成立、无黑天鹅）→ 跌至趋势线=再布局节点",
                    "strength": "strong"}
        return {"id": "S1", "name": "百日趋势线再布局", "triggered": False,
                "detail": f"全A/MA100 最新 {latest:.3f} ≤ {MA100_TRIG}，但牛市前提={bull}、黑天鹅={swan} → 等待企稳",
                "strength": "direction"}
    return {"id": "S1", "name": "百日趋势线再布局", "triggered": False,
            "detail": f"全A/MA100 最新 {latest:.3f} > {MA100_TRIG} → 指数在趋势线上方运行，无再布局信号",
            "strength": "direction"}


def calc_s2(h, extras=None):
    """S2 二十日均线短线抄底。"""
    extras = extras or {}
    field = "ratio_ma20"
    s = get(h, field)
    if s is None:
        return {"id": "S2", "name": "二十日均线抄底", "triggered": False,
                "detail": f"缺字段 {field}", "strength": "direction"}
    latest = s[-1]
    bull = bool(extras.get("bull_market", True))
    if latest < MA20_TRIG and bull:
        return {"id": "S2", "name": "二十日均线抄底", "triggered": True,
                "detail": f"全A/MA20 最新 {latest:.3f} < {MA20_TRIG}（牛市中）→ 短线抄底信号，历史统计约1周、再跌{MA20_EXTRA_DD*100:.0f}%后企稳",
                "strength": "mid"}
    return {"id": "S2", "name": "二十日均线抄底", "triggered": False,
            "detail": f"全A/MA20 最新 {latest:.3f} vs 阈值 {MA20_TRIG}（牛市前提={bull}）→ 未触发",
            "strength": "direction"}


def calc_s3(h, extras=None):
    """S3 成交额占比拥挤度（双向）。"""
    field = "tmt_turnout_pct"
    s = get(h, field)
    if s is None:
        return {"id": "S3", "name": "成交额占比拥挤度", "triggered": False,
                "detail": f"缺字段 {field}", "strength": "direction"}
    latest = s[-1]
    if latest >= TMT_HIGH:
        return {"id": "S3", "name": "成交额占比拥挤度", "triggered": True,
                "detail": f"TMT成交占比最新 {latest:.1f}% ≥ {TMT_HIGH}% → 拥挤度警戒：短期调整概率大，不能再增配（减仓方向）",
                "strength": "strong"}
    if TMT_BUY_LOW <= latest <= TMT_BUY_HIGH:
        return {"id": "S3", "name": "成交额占比拥挤度", "triggered": True,
                "detail": f"TMT成交占比最新 {latest:.1f}% 落入 {TMT_BUY_LOW}-{TMT_BUY_HIGH}% 区间 → 较佳买点（买入方向）",
                "strength": "mid"}
    return {"id": "S3", "name": "成交额占比拥挤度", "triggered": False,
            "detail": f"TMT成交占比最新 {latest:.1f}%（警戒线 {TMT_HIGH}%、买点区 {TMT_BUY_LOW}-{TMT_BUY_HIGH}%）→ 中性区间",
            "strength": "direction"}


def calc_s4(h, extras=None):
    """S4 市场反应度二七法则（按资产类别阈值）。"""
    extras = extras or {}
    focus = extras.get("focus", "growth")
    field = {"cycle": "reaction_cycle", "stable": "reaction_stable", "growth": "reaction_growth"}.get(focus)
    buy_th, sell_th = {
        "cycle": (REACT_BUY_CYCLE, REACT_SELL_CYCLE),
        "stable": (REACT_BUY_STABLE, REACT_SELL_STABLE),
        "growth": (REACT_BUY_GROWTH, REACT_SELL_GROWTH),
    }[focus]
    label = {"cycle": "经济周期类（二七法则）", "stable": "稳定价值类（三七法则）", "growth": "景气成长类（买20卖80）"}[focus]
    s = get(h, field)
    if s is None:
        return {"id": "S4", "name": "市场反应度二七法则", "triggered": False,
                "detail": f"缺字段 {field}", "strength": "direction"}
    latest = s[-1]
    if latest >= sell_th:
        return {"id": "S4", "name": "市场反应度二七法则", "triggered": True,
                "detail": f"{label} 反应度最新 {latest:.0f}% ≥ 卖出阈值 {sell_th}% → 人声鼎沸处，逢高卖出（未来20日低于市场概率~72%）",
                "strength": "strong"}
    if latest < buy_th:
        strength = "mid" if focus != "cycle" else "direction"  # 周期类低位是必要非充分
        note = "（注意：周期类低位买入还需等待宏观政策催化）" if focus == "cycle" else ""
        return {"id": "S4", "name": "市场反应度二七法则", "triggered": True,
                "detail": f"{label} 反应度最新 {latest:.0f}% < 买入阈值 {buy_th}% → 无人问津时，逢低买入（胜率~73.6%、超额~2.8%）{note}",
                "strength": strength}
    return {"id": "S4", "name": "市场反应度二七法则", "triggered": False,
            "detail": f"{label} 反应度最新 {latest:.0f}%（买 {buy_th}% / 卖 {sell_th}%）→ 中性区间（20-60%无显著规律）",
            "strength": "direction"}


def calc_s5(h, extras=None):
    """S5 风格研判：利润增速差值方向。"""
    field = "profit_growth_gap"
    s = get(h, field)
    if s is None:
        return {"id": "S5", "name": "利润增速差值风格", "triggered": False,
                "detail": f"缺字段 {field}", "strength": "direction"}
    cur = recent_avg(s, GAP_WIN)
    prev = recent_avg(s[:-GAP_WIN], GAP_WIN) if len(s) >= 2 * GAP_WIN else None
    latest = s[-1]
    if prev is None:
        return {"id": "S5", "name": "利润增速差值风格", "triggered": False,
                "detail": f"差值最新 {latest:+.1f}pct，数据不足 {2*GAP_WIN} 期无法判趋势", "strength": "direction"}
    if cur > prev:
        return {"id": "S5", "name": "利润增速差值风格", "triggered": True,
                "detail": f"科创创业板-沪深300 增速差 {latest:+.1f}pct，近{GAP_WIN}月均值 {cur:+.1f} > 前{GAP_WIN}月 {prev:+.1f} → 差值扩大，景气成长占优",
                "strength": "direction"}
    return {"id": "S5", "name": "利润增速差值风格", "triggered": True,
            "detail": f"增速差 {latest:+.1f}pct，近{GAP_WIN}月均值 {cur:+.1f} ≤ 前{GAP_WIN}月 {prev:+.1f} → 差值收窄，经济周期/价值类相对占优",
            "strength": "direction"}


def calc_s6(h, extras=None):
    """S6 景气拐点预警（30% / -50% 双经验值）。"""
    field = "profit_growth_tmt"
    s = get(h, field)
    if s is None:
        return {"id": "S6", "name": "景气拐点预警", "triggered": False,
                "detail": f"缺字段 {field}", "strength": "direction"}
    latest = s[-1]
    win = s[-GROWTH_WIN:]
    g_high = max(win) if win else latest
    # ✅ 原文为"增速**由高位**降至30%以下"——须先经历过高位（窗口高点 ≥ 30%）才构成"降至"；
    # 若增速从未达到高位（如长期 <30% 的低景气板块），"低于30%"不触发拐点预警。
    # 高位判定线 = 30%（❌ 推断：与触警线同值，最小假设，可替换）。Phase 4 验证发现并修复。
    cond_low = latest < GROWTH_FLOOR and g_high >= GROWTH_FLOOR
    cond_fall = g_high > 0 and (g_high - latest) / g_high * 100.0 > GROWTH_FALL
    if cond_low or cond_fall:
        why = []
        if cond_low:
            why.append(f"增速 {latest:.1f}% 由高位 {g_high:.1f}% 降至 {GROWTH_FLOOR}% 以下")
        if cond_fall:
            why.append(f"较{GROWTH_WIN}月高点 {g_high:.1f}% 回落 {(g_high-latest)/g_high*100:.0f}% > {GROWTH_FALL}%")
        return {"id": "S6", "name": "景气拐点预警", "triggered": True,
                "detail": " + ".join(why) + " → 景气拐点预警，市场表现将显著变差，规避该主线",
                "strength": "strong"}
    return {"id": "S6", "name": "景气拐点预警", "triggered": False,
            "detail": f"主线增速最新 {latest:.1f}%（窗口高点 {g_high:.1f}%；阈值：由高位降至{GROWTH_FLOOR}%以下或回落超{GROWTH_FALL:.0f}%）→ 产业趋势延续",
            "strength": "direction"}


def calc_s7(h, extras=None):
    """S7 渗透率天花板。"""
    field = "penetration_rate"
    s = get(h, field)
    if s is None:
        return {"id": "S7", "name": "渗透率天花板", "triggered": False,
                "detail": f"缺字段 {field}", "strength": "direction"}
    latest = s[-1]
    if latest >= PEN_ALARM:
        return {"id": "S7", "name": "渗透率天花板", "triggered": True,
                "detail": f"产业渗透率最新 {latest:.1f}% ≥ {PEN_ALARM}% → 强警戒：股价较长时间滞涨风险",
                "strength": "mid"}
    if latest >= PEN_WARN:
        return {"id": "S7", "name": "渗透率天花板", "triggered": True,
                "detail": f"产业渗透率最新 {latest:.1f}% ≥ {PEN_WARN}% → 渗透率进入后半程，降低收益预期",
                "strength": "mid"}
    return {"id": "S7", "name": "渗透率天花板", "triggered": False,
            "detail": f"产业渗透率最新 {latest:.1f}% < {PEN_WARN}% → 早期阶段，空间广阔",
            "strength": "direction"}


def calc_s8(h, extras=None):
    """S8 广义财政→PPI→ROE 传导。"""
    fi = get(h, "fiscal_impulse")
    ppi = get(h, "ppi_yoy")
    if fi is None or ppi is None:
        return {"id": "S8", "name": "财政-PPI-ROE传导", "triggered": False,
                "detail": "缺字段 fiscal_impulse / ppi_yoy", "strength": "direction"}
    fi_now = fi[-1]
    ppi_tail = ppi[-(PPI_CONFIRM_M + 1):]
    ppi_up = len(ppi_tail) >= PPI_CONFIRM_M + 1 and all(
        ppi_tail[i + 1] > ppi_tail[i] for i in range(len(ppi_tail) - 1))
    if fi_now >= FISCAL_TRIG and ppi_up:
        return {"id": "S8", "name": "财政-PPI-ROE传导", "triggered": True,
                "detail": f"广义财政占GDP提升 {fi_now:+.1f}pct ≥ {FISCAL_TRIG}pct 且 PPI 连续{PPI_CONFIRM_M}月回升（最新 {ppi[-1]:.1f}%）→ PPI/ROE上行周期，经济周期类资产反转条件具备",
                "strength": "strong"}
    if fi_now >= FISCAL_FLOOR:
        return {"id": "S8", "name": "财政-PPI-ROE传导", "triggered": False,
                "detail": f"广义财政提升 {fi_now:+.1f}pct（{FISCAL_FLOOR}-{FISCAL_TRIG}pct 区间）→ 托底而非上行周期，周期类资产震荡对待",
                "strength": "direction"}
    return {"id": "S8", "name": "财政-PPI-ROE传导", "triggered": False,
            "detail": f"广义财政提升 {fi_now:+.1f}pct < {FISCAL_FLOOR}pct → 周期类资产继续规避",
            "strength": "direction"}


def calc_s9(h, extras=None):
    """S9 宽基ETF净流入底部信号。"""
    field = "etf_inflow_daily_bn"
    s = get(h, field)
    if s is None:
        return {"id": "S9", "name": "宽基ETF净流入底部", "triggered": False,
                "detail": f"缺字段 {field}", "strength": "direction"}
    latest = s[-1]
    if latest >= ETF_INFLOW_TRIG:
        return {"id": "S9", "name": "宽基ETF净流入底部", "triggered": True,
                "detail": f"宽基ETF日均净流入最新 {latest:.0f} 亿元 ≥ {ETF_INFLOW_TRIG:.0f} 亿 → 历史第三高峰级别（对照：924行情371亿、对等关税期562亿），阶段性底部信号",
                "strength": "strong"}
    return {"id": "S9", "name": "宽基ETF净流入底部", "triggered": False,
            "detail": f"宽基ETF日均净流入最新 {latest:.0f} 亿元 < {ETF_INFLOW_TRIG:.0f} 亿阈值 → 无底部信号",
            "strength": "direction"}


def calc_s10(h, extras=None):
    """S10 主线调整充分性（回撤深度+持续时长）。"""
    field = "tmt_index"
    s = get(h, field)
    if s is None or len(s) < 2:
        return {"id": "S10", "name": "主线调整充分性", "triggered": False,
                "detail": f"缺字段 {field}", "strength": "direction"}
    peak_idx = max(range(len(s)), key=lambda i: s[i])
    # 高点须在序列后半段（当前确处调整中），否则视为创新高
    if peak_idx >= len(s) - 1:
        return {"id": "S10", "name": "主线调整充分性", "triggered": False,
                "detail": f"主线指数最新值即窗口高点 → 无进行中的调整", "strength": "direction"}
    dd_pct = (s[peak_idx] - s[-1]) / s[peak_idx] * 100.0
    dd_months = len(s) - 1 - peak_idx
    ok_pct = dd_pct >= DD_PCT_TRIG
    ok_dur = dd_months >= DD_MONTH_TRIG
    if ok_pct and ok_dur:
        return {"id": "S10", "name": "主线调整充分性", "triggered": True,
                "detail": f"主线自高点回撤 {dd_pct:.1f}%（阈值{DD_PCT_TRIG}%）、持续 {dd_months} 个月（≈{dd_months*21} 交易日，阈值21日）→ 双条件达标，调整充分（历史均值：21个交易日/19%）",
                "strength": "mid"}
    return {"id": "S10", "name": "主线调整充分性", "triggered": False,
            "detail": f"主线自高点回撤 {dd_pct:.1f}%、持续 {dd_months} 个月（阈值 {DD_PCT_TRIG}% / ≥{DD_MONTH_TRIG}个月）→ {'幅度未够' if not ok_pct else ''}{'时长未够' if not ok_dur else ''}调整未充分",
            "strength": "direction"}


def calc_s11(h, extras=None):
    """S11 困境反转恢复率。"""
    rec = get(h, "recovery_np")
    pb = get(h, "pb_pctile")
    if rec is None:
        return {"id": "S11", "name": "困境反转恢复率", "triggered": False,
                "detail": "缺字段 recovery_np", "strength": "direction"}
    latest = rec[-1]
    pb_now = pb[-1] if pb else None
    bonus = pb_now is not None and pb_now < PB_PCTILE_BONUS
    if latest >= REC_EXCELLENT:
        return {"id": "S11", "name": "困境反转恢复率", "triggered": True,
                "detail": f"净利润恢复率 {latest:.0f}% ≥ 优秀线 {REC_EXCELLENT:.0f}%{'+ PB分位 %.0f%%<%.0f%% 估值加成成立' % (pb_now, PB_PCTILE_BONUS) if bonus else '（估值加成未确认）'}→ 反转弹性优选（首选挖坑年不亏损标的）",
                "strength": "strong"}
    if latest >= REC_PASS:
        return {"id": "S11", "name": "困境反转恢复率", "triggered": True,
                "detail": f"净利润恢复率 {latest:.0f}% 在及格线 {REC_PASS:.0f}%-{REC_EXCELLENT:.0f}% 之间 → 表现与市场中位数相当，观察",
                "strength": "direction"}
    return {"id": "S11", "name": "困境反转恢复率", "triggered": False,
            "detail": f"净利润恢复率 {latest:.0f}% < 及格线 {REC_PASS:.0f}% → 收益率明显下滑，规避",
            "strength": "direction"}


def calc_s12(h, extras=None):
    """S12 红利现金替代。"""
    dep = get(h, "deposit_1y")
    div = get(h, "div_yield_pctile")
    if dep is None or div is None:
        return {"id": "S12", "name": "红利现金替代", "triggered": False,
                "detail": "缺字段 deposit_1y / div_yield_pctile", "strength": "direction"}
    dep_now, div_now = dep[-1], div[-1]
    if dep_now < DEPOSIT_TRIG and div_now >= DIV_PCTILE_TRIG:
        return {"id": "S12", "name": "红利现金替代", "triggered": True,
                "detail": f"1年定存利率 {dep_now:.2f}% < {DEPOSIT_TRIG}% 且红利股息率分位 {div_now:.0f}% ≥ {DIV_PCTILE_TRIG:.0f}%（位置低位）→ 红利优于现金/定存/理财（绝对收益逻辑，年化参考~9%）",
                "strength": "mid"}
    return {"id": "S12", "name": "红利现金替代", "triggered": False,
            "detail": f"定存 {dep_now:.2f}%、股息率分位 {div_now:.0f}%（阈值：<{DEPOSIT_TRIG}% 且 ≥{DIV_PCTILE_TRIG}%）→ 未同时满足",
            "strength": "direction"}


# ----------------------------------------------------------------------------
# 信号汇总 → 仓位/结构/配置建议
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    """汇总触发信号 → 仓位/结构建议。

    ⚠️ 仓位档位与加减分幅度为 ❌ 推断工程化设计（最小假设，可替换）：
      刘晨明框架输出为"仓位方向+三类资产结构"，未公布量化仓位公式。
    """
    extras = extras or {}
    trig = [s for s in signals if s["triggered"]]
    strong = [s for s in trig if s.get("strength") == "strong"]
    mid = [s for s in trig if s.get("strength") == "mid"]
    weak = [s for s in trig if s.get("strength") == "direction"]

    equity = 50.0
    # 看多类信号加分（S1/S2/S9 为底部加仓信号）
    for sid in ("S1", "S2", "S9"):
        if any(s["id"] == sid for s in trig):
            equity += 10.0
    # 基本面传导确认加分
    if any(s["id"] == "S8" for s in strong):
        equity += 10.0
    # 风险类信号减分（S3 拥挤警戒、S6 景气拐点）
    if any(s["id"] == "S3" and "警戒" in s["detail"] for s in trig):
        equity -= 10.0
    if any(s["id"] == "S6" for s in strong):
        equity -= 15.0
    equity = max(20.0, min(90.0, equity))

    # 结构建议：按三类资产
    structure = []
    growth_fav = any(s["id"] == "S5" and "成长占优" in s["detail"] for s in trig)
    cycle_fav = any(s["id"] == "S5" and "周期" in s["detail"] for s in trig)
    if growth_fav:
        structure.append("景气成长类：利润增速差值扩大 → 结构上偏成长/科技主线（S5）")
    if cycle_fav:
        structure.append("经济周期类：增速差收窄 → 相对偏周期/价值（S5）")
    if any(s["id"] == "S12" for s in trig):
        structure.append("稳定价值类：红利现金替代条件成立 → 追求绝对收益部分配红利（S12）")
    if any(s["id"] == "S11" for s in strong):
        structure.append("困境反转：恢复率优秀+低PB标的纳入候选池（S11）")
    if any(s["id"] == "S6" for s in strong):
        structure.append("⚠️ 景气拐点预警触发：主线降仓/规避（S6）")
    if not structure:
        structure.append("无明确结构信号，均衡配置三类资产并核对 views.md 最新观点")

    return {
        "equity": round(equity),
        "structure": structure,
        "strong_triggered": [s["id"] for s in strong],
        "mid_triggered": [s["id"] for s in mid],
        "weak_triggered": [s["id"] for s in weak],
    }


# ----------------------------------------------------------------------------
# 报告渲染（领域无关，通用实现）
# ----------------------------------------------------------------------------

def render_report(signals, positions, data, n_triggered, total):
    as_of = data.get("as_of", "N/A")
    demo = not bool(data.get("_real", False))
    lines = []
    lines.append(f"# 刘晨明（广发证券）框架 · 信号报告（截至 {as_of}）")
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
    lines.append(f"- **仓位**：约 **{positions['equity']}%**（工程化估算，❌推断；刘晨明框架给出方向而非量化仓位）")
    lines.append("- **结构/主线**：")
    for t in positions["structure"]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("## 三、风险提示")
    lines.append("")
    lines.append("- 本报告为分析参考，非投资建议；阈值来源标注见 references/decision-rules.md。")
    lines.append("- **观点引用**：须注明'刘晨明（广发证券或天风证券·任职期）+日期'，机构归属随任职变化（约2024年初由天风转广发）。")
    lines.append("- 信号为方向判断的工程化实现，❌推断参数（S5窗口/S6回看期/S8确认窗/S12分位等）是主要不确定来源。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 演示模式数据（合成）
# ----------------------------------------------------------------------------

def demo_data():
    """合成演示数据：36 个月（2023.09-2026.08），字段清单 = decision-rules.md 映射附录。
    设计目标：每个信号在窗口末端或走势中至少触发一次（触发路径自测）。
    明确标注：以下全部为合成数据，非真实行情。
    """
    n = 36
    history = {}
    # 全A/MA100：长期在趋势线上方，末端3个月跌至线下（触发S1）
    history["ratio_ma100"] = [round(1.05 + 0.03 * _m.sin(i / 5), 3) if i < n - 3 else 0.985 for i in range(n)]
    # 全A/MA20：末端跌破（触发S2）
    history["ratio_ma20"] = [round(1.02 + 0.02 * _m.cos(i / 4), 3) if i < n - 1 else 0.985 for i in range(n)]
    # TMT成交占比：中期一个月冲到45（拥挤路径），末端27（买点路径，触发S3）
    tmt = [22 + 8 * _m.sin(i / 6) for i in range(n)]
    tmt[n // 2] = 45.0
    tmt[-1] = 27.0
    history["tmt_turnout_pct"] = [round(x, 1) for x in tmt]
    # 反应度：成长类末端15（<20触发买入）；周期/稳定类中性
    history["reaction_growth"] = [round(50 + 40 * _m.sin(i / 7), 0) for i in range(n)]
    history["reaction_growth"][-1] = 15.0
    history["reaction_cycle"] = [round(50 + 25 * _m.sin(i / 8 + 1), 0) for i in range(n)]
    history["reaction_stable"] = [round(50 + 25 * _m.sin(i / 8 + 2), 0) for i in range(n)]
    # 利润增速差：上行趋势（触发S5成长占优）
    history["profit_growth_gap"] = [round(5 + 0.5 * i + 4 * _m.sin(i / 5), 1) for i in range(n)]
    # 主线净利润增速：从60降至25（同时触发S6双条件）
    history["profit_growth_tmt"] = [round(60 - 1.0 * i + 3 * _m.sin(i / 4), 1) for i in range(n)]
    # 渗透率：升至43（触发S7预警路径，合成演示值）
    history["penetration_rate"] = [round(5 + i * 1.05, 1) for i in range(n)]
    # 广义财政：前24个月1.5（托底），末12个月5.5（触发S8）
    history["fiscal_impulse"] = [1.5] * (n - 12) + [5.5] * 12
    # PPI：末端连续2个月回升
    ppi = [-2.5 + 0.02 * i for i in range(n - 3)] + [-1.6, -1.4, -1.1]
    history["ppi_yoy"] = [round(x, 1) for x in ppi]
    # ETF净流入：平时低位，末端320（触发S9）
    history["etf_inflow_daily_bn"] = [round(60 + 60 * abs(_m.sin(i / 3)), 0) for i in range(n - 1)] + [320.0]
    # 主线指数：前26个月上行至峰值，后10个月回撤22%（触发S10）
    idx = [1000 * (1 + 0.02 * i) for i in range(27)]
    peak = idx[-1]
    idx += [peak * (1 - 0.025 * (j + 1)) for j in range(9)]
    history["tmt_index"] = [round(x, 1) for x in idx]
    # 困境反转：恢复率130（触发S11优秀线），PB分位25（估值加成成立）
    history["recovery_np"] = [85.0] * (n - 1) + [130.0]
    history["pb_pctile"] = [60.0] * (n - 1) + [25.0]
    # 定存0.95 + 股息率分位85（触发S12）
    history["deposit_1y"] = [1.35 - 0.01 * i for i in range(n - 1)] + [0.95]
    history["div_yield_pctile"] = [50.0] * (n - 1) + [85.0]

    return {
        "as_of": "2026-08-01",
        "history": history,
        "extras": {"bull_market": True, "black_swan": False, "focus": "growth"},
    }


# ----------------------------------------------------------------------------
# 主流程（领域无关，通用实现）
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="刘晨明（广发证券）框架信号计算")
    ap.add_argument("--data", help="数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true", help="输出 JSON 格式结果（布尔标志，JSON 打到 stdout）")
    args = ap.parse_args()

    if args.data:
        with open(args.data, encoding="utf-8") as f:
            data = json.load(f)
        if "history" not in data:
            print(f"输入校验错误：JSON 缺少必需键 'history'（应为 字段→月份数组 的转置结构，最新在末尾）", file=sys.stderr)
            return 2
        data["_real"] = True
    else:
        data = demo_data()
        data["_real"] = False

    h = data["history"]
    extras = data.get("extras", {})

    calc_funcs = [calc_s1, calc_s2, calc_s3, calc_s4, calc_s5, calc_s6,
                  calc_s7, calc_s8, calc_s9, calc_s10, calc_s11, calc_s12]
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
    import sys
    main()
