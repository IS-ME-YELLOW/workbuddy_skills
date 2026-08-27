#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phase4_fetch_data_template.py —— A 类·数据准备脚本骨架（analyst-distill）
========================================================================
职责：读取原始数据 → 组装 macro_real.json（screen.py --data 的输入契约）。
落位：复制到目标技能 scripts/phase4_fetch_data.py（固定名；不写在工作区）。

数据来源三层标注（贯穿 docstring / 字段注释 / _meta 三处，缺一不可）：
  ✅ westock 真实数据 —— load_* 直连（哪个接口、哪个字段写进函数 docstring）
  ⚠️ 观点锚点插值     —— ANCHORS 每个锚点须能指到分析师原文出处
  ❌ 工程代理         —— build_proxies 每条写"最小假设，可替换"

用法（在目标技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（原始数据 tmp_{analyst}_{source}.txt 提前落盘在 {workspace}/.workbuddy/，见规范 §五）
"""

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区（按目标分析师修改）
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
START_YEAR, END_YEAR, END_MONTH = 2023, 2026, 8   # ❌ 窗口（与前置约定一致）
FIELDS = ["erp_a", "pe_x", "growth_yoy", "flow_bn"]  # ❌ 替换为 decision-rules.md 数据-规则映射附录的字段清单
# ============================================================

MONTHS = (["%d-%02d" % (y, m) for y in range(START_YEAR, END_YEAR) for m in range(1, 13)]
          + ["%d-%02d" % (END_YEAR, m) for m in range(1, END_MONTH + 1)])
assert len(MONTHS) == 44, len(MONTHS)  # 按实际窗口调整期望长度


# ----------------------------------------------------------------------------
# 通用工具层（领域无关，从本模板直接复制，勿改）
# ----------------------------------------------------------------------------

def flatten(path):
    """解 westock 嵌套结构：{"sections": [[...]]} → 扁平 list；普通 list 直接返回。"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict) and "sections" in d:
        out = []
        for sec in d["sections"]:
            out.extend(sec)
        return out
    return d if isinstance(d, list) else []


def month_of(dt_int):
    """20230131 -> '2023-01'"""
    s = str(int(dt_int))
    return "%s-%s" % (s[:4], s[4:6])


def ffill(d, months):
    """按月份补全序列：d 为 {month: value}，缺失月份用最近可用值前填。"""
    out, last = [], None
    for mo in months:
        if mo in d and d[mo] is not None:
            last = d[mo]
        out.append(last)
    return out


def monthly_avg_from_kline(rows, date_key, value_key):
    """日频/周频 K 线 → 月均序列 {month: avg}。注意先过滤 None 再求均值。"""
    by_month = {}
    for r in rows:
        mo = month_of(r.get(date_key))
        v = r.get(value_key)
        if v is not None:
            by_month.setdefault(mo, []).append(v)
    return {mo: round(sum(vs) / len(vs), 4) for mo, vs in by_month.items()}


def anchor_series(anchor_points, months):
    """锚点线性插值：{month: value} → 整段序列（前后无锚点时向边界延伸）。⚠️ 层专用。"""
    keys = sorted(k for k in anchor_points if anchor_points[k] is not None)
    out = []
    for mo in months:
        if mo in anchor_points and anchor_points[mo] is not None:
            out.append(anchor_points[mo])
            continue
        before = [k for k in keys if k <= mo]
        after = [k for k in keys if k > mo]
        if before and after:
            a, b = before[-1], after[0]
            ia, ib, im = months.index(a), months.index(b), months.index(mo)
            va, vb = anchor_points[a], anchor_points[b]
            out.append(round(va + (vb - va) * (im - ia) / max(1, ib - ia), 2))
        elif before:
            out.append(anchor_points[before[-1]])
        elif after:
            out.append(anchor_points[after[0]])
        else:
            out.append(None)
    return out


# ----------------------------------------------------------------------------
# 加载层：✅ westock 直连（每个数据源一函数；docstring 写明 接口→字段→解析要点）
# ----------------------------------------------------------------------------

def load_kline_index():
    """✅ westock：kline <指数代码> → 月度收盘。解析要点：倒序（最新在前）→ 反转；
    日频 → monthly_avg_from_kline 月均。此函数为【完整实现示范】，其余照此风格写。
    """
    path = os.path.join(TMP_DIR, "tmp_{analyst}_kline_index.txt")  # 替换 {analyst}
    if not os.path.exists(path):
        return None  # 原始数据未落盘时安静返回，由缺口检查暴露
    rows = flatten(path)
    if not rows:
        return None
    # 字段名以实际返回为准（常见 EndDate/TradeDate + Close/ClosePrice）
    by_month = monthly_avg_from_kline(rows, "EndDate", "Close")
    return ffill(by_month, MONTHS)


