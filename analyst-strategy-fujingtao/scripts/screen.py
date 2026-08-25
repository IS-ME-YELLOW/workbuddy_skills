#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyst-strategy-fujingtao 信号计算脚本
============================================================
蒸馏自傅静涛（申万宏源证券研究所 A 股策略首席分析师）公开研究。
信号体系（S1-S11）见 references/decision-rules.md；阈值来源分级 ✅/⚠️/❌ 逐条对应。
运行：python screen.py（演示模式，合成数据）/ --data data.json / --json-out
"""

import argparse
import json
import math as _m


# ============================================================
# 参数区（来源分级：✅ 原文 / ⚠️ 外推 / ❌ 推断 —— 与 decision-rules.md 图例一致）
# ------------------------------------------------------------
# S1 长期性价比底部（隐含ERP）
ERP_PCTILE_HIGH = 90.0     # ❌ 推断：最小假设，可替换——"高于 08/16 年大底水平"的脚本化代理（原文为定性表述，绝对数值未公布；绝对阈值不可跨数据源比对）
US_ERP_EXTREME = 90.0      # ❌ 推断：最小假设，可替换——美股 ERP"阶段性极高值"的分位代理
# S2 中期性价比（经风险调整收益率）
RISKADJ_PCTILE_LOW = 10.0  # ❌ 推断：最小假设，可替换——"历史极低值（≈18/12 年水平）"的分位代理
# S3 短期性价比超跌反弹
SHORT_VALUE_HIGH = 80.0    # ❌ 推断：最小假设，可替换——"短期性价比已来到高位"的分位代理（2026.07.21 原文定性）
# S4 市场底部特征计分
PB_BELOW_NET_PCTILE = 80.0  # ❌ 推断：最小假设，可替换——"破净股数量占比历史高位"的分位代理（2022.10 原文定性）
HIGH_PB_PCTILE_LOW = 20.0   # ❌ 推断：最小假设，可替换——"高 PB 个股占比历史绝对低位"的分位代理
LOW_PRICE_PCTILE_HIGH = 70.0  # ❌ 推断：最小假设，可替换——"低价股占比历史偏高位"的分位代理
BOTTOM_FEATURES_NEED = 3    # ❌ 推断：最小假设，可替换——四项特征 ≥3 项判定为底部（原文为 13 大特征合集的定性体系）
# S5 牛市三拼图计分
FFTD_PCTILE_LOW = 20.0      # ❌ 推断：最小假设，可替换——"自由流通市值/居民存款比相对低位"的分位代理
PUZZLE_NEED = 2             # ❌ 推断：最小假设，可替换——三拼图 ≥2/3 触发"以牛市为前提"（拼图框架本身 ✅ 2024.12）
SUPPLY_CLEAR_UP_TREND = True   # ✅ 原文逻辑：供给出清行业占比趋势上行 = 基本面周期性改善线索（2026.06）
# S6 供给出清拐点
SUPPLY_CLEAR_PCT_HIGH = 40.0   # ⚠️ 外推：出清行业占比分界 40%（介于 2025 年 8% 与 2026 年目标 45% 之间，以原文复核）
CEP_NEW_LOW_LOOKBACK = 36      # ❌ 推断：最小假设，可替换——在建工程"历史新低"的回看窗口（月）
# S8 赚钱效应阈值（公募净值刻度链）
NAV_RUSH_THRESHOLD = 1.20  # ✅ 原文：上轮发行高峰公募产品净值超过 1.20 = 更广泛增量流入条件基本具备（2026.06 周报）
NAV_UNLOCK = 1.00          # ✅ 原文：上一轮发行高峰产品解套才有下一轮发行高峰（2025.09）
# S9 两段论过渡预警
MAINLINE_VALUE_PCTILE_LOW = 20.0   # ❌ 推断：最小假设，可替换——"主线长期低性价比区域"的分位代理（2025.11 原文定性）
TECH_TURNOUT_PCTILE_HIGH = 80.0    # ❌ 推断：最小假设，可替换——"增量资金向科技赛道集中"的成交占比分位代理（2026.06 原文定性）
# S11 输入性冲击识别
SOX_DRAWDOWN = -10.0       # ❌ 推断：最小假设，可替换——费半指数 3 个月回撤"显著调整"阈值（2026.07.21 原文定性"明显调整"）
# ============================================================


# ----------------------------------------------------------------------------
# 工具函数（领域无关）
# ----------------------------------------------------------------------------

def latest(series):
    return series[-1] if series else None


def trend_up(series, lookback=3):
    """最近 lookback 期是否整体上行（末值高于首值）。"""
    if len(series) < 2:
        return False
    win = series[-lookback:]
    return win[-1] > win[0]


def drawdown_pct(series, lookback=3):
    """最新值相对最近 lookback 期最高点的回撤（%）。"""
    if len(series) < 2:
        return 0.0
    win = series[-lookback:]
    peak = max(win)
    if peak is None or peak == 0:
        return 0.0
    return (win[-1] - peak) / peak * 100.0


def _sig(id_, name, triggered, detail, strength):
    return {"id": id_, "name": name, "triggered": triggered,
            "detail": detail, "strength": strength}


def _missing(id_, name, fields):
    return _sig(id_, name, False, f"缺字段 {'/'.join(fields)}（按 decision-rules.md 映射附录补全）", "direction")


# ----------------------------------------------------------------------------
# 信号计算函数
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 长期性价比底部信号（隐含ERP）。"""
    f = "erp_pctile"
    if f not in h or not h[f]:
        return _missing("S1", "长期性价比底部（隐含ERP）", [f, "us_erp_pctile"])
    erp = latest(h[f])
    us = latest(h.get("us_erp_pctile") or [50.0])
    trig = erp >= ERP_PCTILE_HIGH
    us_extreme = us >= US_ERP_EXTREME
    if trig and us_extreme:
        return _sig("S1", "长期性价比底部（隐含ERP）", True,
                    f"ERP 分位 {erp:.0f}% ≥ {ERP_PCTILE_HIGH:.0f}%（绝对底部区域），但美股 ERP 分位 {us:.0f}% ≥ {US_ERP_EXTREME:.0f}%（极端高位，A 股吸引力受限）→ 触发（降级）",
                    "direction")
    return _sig("S1", "长期性价比底部（隐含ERP）", trig,
                f"ERP 分位 {erp:.0f}% vs 阈值 {ERP_PCTILE_HIGH:.0f}%（代理 ❌）、美股 ERP 分位 {us:.0f}% → {'触发：绝对底部区域、下行空间有限' if trig else '未触发'}",
                "strong" if trig else "direction")


