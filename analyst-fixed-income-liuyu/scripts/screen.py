#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst-fixed-income-liuyu 信号计算脚本
============================================================
刘郁（华西证券→兴业证券）框架信号计算：定价内核（货币-信用四象限）→ 债市坐标 → 长逻辑 → 策略落地。
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
# S1 货币-信用四象限（✅ 原文回测：松宽年化 6.31%、胜率 56.93% 最优；❌ 分档阈值）
R007_DOWN_N = 3          # ❌ 推断：连续 N 期下行判定货币趋松（最小假设，可替换）
SF_UP_N = 3              # ❌ 推断：连续 N 期社融同比上行判定信用趋宽（最小假设，可替换）
# S2/S3/S4 纯债行情三分（✅ 原文品种映射；❌ 量化代理阈值）
AMP_BAND_BP = 40         # ❌ 推断：月内振幅带宽（BP），区分走强/回调
MA_FLAT_BP = 2           # ❌ 推断：均线走平带宽（BP）
MA_WIN = 20              # ❌ 推断：10Y 均线窗口（日→月度序列取 6 期近似）
# S5 资金宽松类型二（✅ 原文终结触发条件：政府债放量/信贷回升/稳汇率；❌ 量化）
BILL_RATE_LOW = 0.0100   # ❌ 推断：票据利率低于此值视为信贷需求弱
SUPPLY_SLOW_BP = 0.0     # ❌ 推断：政府债净融资低于同期均值视为供给慢（extras 直接给 supply_slow）
# S6 资金面生命线（✅ 原文方向"资金不紧债市不熊"；❌ 带宽阈值）
DR7_OMO_BAND = 15        # ❌ 推断：DR007-OMO 偏离带宽（BP），> 此值视为资金收敛
# S7 利率锚上沿（⚠️ 外推：10Y 高点约 MLF+20-30BP，取上沿 30BP）
MLF_UPPER_BP = 30        # ⚠️ 外推：10Y 相对 MLF 上沿溢价（BP）
# S8 利率锚下沿（⚠️ 外推：2026 年 10Y 区间约 1.6%-1.9%，取下沿 1.6%）
RATE_10Y_LOWER = 0.0160  # ⚠️ 外推：2026 年 10Y 区间下沿（%）
# S9/S10 机构行为（✅ 原文方向"买长卖短/骤然止盈"；❌ 量化阈值）
FUND_POS_N = 3           # ❌ 推断：基金净买入连续转正期数
FUND_SELL_BIG = -500     # ❌ 推断：基金近 3 期净卖出合计阈值（亿元）→ 放量止盈
# S11 存款自律/非银存款（✅ 原文：2024.12 大行非银存款单月 -3.44 万亿；❌ 阈值）
NONBANK_DEP_DROP = -3000 # ❌ 推断：非银存款单月压降阈值（亿元）
# S12 理财净值化（✅ 原文机制；❌ 由 extras 人工判定）
# S13 月度节奏三阶段（✅ 原文 2026.3.4；❌ 日期切分）
DAY_MID = 10             # ❌ 推断：上旬/中旬分界日
DAY_LATE = 20            # ❌ 推断：中旬/下旬分界日
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


def recent_avg(series, lookback=3):
    """最近 lookback 期均值。"""
    clean = _clean(series)
    if not clean:
        return 0.0
    win = clean[-lookback:]
    return sum(win) / len(win)


def trend_down(series, lookback=3):
    """最近 lookback 期是否整体下行（首>尾）。"""
    clean = _clean(series)
    if len(clean) < 2:
        return False
    win = clean[-lookback:]
    return win[0] > win[-1]


def trend_up(series, lookback=3):
    """最近 lookback 期是否整体上行（尾>首）。"""
    clean = _clean(series)
    if len(clean) < 2:
        return False
    win = clean[-lookback:]
    return win[-1] > win[0]


def consec_pos(series, n):
    """最近连续 n 期均为正。"""
    clean = _clean(series)
    if len(clean) < n:
        return False
    return all(x > 0 for x in clean[-n:])


def consec_neg(series, n):
    """最近连续 n 期均为负。"""
    clean = _clean(series)
    if len(clean) < n:
        return False
    return all(x < 0 for x in clean[-n:])