def load_field_a():
    """TODO ✅ westock：<接口> → <字段>。解析要点：嵌套 sections 须 flatten；
    倒序须反转；增量同比口径与存量同比的差异注明。返回 44 长度序列或 None。"""
    return None


def load_field_b():
    """TODO ✅ westock：<接口> → <字段>（日频数据须月均；None 先过滤）。"""
    return None


# ----------------------------------------------------------------------------
# 锚点层：⚠️ 观点锚点插值（每个锚点须能指到分析师原文出处）
# ----------------------------------------------------------------------------

ANCHORS = {
    # 示例（替换为目标分析师的锚点；每个锚点注明出处）：
    # "2024-01": 8.0,   # ⚠️ 外推：《XX 报告》"ERP 处于 8% 历史高位"（以原文复核）
    # "2025-06": 5.3,   # ⚠️ 外推：2026.03 首席连线引用值
}


def build_anchor_fields():
    """⚠️ 层：对每个锚点字段调用 anchor_series 插值。返回 {field: 序列}。"""
    out = {}
    # 示例：out["pe_x"] = anchor_series(ANCHORS_PE, MONTHS)
    return out


# ----------------------------------------------------------------------------
# 代理层：❌ 工程代理（每条写"最小假设，可替换"）
# ----------------------------------------------------------------------------

def build_proxies():
    """❌ 层：无法从任何真实来源获得的字段，按分析师叙事方向构造。
    每条注明：构造逻辑 + 为什么是代理 + 可替换的更优来源。"""
    out = {}
    # 示例：
    # out["retail_senti"] = [ ... ]  # ❌ 推断：散户情绪无公开月度数据，
    #                                # 以"XX 事件后恐慌"叙事构造方向性序列，最小假设可替换
    return out


# ----------------------------------------------------------------------------
# 组装层
# ----------------------------------------------------------------------------

def build_macro_json():
    """合并三层 → {as_of, history, extras, _meta}。_meta 逐字段写来源（强制）。"""
    history, meta = {}, {}

    loaded = {
        # "erp_a": load_field_a(),      # ✅ westock：<接口> → <字段>
        # "growth_yoy": load_field_b(), # ✅ westock：<接口> → <字段>
    }
    demo = load_kline_index()  # 示范实现（{analyst} 占位路径，通常返回 None）
    if demo is not None:
        loaded["index_close"] = demo

    anchors = build_anchor_fields()   # ⚠️ 层
    proxies = build_proxies()         # ❌ 层

    for f, arr in loaded.items():
        if arr is not None:
            history[f], meta[f] = arr, "✅ westock：见 load_* docstring"
    for f, arr in anchors.items():
        history[f], meta[f] = arr, "⚠️ 锚点插值：见 ANCHORS 注释（出处）"
    for f, arr in proxies.items():
        history[f], meta[f] = arr, "❌ 代理：见 build_proxies（最小假设，可替换）"

    # 保证 FIELDS 全部出现（缺失字段留 None 序列，由缺口检查暴露）
    for f in FIELDS:
        history.setdefault(f, [None] * len(MONTHS))
        meta.setdefault(f, "❌ 未提供：数据源缺失或未实现 load_*")

    return {
        "as_of": MONTHS[-1],
        "history": history,
        "extras": {},  # 风格/阶段类单值（B 类脚本按事件时点另行推断）
        "_meta": {
            "_note": "三层来源：✅ westock 直连 / ⚠️ 观点锚点插值 / ❌ 工程代理（最小假设可替换）",
            "fields": meta,
        },
    }


def gap_check(macro):
    """跑完必须执行：逐字段统计 None 月份，缺口大的字段在 validation.md 中降级。"""
    print("=" * 72)
    print("缺口检查（None 月份统计，共 %d 个月）" % len(MONTHS))
    print("=" * 72)
    for f, arr in macro["history"].items():
        n_none = sum(1 for v in arr if v is None)
        flag = "  ⚠️ 缺口大" if n_none > len(MONTHS) * 0.3 else ""
        print("  %-14s None %2d/%d%s" % (f, n_none, len(MONTHS), flag))


def main():
    ap = argparse.ArgumentParser(description="A 类·数据准备：组装 macro_real.json")
    ap.add_argument("--out", default="macro_real.json",
                    help="输出路径（目标技能内为 assets/data/macro_real.json）")
    args = ap.parse_args()

    macro = build_macro_json()
    gap_check(macro)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(macro, f, ensure_ascii=False, indent=1)
    print("\nwrote:", os.path.abspath(args.out))
    print("下一步：python scripts/screen.py --data %s --json-out" % args.out)


if __name__ == "__main__":
    main()