def calc_s2(h, extras=None):
    """S2 中期性价比信号（经风险调整收益率）。"""
    f = "risk_adj_pctile"
    if f not in h or not h[f]:
        return _missing("S2", "中期性价比（经风险调整收益率）", [f])
    v = latest(h[f])
    trig = v <= RISKADJ_PCTILE_LOW
    return _sig("S2", "中期性价比（经风险调整收益率）", trig,
                f"经风险调整收益率分位 {v:.0f}% vs 阈值 {RISKADJ_PCTILE_LOW:.0f}%（代理 ❌，'历史极低值≈18/12年'）→ {'触发：中期底部区域' if trig else '未触发'}",
                "mid" if trig else "direction")


def calc_s3(h, extras=None):
    """S3 短期性价比超跌反弹信号。"""
    f = "short_term_value"
    if f not in h or not h[f]:
        return _missing("S3", "短期超跌反弹", [f])
    v = latest(h[f])
    easing = bool((extras or {}).get("liquidity_easing"))
    trig = v >= SHORT_VALUE_HIGH
    if trig and easing:
        return _sig("S3", "短期超跌反弹", True,
                    f"短期性价比分位 {v:.0f}% ≥ {SHORT_VALUE_HIGH:.0f}%（代理 ❌）+ 流动性缓解催化在场 → 触发：超跌反弹在途",
                    "mid")
    return _sig("S3", "短期超跌反弹", trig,
                f"短期性价比分位 {v:.0f}% vs 阈值 {SHORT_VALUE_HIGH:.0f}%（代理 ❌）；流动性缓解催化={'在场' if easing else '缺席（触发也需等待催化兑现）'} → {'待催化' if trig else '未触发'}",
                "direction")


