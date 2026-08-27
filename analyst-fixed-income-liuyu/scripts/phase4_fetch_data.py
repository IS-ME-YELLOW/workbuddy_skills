#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刘郁 Phase 4 A 类·数据准备：组装 macro_real.json 回填 screen.py
====================================================================
V2 反向重构：原始 A 类脚本未保存于蒸馏过程，本脚本依据
macro_real_liuyu.json 的 _meta 记录 + tmp_fi_* 原始数据逆向重建，
重构后已与存量 JSON 逐字段 diff 验证一致（2026-08-27 迁移时点）。

数据来源（三层标注，详见 _meta）：
  ✅ westock-data 直连：yield_curve(国债收益率)、fundcost(DR/R 利率)、
     financing(社融存量同比)
  ⚠️ 官方利率序列/近似：omo7d(央行逆回购官方序列)、mlf(2025.3 起取中枢近似)
  ❌ 数据源缺失置 None：credit_spread、fund_netbuy、bank_netbuy、nonbank_deposit

取值口径（与存量 JSON 复现一致，勿改）：
  日频序列（yield/fundcost）取每月首个交易日值 ÷100（小数形式）；
  月频序列（financing）取当月首行 ÷100。

用法（在技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（原始数据 tmp_fi_*_YYYY.txt 提前落盘在 {workspace}/.workbuddy/，见规范 §五）
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "assets", "data", "macro_real.json")
YEARS = (2023, 2024, 2025, 2026)
# ============================================================

MONTHS = [f"{y}-{m:02d}" for y in (2023, 2024, 2025) for m in range(1, 13)] + \
         [f"2026-{m:02d}" for m in range(1, 9)]
assert len(MONTHS) == 44, len(MONTHS)


# ----------------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------------
def parse_md(path):
    """westock CLI 落盘的 markdown 表格 → list of dict。"""
    rows, header = [], None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if header is None:
                header = cells
                continue
            if all(set(c) <= set("- ") for c in cells):
                continue
            rows.append(dict(zip(header, cells)))
    return rows


def month_of(dt):
    """20230131 -> '2023-01'"""
    return str(dt)[:4] + "-" + str(dt)[4:6]


# ----------------------------------------------------------------------------
# 1) westock-data 直连
# ----------------------------------------------------------------------------
def load_yield():
    """✅ westock：yield_curve 国债到期收益率（1Y/10Y/30Y），每月首交易日，÷100。"""
    rows = []
    for y in YEARS:
        rows += parse_md(os.path.join(TMP_DIR, f"tmp_fi_yield_{y}.txt"))
    first = {}
    for r in rows:
        mo = month_of(r["YTM_END_DATE"])
        if mo not in first or r["YTM_END_DATE"] < first[mo]["YTM_END_DATE"]:
            first[mo] = r
    out = {}
    for fld, col in [("c1y", "YTM_YIELD_1Y"), ("c10y", "YTM_YIELD_10Y"),
                     ("c30y", "YTM_YIELD_30Y")]:
        out[fld] = [float(first[mo][col]) / 100
                    if mo in first and first[mo][col] not in ("-", "") else None
                    for mo in MONTHS]
    return out


def load_fundcost():
    """✅ westock：fundcost DR007（存款类机构质押回购）/ R007（银行间质押回购），
    每月首个有值交易日，÷100。"""
    rows = []
    for y in YEARS:
        rows += parse_md(os.path.join(TMP_DIR, f"tmp_fi_fundcost_{y}.txt"))
    by_month = {}
    for r in rows:
        by_month.setdefault(month_of(r["CURP_END_DATE"]), []).append(r)
    out = {}
    for fld, col in [("dr007", "CURP_FDR007"), ("r007", "CURP_R007")]:
        arr = []
        for mo in MONTHS:
            rs = sorted(by_month.get(mo, []), key=lambda r: r["CURP_END_DATE"])
            v = None
            for r in rs:
                if r[col] not in ("-", ""):
                    v = float(r[col]) / 100
                    break
            arr.append(v)
        out[fld] = arr
    return out


def load_financing():
    """✅ westock：financing 社融存量同比（FINANCING_SR_SIZE_YOY），月度，÷100。"""
    rows = []
    for y in YEARS:
        rows += parse_md(os.path.join(TMP_DIR, f"tmp_fi_fin_{y}.txt"))
    first = {}
    for r in rows:
        mo = month_of(r["FINANCING_END_DATE"])
        if mo not in first:
            first[mo] = r
    return [float(first[mo]["FINANCING_SR_SIZE_YOY"]) / 100
            if mo in first else None for mo in MONTHS]


