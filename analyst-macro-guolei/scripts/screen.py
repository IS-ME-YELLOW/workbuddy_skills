#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
screen.py — 郭磊(广发宏观)框架选股/配置信号计算脚本
=====================================================

将郭磊的宏观框架转化为可执行信号（S1-S12），输出仓位/风格/行业建议。

用法：
    python screen.py                  # 演示模式（内置示例数据，验证流程）
    python screen.py --data macro.json  # 用真实宏观数据文件计算
    python screen.py --data macro.json --json-out  # 输出机器可读 JSON

数据文件字段（JSON，所有序列按月排列，最新值在末尾；as_of 为数据截止日）：
{
  "as_of": "2026-07-31",
  "history": {
    "bci":              [..],  # 长江商学院BCI
    "m1_yoy":           [..],  # M1同比(%)
    "ppi_yoy":          [..],  # PPI同比(%)
    "ten_y_yield":      [..],  # 10年期国债收益率(%)
    "div_yield":        [..],  # 万得全A(除金融石油石化)股息率(%)
    "pe":               [..],  # 万得全A市盈率
    "nominal_gdp_yoy":  [..],  # 名义GDP增速(%)
    "fix_inv_yoy":      [..],  # 固定资产投资同比(%)
    "retail_yoy":       [..],  # 社会消费品零售同比(%)
    "export_yoy":       [..],  # 出口同比(%)
    "ind_prod_yoy":     [..],  # 工业增加值同比(%)
    "tech_pmi":         [..],  # 高技术行业PMI
    "construction_pmi": [..],  # 建筑业PMI
    "csad":             [..],  # 羊群因子(CSAD，值越低羊群越强)
    "market_width":     [..],  # 全A 240日宽度(0-100)
    "top5_turnover":    [..]   # 前5%个股成交额占比(%)
  },
  "extras": {
    "ai_chain_inflection": false   # 可选："海外大厂营收-资本开支-国内出口"链二阶拐点
  }
}

依赖：仅标准库。滤波用纯 Python 共轭梯度实现 HP 滤波。
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
#   ✅ 原文  = 郭磊公开研究/报告中明确给出的数值或口径
#   ⚠️ 外推  = 有公开依据但具体数值/分档未经逐字核对，属于合理近似
#   ❌ 推断  = 郭磊未公布，为实现"可脚本化"而作的假设（最小假设，可用真实值替换）
#
#   RATIO_HIST_QUANTILE = 0.10      ✅ 原文（"<10% 分位=权益极具性价比"公开反复出现）
#   DIVERGENCE_WARN/EXTREME_SIGMA  ✅ 原文（"±1σ 警示位、±2σ 极致位"公开表述）
#   DEMAND_WEIGHTS 0.4/0.4/0.2     ⚠️ 外推（公开有"固投+社零+出口加权"口径，具体权重未逐字核对）
#   SCORE_WEIGHTS 等权             ❌ 推断（郭磊公开仅给"三因子加权"与每期因子贡献值，从未公布权重）
#   ROLLING_Z_WINDOW = 36          ⚠️ 外推（"滚动3年标准差"口径公开；36个月为窗口实现）
#   SCORE_MA_WINDOW = 3            ❌ 推断（"近3个月斜率/边际"为资料口径，窗口长度为实现假设）
#   HP 滤波 lambda                 ❌ 推断（公开仅说"滤波提取周期项"，λ 为实现参数）
# ---------------------------------------------------------------------------
DEMAND_WEIGHTS = {"fix_inv": 0.40, "retail": 0.40, "export": 0.20}   # ⚠️ 外推
RATIO_HIST_QUANTILE = 0.10          # ✅ 股债性价比 <10% 分位 = 权益极具性价比
DIVERGENCE_WARN_SIGMA = 1.0         # ✅ 估值-宏观偏离度 +1σ 警示位
DIVERGENCE_EXTREME_SIGMA = 2.0      # ✅ +2σ 极致位
ROLLING_Z_WINDOW = 36               # ⚠️ 滚动3年标准差窗口(月)，口径公开
SCORE_MA_WINDOW = 3                 # ❌ 因子边际变化窗口(月)，推断
# 等权：权重=1，综合得分 = 三因子贡献值之和（郭磊公开口径即"贡献值之和"，数量级 ~0.0x）。
# ❌ 推断：郭磊从未公布权重；此处"每因子1"是最小假设，若获得真实权重（如 0.5/0.3/0.2）直接替换本字典。
SCORE_WEIGHTS = {"growth": 1.0, "monetary": 1.0, "price": 1.0}
HP_LAMBDA = 129600                  # ❌ 实现参数（月度数据常用值，非郭磊公布）