def range_amp_bp(series, lookback=3):
    """近 lookback 期振幅（BP）：(max-min)*10000。"""
    clean = _clean(series)
    if len(clean) < 2:
        return 0.0
    win = clean[-lookback:]
    return (max(win) - min(win)) * 10000


# ----------------------------------------------------------------------------
# 信号计算函数
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 货币-信用四象限定位（大类配置总开关）。"""
    r007 = h.get("r007")
    sf = h.get("sf_yoy")
    policy_loose = (extras or {}).get("policy_loose")
    credit_loose = (extras or {}).get("credit_loose")
    if not r007 or not sf:
        return {"id": "S1", "name": "货币-信用四象限", "triggered": False,
                "detail": "缺字段 r007 / sf_yoy", "strength": "direction"}
    money_loose = trend_down(r007, R007_DOWN_N) or bool(policy_loose)
    credit_wide = trend_up(sf, SF_UP_N) or bool(credit_loose)
    if money_loose and credit_wide:
        quad, act, trig, strength = "货币趋松&信用趋宽", "转债+权益进攻（回测年化 6.31%、胜率 56.93% 最优）", True, "strong"
    elif money_loose and not credit_wide:
        quad, act, trig, strength = "货币趋松&信用趋紧", "趋弱周期，控制仓位，票息策略", False, "mid"
    elif not money_loose and credit_wide:
        quad, act, trig, strength = "货币趋紧&信用趋宽", "纯债防御，转债/权益低配（波动率 13.66% 最低）", False, "mid"
    else:
        quad, act, trig, strength = "货币趋紧&信用趋紧", "纯债为主，短久期防御（回撤 8.84% 最小）", False, "mid"
    return {"id": "S1", "name": "货币-信用四象限", "triggered": trig,
            "detail": f"R007 连续下行 {_count_down(r007, R007_DOWN_N)} 期/政策宽松{'是' if policy_loose else '否'} + 社融同比连续上行 {_count_up(sf, SF_UP_N)} 期 → {quad} → {act}",
            "strength": strength}


def _count_down(series, n):
    clean = _clean(series)
    cnt = 0
    for i in range(len(clean) - 1, 0, -1):
        if clean[i] < clean[i - 1]:
            cnt += 1
        else:
            break
    return cnt


def _count_up(series, n):
    clean = _clean(series)
    cnt = 0
    for i in range(len(clean) - 1, 0, -1):
        if clean[i] > clean[i - 1]:
            cnt += 1
        else:
            break
    return cnt


def calc_s2(h, extras=None):
    """S2 纯债行情走强 → 超长期利率债。"""
    c10y = h.get("c10y")
    if not c10y:
        return {"id": "S2", "name": "行情走强", "triggered": False,
                "detail": "缺字段 c10y", "strength": "direction"}
    ma = recent_avg(c10y, min(MA_WIN // 3, 6))
    amp = range_amp_bp(c10y, 3)
    trig = trend_down(c10y, min(MA_WIN // 3, 6)) and amp < AMP_BAND_BP
    return {"id": "S2", "name": "行情走强", "triggered": trig,
            "detail": f"10Y 均线方向{'下行' if trend_down(c10y, min(MA_WIN // 3, 6)) else '未下行'} + 振幅 {amp:.0f}BP（阈值 <{AMP_BAND_BP}BP）→ {'走强：超长期利率债攫取债牛收益' if trig else '未确认走强'}",
            "strength": "direction"}


def calc_s3(h, extras=None):
    """S3 纯债行情盘整 → 3-5 年信用债。"""
    c10y = h.get("c10y")
    if not c10y:
        return {"id": "S3", "name": "行情盘整", "triggered": False,
                "detail": "缺字段 c10y", "strength": "direction"}
    clean = _clean(c10y)
    if len(clean) < 2:
        return {"id": "S3", "name": "行情盘整", "triggered": False,
                "detail": "序列过短", "strength": "direction"}
    ma = recent_avg(c10y, min(MA_WIN // 3, 6))
    flat = abs(clean[-1] - ma) * 10000 < MA_FLAT_BP
    return {"id": "S3", "name": "行情盘整", "triggered": flat,
            "detail": f"10Y 最新 {clean[-1]*100:.2f}% vs 均线 {ma*100:.2f}% → 偏离 {(clean[-1]-ma)*10000:.1f}BP（带宽 {MA_FLAT_BP}BP）→ {'盘整：3-5 年信用债性价比' if flat else '非盘整'}",
            "strength": "direction"}


def calc_s4(h, extras=None):
    """S4 纯债行情回调 → 短久期利率债防御。"""
    c10y = h.get("c10y")
    if not c10y:
        return {"id": "S4", "name": "行情回调", "triggered": False,
                "detail": "缺字段 c10y", "strength": "direction"}
    amp = range_amp_bp(c10y, 3)
    trig = trend_up(c10y, min(MA_WIN // 3, 6)) and amp > AMP_BAND_BP
    return {"id": "S4", "name": "行情回调", "triggered": trig,
            "detail": f"10Y 均线{'拐头向上' if trend_up(c10y, min(MA_WIN // 3, 6)) else '未向上'} + 振幅 {amp:.0f}BP（阈值 >{AMP_BAND_BP}BP）→ {'回调：短久期利率债防御' if trig else '未确认回调'}",
            "strength": "direction"}


def calc_s5(h, extras=None):
    """S5 资金宽松类型二确认（动能缺失型）→ 加杠杆套息安全边际高。"""
    ex = extras or {}
    bill = h.get("bill_rate")
    sf = h.get("sf_yoy")
    credit_weak = (bill is not None and get(bill) is not None and get(bill) < BILL_RATE_LOW) or \
                  (sf is not None and get(sf) is not None and get(sf) < 11.0)
    supply_slow = ex.get("supply_slow", False)
    ccy_pressure = ex.get("ccy_pressure", False)
    type2 = credit_weak and supply_slow and not ccy_pressure
    # 终结触发：供给放量 且（信贷回升 或 汇率压力）→ 双重确认（❌ 推断：
    # 单因子"供给放量"在 2023-11~2025-05 全程误报终结（Phase 4 验证 2026-08 发现），
    # 收紧为供给放量+信贷回升/汇率压力同时成立，2024 债牛期不再触发）
    end_signal = (not supply_slow) and (
        ccy_pressure or (sf is not None and get(sf) is not None and trend_up(sf, SF_UP_N)))
    if type2:
        act, trig, strength = "动能缺失型确认 → 加杠杆套息安全边际高，宽松延续", True, "mid"
    elif end_signal:
        act, trig, strength = "终结触发（供给放量/信贷回升/汇率压力）→ 提前降杠杆", True, "mid"
    else:
        act, trig, strength = "类型未明（事件扰动型特征）→ 宽松持续性存疑", False, "direction"
    return {"id": "S5", "name": "资金宽松类型", "triggered": trig,
            "detail": f"信贷需求弱{'是' if credit_weak else '否'} + 政府债供给慢{'是' if supply_slow else '否'} + 汇率压力{'是' if ccy_pressure else '否'} → {act}",
            "strength": strength}


def calc_s6(h, extras=None):
    """S6 资金面生命线（资金收敛 → 降杠杆缩久期）。"""
    dr7 = h.get("dr007")
    omo = get(h.get("omo7d"))
    ex = extras or {}
    if not dr7 or omo is None:
        return {"id": "S6", "name": "资金面生命线", "triggered": False,
                "detail": "缺字段 dr007 / omo7d", "strength": "direction"}
    avg = recent_avg(dr7, min(20, 6))
    gap_bp = (avg - omo) * 10000
    tight = gap_bp > DR7_OMO_BAND or bool(ex.get("cbg_net_issue", False))
    return {"id": "S6", "name": "资金面生命线", "triggered": tight,
            "detail": f"DR007 均值 {avg*100:.3f}% vs OMO {omo*100:.3f}% → 偏离 {gap_bp:+.0f}BP（阈值 {DR7_OMO_BAND}BP）{'、央行回笼中长资金' if ex.get('cbg_net_issue') else ''} → {'资金收敛：降杠杆、缩久期' if tight else '资金不紧：债牛延续，持有久期'}",
            "strength": "strong" if tight else "direction"}


def calc_s7(h, extras=None):
    """S7 10Y ≥ MLF+30BP → 逢高配置、拉久期。"""
    c10y = h.get("c10y")
    mlf = get(h.get("mlf"))
    if not c10y or mlf is None:
        return {"id": "S7", "name": "利率锚上沿", "triggered": False,
                "detail": "缺字段 c10y / mlf", "strength": "direction"}
    upper = mlf + MLF_UPPER_BP / 10000
    latest = c10y[-1]
    trig = latest >= upper
    return {"id": "S7", "name": "利率锚上沿", "triggered": trig,
            "detail": f"10Y {latest*100:.2f}% vs MLF+{MLF_UPPER_BP}BP 上沿 {upper*100:.2f}% → {'逼近/突破锚上沿：配置价值显现，逢高配置、拉久期' if trig else '未达上沿'}",
            "strength": "mid" if trig else "direction"}


def calc_s8(h, extras=None):
    """S8 10Y ≤ 区间下沿（2026：1.6%）→ 交易拥挤，止盈防回调。"""
    c10y = h.get("c10y")
    if not c10y:
        return {"id": "S8", "name": "利率锚下沿", "triggered": False,
                "detail": "缺字段 c10y", "strength": "direction"}
    latest = c10y[-1]
    trig = latest <= RATE_10Y_LOWER + 0.0005
    return {"id": "S8", "name": "利率锚下沿", "triggered": trig,
            "detail": f"10Y {latest*100:.2f}% vs 2026 区间下沿 {RATE_10Y_LOWER*100:.2f}% → {'贴近下沿：交易拥挤，防回调、止盈' if trig else '未达下沿'}",
            "strength": "mid" if trig else "direction"}


def calc_s9(h, extras=None):
    """S9 交易盘由卖转买（基金净买入连续 3 期转正）→ 情绪修复可回补。"""
    fund = h.get("fund_netbuy")
    if not fund or not _clean(fund):
        return {"id": "S9", "name": "交易盘转买", "triggered": False,
                "detail": "缺字段 fund_netbuy（亿元）", "strength": "direction"}
    trig = consec_pos(fund, FUND_POS_N)
    last3 = sum(_clean(fund)[-3:]) if len(_clean(fund)) >= 3 else sum(_clean(fund))
    return {"id": "S9", "name": "交易盘转买", "triggered": trig,
            "detail": f"基金净买入近 {FUND_POS_N} 期{'连续为正' if trig else '未连续为正'}（近 3 期合计 {last3:.0f} 亿）→ {'情绪修复，可回补' if trig else '交易盘未转多'}",
            "strength": "mid" if trig else "direction"}


def calc_s10(h, extras=None):
    """S10 交易盘集体止盈（基金净卖出放量）→ 阶段性防守。"""
    fund = h.get("fund_netbuy")
    if not fund or not _clean(fund):
        return {"id": "S10", "name": "交易盘止盈", "triggered": False,
                "detail": "缺字段 fund_netbuy（亿元）", "strength": "direction"}
    last3 = sum(_clean(fund)[-3:]) if len(_clean(fund)) >= 3 else sum(_clean(fund))
    trig = last3 < FUND_SELL_BIG
    return {"id": "S10", "name": "交易盘止盈", "triggered": trig,
            "detail": f"基金近 3 期净卖出合计 {last3:.0f} 亿（放量阈值 {FUND_SELL_BIG} 亿）→ {'集体止盈：阶段性防守，降久期' if trig else '未见放量止盈'}",
            "strength": "mid" if trig else "direction"}


def calc_s11(h, extras=None):
    """S11 存款自律落地 + 非银存款压降 → 增配低波票息资产。"""
    ex = extras or {}
    dep = h.get("nonbank_deposit")
    deposit_pact = bool(ex.get("deposit_pact", False))
    latest = get(dep) if dep else None
    drop = (latest is not None) and (latest < NONBANK_DEP_DROP)
    trig = deposit_pact and drop
    return {"id": "S11", "name": "存款自律/非银存款", "triggered": trig,
            "detail": f"存款自律落地{'是' if deposit_pact else '否'} + 非银存款单月 {latest if latest is not None else 'N/A'} 亿（压降阈值 {NONBANK_DEP_DROP} 亿）→ {'票息资产稀缺化：增配低波票息（短端/存单/高等级短久期信用）' if trig else '负债端未现重构'}",
            "strength": "mid" if trig else "direction"}


def calc_s12(h, extras=None):
    """S12 理财净值化 + 赎回异动 → 负反馈预警。"""
    ex = extras or {}
    wealth_nav = bool(ex.get("wealth_nav", False))
    redraw = bool(ex.get("wealth_redraw", False))
    trig = wealth_nav and redraw
    return {"id": "S12", "name": "理财净值化赎回", "triggered": trig,
            "detail": f"理财净值化{'是' if wealth_nav else '否'} + 赎回异动{'是' if redraw else '否'} → {'负反馈预警：降杠杆、增流动性' if trig else '未现赎回负反馈'}",
            "strength": "mid" if trig else "direction"}


def calc_s13(h, extras=None):
    """S13 月度节奏三阶段（上旬套息/中旬加久期/下旬降杠杆）。"""
    ex = extras or {}
    month = ex.get("month")
    day = ex.get("day")
    if month is None or day is None:
        return {"id": "S13", "name": "月度节奏阶段", "triggered": False,
                "detail": "缺 extras.month / extras.day", "strength": "direction"}
    if day <= DAY_MID:
        act, tag = "套息策略占优（增量信息繁杂，博弈成本高）", "上旬"
        trig, strength = True, "direction"
    elif day <= DAY_LATE:
        act, tag = "追加久期窗口（政策落地+数据明朗）", "中旬"
        trig, strength = True, "direction"
    else:
        act, tag = "提前压降杠杆（跨季资金波动）；短端调整即补仓机会", "下旬"
        trig, strength = True, "direction"
    return {"id": "S13", "name": "月度节奏阶段", "triggered": trig,
            "detail": f"{month} 月{tag}（day={day}）→ {act}",
            "strength": strength}


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
    if "S8" in mid:
        duration = "缩短久期（防回调/止盈）"
    elif "S10" in mid:
        duration = "降久期（交易盘止盈）"
    elif "S7" in mid:
        duration = "拉长久期（逢高配置）"
    elif "S2" in weak and "S4" not in weak:
        duration = "持有久期（行情走强）"

    leverage = "中性"
    if "S6" in strong:
        leverage = "降杠杆（资金收敛）"
    elif "S12" in mid:
        leverage = "降杠杆（赎回负反馈）"
    elif "S5" in mid:
        leverage = "可加杠杆套息（动能缺失型宽松）"

    structure = []
    if "S1" in strong:
        structure.append("转债+权益进攻（货币趋松&信用趋宽）")
    elif "S1" in mid:
        structure.append("纯债相对占优（非双宽象限）")
    if "S2" in weak:
        structure.append("超长期利率债（行情走强）")
    if "S3" in weak:
        structure.append("3-5 年信用债（行情盘整）")
    if "S4" in weak:
        structure.append("短久期利率债防御（行情回调）")
    if "S11" in mid:
        structure.append("低波票息资产：短端/存单/高等级短久期信用（存款自律）")
    if "S9" in mid:
        structure.append("交易盘转买 → 可回补")
    if "S13" in weak:
        s13 = [s for s in trig if s["id"] == "S13"]
        if s13:
            structure.append("月度节奏：" + s13[0]["detail"].split("→")[-1].strip())

    return {
        "duration": duration,
        "leverage": leverage,
        "structure": structure if structure else ["无强信号，均衡配置（60% 配置仓+40% 弹性仓）"],
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
    lines.append(f"# 刘郁框架 · 债市信号报告（截至 {as_of}）")
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
    lines.append("- **观点引用**：须注明'截至 {日期} 刘郁（{任职机构}）观点'；2023.8-2024.2 属广发证券、2024.3-2026.4 属华西证券、2026.4 后属兴业证券。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 输入契约
# ----------------------------------------------------------------------------

def schema():
    return {
        "description": "analyst-fixed-income-liuyu input schema",
        "history": {
            "required": [
                {"field": "dr007", "description": "DR007 月度序列，最新在末尾"},
                {"field": "r007", "description": "R007 月度序列（货币-信用四象限货币维度）"},
                {"field": "omo7d", "description": "OMO 7 天政策利率序列"},
                {"field": "mlf", "description": "MLF 利率序列（长端核心锚）"},
                {"field": "c10y", "description": "10Y 国债收益率月度序列"},
                {"field": "c1y", "description": "1Y 国债收益率月度序列"},
                {"field": "c30y", "description": "30Y 国债收益率月度序列"},
                {"field": "credit_spread", "description": "信用利差（BP）月度序列"},
                {"field": "sf_yoy", "description": "社融存量同比月度序列（信用维度）"},
                {"field": "fund_netbuy", "description": "基金二级净买入（亿元）月度序列（交易盘）"},
                {"field": "bank_netbuy", "description": "大行二级净买入（亿元）月度序列（配置盘）"},
                {"field": "nonbank_deposit", "description": "非银存款单月变化（亿元）月度序列"},
            ],
            "optional": [
                {"field": "bill_rate", "description": "票据利率（%），供 S5 信贷需求弱判断"},
                {"field": "m1_yoy", "description": "M1 同比（%），货币维度辅助"},
                {"field": "m2_yoy", "description": "M2 同比（%），货币维度辅助"},
            ],
            "format": "字段 -> 月份数组；月份升序，最新值在末尾",
        },
        "extras": {
            "required": [],
            "optional": [
                {"field": "month", "description": "当前月份（1-12），S13 节奏判断"},
                {"field": "day", "description": "当前日（1-31），S13 上/中/下旬切分"},
                {"field": "policy_loose", "description": "降准降息等宽松政策落地（bool）"},
                {"field": "credit_loose", "description": "信用宽松人工判定（bool）"},
                {"field": "supply_slow", "description": "政府债供给偏慢（bool），S5 终结触发判断"},
                {"field": "ccy_pressure", "description": "稳汇率迫切性上升（bool），S5 终结触发"},
                {"field": "cbg_net_issue", "description": "央行回笼中长资金（bool），S6 收紧信号"},
                {"field": "deposit_pact", "description": "存款自律机制落地（bool），S11"},
                {"field": "wealth_nav", "description": "理财回归净值化（bool），S12"},
                {"field": "wealth_redraw", "description": "理财赎回异动（bool），S12"},
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
        "dr007": [round(0.0150 + 0.0004 * _m.sin(i / 6 + 0.5), 4) for i in range(n)],  # 围绕 OMO 波动（资金平稳）
        "r007":  wave(6, 1.0, 0.0006, 0.0008),      # 缓步下行（货币趋松）
        "omo7d": [0.0150] * n,
        "mlf":   [0.0300] * n,
        "c10y":  [round(0.0185 - 0.0016 * _m.sin(i / 6), 4) for i in range(n)],
        "c30y":  [round(0.0235 - 0.0015 * _m.sin(i / 6), 4) for i in range(n)],
        "c1y":   [round(0.0145 + 0.0005 * _m.sin(i / 5), 4) for i in range(n)],
        "credit_spread": [round(48 + 12 * _m.sin(i / 4 + 1), 1) for i in range(n)],
        "sf_yoy": [round(0.108 + 0.0009 * i, 4) for i in range(n)],     # 社融回升（信用趋宽）
        "fund_netbuy": [round(120 * _m.sin(i / 3) - 20, 1) for i in range(n)],
        "bank_netbuy": [round(300 + 80 * _m.sin(i / 4), 1) for i in range(n)],
        "nonbank_deposit": [round(2000 + 1500 * _m.sin(i / 5), 1) for i in range(n)],
        "bill_rate": [round(0.0095 + 0.0003 * _m.sin(i / 4), 4) for i in range(n)],
        "m1_yoy": [round(0.03 + 0.001 * i, 4) for i in range(n)],
        "m2_yoy": [round(0.075 + 0.0004 * i, 4) for i in range(n)],
    }

    return {
        "as_of": months[-1] + "-01",
        "history": history,
        "extras": {
            "month": 8, "day": 15,
            "policy_loose": True, "credit_loose": True,
            "supply_slow": False, "ccy_pressure": False,
            "cbg_net_issue": False,
            "deposit_pact": False, "wealth_nav": True, "wealth_redraw": False,
        },
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="刘郁固收框架信号计算")
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