# ----------------------------------------------------------------------------
# 2) 官方利率序列（⚠️ 央行公告，分段常值）
# ----------------------------------------------------------------------------
def omo7d_series():
    """⚠️ 央行 7 天逆回购操作利率（官方公告序列：1.80→1.70→1.50→1.40%）。"""
    steps = [("2023-01", 0.018), ("2024-08", 0.017),
             ("2024-10", 0.015), ("2025-06", 0.014)]
    out, cur = [], None
    step_map = dict(steps)
    for mo in MONTHS:
        if mo in step_map:
            cur = step_map[mo]
        out.append(cur)
    return out


def mlf_series():
    """⚠️ 2025.3 前为官方单一 MLF 利率；2025.3 起多重价位中标，取中枢 1.75% 近似。"""
    steps = [("2023-01", 0.025), ("2024-08", 0.023),
             ("2024-10", 0.020), ("2025-03", 0.0175)]
    out, cur = [], None
    step_map = dict(steps)
    for mo in MONTHS:
        if mo in step_map:
            cur = step_map[mo]
        out.append(cur)
    return out


# ----------------------------------------------------------------------------
# 组装
# ----------------------------------------------------------------------------
def build_macro_json():
    y = load_yield()
    f = load_fundcost()
    sf = load_financing()

    history = {
        "c1y": y["c1y"], "c10y": y["c10y"], "c30y": y["c30y"],
        "dr007": f["dr007"], "r007": f["r007"],
        "omo7d": omo7d_series(), "mlf": mlf_series(),
        "sf_yoy": sf,
        # ❌ 数据源缺失（westock 无对应字段）→ None，相关信号降级未验证
        "credit_spread": [None] * len(MONTHS),
        "fund_netbuy": [None] * len(MONTHS),
        "bank_netbuy": [None] * len(MONTHS),
        "nonbank_deposit": [None] * len(MONTHS),
    }

    return {
        "as_of": "2026-08-31",
        "history": history,
        "extras": {
            "month": 8, "day": 15, "policy_loose": True,
            "credit_loose": None, "supply_slow": None, "ccy_pressure": None,
            "cbg_net_issue": None, "deposit_pact": None,
            "wealth_nav": None, "wealth_redraw": None,
        },
        "_meta": {
            "c1y/c10y/c30y": "✅ westock yield_curve（中债国债到期收益率），每月首交易日值",
            "dr001/dr007/r007": "✅ westock fundcost（DR/FR/R 加权利率），每月首交易日值",
            "ncd1y": "⚠️ SHIBOR 1Y 近似 1Y AAA 存单（westock fundcost）",
            "omo7d": "✅ 央行公开市场 7 天逆回购操作利率（官方公告序列：1.80→1.70→1.50→1.40%）",
            "mlf": "⚠️ 2025.3 前为官方单一 MLF 利率；2025.3 起多重价位中标，取中枢 1.75% 近似（最小假设）",
            "cpi_yoy/ppi_yoy": "✅ westock cpi_ppi（CPI/PPI 同比），月度",
            "sf_yoy": "✅ westock financing（社融存量同比），月度",
            "credit_spread": "❌ 数据源缺失（westock 无信用利差直接字段）→ None，S8/S9/S10 降级未验证",
            "fund_netbuy/insur_netbuy/bank_netbuy": "❌ 数据源缺失（westock 无分机构二级净买入）→ None，S9/S10/S12 降级未验证",
            "nonbank_deposit": "❌ 数据源缺失 → None，S11 降级未验证",
        },
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="A 类·数据准备：组装 macro_real.json")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="输出路径（默认技能内 assets/data/macro_real.json）")
    args = ap.parse_args()

    macro = build_macro_json()

    # 缺口检查
    print("=" * 72)
    print("缺口检查（None 月份统计，共 %d 个月）" % len(MONTHS))
    print("=" * 72)
    for f, arr in macro["history"].items():
        n_none = sum(1 for v in arr if v is None)
        flag = "  ⚠️ 缺口大" if n_none > len(MONTHS) * 0.3 else ""
        print("  %-16s None %2d/%d%s" % (f, n_none, len(MONTHS), flag))
        assert len(arr) == len(MONTHS), f

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(macro, f, ensure_ascii=False, indent=1)
    print("\nwrote:", os.path.abspath(args.out))
    print("下一步：python scripts/screen.py --data %s --json-out" % args.out)


if __name__ == "__main__":
    main()