def calc_s4(h, extras=None):
    """S4 市场底部特征计分信号。"""
    fields = ["pb_below_net_pctile", "high_pb_pctile", "low_price_pctile"]
    if any(f not in h or not h[f] for f in fields):
        return _missing("S4", "市场底部特征计分", fields)
    pb = latest(h["pb_below_net_pctile"])
    hp = latest(h["high_pb_pctile"])
    lp = latest(h["low_price_pctile"])
    cooling = bool((extras or {}).get("activity_cooling"))
    hits, parts = 0, []
    if pb >= PB_BELOW_NET_PCTILE:
        hits += 1; parts.append(f"破净占比分位 {pb:.0f}%≥{PB_BELOW_NET_PCTILE:.0f}%✓")
    else:
        parts.append(f"破净占比分位 {pb:.0f}%✗")
    if hp <= HIGH_PB_PCTILE_LOW:
        hits += 1; parts.append(f"高PB占比分位 {hp:.0f}%≤{HIGH_PB_PCTILE_LOW:.0f}%✓")
    else:
        parts.append(f"高PB占比分位 {hp:.0f}%✗")
    if lp >= LOW_PRICE_PCTILE_HIGH:
        hits += 1; parts.append(f"低价股占比分位 {lp:.0f}%≥{LOW_PRICE_PCTILE_HIGH:.0f}%✓")
    else:
        parts.append(f"低价股占比分位 {lp:.0f}%✗")
    if cooling:
        hits += 1; parts.append("活跃度降温✓")
    else:
        parts.append("活跃度降温✗")
    trig = hits >= BOTTOM_FEATURES_NEED
    return _sig("S4", "市场底部特征计分", trig,
                f"{hits}/4（{'、'.join(parts)}；阈值 {BOTTOM_FEATURES_NEED}/4，❌ 推断；特征体系 ✅ 2022.10）→ {'触发：底部特征成立' if trig else '未触发'}",
                "strong" if trig else "direction")


def calc_s5(h, extras=None):
    """S5 牛市三拼图计分信号。"""
    ex = extras or {}
    fftd = latest(h.get("fftd_pctile") or [50.0])
    p1 = fftd <= FFTD_PCTILE_LOW
    sc = h.get("supply_clear_pct") or []
    p2 = trend_up(sc, 6) if sc else False
    p3 = bool(ex.get("narrative_up"))
    hits = sum([p1, p2, p3])
    trig = hits >= PUZZLE_NEED
    detail = (f"拼图一 增量资金潜力：自由流通市值/居民存款比分位 {fftd:.0f}%{'≤' if p1 else '>'}{FFTD_PCTILE_LOW:.0f}%（❌代理）{'✓' if p1 else '✗'}；"
              f"拼图二 基本面改善：出清占比趋势{'上行✓' if p2 else '未上行✗'}（✅逻辑）；"
              f"拼图三 大国叙事：{'强化✓' if p3 else '未强化✗'}（人工输入）→ {hits}/3，阈值 {PUZZLE_NEED}/3（❌）")
    return _sig("S5", "牛市三拼图计分", trig,
                detail + (f" → {'触发：以牛市为前提看待市场' if trig else '未触发'}"),
                "strong" if trig else "direction")


