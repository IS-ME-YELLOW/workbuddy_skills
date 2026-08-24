#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst-macro-lichao 信号计算脚本（screen.py）
================================================
李超（浙商证券首席经济学家）框架的可执行信号实现。
依据：references/decision-rules.md（规则 1-10 + S1-S12 汇总表）。
信号编号 S1-S12 为工程化设计（李超本人无此编号体系），底层阈值来源见参数区标注。

输入 JSON schema（--data）：
{
  "history": {   # "字段 → 月份数组"转置结构，升序，最新在末尾
    "gb10y":              [2.6, 2.5, ...],   # 10Y国债收益率（月均，%）
    "cgs_yield":          [4.0, 4.1, ...],   # 央企红利指数股息率（%）
    "cn_us_event_score":  [0, 1, -1, ...],   # 中美事件净分值（月度，-2..+2 汇总）
    "hh_dep_yoy":         [14, 13.8, ...],   # 居民存款同比（%）
    "nb_dep_yoy":         [5, 5.5, ...],     # 非银存款同比（%）
    "baidu_idx":          [100, 105, ...],   # 百度指数（信息杠杆代理）
    "turnover":           [6000, 6200, ...], # A股成交额（月均，亿元）
    "cb_gold_buy":        [55, 60, ...],     # 央行购金量（月度化，吨）
    "dr001":              [1.5, 1.45, ...],  # DR001（月均，%）
    "corridor_width":     [70, 70, 50, ...], # 利率走廊宽度（BP）
    "hs300":              [3200, 3245, ...], # 沪深300月度收盘
    "ai_price_idx":       [100, 102, ...],   # 硅基通胀代理：算力/AI硬件价格指数
    "cpi_service_yoy":    [1.2, 1.1, ...]    # 碳基通缩代理：CPI服务分项同比（%）
  },
  "extras": {    # 风格/阶段/事件类单值
    "gold_risk_flag": 0,       # 黄金四大利空显性化数量（0-4）
    "corridor_center": 1.30,   # 利率走廊中枢（%，以 OMO 7D 为准）
    "barbell_tech_share": 55,  # 杠铃科技端当前市值占比（%）
    "stabilizing_flag": false  # 类平准基金兜底信号（官方增持公告/ETF异常放量）
  },
  "_meta": {     # 数据来源说明（Phase 4 回填时写）
    "gb10y": "westock-data 国债收益率曲线 10Y 日频→月均"
  }
}

运行：
  python screen.py                    # 演示模式（合成数据，验证流程）
  python screen.py --data macro.json  # 真实数据计算
  python screen.py --json-out         # 机器可读 JSON（布尔标志，stdout）