# ---------------------------------------------------------------------------
# 基础工具函数
# ---------------------------------------------------------------------------
def _is_number(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def zscore(series):
    """对序列做 z-score 标准化。"""
    vals = [v for v in series if _is_number(v)]
    if len(vals) < 2:
        return [0.0] * len(series)
    mu = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    if sd == 0:
        return [0.0] * len(series)
    return [(v - mu) / sd if _is_number(v) else 0.0 for v in series]


def percentile_rank(value, series):
    """value 在历史序列中的分位(0-100)。"""
    vals = sorted(v for v in series if _is_number(v))
    if not vals:
        return 50.0
    below = sum(1 for v in vals if v <= value)
    return 100.0 * below / len(vals)


def rolling_zscore(value, series, window=ROLLING_Z_WINDOW):
    """value 相对近 window 期的均值/标准差倍数。"""
    recent = [v for v in series[-window:] if _is_number(v)]
    if len(recent) < 12:
        return 0.0
    mu = statistics.mean(recent)
    sd = statistics.pstdev(recent)
    if sd == 0:
        return 0.0
    return (value - mu) / sd


def hp_filter(series, lamb=129600.0, iters=300):
    """
    Hodrick-Prescott 滤波（月度默认 λ=129600；季度为 1600）。
    纯 Python 共轭梯度求解 (I + λ·D'D)x = y，D 为二阶差分算子。
    返回 (trend, cycle)，cycle = series - trend。
    """
    n = len(series)
    y = [v if _is_number(v) else statistics.mean([v2 for v2 in series if _is_number(v2)]) for v in series]
    x = y[:]

    def d4(v):
        """二阶差分的平方作用于 v（即 D'D v）。"""
        out = [0.0] * n
        for i in range(n):
            s = 0.0
            if i >= 2:
                s += v[i - 2]
            if i >= 1:
                s += -4.0 * v[i - 1]
            s += 6.0 * v[i]
            if i + 1 < n:
                s += -4.0 * v[i + 1]
            if i + 2 < n:
                s += v[i + 2]
            out[i] = s
        return out

    def grad(x):
        g = [0.0] * n
        d = d4(x)
        for i in range(n):
            g[i] = 2.0 * (x[i] - y[i]) + 2.0 * lamb * d[i]
        return g

    r = [-g for g in grad(x)]
    p = r[:]
    rsold = sum(ri * ri for ri in r)
    for _ in range(iters):
        ap = [0.0] * n
        d = d4(p)
        for i in range(n):
            ap[i] = 2.0 * p[i] + 2.0 * lamb * d[i]
        alpha = rsold / (sum(pi * ai for pi, ai in zip(p, ap)) + 1e-12)
        for i in range(n):
            x[i] += alpha * p[i]
            r[i] -= alpha * ap[i]
        rsnew = sum(ri * ri for ri in r)
        if math.sqrt(rsnew) < 1e-10:
            break
        p = [ri + (rsnew / rsold) * pi for ri, pi in zip(r, p)]
        rsold = rsnew
    return x, [yi - xi for yi, xi in zip(y, x)]


# ---------------------------------------------------------------------------
# 规则 1：M1-BCI-PPI 三因子择时
# ---------------------------------------------------------------------------
def calc_m1_bci_ppi(bci, m1_yoy, ppi_yoy):
    """
    返回 dict：三因子 z-score、边际贡献、综合得分、历史得分序列、结论。
    增长=BCI，货币=M1同比，价格=PPI滤波周期项。
    综合得分 = 三因子 z-score 边际变化（近 SCORE_MA_WINDOW 期斜率）之和。
    """
    n = len(bci)
    ppi_trend, ppi_cycle = hp_filter(ppi_yoy, lamb=HP_LAMBDA)
    z_bci = zscore(bci)
    z_m1 = zscore(m1_yoy)
    z_ppi = zscore(ppi_cycle)

    def marginal(z):
        """近 SCORE_MA_WINDOW 期的边际变化（线性斜率）。"""
        w = min(SCORE_MA_WINDOW, n)
        seg = z[-w:]
        if w < 2:
            return 0.0
        xs = list(range(w))
        mx = statistics.mean(xs)
        my = statistics.mean(seg)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, seg))
        den = sum((x - mx) ** 2 for x in xs)
        return num / den if den else 0.0

    contrib = {"growth": marginal(z_bci), "monetary": marginal(z_m1), "price": marginal(z_ppi)}
    score = sum(SCORE_WEIGHTS[k] * v for k, v in contrib.items())   # 等权（❌推断，可替换为真实权重）
    # 历史得分序列（用于判断拐点）：逐月滚动计算
    score_series = []
    for i in range(1, n):
        seg_bci, seg_m1, seg_ppi = z_bci[:i + 1], z_m1[:i + 1], z_ppi[:i + 1]
        w = min(SCORE_MA_WINDOW, i + 1)
        s = 0.0
        for seg, wk in ((seg_bci, SCORE_WEIGHTS["growth"]),
                        (seg_m1, SCORE_WEIGHTS["monetary"]),
                        (seg_ppi, SCORE_WEIGHTS["price"])):
            xs = list(range(w))
            tail = seg[-w:]
            mx = statistics.mean(xs)
            my = statistics.mean(tail)
            num = sum((x - mx) * (y - my) for x, y in zip(xs, tail))
            den = sum((x - mx) ** 2 for x in xs)
            s += wk * (num / den if den else 0.0)
        score_series.append(s)
    prev_score = score_series[-2] if len(score_series) >= 2 else 0.0
    return {
        "contrib": contrib,
        "score": score,
        "prev_score": prev_score,
        "score_series": score_series,
        "verdict": "positive" if score > 0 else ("negative" if score < 0 else "neutral"),
    }