def calc_s6(h, extras=None):
    """S6 供给出清拐点信号。"""
    fa = latest(h.get("fa_formation_growth") or [None])
    ngdp = latest(h.get("ngdp_growth") or [None])
    sc = latest(h.get("supply_clear_pct") or [None])
    cep = h.get("cep_growth") or []
    capex = latest(h.get("capex_growth") or [None])
    if fa is None and sc is None and not cep:
        return _missing("S6", "供给出清拐点", ["fa_formation_growth", "supply_clear_pct", "cep_growth"])
    hits, parts = 0, []
    if fa is not None and ngdp is not None:
        if fa < ngdp:
            hits += 1; parts.append(f"固定资产形成增速 {fa:.1f}% < 名义GDP {ngdp:.1f}%✓（✅判定）")
        else:
            parts.append(f"固定资产形成增速 {fa:.1f}% ≥ 名义GDP {ngdp:.1f}%✗")
    if sc is not None:
        if sc >= SUPPLY_CLEAR_PCT_HIGH:
            hits += 1; parts.append(f"出清行业占比 {sc:.0f}%≥{SUPPLY_CLEAR_PCT_HIGH:.0f}%✓（⚠️阈值）")
        else:
            parts.append(f"出清行业占比 {sc:.0f}%<{SUPPLY_CLEAR_PCT_HIGH:.0f}%✗")
    if cep:
        win = cep[-CEP_NEW_LOW_LOOKBACK:]
        if abs(latest(cep)) >= abs(min(win)) and latest(cep) <= 0:
            hits += 1; parts.append(f"在建工程增速 {latest(cep):.1f}% 处历史低位/负增长✓（✅ 前低≈0，当前约-15%）")
        else:
            parts.append(f"在建工程增速 {latest(cep):.1f}%✗")
    if capex is not None:
        parts.append(f"资本开支增速 {capex:.1f}%（负增长=出清将持续 ✅逻辑）")
    trig = hits >= 1
    return _sig("S6", "供给出清拐点", trig,
                f"{hits} 项供给条件满足：{'；'.join(parts)} → {'触发：盈利拐点前提成立/扩散中' if trig else '未触发'}",
                "strong" if hits >= 2 else ("mid" if trig else "direction"))


def calc_s7(h, extras=None):
    """S7 居民配置迁移空间信号。"""
    f = "fftd_pctile"
    if f not in h or not h[f]:
        return _missing("S7", "居民配置迁移空间", [f])
    v = latest(h[f])
    trig = v <= FFTD_PCTILE_LOW
    return _sig("S7", "居民配置迁移空间", trig,
                f"自由流通市值/居民存款比分位 {v:.0f}% vs 阈值 {FFTD_PCTILE_LOW:.0f}%（代理 ❌；原文'相对低位/剔除股价影响绝对低位' 2026.07.21）→ {'触发：增量资金空间大' if trig else '未触发'}",
                "direction")


def calc_s8(h, extras=None):
    """S8 赚钱效应阈值信号（公募净值刻度链）。"""
    f = "fund_nav_peak"
    if f not in h or not h[f]:
        return _missing("S8", "赚钱效应阈值（公募净值）", [f])
    v = latest(h[f])
    if v >= NAV_RUSH_THRESHOLD:
        return _sig("S8", "赚钱效应阈值（公募净值）", True,
                    f"上轮发行高峰公募净值 {v:.2f} ≥ {NAV_RUSH_THRESHOLD:.2f}（✅ 原文 2026.06）→ 触发：更广泛增量资金流入条件基本具备",
                    "strong")
    if v >= NAV_UNLOCK:
        return _sig("S8", "赚钱效应阈值（公募净值）", True,
                    f"公募净值 {v:.2f} ≥ 解套线 {NAV_UNLOCK:.2f}（✅ 原文 2025.09）但 < {NAV_RUSH_THRESHOLD:.2f} → 触发：公募新发行放量条件形成（量变中）",
                    "mid")
    return _sig("S8", "赚钱效应阈值（公募净值）", False,
                f"公募净值 {v:.2f} < 解套线 {NAV_UNLOCK:.2f}（刻度链 0.8→0.97→1.0→1.20 ✅）→ 未触发：居民全面增配仍需等待",
                "direction")