"""

import argparse
import json
import math as _m
import sys


# ============================================================
# 参数区（来源分级：✅ 原文 / ⚠️ 外推 / ❌ 推断 —— 与 decision-rules.md 图例一致）
# ------------------------------------------------------------
# 规则：所有阈值集中在此，函数体内不散落裸阈值；每条与 decision-rules.md 逐条对应。
#   ✅ 原文 = 李超公开研究中明确给出的数值（注明出处）
#   ⚠️ 外推 = 有公开依据但未逐字核对（注明"以原文复核"）
#   ❌ 推断 = 李超未公布、为实现可脚本化的假设（必须写"最小假设，可替换"）
# ------------------------------------------------------------
# S1/S2 中美博弈风险偏好开关（规则 1）
EVENT_WIN = 3               # ❌ 推断：事件净分值滚动窗口（月），最小假设可替换
# S3/S4 利率区间三档择时（规则 2）
GB10Y_LOW = 1.5             # ✅ 原文：10Y 国债区间下沿 1.5%（2025 系列报告"1.5-2%区间"）
GB10Y_HIGH = 2.0            # ✅ 原文：10Y 国债区间上沿 2.0%（同上）
GB10Y_MID = 1.75            # ✅ 原文：10Y 中枢 1.75%（同上）
GB10Y_BREAK_M = 2           # ❌ 推断：上破上沿持续月数 ≥2，最小假设可替换
# S5 股息率-票息比价（规则 3）
SPREAD_WIN = 12             # ❌ 推断：比价差分位窗口（月），最小假设可替换
SPREAD_PCT_HI = 70.0        # ❌ 推断：比价优势走阔分位阈值（%），最小假设可替换
SPREAD_PCT_LO = 30.0        # ❌ 推断：比价优势收窄分位阈值（%），最小假设可替换
CGS_YIELD_ANCHOR = 4.4      # ✅ 原文：央企红利股息率约 4.4%（2026.04 口径），参照锚
# S6 存款搬家确认（规则 4）
DEP_FALL_M = 2              # ❌ 推断：居民存款增速连续回落月数，最小假设可替换
BAIDU_JUMP = 50.0           # ❌ 推断：百度指数较前3月均值跳升阈值（%），信息杠杆概念为 ✅ 原文、量化阈值 ❌
DEP_TRIG_MIN = 2            # ❌ 推断：三大跟踪指标最少触发数（原文"三指标"，取 ≥2 为工程化宽放）
# S7/S8 黄金央行购金框架（规则 5）
GOLD_POS_M = 6              # ❌ 推断：购金量连续为正月数（≈连续两个季度），最小假设可替换
GOLD_TARGET = 5600          # ✅ 原文：伦敦金目标价 5600 美元
# S9 利率走廊与资金面（规则 6）
DR001_LOOKBACK = 3          # ❌ 推断：DR001 均值回看月数，最小假设可替换
CORRIDOR_LOW_HALF = 0.5     # ❌ 推断：低于（中枢 − 半宽×0.5）视为贴走廊下沿，最小假设可替换
CORRIDOR_CENTER_DFLT = 1.30 # ❌ 推断：走廊中枢默认值（%）——应以当期 OMO 7D 政策利率为准
CORRIDOR_NARROW_WIN = 12    # ❌ 推断：走廊收窄事件回看窗口（月），最小假设可替换
# S10 杠铃再平衡（规则 7）
BARBELL_TARGET = 50.0       # ❌ 推断：杠铃两端目标各 50%（李超口诀未给具体比例，可替换）
BARBELL_BAND = 10.0         # ❌ 推断：单端偏离带宽 ±10pct（decision-rules 规则 7），可替换
# S11 类平准基金兜底（规则 10）
DRAWDOWN_PCT = 20.0         # ❌ 推断：宽基回撤阈值（%），最小假设可替换
DRAWDOWN_WIN_M = 2          # ❌ 推断：快速下跌窗口（月），最小假设可替换
# S12 K型结构验证（规则 9）
K_LOOKBACK = 3              # ❌ 推断：硅基/碳基趋势确认窗口（月），最小假设可替换
# ============================================================

HISTORY_FIELDS = [
    "gb10y", "cgs_yield", "cn_us_event_score", "hh_dep_yoy", "nb_dep_yoy",
    "baidu_idx", "turnover", "cb_gold_buy", "dr001", "corridor_width",
    "hs300", "ai_price_idx", "cpi_service_yoy",
]


# ----------------------------------------------------------------------------
# 工具函数（领域无关）
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


def trend_down(series, lookback=3):
    """最近 lookback 期是否整体下行。"""
    if len(series) < 2:
        return False
    win = series[-lookback:]
    return win[-1] < win[0]


def recent_avg(series, lookback=3):
    """最近 lookback 期均值（不含末值时用 prior_avg）；序列不足取全部。"""
    if not series:
        return 0.0
    win = series[-lookback:]
    return sum(win) / len(win)


def prior_avg(series, lookback=3):
    """末值之前 lookback 期均值。"""
    if len(series) < 2:
        return 0.0
    win = series[-(lookback + 1):-1]
    return sum(win) / len(win)


def _miss(field):
    return {"triggered": False, "detail": f"缺字段 {field}（按脚本头部 schema 补全）",
            "strength": "direction"}


# ----------------------------------------------------------------------------
# 信号计算函数（契约：输入 h / extras → 返回 dict）
#   id/name/triggered/detail/strength；detail 必须含读数
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 中美对抗升级：净分值 < 0 且较上一窗口恶化 → 切换向红利端。"""
    f = "cn_us_event_score"
    if f not in h or len(h.get(f) or []) < EVENT_WIN * 2:
        s = _miss(f); s.update({"id": "S1", "name": "中美对抗升级"}); return s
    sc = h[f]
    net3 = sum(sc[-EVENT_WIN:])
    prev3 = sum(sc[-EVENT_WIN * 2:-EVENT_WIN])
    trig = net3 < 0 and net3 < prev3
    return {"id": "S1", "name": "中美对抗升级", "triggered": trig,
            "detail": (f"近{EVENT_WIN}月事件净分值 {net3:+d}，前{EVENT_WIN}月 {prev3:+d} → "
                       f"{'对抗升级：红利超配、科技减配（口诀✅原文）' if trig else '未触发（对抗未升级）'}"),
            "strength": "strong" if trig else "direction"}