# ---------------------------------------------------------------------------
# 规则 2：胜率-赔率（股债性价比）
# ---------------------------------------------------------------------------
def calc_equity_bond_ratio(ten_y_yield, div_yield):
    """股债性价比 = 10Y国债收益率 - 股息率；返回历史分位 + 滚动3年σ。"""
    spread = [t - d for t, d in zip(ten_y_yield, div_yield)]
    latest = spread[-1]
    pct = percentile_rank(latest, spread)
    z = rolling_zscore(latest, spread)
    return {"spread": latest, "percentile": pct, "rolling_z": z}


# ---------------------------------------------------------------------------
# 规则 3：估值-宏观偏离度
# ---------------------------------------------------------------------------
def calc_valuation_divergence(pe, nominal_gdp_yoy):
    """偏离度 = P/E - 名义GDP增速；返回 σ 倍数。"""
    div = [p - g for p, g in zip(pe, nominal_gdp_yoy)]
    latest = div[-1]
    z = rolling_zscore(latest, div)
    mu = statistics.mean(div)
    return {"divergence": latest, "mean": mu, "sigma": z}


# ---------------------------------------------------------------------------
# 规则 4：供需比
# ---------------------------------------------------------------------------
def calc_supply_demand_ratio(fix_inv, retail, export, ind_prod):
    """
    需求代理 = 0.4×固投 + 0.4×社零 + 0.2×出口；供给代理 = 工业增加值。
    返回序列与方向（最新 vs 3个月均值的边际变化）。
    """
    demand = [DEMAND_WEIGHTS["fix_inv"] * f + DEMAND_WEIGHTS["retail"] * r +
              DEMAND_WEIGHTS["export"] * e for f, r, e in zip(fix_inv, retail, export)]
    supply = list(ind_prod)
    ratio = [d / s if s and s != 0 else 0.0 for d, s in zip(demand, supply)]
    latest = ratio[-1]
    prev_3m = statistics.mean(ratio[-4:-1]) if len(ratio) >= 4 else latest
    direction = "up" if latest > prev_3m else ("down" if latest < prev_3m else "flat")
    return {"demand": demand[-1], "supply": supply[-1], "ratio": latest,
            "ratio_series": ratio, "direction": direction}