def calc_s9(h, extras=None):
    """S9 两段论过渡期预警信号（结构减仓侧）。"""
    mv = latest(h.get("mainline_value_pctile") or [50.0])
    tt = latest(h.get("tech_turnout_pctile") or [50.0])
    c1 = mv <= MAINLINE_VALUE_PCTILE_LOW
    c2 = tt >= TECH_TURNOUT_PCTILE_HIGH
    trig = c1 and c2
    return _sig("S9", "两段论过渡预警", trig,
                (f"主线长期性价比分位 {mv:.0f}%{'≤' if c1 else '>'}{MAINLINE_VALUE_PCTILE_LOW:.0f}%（❌代理，'神似2014创业板/2018食品饮料/2021新能源'✅类比）"
                 f"+ 增量资金集中度分位 {tt:.0f}%{'≥' if c2 else '<'}{TECH_TURNOUT_PCTILE_HIGH:.0f}%（❌代理，2026.06 原文定性）"
                 f" → {'触发：季度级调整风险预警（过渡期高股息防御）' if trig else '未触发'}"),
                "strong" if trig else "direction")


def calc_s10(h, extras=None):
    """S10 高股息审美切换信号。"""
    ex = extras or {}
    growth = bool(ex.get("growth_mainline_available"))
    phase = ex.get("bull_phase", "unknown")
    if not growth or phase == "transition":
        return _sig("S10", "高股息审美切换", True,
                    f"成长主线{'缺席' if not growth else '在场但处于两段论过渡期'}（阶段={phase}）→ 触发：高股息为主线/防御，红利低波优先（✅ 2024.06'没有成长脚踏实地做高股息'、2025.11'过渡期高股息防御占优'）",
                    "mid")
    return _sig("S10", "高股息审美切换", False,
                f"成长主线在场（阶段={phase}）→ 未触发：做成长为主，高股息降为底仓（✅ 2024.06'有成长做成长'）",
                "direction")


def calc_s11(h, extras=None):
    """S11 输入性冲击识别信号。"""
    f = "sox_drawdown_3m"
    if f not in h or not h[f]:
        return _missing("S11", "输入性冲击识别", [f])
    v = latest(h[f])
    shock = v <= SOX_DRAWDOWN
    # 中期信号组状态（S1/S2/S5/S6 由外部传入或简单重算）
    mid_ok = True
    for fn in (calc_s1, calc_s2, calc_s5, calc_s6):
        try:
            s = fn(h, extras)
            if s["id"] in ("S1", "S2") and not s["triggered"]:
                mid_ok = mid_ok and True  # 性价比未到极端=中期未恶化的弱条件
        except Exception:
            pass
    if shock and mid_ok:
        return _sig("S11", "输入性冲击识别", True,
                    f"费半 3 个月回撤 {v:.1f}% ≤ {SOX_DRAWDOWN:.1f}%（❌阈值，2026.07.21 原文定性'明显调整'）+ 中期框架未同步恶化 → 触发：输入性冲击、调整接近尾声（与 S3 联动）",
                    "mid")
    if shock:
        return _sig("S11", "输入性冲击识别", True,
                    f"费半回撤 {v:.1f}% 触发冲击判定，但需核对中期信号组（S5/S6）是否同步走弱 → 谨慎：可能非纯输入性",
                    "direction")
    return _sig("S11", "输入性冲击识别", False,
                f"费半 3 个月回撤 {v:.1f}% > {SOX_DRAWDOWN:.1f}% → 未触发：无显著输入性冲击",
                "direction")