def calc_s2(h, extras=None):
    """S2 中美合作缓和：净分值 > 0 且较上一窗口改善 → 切换向科技端。"""
    f = "cn_us_event_score"
    if f not in h or len(h.get(f) or []) < EVENT_WIN * 2:
        s = _miss(f); s.update({"id": "S2", "name": "中美合作缓和"}); return s
    sc = h[f]
    net3 = sum(sc[-EVENT_WIN:])
    prev3 = sum(sc[-EVENT_WIN * 2:-EVENT_WIN])
    trig = net3 > 0 and net3 > prev3
    return {"id": "S2", "name": "中美合作缓和", "triggered": trig,
            "detail": (f"近{EVENT_WIN}月事件净分值 {net3:+d}，前{EVENT_WIN}月 {prev3:+d} → "
                       f"{'合作缓和：科技超配、红利减配（口诀✅原文）' if trig else '未触发（合作未缓和）'}"),
            "strength": "strong" if trig else "direction"}


def calc_s3(h, extras=None):
    """S3 流动性极致：10Y < 1.5%（区间下沿以下）→ 权益弹性最大档。"""
    f = "gb10y"
    if f not in h or not h.get(f):
        s = _miss(f); s.update({"id": "S3", "name": "流动性极致宽松"}); return s
    latest = h[f][-1]
    trig = latest < GB10Y_LOW
    return {"id": "S3", "name": "流动性极致宽松", "triggered": trig,
            "detail": (f"10Y 国债最新 {latest:.2f}% vs 下沿 {GB10Y_LOW}%（区间 {GB10Y_LOW}-{GB10Y_HIGH}%，"
                       f"中枢 {GB10Y_MID}% ✅原文） → "
                       f"{'流动性极致：成长/久期资产进攻' if trig else '未触发（未破区间下沿）'}"),
            "strength": "strong" if trig else "direction"}


def calc_s4(h, extras=None):
    """S4 双牛逻辑受损预警：10Y > 2.0% 持续 ≥2 个月。"""
    f = "gb10y"
    if f not in h or len(h.get(f) or []) < GB10Y_BREAK_M:
        s = _miss(f); s.update({"id": "S4", "name": "双牛逻辑受损预警"}); return s
    g = h[f]
    above = sum(1 for x in g[-GB10Y_BREAK_M:] if x > GB10Y_HIGH)
    trig = above >= GB10Y_BREAK_M
    return {"id": "S4", "name": "双牛逻辑受损预警", "triggered": trig,
            "detail": (f"10Y 国债最近{GB10Y_BREAK_M}个月中 {above} 个月高于上沿 {GB10Y_HIGH}% → "
                       f"{'有效上破：减久期、降估值弹性敞口' if trig else '未触发（未持续上破上沿）'}"
                       f"（上破 2% = 框架假设失效警戒线 ✅原文区间含义）"),
            "strength": "strong" if trig else "direction"}


def calc_s5(h, extras=None):
    """S5 股息率-票息比价优势走阔：比价差 > 近12个月70%分位 → 红利端加仓。"""
    for f in ("cgs_yield", "gb10y"):
        if f not in h or not h.get(f):
            s = _miss(f); s.update({"id": "S5", "name": "股息率-票息比价走阔"}); return s
    n = min(len(h["cgs_yield"]), len(h["gb10y"]))
    win = min(SPREAD_WIN, n)
    spread = [round(h["cgs_yield"][i] - h["gb10y"][i], 3) for i in range(n - win, n)]
    latest = spread[-1]
    pr = pct_rank(spread[:-1] if len(spread) > 1 else spread, latest)
    if pr >= SPREAD_PCT_HI:
        act, strength = "红利端加仓（新黄金逻辑强化）", "mid"
    elif pr < SPREAD_PCT_LO:
        act, strength = "红利减配预警（比价优势收窄）", "mid"
    else:
        act, strength = "红利标配（杠铃防守端基准仓）", "direction"
    return {"id": "S5", "name": "股息率-票息比价走阔", "triggered": pr >= SPREAD_PCT_HI,
            "detail": (f"比价差最新 {latest:.2f}pct（股息率 {h['cgs_yield'][-1]:.2f}% − 10Y "
                       f"{h['gb10y'][-1]:.2f}%），近{win}月分位 {pr:.0f}% → {act}"
                       f"（参照锚：央企股息率 {CGS_YIELD_ANCHOR}% ✅原文）"),
            "strength": strength}