# ---------------------------------------------------------------------------
# 规则 5：新旧经济锚
# ---------------------------------------------------------------------------
def calc_new_old_anchor(tech_pmi, construction_pmi):
    latest_tech = tech_pmi[-1]
    latest_cons = construction_pmi[-1]
    tech_mom = tech_pmi[-1] - (statistics.mean(tech_pmi[-4:-1]) if len(tech_pmi) >= 4 else tech_pmi[-1])
    cons_mom = construction_pmi[-1] - (statistics.mean(construction_pmi[-4:-1]) if len(construction_pmi) >= 4 else construction_pmi[-1])
    return {
        "tech_pmi": latest_tech, "construction_pmi": latest_cons,
        "tech_momentum": tech_mom, "construction_momentum": cons_mom,
        "growth_style": latest_tech > latest_cons,
    }


# ---------------------------------------------------------------------------
# 规则 6：叙事周期
# ---------------------------------------------------------------------------
def assess_narrative(csad, width, top5):
    latest_csad = csad[-1]
    csad_pct = percentile_rank(latest_csad, csad)
    latest_width = width[-1]
    latest_top5 = top5[-1]
    top5_high = latest_top5 > statistics.mean(top5) + statistics.pstdev(top5)
    csad_low = csad_pct < 25  # CSAD 处于低分位 = 羊群强 = 叙事强
    if csad_low and top5_high and latest_width < 40:
        stage = "frenzy"      # 狂热期
    elif csad_low and latest_width < 50:
        stage = "acceptance"  # 认同期
    elif not csad_low and latest_width > 60:
        stage = "decline"     # 消退期
    else:
        stage = "neutral"
    return {"csad_percentile": csad_pct, "width": latest_width, "top5": latest_top5, "stage": stage}


