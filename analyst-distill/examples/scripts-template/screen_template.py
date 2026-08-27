#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
<skill-name> 信号计算脚本 —— 结构模板（screen_template.py）
============================================================
本文件是 analyst-distill 的【不完整骨架】：
  - 框架已就位且可运行：工具函数 / 参数区 / 五函数结构 / JSON schema / --schema / 四入口
  - 各 calc_* 信号函数为占位实现（返回"未实现"），需按 references/decision-rules.md 填充

标准做法（详见 references/scripts-conventions.md）：
  1. 复制本文件到目标技能 scripts/screen.py
  2. 按 decision-rules.md 的 S 信号表重写参数区（每个阈值带来源分级 ✅/⚠️/❌）
  3. 逐个实现 calc_*（触发条件/阈值/强度），detail 必须含读数
  4. 按领域调整 aggregate_signals（宏观→股债+风格+行业；策略→仓位+风格+区域+主线；等）
  5. 替换 demo_data 字段为 decision-rules.md 数据-规则映射附录的字段清单
  6. 自测：演示模式跑通、demo 下每信号至少触发一次、--schema/--json-out 可解析
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
# 规则：所有阈值集中在此，函数体内不散落裸阈值；每条与 decision-rules.md 逐条对应。
# 格式：<PARAM> = <value>   # 分级：来源说明
#   ✅ 原文 = 分析师公开研究中明确给出的数值（注明出处）
#   ⚠️ 外推 = 有公开依据但未逐字核对（注明"以原文复核"）
#   ❌ 推断 = 分析师未公布、为实现可脚本化的假设（必须写"最小假设，可替换"）
# ------------------------------------------------------------
# 示例（必须按目标分析师的 decision-rules.md 全部替换）：
ERP_HIGH = 0.05      # ✅ 原文：ERP 高于 5% 为高性价比区（示例占位）
ERP_TOP_WARN = 0.00  # ✅ 原文：牛市风险溢价回零 = 顶部预警（示例占位）
PE_CHEAP = 11.0      # ⚠️ 外推：估值洼地分界（以原文复核）
SENTI_COLD = 35.0    # ❌ 推断：最小假设，可替换——情绪冰点阈值
# ============================================================


# ----------------------------------------------------------------------------
# 工具函数（领域无关，通用实现，保留即可）
# ----------------------------------------------------------------------------

def pct_rank(series, value):
    """value 在 series 中的百分位（0-100），用于分位类阈值判断。"""
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


# ----------------------------------------------------------------------------
# 信号计算函数（契约：输入 h / extras → 返回 dict）
# 返回 dict 固定四键：
#   id/name    -> 信号编号与名称（与 decision-rules.md 汇总表一致）
#   triggered  -> bool 是否触发
#   detail     -> str 必须含读数（"XX 最新 5.2% > 阈值 5.0% → 触发"）
#   strength   -> "strong" / "mid" / "direction"（与 decision-rules 规则 0 分级一致）
# ----------------------------------------------------------------------------

def calc_s1(h, extras=None):
    """S1 完整实现示范（照此风格实现其余信号）。

    注意：本函数用占位参数演示【完整实现长什么样】——
    - 从参数区取阈值（不带裸数字）
    - 检查字段缺失（缺失则返回未触发 + 明确提示）
    - detail 含读数与比较结果
    实现新信号时替换为本分析师的 S1 逻辑。
    """
    field = "erp_a"
    if field not in h or not h[field]:
        return {"id": "S1", "name": "示例信号", "triggered": False,
                "detail": f"缺字段 {field}（按映射附录补全）", "strength": "direction"}
    latest = h[field][-1]
    trig = latest > ERP_HIGH
    return {"id": "S1", "name": "示例信号", "triggered": trig,
            "detail": f"{field} 最新 {latest:.3f} vs 阈值 {ERP_HIGH} → {'触发' if trig else '未触发'}",
            "strength": "strong" if trig else "direction"}


def calc_s2(h, extras=None):
    """S2 TODO：从 decision-rules.md 实现（参照 calc_s1 的完整实现风格）。"""
    return {"id": "S2", "name": "S2 待实现", "triggered": False,
            "detail": "TODO：按 decision-rules.md 实现触发逻辑（阈值从参数区取）",
            "strength": "direction"}


def calc_s3(h, extras=None):
    """S3 TODO：同上。多条件信号（如三重共振）须逐项列读数。"""
    return {"id": "S3", "name": "S3 待实现", "triggered": False,
            "detail": "TODO：多条件信号应写 '条件A读数 + 条件B读数 + 条件C读数 → n/m'",
            "strength": "direction"}


# ... 其余 calc_s4 .. calc_sN 同 calc_s2 占位模式，按 decision-rules.md 的信号数补齐


# ----------------------------------------------------------------------------
# 信号汇总 → 仓位/结构/区域建议
# ----------------------------------------------------------------------------