def calc_s6(h, extras=None):
    """S6 存款搬家确认：三大跟踪指标 ≥2 项触发 + 成交额放大。"""
    need = ("hh_dep_yoy", "nb_dep_yoy", "baidu_idx", "turnover")
    for f in need:
        if f not in h or len(h.get(f) or []) < 4:
            s = _miss(f); s.update({"id": "S6", "name": "存款搬家确认"}); return s
    dep = h["hh_dep_yoy"]
    # 条件1：居民存款增速连续 ≥2 个月回落
    c1 = len(dep) >= DEP_FALL_M + 1 and all(
        dep[-1 - k] < dep[-2 - k] for k in range(DEP_FALL_M))
    # 条件2：非银存款同比上行（3个月趋势）
    c2 = trend_up(h["nb_dep_yoy"], 3)
    # 条件3：百度指数较前3月均值跳升 > BAIDU_JUMP%
    bd = h["baidu_idx"]
    pa = prior_avg(bd, 3)
    jump = (bd[-1] / pa - 1) * 100 if pa else 0.0
    c3 = jump > BAIDU_JUMP
    # 确认项：成交额中枢抬升
    to = h["turnover"]
    vol_up = to[-1] > prior_avg(to, 3)
    n_trig = sum([c1, c2, c3])
    trig = n_trig >= DEP_TRIG_MIN and vol_up
    return {"id": "S6", "name": "存款搬家确认", "triggered": trig,
            "detail": (f"三指标：存款增速回落{DEP_FALL_M}月={'√' if c1 else '×'}、非银存款上行="
                       f"{'√' if c2 else '×'}、信息杠杆跳升 {jump:+.0f}%（阈值>{BAIDU_JUMP:.0f}% ❌推断）"
                       f"={'√' if c3 else '×'} → {n_trig}/3；成交额放大={'√' if vol_up else '×'} → "
                       f"{'搬家确认：权益仓位上调，偏向高beta成长/券商' if trig else '未确认搬家'}"),
            "strength": "strong" if trig else "direction"}


def calc_s7(h, extras=None):
    """S7 黄金战略持有：央行购金连续为正且四大利空未显性化。"""
    f = "cb_gold_buy"
    if f not in h or len(h.get(f) or []) < GOLD_POS_M:
        s = _miss(f); s.update({"id": "S7", "name": "黄金战略持有"}); return s
    buys = h[f][-GOLD_POS_M:]
    all_pos = all(x > 0 for x in buys)
    risk = int((extras or {}).get("gold_risk_flag", 0))
    trig = all_pos and risk == 0
    return {"id": "S7", "name": "黄金战略持有", "triggered": trig,
            "detail": (f"近{GOLD_POS_M}月央行购金月均 {sum(buys)/len(buys):.0f} 吨、全部为正="
                       f"{'√' if all_pos else '×'}；四大利空显性化 {risk} 项 → "
                       f"{'战略持有（50/50底仓黄金腿 ✅原文方案，目标伦敦金' + str(GOLD_TARGET) + '美元）' if trig else '持有条件不成立'}"),
            "strength": "mid" if trig else "direction"}


def calc_s8(h, extras=None):
    """S8 黄金减仓预警：四大利空任一显性化。"""
    risk = int((extras or {}).get("gold_risk_flag", 0))
    trig = risk >= 1
    return {"id": "S8", "name": "黄金减仓预警", "triggered": trig,
            "detail": (f"四大利空（✅原文：①金融危机流动性抛售②美国能源体系重构③机器人广泛应用④人造黄金）"
                       f"显性化 {risk} 项 → {'减仓预警' if trig else '未触发'}"
                       f"（显性化判定标准为 ❌推断）"),
            "strength": "strong" if trig else "direction"}