# ---------------------------------------------------------------------------
# 信号聚合（S1-S12）
# ---------------------------------------------------------------------------
def aggregate_signals(m1bcippi, ebr, vd, sdr, anchor, narrative, fix_inv, extras):
    signals = []
    s = lambda sid, name, triggered, strength, action, detail: {
        "id": sid, "name": name, "triggered": triggered, "strength": strength,
        "action": action, "detail": detail,
    }

    score = m1bcippi["score"]
    prev = m1bcippi["prev_score"]
    signals.append(s("S1", "M1-BCI-PPI由负转正", prev <= 0 < score, "strong",
                     "权益仓位上调至进攻档", f"得分 {prev:.3f}→{score:.3f}"))
    signals.append(s("S2", "M1-BCI-PPI由正转负", prev > 0 >= score, "strong",
                     "权益仓位下调至防御档", f"得分 {prev:.3f}→{score:.3f}"))
    signals.append(s("S3", "股债性价比<10%分位", ebr["percentile"] < 10, "strong",
                     "逢低重仓优质权益", f"分位 {ebr['percentile']:.1f}% / 滚动3年 {ebr['rolling_z']:+.2f}σ"))
    signals.append(s("S4", "估值-宏观偏离度>+1σ", vd["sigma"] > DIVERGENCE_WARN_SIGMA, "strong",
                     "减仓、增配高股息", f"偏离度 {vd['divergence']:.1f} / {vd['sigma']:+.2f}σ"))
    signals.append(s("S5", "估值-宏观偏离度≥+2σ", vd["sigma"] >= DIVERGENCE_EXTREME_SIGMA, "strong",
                     "大幅防御", f"{vd['sigma']:+.2f}σ"))
    signals.append(s("S6", "供需比由降转升", sdr["direction"] == "up", "medium",
                     "增配周期/顺周期", f"供需比 {sdr['ratio']:.3f}（{sdr['direction']}）"))
    signals.append(s("S7", "高技术PMI上行且>建筑业PMI",
                     anchor["growth_style"] and anchor["tech_momentum"] > 0, "medium",
                     "科技成长占优", f"高技术PMI {anchor['tech_pmi']:.1f} vs 建筑业PMI {anchor['construction_pmi']:.1f}"))
    signals.append(s("S8", "建筑业PMI见底回升", anchor["construction_momentum"] > 0 and
                     anchor["construction_pmi"] < 55, "medium",
                     "增配价值/地产链，对冲利率上行", f"建筑业PMI {anchor['construction_pmi']:.1f}（动量 {anchor['construction_momentum']:+.1f}）"))
    signals.append(s("S9", "叙事进入狂热期", narrative["stage"] == "frenzy", "medium",
                     "主题兑现减仓", f"CSAD分位 {narrative['csad_percentile']:.0f}% / 宽度 {narrative['width']:.0f} / 前5%成交 {narrative['top5']:.1f}%"))
    signals.append(s("S10", "叙事收敛+宽度压力释放", narrative["stage"] == "decline" or
                     (narrative["stage"] == "neutral" and narrative["width"] > 60), "medium",
                     "均值回归布局窗口", f"叙事阶段 {narrative['stage']}"))
    signals.append(s("S11", "固投持续下行(供强需弱加剧)",
                     len(fix_inv) >= 3 and fix_inv[-1] < fix_inv[-2] < fix_inv[-3], "weak",
                     "规避产能过剩上游，聚焦内需政策链", f"固投同比 {fix_inv[-1]:.1f}%"))
    signals.append(s("S12", "AI链二阶拐点", bool(extras.get("ai_chain_inflection", False)), "weak",
                     "AI链减配至标配", "海外大厂营收-资本开支-国内出口链减速"))
    return signals


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------
def render_report(data, m1bcippi, ebr, vd, sdr, anchor, narrative, signals, demo=False):
    lines = []
    lines.append(f"# 郭磊框架 · 宏观择时信号报告（截至 {data.get('as_of', 'N/A')}）")
    if demo:
        lines.append("")
        lines.append("> ⚠️ 数据来源：**演示模式（合成数据）**，仅用于验证流程，非真实宏观数据。请用 --data 传入真实数据。")
    lines.append("")
    lines.append("## 一、M1-BCI-PPI 择时分")
    c = m1bcippi["contrib"]
    lines.append(f"- 综合得分：**{m1bcippi['score']:+.3f}**（上月 {m1bcippi['prev_score']:+.3f}）→ {m1bcippi['verdict']}")
    lines.append(f"- 增长因子(BCI)贡献 {c['growth']:+.3f} ｜ 货币因子(M1)贡献 {c['monetary']:+.3f} ｜ 价格因子(PPI周期项)贡献 {c['price']:+.3f}")
    lines.append("")
    lines.append("## 二、胜率-赔率（股债性价比）")
    lines.append(f"- 10Y国债 − 股息率：**{ebr['spread']:.2f}%**，2015年以来分位 **{ebr['percentile']:.1f}%**，滚动3年 **{ebr['rolling_z']:+.2f}σ**")
    if ebr["percentile"] < 10:
        lines.append("- ⚠️ 分位<10%：权益极具性价比（强买信号）")
    lines.append("")
    lines.append("## 三、估值-宏观偏离度（P/E − 名义GDP）")
    lines.append(f"- 偏离度 {vd['divergence']:.1f}，相对历史均值 {vd['sigma']:+.2f}σ（+1σ 警示 / +2σ 极致）")
    lines.append("")
    lines.append("## 四、供需比")
    lines.append(f"- 需求代理 {sdr['demand']:.2f} vs 供给代理 {sdr['supply']:.2f} → 供需比 {sdr['ratio']:.3f}（{sdr['direction']}）")
    lines.append("")
    lines.append("## 五、新旧经济锚（风格）")
    lines.append(f"- 高技术PMI {anchor['tech_pmi']:.1f}（动量 {anchor['tech_momentum']:+.1f}） vs 建筑业PMI {anchor['construction_pmi']:.1f}（动量 {anchor['construction_momentum']:+.1f}）")
    lines.append(f"- 结论：{'成长/科技占优' if anchor['growth_style'] else '价值/旧经济占优'}")
    lines.append("")
    lines.append("## 六、叙事周期")
    lines.append(f"- 阶段：**{narrative['stage']}**（CSAD分位 {narrative['csad_percentile']:.0f}%、宽度 {narrative['width']:.0f}、前5%成交 {narrative['top5']:.1f}%）")
    lines.append("")
    lines.append("## 七、信号汇总（S1-S12）")
    triggered = [sig for sig in signals if sig["triggered"]]
    lines.append(f"- 触发 {len(triggered)}/{len(signals)} 条：{', '.join(sig['id'] for sig in triggered) if triggered else '无'}")
    for sig in triggered:
        lines.append(f"  - **{sig['id']}** [{sig['strength']}] {sig['name']} → {sig['action']}（{sig['detail']}）")
    lines.append("")
    lines.append("## 八、综合建议")
    strong_bull = any(sig["id"] in ("S1", "S3") for sig in triggered)
    strong_bear = any(sig["id"] in ("S2", "S5") for sig in triggered)
    warn = any(sig["id"] == "S4" for sig in triggered)
    if strong_bull and not strong_bear and not warn:
        lines.append("- 仓位：**进攻档**（权益偏重，逢低加仓）")
    elif strong_bull and warn:
        lines.append("- 仓位：**进攻但逢低布局**（赔率极佳但估值偏离度偏高，勿追高，回调分批加仓）")
    elif strong_bear:
        lines.append("- 仓位：**防御档**（降低权益，增配债券/高股息）")
    elif warn:
        lines.append("- 仓位：**谨慎**（估值偏高，减仓增配高股息防守）")
    else:
        lines.append("- 仓位：**中性**（均衡配置，等待信号强化）")
    if anchor["growth_style"] and not strong_bear:
        lines.append("- 风格：科技/成长占优；如叙事进入狂热期则兑现部分主题")
    else:
        lines.append("- 风格：价值/高股息防守优先")
    if sdr["direction"] == "up":
        lines.append("- 结构：供需比回升，可关注周期/顺周期弹性")
    else:
        lines.append("- 结构：供强需弱，规避产能过剩上游，聚焦内需政策链与高景气新经济")
    lines.append("")
    lines.append("> 说明：观点为时效信息，最新郭磊观点见 assets/views.md；信号与观点冲突时优先遵循信号。")
    lines.append("> 本报告为分析参考，非投资建议。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 演示数据（2022-08 ~ 2026-07，48个月；含 2026.6-7 近似真实值）
# ---------------------------------------------------------------------------
def demo_data():
    import random
    rng = random.Random(42)
    n = 48
    t = list(range(n))
    bci = [50 + 2.2 * math.sin((x - 12) / 9) + rng.uniform(-0.5, 0.5) for x in t]
    m1 = [4.0 + 1.6 * math.sin((x - 6) / 14) + rng.uniform(-0.3, 0.3) for x in t]
    ppi = [-2.5 + 0.13 * x + 1.4 * math.sin(x / 7) + rng.uniform(-0.4, 0.4) for x in t]
    ten_y = [2.35 - 0.018 * x + rng.uniform(-0.05, 0.05) for x in t]
    div = [3.0 + 0.012 * x + rng.uniform(-0.08, 0.08) for x in t]
    pe = [15.5 + 0.06 * x + rng.uniform(-0.4, 0.4) for x in t]
    ngdp = [4.0 + 0.5 * math.sin((x - 6) / 12) + rng.uniform(-0.2, 0.2) for x in t]
    fix = [3.5 - 0.18 * x + rng.uniform(-0.5, 0.5) for x in t]
    retail = [5.0 + 0.5 * math.sin(x / 10) + rng.uniform(-0.4, 0.4) for x in t]
    exp = [3.0 + 0.35 * x + rng.uniform(-0.8, 0.8) for x in t]
    ind = [4.5 + 0.05 * x + rng.uniform(-0.3, 0.3) for x in t]
    tech = [52.5 + 0.7 * math.sin(x / 8) + rng.uniform(-0.4, 0.4) for x in t]
    cons = [54.0 - 0.35 * x / 12 + rng.uniform(-0.5, 0.5) for x in t]
    csad = [1.4 - 0.02 * math.sin(x / 6) + rng.uniform(-0.05, 0.05) for x in t]
    width = [52 + 6 * math.sin(x / 8) + rng.uniform(-2, 2) for x in t]
    top5 = [11.5 + 0.9 * math.sin(x / 9) + rng.uniform(-0.3, 0.3) for x in t]

    # 让最新几期贴近 2026.6-7 的公开值
    bci[-2:] = [50.84, 50.47]
    m1[-3:] = [4.6, 5.0, 4.8]
    ppi[-3:] = [3.1, 3.47, 3.2]
    fix[-3:] = [-1.8, -3.0, -4.1]
    return {
        "as_of": "2026-07-31",
        "history": {
            "bci": bci, "m1_yoy": m1, "ppi_yoy": ppi,
            "ten_y_yield": ten_y, "div_yield": div, "pe": pe, "nominal_gdp_yoy": ngdp,
            "fix_inv_yoy": fix, "retail_yoy": retail, "export_yoy": exp, "ind_prod_yoy": ind,
            "tech_pmi": tech, "construction_pmi": cons, "csad": csad,
            "market_width": width, "top5_turnover": top5,
        },
        "extras": {"ai_chain_inflection": False},
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="郭磊框架宏观择时信号计算")
    ap.add_argument("--data", help="宏观数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true", help="输出 JSON 格式结果")
    args = ap.parse_args()

    data = demo_data() if not args.data else json.load(open(args.data, encoding="utf-8"))
    h = data["history"]
    extras = data.get("extras", {})

    m1bcippi = calc_m1_bci_ppi(h["bci"], h["m1_yoy"], h["ppi_yoy"])
    ebr = calc_equity_bond_ratio(h["ten_y_yield"], h["div_yield"])
    vd = calc_valuation_divergence(h["pe"], h["nominal_gdp_yoy"])
    sdr = calc_supply_demand_ratio(h["fix_inv_yoy"], h["retail_yoy"], h["export_yoy"], h["ind_prod_yoy"])
    anchor = calc_new_old_anchor(h["tech_pmi"], h["construction_pmi"])
    narrative = assess_narrative(h["csad"], h["market_width"], h["top5_turnover"])
    signals = aggregate_signals(m1bcippi, ebr, vd, sdr, anchor, narrative, h["fix_inv_yoy"], extras)

    if args.json_out:
        out = {
            "as_of": data.get("as_of"), "demo": not args.data, "m1_bci_ppi": m1bcippi,
            "equity_bond_ratio": ebr, "valuation_divergence": vd, "supply_demand_ratio": sdr,
            "new_old_anchor": anchor, "narrative": narrative, "signals": signals,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render_report(data, m1bcippi, ebr, vd, sdr, anchor, narrative, signals, demo=not args.data))


if __name__ == "__main__":
    sys.exit(main())