def aggregate_signals(signals, h, extras):
    """汇总触发信号 → 配置建议。

    ⚠️ 本函数是【领域相关骨架】：仓位档位与加减分是 ❌ 推断工程化设计，且因领域而异：
      宏观 -> 股债+风格+行业；策略 -> 仓位+风格+区域+主线；
      固收 -> 久期+曲线形态+信用利差；买方 -> 组合约束+风险预算+回撤控制。
    请按目标分析师 decision-rules.md 的"信号→操作映射"重写建议逻辑（结构保留）。
    """
    trig = [s for s in signals if s["triggered"]]
    strong = [s["id"] for s in trig if s.get("strength") == "strong"]
    mid = [s["id"] for s in trig if s.get("strength") == "mid"]
    weak = [s["id"] for s in trig if s.get("strength") == "direction"]

    equity = 50.0
    if strong:
        equity += 10.0 * len(strong)
    if mid:
        equity += 5.0 * len(mid)
    if weak:
        equity += 2.0 * len(weak)
    equity = max(30.0, min(80.0, equity))

    structure = [f"触发信号：{', '.join(s['id'] for s in trig)}" if trig else "无信号触发，均衡配置"]

    return {
        "equity": round(equity),
        "structure": structure,
        "strong_triggered": strong,
        "mid_triggered": mid,
        "weak_triggered": weak,
    }


# ----------------------------------------------------------------------------
# 报告渲染（领域无关，通用实现）
# ----------------------------------------------------------------------------

def render_report(signals, positions, data, n_triggered, total):
    as_of = data.get("as_of", "N/A")
    demo = not bool(data.get("_real", False))
    lines = []
    lines.append(f"# <skill-name> 框架 · 信号报告（截至 {as_of}）")
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
    lines.append("- **结构/主线**：")
    for t in positions["structure"]:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("## 三、风险提示")
    lines.append("")
    lines.append("- 本报告为分析参考，非投资建议；阈值来源标注见 references/decision-rules.md。")
    lines.append("- **观点引用**：须注明'{分析师姓名}（{任职机构}）{日期}观点'，机构归属随任职变化。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 输入契约（领域相关，交付时按 decision-rules.md 数据-规则映射附录替换）
# ----------------------------------------------------------------------------

def schema():
    """返回调用方准备 --data 所需的最小输入契约。

    成品 SKILL.md 应要求 agent 运行 `python scripts/screen.py --schema` 获取字段清单，
    不要读取 screen.py 源码。
    """
    return {
        "description": "<skill-name> input schema",
        "history": {
            "required": [
                {"field": "erp_a", "description": "示例：A股 ERP 月度序列，最新在末尾"},
            ],
            "optional": [
                {"field": "pe_x", "description": "示例：估值月度序列"},
                {"field": "growth_yoy", "description": "示例：盈利或景气同比月度序列"},
                {"field": "flow_bn", "description": "示例：资金流月度序列，单位亿元"},
            ],
            "format": "字段 -> 月份数组；月份升序，最新值在末尾",
        },
        "extras": {
            "required": [],
            "optional": [
                {"field": "<style_or_stage>", "description": "风格/阶段类人工判定字段，按目标分析师规则替换"}
            ],
        },
        "_meta": "可选；记录每个字段的数据来源、口径差异和降级方式",
    }


# ----------------------------------------------------------------------------
# 演示模式数据（合成）
# ----------------------------------------------------------------------------

def demo_data():
    """生成合成演示数据：字段名 = decision-rules.md 数据-规则映射附录的字段清单。
    序列用"趋势 + 正弦波动"通用生成；实现时按真实字段替换生成逻辑，
    且保证每个信号在窗口内至少触发一次（供自测触发路径）。
    """
    n = 36  # ≥ 30 个月
    fields = ["erp_a", "pe_x", "growth_yoy", "flow_bn"]  # 示例字段，替换为映射附录清单
    rng_base = 2023
    history = {}
    for fi, fld in enumerate(fields):
        series = []
        for i in range(n):
            trend = 0.02 * i                        # 上行趋势（可调方向）
            wave = 0.05 * _m.sin(i / 4 + fi)        # 波动
            series.append(round(1.0 + trend + wave, 3))
        history[fld] = series
    y = rng_base + (n - 1) // 12
    m = (n - 1) % 12 + 1
    return {
        "as_of": f"{y}-{m:02d}-01",
        "history": history,
        "extras": {},  # 风格/阶段类单值，按需填
    }


# ----------------------------------------------------------------------------
# 主流程（领域无关，通用实现，保留即可）
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="<skill-name> 框架信号计算")
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

    # 收集全部信号（calc_* 返回 None 或缺失字段时自动跳过）
    calc_funcs = [calc_s1, calc_s2, calc_s3]  # 实现完成后补全全部 calc_*
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