def calc_s9(h, extras=None):
    """S9 资金面宽松确认：DR001 贴走廊下沿 / 走廊收窄落地。"""
    for f in ("dr001", "corridor_width"):
        if f not in h or not h.get(f):
            s = _miss(f); s.update({"id": "S9", "name": "资金面宽松确认"}); return s
    dr = h["dr001"]
    cw = h["corridor_width"]
    center = float((extras or {}).get("corridor_center", CORRIDOR_CENTER_DFLT))
    width_bps = cw[-1]
    lower_zone = center - (width_bps / 100.0 / 2.0) * (1.0 + CORRIDOR_LOW_HALF)
    dr_avg = recent_avg(dr, DR001_LOOKBACK)
    near_low = dr_avg < lower_zone
    w_win = cw[-CORRIDOR_NARROW_WIN:] if len(cw) >= CORRIDOR_NARROW_WIN else cw
    narrowed = any(w_win[i + 1] < w_win[i] for i in range(len(w_win) - 1))
    trig = near_low or narrowed
    return {"id": "S9", "name": "资金面宽松确认", "triggered": trig,
            "detail": (f"DR001 近{DR001_LOOKBACK}月均值 {dr_avg:.2f}% vs 贴下沿阈值 {lower_zone:.2f}%"
                       f"（中枢{center:.2f}%/宽{width_bps:.0f}BP）={'√' if near_low else '×'}；"
                       f"走廊收窄落地={'√' if narrowed else '×'}（70BP→50BP ✅原文） → "
                       f"{'资金面宽松：久期友好' if trig else '未触发'}"),
            "strength": "mid" if trig else "direction"}


def calc_s10(h, extras=None):
    """S10 杠铃再平衡：科技端占比偏离目标 ±10pct。"""
    share = (extras or {}).get("barbell_tech_share")
    if share is None:
        s = _miss("extras.barbell_tech_share"); s.update({"id": "S10", "name": "杠铃再平衡"}); return s
    share = float(share)
    dev = share - BARBELL_TARGET
    trig = abs(dev) > BARBELL_BAND
    direction = "科技端超配" if dev > 0 else "红利端超配"
    return {"id": "S10", "name": "杠铃再平衡", "triggered": trig,
            "detail": (f"科技端占比 {share:.0f}% vs 目标 {BARBELL_TARGET:.0f}%（❌推断，可替换），"
                       f"偏离 {dev:+.0f}pct vs 带宽 ±{BARBELL_BAND:.0f}pct → "
                       f"{'触发：再平衡回目标比例' if trig else '未触发（带宽内）'}"),
            "strength": "mid" if trig else "direction"}


def calc_s11(h, extras=None):
    """S11 类平准基金兜底区：宽基 ≤2 个月回撤 >20% + 兜底资金信号。"""
    f = "hs300"
    if f not in h or len(h.get(f) or []) < DRAWDOWN_WIN_M + 1:
        s = _miss(f); s.update({"id": "S11", "name": "类平准基金兜底区"}); return s
    px = h[f]
    win = px[-(DRAWDOWN_WIN_M + 1):]
    peak = max(win)
    dd = (peak - px[-1]) / peak * 100 if peak else 0.0
    stab = bool((extras or {}).get("stabilizing_flag", False))
    trig = dd > DRAWDOWN_PCT and stab
    return {"id": "S11", "name": "类平准基金兜底区", "triggered": trig,
            "detail": (f"近{DRAWDOWN_WIN_M}个月自高点回撤 {dd:.1f}%（阈值>{DRAWDOWN_PCT:.0f}% ❌推断），"
                       f"兜底资金信号={'√' if stab else '×'} → "
                       f"{'兜底区：逢低承接而非止损（方向✅原文）' if trig else '未触发'}"),
            "strength": "mid" if trig else "direction"}