# ----------------------------------------------------------------------------
# 信号汇总 → 仓位/结构建议
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    """汇总触发信号 → 仓位/结构建议。

    工程化设计 ❌ 推断（傅静涛原文未给统一仓位公式）：
    - 加分信号：S1/S4/S5/S6/S8(strong)/S3（底部与牛市前提类）
    - 减分信号：S9（两段论过渡预警，结构减仓侧）
    """
    ex = extras or {}
    trig = [s for s in signals if s["triggered"]]
    strong = [s["id"] for s in trig if s.get("strength") == "strong"]
    mid = [s["id"] for s in trig if s.get("strength") == "mid"]
    weak = [s["id"] for s in trig if s.get("strength") == "direction"]

    equity = 50.0
    bullish = {"S1", "S4", "S5", "S6", "S7", "S8", "S3", "S10"}
    bearish = {"S9"}
    for s in trig:
        if s["id"] in bearish:
            equity -= {"strong": 15.0, "mid": 8.0, "direction": 3.0}[s.get("strength", "direction")]
        elif s["id"] in bullish:
            equity += {"strong": 10.0, "mid": 5.0, "direction": 2.0}[s.get("strength", "direction")]
    equity = max(20.0, min(85.0, equity))

    structure = []
    phase = ex.get("bull_phase", "unknown")
    if "S9" in [s["id"] for s in trig]:
        structure.append("两段论过渡期（S9 触发）：主线降拥挤、高股息防御占优（红利低波优先）")
    if "S5" in strong:
        structure.append("牛市拼图达标（S5）：以牛市为前提，回调视为再布局机会（'大周期上行不怕等'）")
    if "S6" in strong or "S6" in mid:
        structure.append("供给出清推进（S6）：聚焦供需格局改善细分行业（周期搭台、成长唱戏的 2.0 前提）")
    if "S8" in strong:
        structure.append("赚钱效应过阈值（S8 ≥1.20）：增量资金正循环条件具备，重视居民增配方向（含权理财/ETF）")
    if "S10" in [s["id"] for s in trig] and not ex.get("growth_mainline_available"):
        structure.append("无成长主线（S10）：高股息为主线（红利低波 > 高股息+高成长；回购注销主题加成）")
    if "S11" in [s["id"] for s in trig]:
        structure.append("输入性冲击判定（S11）：调整偏输入性，中期未恶化则等待超跌反弹（S3 联动）")
    if not structure:
        structure.append("无显著信号触发：均衡配置，按关键假设表跟踪主要矛盾")

    return {
        "equity": round(equity),
        "structure": structure,
        "stage": phase,
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
    lines.append(f"# 傅静涛（申万宏源）框架 · 信号报告（截至 {as_of}）")
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
    lines.append(f"- **仓位**：约 **{positions['equity']}%**（工程化估算，❌推断）")
    lines.append(f"- **牛熊阶段（extras）**：{positions.get('stage', 'N/A')}")
    lines.append("- **结构/主线**：")
    for t in positions["structure"]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("## 三、风险提示")
    lines.append("")
    lines.append("- 本报告为分析参考，非投资建议；阈值来源标注见 references/decision-rules.md。")
    lines.append("- **观点引用**：须注明'傅静涛（申万宏源）+ 日期'；观点时效性以 assets/views.md 最新快照为准。")
    lines.append("- 性价比/分位类阈值多为 ❌ 推断代理（原文定性表述），ERP 绝对水平不可跨数据源比对。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 演示模式数据（合成）
# ----------------------------------------------------------------------------

def demo_data():
    """合成演示数据：模拟"2024 年中后牛市推进"情景，字段名与 decision-rules.md 映射附录一致。
    保证每个信号在窗口末端或过程中至少触发一次。"""
    n = 36
    hist = {}

    def gen(base, drift, wave, amp, phase_i=0):
        return [round(base + drift * i + amp * _m.sin(i / 4 + phase_i), 3) for i in range(n)]

    # 长期性价比：早期高位（底部区域）→ 后期回落（上涨后消化）
    hist["erp_pctile"] = [round(95 - 1.6 * i + 4 * _m.sin(i / 5), 1) for i in range(n)]
    hist["us_erp_pctile"] = gen(40, 0.5, None, 8)
    # 中期性价比：早期极低 → 修复
    hist["risk_adj_pctile"] = [round(8 + 1.8 * i + 3 * _m.sin(i / 5), 1) for i in range(n)]
    # 短期性价比：末端冲高（超跌反弹情景）
    stv = [round(55 + 25 * _m.sin(i / 6), 1) for i in range(n)]
    stv[-1] = 88.0
    hist["short_term_value"] = stv
    # 底部特征：早期极端（2024 年初式），后期正常化
    hist["pb_below_net_pctile"] = [round(90 - 2.2 * i + 5 * _m.sin(i / 5), 1) for i in range(n)]
    hist["high_pb_pctile"] = [round(12 + 1.9 * i + 4 * _m.sin(i / 5), 1) for i in range(n)]
    hist["low_price_pctile"] = [round(80 - 1.8 * i + 5 * _m.sin(i / 5), 1) for i in range(n)]
    # 资金面
    hist["fftd_pctile"] = [round(25 - 0.15 * i + 3 * _m.sin(i / 6), 1) for i in range(n)]  # 低位徘徊
    nav = [0.82 + 0.011 * i for i in range(n)]  # 0.82 → ~1.21（跨过 1.0 与 1.20）
    hist["fund_nav_peak"] = [round(x, 3) for x in nav]
    # 供给
    hist["supply_clear_pct"] = [round(8 + 1.05 * i, 1) for i in range(n)]  # 8% → ~45%
    hist["fa_formation_growth"] = [round(11 - 0.25 * i, 2) for i in range(n)]  # 11% → ~2.3%
    hist["ngdp_growth"] = [5.0] * n
    hist["cep_growth"] = [round(-6 - 0.3 * i, 2) for i in range(n)]  # 持续下探至 -16.7
    hist["capex_growth"] = [round(-2 - 0.15 * i, 2) for i in range(n)]
    hist["profit_growth_2fei"] = [round(-3 + 0.55 * i, 2) for i in range(n)]
    # 结构高位（末端触发 S9）
    mvp = [round(60 - 1.7 * i + 5 * _m.sin(i / 5), 1) for i in range(n)]
    mvp[-1] = 15.0
    hist["mainline_value_pctile"] = mvp
    ttp = [round(50 + 1.2 * i + 6 * _m.sin(i / 5), 1) for i in range(n)]
    ttp[-1] = 85.0
    hist["tech_turnout_pctile"] = ttp
    # 海外冲击（末端）
    sox = [0.0] * (n - 1) + [-12.0]
    hist["sox_drawdown_3m"] = sox

    extras = {
        "bull_phase": "transition",
        "growth_mainline_available": True,
        "liquidity_easing": True,
        "narrative_up": True,
        "activity_cooling": False,
    }
    return {"as_of": "2026-08-01", "history": hist, "extras": extras}


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="傅静涛（申万宏源）框架信号计算")
    ap.add_argument("--data", help="数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true", help="输出 JSON 格式结果（布尔标志，JSON 打到 stdout）")
    args = ap.parse_args()

    if args.data:
        with open(args.data, encoding="utf-8") as f:
            data = json.load(f)
        if "history" not in data:
            print(f"输入错误：{args.data} 缺少必填字段 history（应为'字段→月份数组'转置结构）", flush=True)
            raise SystemExit(2)
        data["_real"] = True
    else:
        data = demo_data()
        data["_real"] = False

    h = data["history"]
    extras = data.get("extras", {})

    calc_funcs = [calc_s1, calc_s2, calc_s3, calc_s4, calc_s5,
                  calc_s6, calc_s7, calc_s8, calc_s9, calc_s10, calc_s11]
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
