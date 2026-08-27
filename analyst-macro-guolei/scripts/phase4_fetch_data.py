#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
郭磊 Phase 4 A 类·数据准备：组装 macro_real.json 回填 screen.py
====================================================================
V2 迁移自工作区 phase4_validate.py 的数据构造部分（V1 范式：硬编码
序列 + 日频文件月均，计算逻辑原样保留，已与存量 JSON diff 验证一致）。

数据来源（westock-data / 国家统计局公开值，详见 _meta）：
  - M1同比: fundquantity 2021-2026（查询值）
  - PPI同比: 2023-2026 查询值；2021-2022 统计局公开值
  - 企业景气指数(BCI代理): prosperity 2021-2026 季度值（月度前向填充）
  - 10Y国债收益率: yield_curve 日频月均
  - 股债溢价率: premium_curve 日频（EquityPremium=E/P−10Y; DividendPremium=股息率−10Y）
  - 名义GDP/PMI: gdp、prosperity 查询值
  代理与缺口说明见 references/validation.md

用法（在技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（日频原始数据 tmp_premium_curve.txt / tmp_yield_curve.txt 提前落盘在
  {workspace}/.workbuddy/，见规范 §五）
"""
import argparse
import json
import os
import statistics
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "assets", "data", "macro_real.json")
# ============================================================

# ---------------------------------------------------------------------------
# 月度序列（2021-01 ~ 2026-07，67 个月；macro 输出窗口为其中 2023-01 起）
# ---------------------------------------------------------------------------
MONTHS = []
for y in range(2021, 2027):
    for m in range(1, 13):
        if y == 2026 and m > 7:
            break
        MONTHS.append(f"{y}-{m:02d}")

M1_YOY = [
    # 2021
    14.7, 7.4, 7.1, 6.2, 6.1, 5.5, 4.9, 4.2, 3.7, 2.8, 3.0, 3.5,
    # 2022
    -1.9, 4.7, 4.7, 5.1, 4.6, 5.8, 6.7, 6.1, 6.4, 5.8, 4.6, 3.7,
    # 2023
    6.7, 5.8, 5.1, 5.3, 4.7, 3.1, 2.3, 2.2, 2.1, 1.9, 1.3, 1.3,
    # 2024
    3.3, 2.6, 2.3, 0.6, -0.8, -1.7, -2.6, -3.0, -3.3, -2.3, -0.7, 1.2,
    # 2025
    0.4, 0.1, 1.6, 1.5, 2.3, 4.6, 5.6, 6.0, 7.2, 6.2, 4.9, 3.8,
    # 2026
    4.9, 5.9, 5.1, 5.0, 5.5, 4.0, 4.0,
]

PPI_YOY = [
    # 2021（统计局公开值）
    0.3, 1.7, 4.4, 6.8, 9.0, 8.8, 9.0, 9.5, 10.7, 13.5, 12.9, 10.3,
    # 2022（统计局公开值）
    9.1, 8.8, 8.3, 8.0, 6.4, 6.1, 4.2, 2.3, 0.9, -1.3, -1.3, -0.7,
    # 2023（统计局公开值）
    -0.8, -1.4, -2.5, -3.6, -4.6, -5.4, -4.4, -3.0, -2.5, -2.6, -3.0, -2.7,
    # 2024（westock-data 查询值，1/6月以公开值补全）
    -2.5, -2.7, -2.8, -2.5, -1.4, -0.8, -0.8, -1.0, -2.8, -2.9, -2.5, -2.3,
    # 2025（westock-data 查询值）
    -2.3, -2.2, -2.5, -2.7, -3.3, -3.6, -3.6, -2.9, -2.3, -2.1, -2.2, -1.9,
    # 2026（westock-data 查询值）
    -1.4, -0.9, 0.5, 2.8, 3.9, 4.1, 3.5,
]

# 企业景气指数(企业家信心指数, 季度) — BCI 代理（westock-data prosperity 查询值）
BOOM_Q = {
    2021: [125.2, 123.8, 119.2, 119.2],
    2022: [112.7, 101.8, 100.6, 98.9],
    2023: [107.8, 105.9, 108.6, 109.0],
    2024: [109.1, 107.5, 108.1, 108.3],
    2025: [108.5, 108.5, 108.9, 108.4],
    2026: [109.3, 109.5],
}

def boom_monthly():
    out = []
    for y in range(2021, 2027):
        for m in range(1, 13):
            if y == 2026 and m > 7:
                break
            q = min((m - 1) // 3, len(BOOM_Q[y]) - 1)
            out.append(BOOM_Q[y][q])
    return out

BCI_PROXY = boom_monthly()

# 名义GDP当季同比（westock-data gdp 查询值，季度→月度填充）
NGDP_Q = {  # (year, quarter) -> 当季同比%
    (2023, 1): 5.5, (2023, 2): 5.3, (2023, 3): 4.0, (2023, 4): 3.7,
    (2024, 1): 4.0, (2024, 2): 4.1, (2024, 3): 4.0, (2024, 4): 4.6,
    (2025, 1): 7.6, (2025, 2): 6.6, (2025, 3): 6.5, (2025, 4): 3.8,
    (2026, 1): 4.8, (2026, 2): 5.8,
}

def ngdp_monthly():
    out = []
    for y in range(2023, 2027):
        for m in range(1, 13):
            if y == 2026 and m > 7:
                break
            q = min((m - 1) // 3 + 1, 4)
            out.append(NGDP_Q.get((y, q), NGDP_Q[(y, 2 if y == 2026 else 4)]))
    return out

# PMI（westock-data 查询值，制造业 / 非制造业商务活动）
PMI_MANU = [
    50.1, 52.6, 51.9, 49.2, 48.8, 49.0, 49.3, 49.7, 50.2, 49.5, 49.4, 49.0,  # 2023
    49.2, 49.1, 50.8, 50.4, 49.5, 49.5, 49.4, 49.1, 49.8, 50.1, 50.3, 50.1,  # 2024
    49.1, 50.2, 50.5, 49.0, 49.5, 49.7, 49.3, 49.4, 49.8, 49.0, 49.2, 50.1,  # 2025
    49.3, 49.0, 50.4, 50.3, 50.0, 50.3, 49.2,                                # 2026
]
PMI_NONMANU = [
    54.4, 56.3, 58.2, 56.4, 54.5, 53.2, 51.5, 51.0, 51.7, 50.6, 50.2, 50.4,  # 2023
    50.7, 51.4, 53.0, 51.2, 51.1, 50.5, 50.2, 50.3, 50.0, 50.2, 50.0, 52.2,  # 2024
    50.2, 50.4, 50.8, 50.4, 50.3, 50.5, 50.1, 50.3, 50.0, 50.1, 49.5, 50.2,  # 2025
    49.4, 49.5, 50.1, 49.4, 50.1, 50.2, 49.0,                                # 2026
]

# ---------------------------------------------------------------------------
# 解析日频文件：溢价率曲线 / 10Y 收益率
# ---------------------------------------------------------------------------
def parse_premium_curve():
    dates, ep, dp = [], [], []
    with open(os.path.join(TMP_DIR, "tmp_premium_curve.txt"), encoding="utf-8") as f:
        for line in f:
            parts = [p.strip() for p in line.split("|")]
            # 行格式: | EndDate | DividendPremium | EquityPremium |
            if len(parts) >= 4 and parts[1].isdigit() and len(parts[1]) == 8:
                try:
                    dates.append(parts[1])
                    dp.append(float(parts[2]))   # DividendPremium = 股息率 - 10Y
                    ep.append(float(parts[3]))   # EquityPremium = E/P - 10Y
                except ValueError:
                    dates.pop()
                    continue
    return dates, ep, dp

def parse_yield10():
    dates, y10 = [], []
    with open(os.path.join(TMP_DIR, "tmp_yield_curve.txt"), encoding="utf-8") as f:
        for line in f:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[1].isdigit() and len(parts[1]) == 8:
                try:
                    dates.append(parts[1]); y10.append(float(parts[3]))
                except ValueError:
                    pass
    return dates, y10

PREM_DATES, PREM_EP, PREM_DP = parse_premium_curve()
Y10_DATES, Y10 = parse_yield10()

def monthly_avg(series_dates, series_vals, y, m):
    vals = [v for d, v in zip(series_dates, series_vals) if d[:4] == str(y) and d[4:6] == f"{m:02d}"]
    return statistics.mean(vals) if vals else None

# ---------------------------------------------------------------------------
# 生成真实数据 macro_real.json（2023-01 ~ 2026-07，43 个月）
# ---------------------------------------------------------------------------
def build_macro_json():
    n0 = MONTHS.index("2023-01")
    n1 = MONTHS.index("2026-07") + 1
    months = MONTHS[n0:n1]
    ten_y, div_y, pe, ep_series, dp_series = [], [], [], [], []
    for m in months:
        y, mm = int(m[:4]), int(m[5:])
        t = monthly_avg(Y10_DATES, Y10, y, mm)
        e = monthly_avg(PREM_DATES, PREM_EP, y, mm)
        d = monthly_avg(PREM_DATES, PREM_DP, y, mm)
        t = t if t is not None else (ten_y[-1] if ten_y else 2.0)
        e = e if e is not None else (ep_series[-1] if ep_series else 3.0)
        d = d if d is not None else (dp_series[-1] if dp_series else 2.0)
        ep_series.append(e); dp_series.append(d)
        ten_y.append(t)
        div_y.append(round(d + t, 4))          # 股息率 = DividendPremium + 10Y
        ep_over_10y = e + t                    # E/P = EquityPremium + 10Y
        pe.append(round(100.0 / ep_over_10y, 2))  # PE ≈ 1/(E/P)
    n = len(months)
    return {
        "as_of": "2026-07-31",
        "history": {
            "bci": [round(v, 2) for v in BCI_PROXY[n0:n1]],       # 代理：企业景气指数(季度ffill)
            "m1_yoy": M1_YOY[n0:n1],
            "ppi_yoy": PPI_YOY[n0:n1],
            "ten_y_yield": [round(v, 4) for v in ten_y],
            "div_yield": div_y,                                    # 派生：股息率=红利溢价+10Y
            "pe": pe,                                              # 派生：PE=1/(E/P)
            "nominal_gdp_yoy": ngdp_monthly(),                     # 季度→月度ffill
            "fix_inv_yoy": [0.0] * n,                              # 数据缺口：中性填充，S6/S11不参与
            "retail_yoy": [0.0] * n,                               # 数据缺口：中性填充
            "export_yoy": [0.0] * n,                               # 数据缺口：中性填充
            "ind_prod_yoy": [1.0] * n,                             # 数据缺口：中性填充
            "tech_pmi": PMI_MANU,                                  # 代理：制造业PMI
            "construction_pmi": PMI_NONMANU,                       # 代理：非制造业商务活动PMI
            "csad": [1.0] * n,                                     # 数据缺口：中性填充，S9/S10不参与
            "market_width": [55.0] * n,                            # 数据缺口
            "top5_turnover": [10.0] * n,                           # 数据缺口
        },
        "extras": {"ai_chain_inflection": False},
        "_meta": {
            "source": "westock-data 实测数据 2026-08-20 拉取",
            "proxies": {
                "bci": "企业景气指数(季度,前向填充) 代理长江BCI",
                "tech_pmi": "制造业PMI 代理高技术PMI",
                "construction_pmi": "非制造业商务活动PMI 代理建筑业PMI",
                "pe": "由 EquityPremium(E/P-10Y) + 10Y 反推",
                "div_yield": "由 DividendPremium(股息率-10Y) + 10Y 反推",
            },
            "gaps": "fix_inv/retail/export/ind_prod/csad/market_width/top5_turnover 为中性填充，对应信号不参与判断",
        },
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="A 类·数据准备：组装 macro_real.json")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="输出路径（默认技能内 assets/data/macro_real.json）")
    args = ap.parse_args()

    macro = build_macro_json()

    # 缺口检查
    n = len(next(iter(macro["history"].values())))
    print("=" * 72)
    print("缺口检查（None/中性填充统计，共 %d 个月，2023-01~2026-07）" % n)
    print("=" * 72)
    for f, arr in macro["history"].items():
        print("  %-16s len=%d" % (f, len(arr)))
        assert len(arr) == n, f

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(macro, f, ensure_ascii=False, indent=2)
    print("\nwrote:", os.path.abspath(args.out))
    print("下一步：python scripts/screen.py --data %s --json-out" % args.out)


if __name__ == "__main__":
    main()
