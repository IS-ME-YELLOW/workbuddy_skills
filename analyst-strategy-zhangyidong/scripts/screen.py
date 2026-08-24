#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
张忆东策略框架 · 信号计算脚本（screen.py）
=========================================
将张忆东（兴业/海通国际全球首席策略）的方法论编码为 S1-S12 可执行信号。

用法：
    python screen.py                  # 演示模式（内置合成数据，验证流程）
    python screen.py --data macro.json  # 用真实数据文件计算信号
    python screen.py --json-out        # 输出机器可读 JSON

数据文件字段（JSON，所有序列按月排列、旧→新，最新值在末尾；as_of 为数据截止日）：
{
  "as_of": "2026-07-31",
  "history": {
    "erp_a": [...],            # A股 ERP（%），规则1
    "hsi_pe": [...],           # 恒指前瞻 PE（倍），规则2
    "short_ratio": [...],      # 港股卖空成交占比（%），规则3
    "south_flow": [...],       # 南向资金净流入（亿港元/月），规则2/8
    "south_growth_pct": [...], # 南向资金成长风格占比（%），规则8
    "corp_profit_yoy": [...],  # 工业企业利润同比（%），规则2
    "social_financing_yoy": [...], # 社融存量同比（%），规则4
    "m1_yoy": [...],           # M1 同比（%），规则4
    "ust10": [...],            # 10Y 美债收益率（%），规则5
    "usd_index": [...],        # 美元指数，规则5
    "ai_hardware_crowd": [...],# AI 硬件拥挤度（0-100），规则6
    "ai_app_visible": [...],   # AI 应用盈利可见性（0-1），规则6
    "smart_risk": [...],       # 风险偏好读数（0-100，低=避险），规则7
    "unlock_amt": [...],       # 港股月度解禁规模（亿港元），规则9
    "etf_inflow": [...],       # 机构 ETF 净流入（亿元/月），规则10
    "retail_sentiment": [...], # 散户情绪（0-100，高=亢奋），规则10
    "hs300_pe": [...],         # 沪深300 PE（倍），参考
    "sp500_pe": [...],         # 标普500 席勒PE（倍），参考
    "erp_hsi": [...],          # 恒指 ERP（%），参考
    "foreign_flow": [...]      # 外资净流入中国资产（亿港元/月），参考
  },
  "extras": {
    "south_style": "growth",   # 南向当前风格：growth/dividend
    "ai_phase": "application"  # AI 当前阶段：hardware/application
  }
}