def calc_s12(h, extras=None):
    """S12 K型结构验证：硅基通胀代理上行 + 碳基通缩代理下行。"""
    for f in ("ai_price_idx", "cpi_service_yoy"):
        if f not in h or not h.get(f):
            s = _miss(f); s.update({"id": "S12", "name": "K型结构验证"}); return s
    silicon_up = trend_up(h["ai_price_idx"], K_LOOKBACK)
    carbon_down = trend_down(h["cpi_service_yoy"], K_LOOKBACK)
    trig = silicon_up and carbon_down
    return {"id": "S12", "name": "K型结构验证", "triggered": trig,
            "detail": (f"硅基通胀代理近{K_LOOKBACK}月{'上行' if silicon_up else '未上行'}、"
                       f"碳基通缩代理{'下行' if carbon_down else '未下行'}（代理构造 ❌推断） → "
                       f"{'K型成立：杠铃框架健康，结构延续' if trig else 'K型未获验证'}"),
            "strength": "direction"}


# ----------------------------------------------------------------------------
# 信号汇总 → 仓位 / 杠铃结构 / 黄金建议
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    """汇总触发信号 → 配置建议（档位与加减分为 ❌推断工程化设计）。"""
    trig = [s for s in signals if s["triggered"]]
    strong = [s["id"] for s in trig if s.get("strength") == "strong"]
    mid = [s["id"] for s in trig if s.get("strength") == "mid"]
    weak = [s["id"] for s in trig if s.get("strength") == "direction"]

    # 权益仓位：基准 50%，强信号 +10、中信号 +5、双牛受损(S4)/黄金减仓(S8) 各 -10
    equity = 50.0
    for sid in strong:
        equity += -10.0 if sid in ("S4", "S8") else 10.0
    equity += 5.0 * len(mid)
    equity = max(30.0, min(80.0, equity))

    # 杠铃两端（S1/S2 互斥开关）
    by_id = {s["id"]: s for s in signals}
    if by_id.get("S1", {}).get("triggered"):
        barbell = "中美对抗升级 → 红利端超配、科技端减配（口诀 ✅原文）"
    elif by_id.get("S2", {}).get("triggered"):
        barbell = "中美合作缓和 → 科技端超配、红利端减配（口诀 ✅原文）"
    elif by_id.get("S10", {}).get("triggered"):
        barbell = "开关中性但单端偏离带宽 → 再平衡回目标比例（❌推断纪律）"
    else:
        barbell = "开关中性 → 维持科技+红利二元杠铃（默认结构 ✅原文），不配中间风格"

    # 流动性档位（S3/S4 互斥）
    if by_id.get("S3", {}).get("triggered"):
        liquidity = "10Y 破下沿：流动性极致，权益弹性最大档（成长/久期进攻）"
    elif by_id.get("S4", {}).get("triggered"):
        liquidity = "10Y 上破 2%：双牛逻辑受损，减久期、降估值弹性敞口"
    else:
        liquidity = f"10Y 处 {GB10Y_LOW}-{GB10Y_HIGH}% 区间（中枢 {GB10Y_MID}%）：股债双牛持有"

    # 黄金
    if by_id.get("S8", {}).get("triggered"):
        gold = "四大利空显性化 → 黄金减仓预警"
    elif by_id.get("S7", {}).get("triggered"):
        gold = f"央行购金持续 → 黄金战略持有（50/50 底仓黄金腿 ✅原文，目标 {GOLD_TARGET} 美元）"
    else:
        gold = "购金持续性或利空状态存疑 → 黄金中性观察"

    structure = []
    if by_id.get("S6", {}).get("triggered"):
        structure.append("存款搬家确认 → 增量资金入场，结构偏向高 beta 成长、券商")
    if by_id.get("S5", {}).get("triggered"):
        structure.append("股息率-票息比价走阔 → 红利端（新黄金）加仓")
    if by_id.get("S12", {}).get("triggered"):
        structure.append("K型验证成立 → 硅基端（AI/算力/机器人）+ 碳基端（红利/确定性）两端配置延续")
    if by_id.get("S11", {}).get("triggered"):
        structure.append("兜底区 → 逢低承接杠铃两端而非止损（类平准基金 ✅原文）")
    if not structure:
        structure.append("无结构信号触发 → 维持默认杠铃 + 50/50 底仓（✅原文方案）")

    return {
        "equity": round(equity),
        "barbell": barbell,
        "liquidity": liquidity,
        "gold": gold,
        "structure": structure,
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
    lines.append(f"# 李超（浙商宏观）框架 · 信号报告（截至 {as_of}）")
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
    lines.append(f"- **权益仓位**：约 **{positions['equity']}%**（工程化估算，❌推断）")
    lines.append(f"- **流动性档位**：{positions['liquidity']}")
    lines.append(f"- **杠铃结构**：{positions['barbell']}")
    lines.append(f"- **黄金**：{positions['gold']}")
    lines.append("- **结构/主线**：")
    for t in positions["structure"]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("## 三、风险提示")
    lines.append("")
    lines.append("- 本报告为分析参考，非投资建议；阈值来源标注见 references/decision-rules.md 与脚本参数区。")
    lines.append("- **观点引用**：须注明'李超（浙商证券）{日期}观点'，机构归属随任职变化。")
    lines.append("- S1-S12 编号系工程化设计，李超本人无此编号体系。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 演示模式数据（合成）
# ----------------------------------------------------------------------------

def demo_data():
    """合成演示数据：36 个月，覆盖各信号触发/未触发路径。

    场景设定（合成叙事）：利率自 2.6% 一路下行破 1.5% → 股债双牛走向极致；
    末端中美摩擦升级（红利端）；存款搬家三指标共振 + 成交放大；
    央行持续购金；利率走廊 70BP→50BP 收窄；指数末两月快速回撤 24% 进入兜底区；
    K 型（硅基涨/碳基缩）成立。
    """
    n = 36
    history = {}
    history["gb10y"] = [round(2.6 - 0.033 * i, 3) for i in range(n)]          # 2.60 → 1.45
    history["cgs_yield"] = [round(4.0 + 0.014 * i + 0.08 * _m.sin(i / 5), 3) for i in range(n)]
    score = [0] * n
    for i, v in zip(range(28, 36), [0, 1, 1, 0, -1, -1, -2, -2]):            # 末端对抗升级
        score[i] = v
    history["cn_us_event_score"] = score
    history["hh_dep_yoy"] = [round(14 - 0.12 * i, 2) for i in range(n)]       # 持续回落
    history["nb_dep_yoy"] = [round(5 + 0.28 * i + 0.5 * _m.sin(i / 3), 2) for i in range(n)]
    baidu = [round(100 + 10 * _m.sin(i / 4), 1) for i in range(n)]
    baidu[34], baidu[35] = 180.0, 215.0                                       # 信息杠杆跳升
    history["baidu_idx"] = baidu
    to = [6000 + 200 * i for i in range(n)]
    to[34] += 3000; to[35] += 5000                                            # 成交放大
    history["turnover"] = to
    history["cb_gold_buy"] = [round(55 + 10 * _m.sin(i / 4), 1) for i in range(n)]  # 恒为正
    history["dr001"] = [round(1.55 - 0.012 * i, 3) for i in range(n)]
    history["corridor_width"] = [70 if i < 30 else 50 for i in range(n)]      # 收窄落地
    hs = [3200 + 45 * i for i in range(34)] + [3900, 3550]                    # 末端快速回撤
    history["hs300"] = hs
    history["ai_price_idx"] = [100 + 1.7 * i for i in range(n)]               # 硅基通胀
    history["cpi_service_yoy"] = [round(1.2 - 0.025 * i, 3) for i in range(n)]  # 碳基通缩
    return {
        "as_of": "2026-08-01",
        "history": history,
        "extras": {
            "gold_risk_flag": 0,
            "corridor_center": 1.30,
            "barbell_tech_share": 62,
            "stabilizing_flag": True,
        },
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="李超（浙商宏观）框架信号计算")
    ap.add_argument("--data", help="数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true",
                    help="输出 JSON 格式结果（布尔标志，JSON 打到 stdout）")
    args = ap.parse_args()

    if args.data:
        with open(args.data, encoding="utf-8") as f:
            data = json.load(f)
        if "history" not in data or not isinstance(data["history"], dict):
            print("错误：输入 JSON 缺少 history 字段（字段→月份数组），"
                  "schema 见脚本头部说明。", file=sys.stderr)
            sys.exit(2)
        missing = [f for f in HISTORY_FIELDS if f not in data["history"]]
        if missing:
            print(f"错误：history 缺少字段：{', '.join(missing)}（口径见脚本头部 schema）",
                  file=sys.stderr)
            sys.exit(2)
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
        except Exception as e:  # 单信号出错不阻塞整体输出
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
