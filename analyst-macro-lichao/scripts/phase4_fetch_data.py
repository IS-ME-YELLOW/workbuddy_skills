#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
李超 Phase 4 A 类·数据准备：组装 macro_real.json 回填 screen.py
================================================================
V2 迁移自工作区 phase4_lichao.py 的数据构造部分（build()）：
用 westock-data 真实数据 + 公开锚点，构造 macro_real.json 回填
screen.py 全部 13 个 history 字段 + 4 个 extras。
重跑后已与存量 macro_real_lichao.json 逐字段 diff 验证一致
（2026-08-21 迁移时点，数字零漂移）。

数据来源（三层标注，详见 _meta）：
  ✅ westock 直连：yield_curve(10Y日频月均)、premium_curve(股息率)、
     fundcost(FDR001)、kline(hs300/csiall/ai 月K线)、fundquantity(M1/M2)、
     cpi_ppi(服务类分项)
  ⚠️ 观点锚点+公开数据：央行购金月度量、居民/非银存款年度锚、
     利率走廊宽度、OMO 7D 中枢
  ❌ 工程代理：cn_us_event_score（事件时间线人工打分）、
     baidu_idx（成交额相对前12月中枢放大倍数）

窗口：2023-08 ~ 2026-07（36 个月，as_of 2026-07-31；
      黄金储备/货币信贷数据滞后一个月）。

用法（在技能根目录）：
  python scripts/phase4_fetch_data.py --out assets/data/macro_real.json