信号 S1-S12 为工程化设计（张忆东没有此编号体系），阈值来源见
references/decision-rules.md 各规则标注（✅原文/⚠️外推/❌推断）。
"""

import argparse
import json
import math
import statistics
import sys


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------

def pct_rank(series, value):
    """value 在 series 中的百分位（0-100）。series 为历史序列（旧→新）。"""
    s = sorted(series)
    n = len(s)
    if n == 0:
        return 50.0
    import bisect
    i = bisect.bisect_left(s, value)
    return i / n * 100.0


def trend_up(series, lookback=3):
    """最新 lookback 月均值 相对 前 lookback 月均值 是否上升。"""
    if len(series) < lookback * 2:
        return False
    recent = statistics.mean(series[-lookback:])
    prior = statistics.mean(series[-lookback * 2:-lookback])
    return recent > prior


def recent_avg(series, lookback=3):
    if len(series) < lookback:
        return statistics.mean(series)
    return statistics.mean(series[-lookback:])


# ----------------------------------------------------------------------------
# 信号计算（S1-S12）
# ----------------------------------------------------------------------------

def calc_erp_signal(h):
    """规则1：风险溢价择时 → S1 高性价比 / S2 顶部预警。"""
    erp = h["erp_a"]
    if not erp:
        return None, None
    v = erp[-1]
    p = pct_rank(erp, v)  # ❌推断：分位窗口=序列全长（约3年），原文未公布窗口
    s1 = {"id": "S1", "name": "A股ERP高性价比", "triggered": False,
          "detail": f"A股ERP {v:.1f}%（{p:.0f}%分位）"}
    s2 = {"id": "S2", "name": "A股ERP顶部预警", "triggered": False,
          "detail": f"A股ERP {v:.1f}%（{p:.0f}%分位）"}
    # ✅原文：>5% 高性价比区（2024.12/2026.03 锚）；牛市 ERP 回 0 = 顶部
    if v > 5.0 or p > 70.0:
        s1["triggered"] = True
        s1["detail"] += " → 高性价比区，权益左侧布局/加仓"
    if v < 1.0 or p < 10.0:
        s2["triggered"] = True
        s2["detail"] += " → 趋近0/低分位，顶部预警，减仓"
    return s1, s2


def calc_hk_resonance(h):
    """规则2：港股三重共振 → S3。估值(<11倍)+资金(南向为正)+盈利(利润改善)，≥2/3 触发。"""
    pe = h["hsi_pe"][-1] if h["hsi_pe"] else None
    south = recent_avg(h["south_flow"], 3) if h["south_flow"] else None
    profit_ok = trend_up(h["corp_profit_yoy"], 3) if h["corp_profit_yoy"] else False

    score = 0
    parts = []
    if pe is not None:
        if pe < 11.0:  # ✅原文：2026.07.30 恒指前瞻 PE <11 倍为估值洼地锚
            score += 1
            parts.append(f"估值✅(PE {pe:.1f}倍<11)")
        else:
            parts.append(f"估值✗(PE {pe:.1f}倍≥11)")
    if south is not None:
        if south > 0:
            score += 1
            parts.append(f"资金✅(南向3月均值{south:.0f}亿>0)")
        else:
            parts.append(f"资金✗(南向{south:.0f}亿≤0)")
    if profit_ok:
        score += 1
        parts.append("盈利✅(利润同比趋势向上)")
    else:
        parts.append("盈利✗(利润趋势未向上)")

    # ❌推断：阈值 2/3（原文未公布，默认 ≥2 项满足）
    s3 = {"id": "S3", "name": "港股三重共振", "triggered": score >= 2,
          "detail": f"{score}/3 共振 | " + " | ".join(parts)}
    return s3


def calc_short_ratio(h):
    """规则3：卖空占比极值 → S4。>18% 高位 = 杀空动能积蓄（✅原文均值15%）。"""
    sr = h["short_ratio"][-1] if h["short_ratio"] else None
    s4 = {"id": "S4", "name": "卖空占比高位", "triggered": False,
          "detail": f"卖空占比 {sr:.1f}%" if sr is not None else "数据缺失"}
    if sr is not None and sr > 18.0:
        s4["triggered"] = True
        s4["detail"] += " → 高位，杀空动能积蓄，港股反弹弹性大"
    elif sr is not None:
        s4["detail"] += f"（历史均值15%，当前{'偏高' if sr > 15 else '偏低'}）"
    return s4


def calc_credit_expansion(h):
    """规则4：信用创造方向 → S5。社融回升 + M1 回升（✅原文：企业中长贷是关键）。"""
    sf = h["social_financing_yoy"]
    m1 = h["m1_yoy"]
    sf_ok = trend_up(sf, 3) if sf else False
    m1_ok = trend_up(m1, 3) if m1 else False
    s5 = {"id": "S5", "name": "信用扩张确认", "triggered": False,
          "detail": f"社融趋势{'回升✅' if sf_ok else '未回升✗'} | M1趋势{'回升✅' if m1_ok else '未回升✗'}"}
    if sf_ok and m1_ok:
        s5["triggered"] = True
        s5["detail"] += " → 信用扩张，权益仓位中枢上移"
    return s5


def calc_ust_chain(h):
    """规则5：美债-美元传导链 → S6 破4%进攻 / S7 摸5%灰犀牛。"""
    ust = h["ust10"][-1] if h["ust10"] else None
    s6 = {"id": "S6", "name": "美债破4%估值扩张", "triggered": False,
          "detail": f"10Y美债 {ust:.2f}%" if ust is not None else "数据缺失"}
    s7 = {"id": "S7", "name": "美债高位灰犀牛", "triggered": False,
          "detail": f"10Y美债 {ust:.2f}%" if ust is not None else "数据缺失"}
    if ust is not None:
        if ust < 4.0:  # ✅原文：2026 Q4 路径向下突破4% → 估值扩张窗口
            s6["triggered"] = True
            s6["detail"] += " → 估值扩张窗口，中国资产进攻"
        elif ust > 4.5:  # ✅原文：2026.08 或向4.8-4.9%、可能摸5% = 灰犀牛
            s7["triggered"] = True
            s7["detail"] += " → 高位灰犀牛，短期压制，逆势布局不追高"
    return s6, s7


def calc_ai_clock(h):
    """规则6：AI 应用扩散时钟 → S8。硬件拥挤回落 + 应用盈利可见。"""
    crowd = h["ai_hardware_crowd"]
    app = h["ai_app_visible"]
    crowd_ok = False
    if crowd and len(crowd) >= 4:
        crowd_ok = crowd[-1] < statistics.mean(crowd[-4:-1])  # 最新 < 前3月均值 = 拥挤回落
    app_ok = bool(app and app[-1] > 0.6)  # ❌推断：0.6 阈值，原文只给方向
    s8 = {"id": "S8", "name": "AI应用扩散确认", "triggered": False,
          "detail": f"硬件拥挤{'回落✅' if crowd_ok else '未回落✗'} | 应用可见性{app[-1] if app else 'N/A'}{'>0.6✅' if app_ok else '≤0.6✗'}"}
    if crowd_ok and app_ok:
        s8["triggered"] = True
        s8["detail"] += " → 应用下半场启动，超配AI应用，减配拥挤硬件"
    return s8


def calc_smart_rotation(h):
    """规则7：SMART 三主线轮动 → S9。风险偏好决定主线倾斜。"""
    risk = h["smart_risk"][-1] if h["smart_risk"] else None
    s9 = {"id": "S9", "name": "SMART主线轮动", "triggered": False,
          "detail": f"风险偏好 {risk:.0f}（0-100）" if risk is not None else "数据缺失"}
    if risk is not None:
        if risk < 30:  # ❌推断：分档阈值，方向✅原文（风险偏好低→S安全资产）
            s9["detail"] += " → S安全资产占优（避险）"
        elif risk > 70:
            s9["detail"] += " → RT硬科技占优（进攻）"
        else:
            s9["detail"] += " → MA制造出海/均衡"
        s9["triggered"] = True  # 轮动信号总是输出方向（非触发型）
    return s9


def calc_south_style(h, extras):
    """规则8：南向风格切换 → S10。成长占比高/上升 = 港股结构进攻。"""
    g = h["south_growth_pct"]
    style = extras.get("south_style", "dividend")
    val = g[-1] if g else None
    s10 = {"id": "S10", "name": "南向风格转向成长", "triggered": False,
           "detail": f"成长占比 {val:.0f}%（风格={style}）" if val is not None else f"风格={style}"}
    growth_ok = (val is not None and val > 50) or (g is not None and trend_up(g, 3) and val > 40)
    if style == "growth" or growth_ok:
        s10["triggered"] = True
        s10["detail"] += " → 港股结构进攻（成长扩散）"
    else:
        s10["detail"] += " → 红利防御阶段"
    return s10


def calc_unlock(h):
    """规则9：解禁/IPO 供给冲击 → S11。>4000 亿港元 = 高峰月。"""
    amt = h["unlock_amt"][-1] if h["unlock_amt"] else None
    s11 = {"id": "S11", "name": "解禁/IPO高峰", "triggered": False,
           "detail": f"当月解禁 {amt:.0f}亿港元" if amt is not None else "数据缺失"}
    if amt is not None and amt > 4000:  # ✅原文：2026.09 解禁5007亿为高峰；4000为⚠️外推阈值
        s11["triggered"] = True
        s11["detail"] += " → 供给压力窗口，不追高分批建仓"
    return s11


def calc_bottom_feature(h):
    """规则10：机构-散户背离 → S12。机构ETF净流入 + 散户撤离 = 底部特征。"""
    etf = h["etf_inflow"][-1] if h["etf_inflow"] else None
    retail = h["retail_sentiment"][-1] if h["retail_sentiment"] else None
    s12 = {"id": "S12", "name": "机构散户背离(底部特征)", "triggered": False,
           "detail": f"机构ETF净流入{etf if etf is not None else 'N/A'}亿 | 散户情绪{retail if retail is not None else 'N/A'}"}
    # ✅原文：2026.07 机构ETF +4700亿、散户恐慌撤离 = 底部特征
    if etf is not None and retail is not None and etf > 0 and retail < 40:
        s12["triggered"] = True
        s12["detail"] += " → 机构吸筹+散户撤离，逆势布局辅助确认"
    return s12


# ----------------------------------------------------------------------------
# 汇总与配置建议
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    """统计触发数并生成仓位/结构/港股建议。仓位档位为 ❌推断工程化设计。"""
    strong_trig = [s["id"] for s in signals if s["triggered"] and s["id"] in
                   ("S1", "S3", "S6", "S8")]
    mid_trig = [s["id"] for s in signals if s["triggered"] and s["id"] in
                ("S2", "S4", "S5", "S7", "S10")]
    weak_trig = [s["id"] for s in signals if s["triggered"] and s["id"] in
                 ("S11", "S12")]

    equity = 50.0
    if "S1" in strong_trig:
        equity += 10
    if "S6" in strong_trig:
        equity += 5
    if "S2" in strong_trig:
        equity -= 15
    if "S7" in mid_trig:
        equity -= 5
    if "S5" in mid_trig:
        equity += 5
    if "S12" in weak_trig:
        equity += 3
    equity = max(30.0, min(80.0, equity))

    structure = []
    if "S8" in strong_trig:
        structure.append("超配AI应用（软件/传媒/智能化终端/AI+出海），减配拥挤硬件")
    s9 = next((s for s in signals if s["id"] == "S9"), None)
    if s9 and "占优" in s9["detail"]:
        structure.append("SMART主线：" + s9["detail"].split("→ ")[-1])
    if "S12" in weak_trig:
        structure.append("逆势布局期：左侧分批，不追高")
    if "S7" in mid_trig:
        structure.append("外部压制期：聚焦错杀机会（有色/黄金铜铝小金属）")
    if not structure:
        structure.append("均衡配置 SMART 三主线（S/MA/RT 等权分散）")

    hk = []
    if "S3" in strong_trig:
        hk.append("港股战略配置（三重共振）")
    if "S4" in mid_trig:
        hk.append("卖空高位=杀空动能，反弹弹性大")
    if "S10" in mid_trig:
        hk.append("南向成长化→港股成长/资讯科技进攻")
    if "S11" in weak_trig:
        hk.append("解禁高峰月，不追高分批建仓")
    if not hk:
        hk.append("港股中性（防守反击：科技成长/高股息红利/价值成长）")

    return {
        "equity": round(equity),
        "structure": structure,
        "hk": hk,
        "strong_triggered": strong_trig,
        "mid_triggered": mid_trig,
        "weak_triggered": weak_trig,
    }


# ----------------------------------------------------------------------------
# 报告渲染
# ----------------------------------------------------------------------------

def render_report(signals, positions, data, n_triggered, total):
    as_of = data.get("as_of", "N/A")
    demo = not bool(data.get("_real", False))
    lines = []
    lines.append(f"# 张忆东框架 · 策略信号报告（截至 {as_of}）")
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
    lines.append(f"- **权益仓位**：约 **{positions['equity']}%**（工程化估算，❌推断）")
    lines.append("- **结构主线**：")
    for t in positions["structure"]:
        lines.append(f"  - {t}")
    lines.append("- **港股**：")
    for t in positions["hk"]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("## 三、风险提示")
    lines.append("")
    lines.append("- 本报告为分析参考，非投资建议；阈值来源标注见 references/decision-rules.md。")
    lines.append("- **观点引用**：须注明'张忆东（机构）{日期}观点'，机构归属 2025.12 前兴业/2026.02 起海通国际。")
    lines.append("- **2028 预警**（✅原文）：2028 年对 AI 牛市是一道大坎，不排除'灭顶之灾'——2027 下半年起逐步降杠杆。")
    lines.append("- '别上杠杆，别追拥挤板块'（✅原文 2026.07.30）。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 演示模式数据（合成，43 个月：2023-01 ~ 2026-07）
# ----------------------------------------------------------------------------

def demo_data():
    n = 43
    import math as _m
    base = 2023 + (0.0 / 12)
    # 构造时间序列：ERP 从高位（2023 平衡市 ~5.5%）→ 2024 底部抬升 → 2025 牛市回落 → 2026 调整
    erp_a = []
    for i in range(n):
        # 2023 前段 5.6→5.2，2024 见顶 5.5，2025 回落 3.5，2026 再抬 4.6
        m = i % 12 + 1
        yr = 2023 + i // 12
        if yr == 2023:
            v = 5.7 - 0.05 * m
        elif yr == 2024:
            v = 5.2 + 0.05 * m
        elif yr == 2025:
            v = 4.2 - 0.12 * m
        else:
            v = 3.2 + 0.1 * m
        erp_a.append(round(v + 0.05 * _m.sin(i / 2), 2))

    hsi_pe = [round(9.2 + 0.2 * _m.sin(i / 3), 1) for i in range(n)]
    short_ratio = [round(15 + 3 * _m.sin(i / 4) + (2 if i > 30 else 0), 1) for i in range(n)]
    south_flow = [round(300 + 200 * _m.sin(i / 3), 0) for i in range(n)]
    south_growth_pct = [round(min(70, 30 + i * 1.0), 0) for i in range(n)]
    corp_profit_yoy = [round(-5 + 0.4 * i, 1) for i in range(n)]
    social_financing_yoy = [round(9.0 + 0.05 * i, 2) for i in range(n)]
    m1_yoy = [round(-3 + 0.3 * i, 1) for i in range(n)]
    ust10 = [round(4.6 - 0.02 * i + 0.4 * _m.sin(i / 5), 2) for i in range(n)]
    usd_index = [round(104 - 0.05 * i + _m.sin(i / 4), 1) for i in range(n)]
    ai_hardware_crowd = [round(50 + 20 * _m.sin(i / 6) + (15 if i > 24 else 0), 0) for i in range(n)]
    ai_app_visible = [round(min(1.0, 0.15 + 0.02 * i), 2) for i in range(n)]
    smart_risk = [round(45 + 15 * _m.sin(i / 5), 0) for i in range(n)]
    unlock_amt = [round(2500 + 600 * _m.sin(i / 4) + (2500 if i in (36, 37, 38) else 0), 0) for i in range(n)]
    etf_inflow = [round(200 + 250 * _m.sin(i / 4) + (400 if i > 35 else 0), 0) for i in range(n)]
    retail_sentiment = [round(60 - 0.6 * i, 0) for i in range(n)]
    hs300_pe = [round(11 + 0.6 * _m.sin(i / 4), 1) for i in range(n)]
    sp500_pe = [round(30 + 0.5 * i / 2, 1) for i in range(n)]
    erp_hsi = [round(8.5 - 0.06 * i, 1) for i in range(n)]
    foreign_flow = [round(50 + 80 * _m.sin(i / 3), 0) for i in range(n)]

    return {
        "as_of": "2026-07-31",
        "history": {
            "erp_a": erp_a, "hsi_pe": hsi_pe, "short_ratio": short_ratio,
            "south_flow": south_flow, "south_growth_pct": south_growth_pct,
            "corp_profit_yoy": corp_profit_yoy, "social_financing_yoy": social_financing_yoy,
            "m1_yoy": m1_yoy, "ust10": ust10, "usd_index": usd_index,
            "ai_hardware_crowd": ai_hardware_crowd, "ai_app_visible": ai_app_visible,
            "smart_risk": smart_risk, "unlock_amt": unlock_amt,
            "etf_inflow": etf_inflow, "retail_sentiment": retail_sentiment,
            "hs300_pe": hs300_pe, "sp500_pe": sp500_pe, "erp_hsi": erp_hsi,
            "foreign_flow": foreign_flow,
        },
        "extras": {"south_style": "growth", "ai_phase": "application"},
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="张忆东策略框架信号计算")
    ap.add_argument("--data", help="数据 JSON 文件路径（缺省为演示模式）")
    ap.add_argument("--json-out", action="store_true", help="输出 JSON 格式结果")
    args = ap.parse_args()

    if args.data:
        with open(args.data, encoding="utf-8") as f:
            data = json.load(f)
        data["_real"] = True
    else:
        data = demo_data()
        data["_real"] = False

    h = data["history"]
    extras = data.get("extras", {})

    s1, s2 = calc_erp_signal(h)
    s3 = calc_hk_resonance(h)
    s4 = calc_short_ratio(h)
    s5 = calc_credit_expansion(h)
    s6, s7 = calc_ust_chain(h)
    s8 = calc_ai_clock(h)
    s9 = calc_smart_rotation(h)
    s10 = calc_south_style(h, extras)
    s11 = calc_unlock(h)
    s12 = calc_bottom_feature(h)

    signals = [s for s in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12) if s]
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
        report = render_report(signals, positions, data, n_trig, len(signals))
        print(report)


if __name__ == "__main__":
    main()