（原始数据 tmp_lichao_*.txt 提前落盘在 {workspace}/.workbuddy/，见规范 §五）
"""
import argparse
import json
import os
import statistics
import sys
from collections import OrderedDict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 配置区
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "assets", "data", "macro_real.json")

MONTHS = [f"{y}{m:02d}" for y in range(2023, 2027) for m in range(1, 13)
          if not (y == 2023 and m < 8) and not (y == 2026 and m > 7)]
N = len(MONTHS)
assert N == 36, N
# ============================================================


# ----------------------------------------------------------------------------
# 解析工具
# ----------------------------------------------------------------------------
def parse_pipe_rows(path, val_idx, date_idx=1, min_parts=None):
    """解析 markdown 表格行 → {yyyymm: [按行值]}（同月多行收集）。"""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < (min_parts or val_idx + 1):
                    continue
                d = parts[date_idx]
                if not (d.isdigit() and len(d) == 8):
                    continue
                try:
                    out.setdefault(d[:6], []).append(float(parts[val_idx]))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return out


def monthly_avg(daily_map, ym):
    vals = daily_map.get(ym, [])
    return statistics.mean(vals) if vals else None


def parse_kline(path):
    """月K线 → {ym: (close, amount_sum)}。"""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 9:
                    continue
                d = parts[1]
                if not (len(d) == 10 and d[4] == "-" and d[:4].isdigit()):
                    continue
                try:
                    close = float(parts[4])   # last
                    amt = float(parts[7])     # amount（元）
                except ValueError:
                    continue
                out.setdefault(d[:7].replace("-", ""), []).append((close, amt))
    except FileNotFoundError:
        pass
    # 月内取最后一根K线的收盘、金额求和
    return {k: (v[-1][0], sum(a for _, a in v)) for k, v in out.items()}


# ----------------------------------------------------------------------------
# 1. westock 直连字段
# ----------------------------------------------------------------------------
def load_yield10():
    m = {}
    for y in range(2023, 2027):
        m.update(parse_pipe_rows(os.path.join(TMP_DIR, f"tmp_lichao_yield_{y}.txt"), val_idx=3))
    return m


def load_fdr001():
    m = {}
    for y in range(2023, 2027):
        m.update(parse_pipe_rows(os.path.join(TMP_DIR, f"tmp_lichao_fundcost_{y}.txt"), val_idx=3))
    return m


def load_divpremium():
    m = {}
    try:
        with open(os.path.join(TMP_DIR, "tmp_lichao_premium.txt"), encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    continue
                d = parts[1]
                if not (d.isdigit() and len(d) == 8):
                    continue
                try:
                    m.setdefault(d[:6], []).append(float(parts[2]))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return m


def load_m1m2():
    m1, m2 = {}, {}
    for y in range(2023, 2027):
        try:
            with open(os.path.join(TMP_DIR, f"tmp_lichao_fq_{y}.txt"), encoding="utf-8") as f:
                for line in f:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) < 9:
                        continue
                    d = parts[1]
                    if not (d.isdigit() and len(d) == 8):
                        continue
                    try:
                        m1[d[:6]] = float(parts[6])   # CURV_M1_YOY
                        m2[d[:6]] = float(parts[8])   # CURV_M2_YOY
                    except ValueError:
                        continue
        except FileNotFoundError:
            pass
    return m1, m2


def load_cpi_service():
    """服务类分项（交通通信/教育文化娱乐/居住/医疗保健）均值 → CPI服务代理。"""
    out = {}
    idx = [6, 7, 8, 13]  # JTTX, JYWY, JZ, YLBJ
    for y in range(2023, 2027):
        try:
            with open(os.path.join(TMP_DIR, f"tmp_lichao_cpi_{y}.txt"), encoding="utf-8") as f:
                for line in f:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) < 14:
                        continue
                    d = parts[1]
                    if not (d.isdigit() and len(d) == 8):
                        continue
                    vals = []
                    for i in idx:
                        try:
                            vals.append(float(parts[i]))
                        except ValueError:
                            continue
                    if len(vals) >= 3:
                        out[d[:6]] = round(statistics.mean(vals), 2)
        except FileNotFoundError:
            pass
    return out


# ----------------------------------------------------------------------------
# 2. 硬编码序列（⚠️ 公开锚点 / ❌ 工程代理）
# ----------------------------------------------------------------------------
# 央行购金（吨/月）：2024-11 起为外汇局+世界黄金协会公开报道值；
# 2023-08~2024-04 为上一轮连续增持期（约 7-9 吨/月，⚠️锚点）；2024-05~10 暂停
CB_GOLD_BUY = {
    "2023-08": 9.0, "2023-09": 8.0, "2023-10": 8.0, "2023-11": 8.0, "2023-12": 9.0,
    "2024-01": 8.0, "2024-02": 8.0, "2024-03": 7.0, "2024-04": 6.0,
    "2024-05": 0.0, "2024-06": 0.0, "2024-07": 0.0, "2024-08": 0.0, "2024-09": 0.0, "2024-10": 0.0,
    "2024-11": 5.0, "2024-12": 10.0,
    "2025-01": 5.0, "2025-02": 5.0, "2025-03": 3.0, "2025-04": 2.0, "2025-05": 2.0,
    "2025-06": 2.0, "2025-07": 2.0, "2025-08": 2.0, "2025-09": 1.24, "2025-10": 0.93,
    "2025-11": 0.93, "2025-12": 0.93,
    "2026-01": 1.24, "2026-02": 0.93, "2026-03": 4.98, "2026-04": 8.09, "2026-05": 9.95,
    "2026-06": 15.0, "2026-07": 19.91,
}

# 中美事件净分值（月度，-2..+2，❌按规则1分级表人工打分，依据公开事件时间线）
CN_US_EVENT = {
    "2023-08": -1, "2023-09": -1, "2023-10": -1, "2023-11": 2, "2023-12": 1,
    "2024-01": -1, "2024-02": -1, "2024-03": -1, "2024-04": -1, "2024-05": 0,
    "2024-06": 0, "2024-07": 0, "2024-08": -1, "2024-09": -1, "2024-10": -1,
    "2024-11": 0, "2024-12": -1,
    "2025-01": -1, "2025-02": -1, "2025-03": -1, "2025-04": -2, "2025-05": 2,
    "2025-06": 1, "2025-07": 1, "2025-08": 1, "2025-09": 1, "2025-10": 2,
    "2025-11": 1, "2025-12": 1,
    "2026-01": 1, "2026-02": -1, "2026-03": 1, "2026-04": 1, "2026-05": 2,
    "2026-06": 1, "2026-07": 1,
}

# OMO 7D 政策利率中枢（%，⚠️公开公告：2024.07→1.70 / 2024.09→1.50 / 2025.05→1.40）
OMO_CENTER = {}
for ym in MONTHS:
    if ym >= "202505":
        OMO_CENTER[ym] = 1.40
    elif ym >= "202409":
        OMO_CENTER[ym] = 1.50
    elif ym >= "202407":
        OMO_CENTER[ym] = 1.70
    else:
        OMO_CENTER[ym] = 1.80

# 利率走廊宽度（BP）：2024.07 新机制 70BP（OMO-20~+50）；2026.06 收窄 50BP（OMO±25）✅李超原文
CORRIDOR_W = {ym: (50 if ym >= "202606" else 70) for ym in MONTHS}

# 居民/非银存款年度余额同比锚（PBOC 公开数据，复用张瑜验证锚点，⚠️）
RES_DEP_ANNUAL = {2023: 11.8, 2024: 10.7, 2025: 9.9, 2026: 7.2}
NB_DEP_ANNUAL = {2023: 12.2, 2024: 11.3, 2025: 25.0, 2026: 17.9}

# 统一为无横杠月份键
CB_GOLD_BUY = {k.replace("-", ""): v for k, v in CB_GOLD_BUY.items()}
CN_US_EVENT = {k.replace("-", ""): v for k, v in CN_US_EVENT.items()}


# ----------------------------------------------------------------------------
# 3. 组装月度序列
# ----------------------------------------------------------------------------
def build():
    y10 = load_yield10()
    fdr = load_fdr001()
    divp = load_divpremium()
    m1, m2 = load_m1m2()
    cpi_srv = load_cpi_service()
    hs300_k = parse_kline(os.path.join(TMP_DIR, "tmp_lichao_hs300.txt"))
    csiall_k = parse_kline(os.path.join(TMP_DIR, "tmp_lichao_csiall.txt"))
    ai_k = parse_kline(os.path.join(TMP_DIR, "tmp_lichao_ai.txt"))

    m2_annual = {}
    for y in range(2023, 2027):
        vals = [m2[ym] for ym in m2 if ym.startswith(str(y))]
        m2_annual[y] = statistics.mean(vals) if vals else 0.0

    gb10y, cgs, dr001, hh, nb, cpi_s, hs300, to, ai, omo, cw, gold, ev = ([] for _ in range(13))
    baidu_raw = []  # 先存成交额，再构造信息杠杆代理
    turnover_daily = []
    for ym in MONTHS:
        g = monthly_avg(y10, ym)
        dp = monthly_avg(divp, ym)
        gb10y.append(round(g, 3) if g else None)
        cgs.append(round(dp + g, 2) if (dp is not None and g) else None)
        d = monthly_avg(fdr, ym)
        dr001.append(round(d, 3) if d else None)
        # 存款分项：年度锚 + 0.15*(M2-年度M2均值)（同张瑜构造，⚠️）
        y = int(ym[:4])
        m2v = m2.get(ym)
        hh.append(round(RES_DEP_ANNUAL[y] + 0.15 * (m2v - m2_annual[y]), 2) if m2v else None)
        nb.append(NB_DEP_ANNUAL[y])
        cpi_s.append(cpi_srv.get(ym))
        hs300.append(hs300_k[ym][0] if ym in hs300_k else None)
        # 日均成交额（亿元）
        amt = csiall_k.get(ym, (None, 0))[1]
        ndays = 21  # 近似交易日数
        td = round(amt / 1e8 / ndays, 1) if amt else None
        turnover_daily.append(td)
        ai.append(ai_k[ym][0] if ym in ai_k else None)
        omo.append(OMO_CENTER[ym])
        cw.append(CORRIDOR_W[ym])
        gold.append(CB_GOLD_BUY[ym])
        ev.append(CN_US_EVENT[ym])

    # 信息杠杆代理（❌）：百度指数无数据源，用成交额相对前12月中枢的放大倍数×100
    baidu = []
    for i in range(N):
        prior = [v for v in turnover_daily[max(0, i - 12):i] if v]
        base = statistics.mean(prior) if prior else turnover_daily[i]
        baidu.append(round(100.0 * turnover_daily[i] / base, 1) if base and turnover_daily[i] else 100.0)

    # AI 指数归一化（首月=100）
    if ai and ai[0]:
        ai = [round(v / ai[0] * 100, 2) if v else None for v in ai]

    history = OrderedDict([
        ("gb10y", gb10y), ("cgs_yield", cgs), ("cn_us_event_score", ev),
        ("hh_dep_yoy", hh), ("nb_dep_yoy", nb), ("baidu_idx", baidu),
        ("turnover", turnover_daily), ("cb_gold_buy", gold), ("dr001", dr001),
        ("corridor_width", cw), ("hs300", hs300), ("ai_price_idx", ai),
        ("cpi_service_yoy", cpi_s),
    ])
    return history


META = {
    "gb10y": "✅westock yield_curve 10Y日频月均",
    "cgs_yield": "✅westock premium_curve DividendPremium月均 + gb10y（股息率=溢价+10Y；口径为红利类指数股息率，与李超央企红利4.4%锚点接近但非同一指数）",
    "cn_us_event_score": "❌工程代理：按decision-rules规则1分级表对公开事件时间线人工打分",
    "hh_dep_yoy": "⚠️PBOC年度余额锚（11.8/10.7/9.9/7.2）+0.15*(M2-年度均值)月度模式（同张瑜构造）",
    "nb_dep_yoy": "⚠️PBOC年度余额锚（12.2/11.3/25.0/17.9），年内恒定",
    "baidu_idx": "❌工程代理：百度指数无数据源，成交额/前12月中枢×100",
    "turnover": "✅westock kline sh000985 月度成交额→日均（亿元）",
    "cb_gold_buy": "⚠️外汇局+世界黄金协会公开报道（2024-11起逐月；2023-08~2024-04上一轮增持约7-9吨/月锚点；2024-05~10暂停为0）",
    "dr001": "⚠️westock fundcost CURP_FDR001（DR001定盘代理，日频月均）",
    "corridor_width": "✅李超原文：2024.07新机制70BP→2026.06收窄50BP（2023-08~2024-06为旧机制，以70占位）",
    "hs300": "✅westock kline sh000300 月收盘",
    "ai_price_idx": "❌工程代理：cs931071中证人工智能主题指数月收盘归一化（硅基通胀价格代理）",
    "cpi_service_yoy": "❌工程代理：westock cpi_ppi服务类分项（交通通信/教育文化娱乐/居住/医疗保健）均值",
    "_extras": {
        "gold_risk_flag": "⚠️按四大利空叙事判断（默认0；2025-04关税冲击计流动性抛售风险1项）",
        "corridor_center": "✅OMO 7D公开公告（1.80→1.70 2024.07→1.50 2024.09→1.40 2025.05）",
        "barbell_tech_share": "❌工程估计（无杠铃两端占比观测数据）",
        "stabilizing_flag": "⚠️按官方增持/政策组合拳公告月份（2024-09、2025-04、2026-07）",
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

    history = build()

    # 缺口检查
    print("=" * 72)
    print("缺口检查（None 月份统计，共 %d 个月：2023-08 ~ 2026-07）" % N)
    print("=" * 72)
    for k, vals in history.items():
        n_none = sum(1 for v in vals if v is None)
        flag = "  ⚠️ 缺口大" if n_none > N * 0.3 else ""
        print("  %-18s None %2d/%d%s" % (k, n_none, N, flag))
        assert len(vals) == N, k

    out = {
        "as_of": "2026-07-31",
        "history": history,
        "extras": {"gold_risk_flag": 0, "corridor_center": 1.40,
                   "barbell_tech_share": 55, "stabilizing_flag": True},
        "_meta": META,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nwrote:", os.path.abspath(args.out))
    print("下一步：python scripts/phase4_validate_events.py --data %s" % args.out)


if __name__ == "__main__":
    main()
