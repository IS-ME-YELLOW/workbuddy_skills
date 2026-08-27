#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
李超 Phase 4 B 类·事件复算：信号-观点-行情三方对照
===================================================
V2 迁移自工作区 phase4_lichao.py 的验证部分（recompute()）：
对 7 个关键事件时点用截至该月的数据切片（无前视）复算 S1-S12 全部
信号，与①李超同期观点②沪深300前瞻 1M/3M 行情三方对照。
重跑后已与存量 lichao_event_recompute.json 逐事件对照验证一致
（triggered / detail / fwd1 / fwd3 / gb10y，2026-08-21 迁移时点）。

输出统一 signalcheck.json 格式；V1 事件表原字段（triggered 列表、
detail 全量信号明细、gb10y）作为扩展键保留。
V1 事件含分析师同期观点（view 文本）但无 ✅/⚠️ 分级与预期方向，
故 view_grade / expect 留空、align 填 "n/a"（诚实标注，不虚构）。

用法（在技能根目录）：
  python scripts/phase4_validate_events.py --data assets/data/macro_real.json --out assets/data/signalcheck.json
（2026-07 事件的前瞻 1M 基准为 tmp_lichao_hs300.txt 中 2026-08 部分月收盘）
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen as scr  # 复用技能脚本，确保逻辑一致  # noqa: E402

# ============================================================
# 配置区
# ------------------------------------------------------------
TMP_DIR = os.path.join(os.path.expanduser("~"), "sell-side-workbuddy", ".workbuddy")
ANALYST = "lichao"
FWD_FIELD = "hs300"             # 前瞻标的：沪深300（月收盘）
FWD_UNIT = "pct"                # 前瞻收益 %
# ============================================================

MONTHS = [f"{y}{m:02d}" for y in range(2023, 2027) for m in range(1, 13)
          if not (y == 2023 and m < 8) and not (y == 2026 and m > 7)]
N = len(MONTHS)

# ---------------------------------------------------------------------------
# 事件时点（月份, 标签, 分析师同期观点, extras 覆盖）
# ---------------------------------------------------------------------------
EVENTS = [
    ("202409", "924金融组合拳", "李超2024.09解读：政策底明确，风险偏好大幅修复",
     {"gold_risk_flag": 0, "corridor_center": 1.50, "barbell_tech_share": 50, "stabilizing_flag": True}),
    ("202504", "对等关税冲击", "中美对抗急剧升级（对华关税最高145%）→口诀'中美对抗买红利'",
     {"gold_risk_flag": 1, "corridor_center": 1.40, "barbell_tech_share": 48, "stabilizing_flag": True}),
    ("202507", "柳暗花明·股债双牛", "李超2025中期策略：利率下行驱动股债双牛，切换在冬季",
     {"gold_risk_flag": 0, "corridor_center": 1.40, "barbell_tech_share": 52, "stabilizing_flag": False}),
    ("202510", "釜山会晤+吉隆坡联合安排", "中美合作缓和（贸易休战至2026.11）→口诀'中美合作买科技'",
     {"gold_risk_flag": 0, "corridor_center": 1.40, "barbell_tech_share": 55, "stabilizing_flag": False}),
    ("202601", "直挂云帆济沧海", "李超2026年度展望：经济走K型、资产举杠铃",
     {"gold_risk_flag": 0, "corridor_center": 1.40, "barbell_tech_share": 58, "stabilizing_flag": False}),
    ("202605", "特朗普访华·新定位", "中美'建设性战略稳定关系' → 科技端",
     {"gold_risk_flag": 0, "corridor_center": 1.40, "barbell_tech_share": 60, "stabilizing_flag": False}),
    ("202607", "最新月·K型分化", "李超2026.07.30演讲：K型分化；2026.08政治局'存量政策效能'",
     {"gold_risk_flag": 0, "corridor_center": 1.40, "barbell_tech_share": 55, "stabilizing_flag": True}),
]


def load_hs300_aug():
    """2026-08 部分月收盘（截至 8.24），供 202607 事件的前瞻 1M 用。"""
    hs300_aug = None
    try:
        with open(os.path.join(TMP_DIR, "tmp_lichao_hs300.txt"), encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 8 and parts[1].startswith("2026-08"):
                    hs300_aug = float(parts[4])
    except FileNotFoundError:
        pass
    return hs300_aug


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="B 类·事件复算：信号-观点-行情对照")
    ap.add_argument("--data", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "data", "macro_real.json"),
        help="A 类脚本输出的 macro_real.json 路径")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "data", "signalcheck.json"),
        help="输出路径（默认技能内 assets/data/signalcheck.json）")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        macro = json.load(f)
    history = macro["history"]
    for f_name, arr in history.items():
        assert len(arr) == N, f"{f_name}: {len(arr)} != {N}"

    hs_aug_val = load_hs300_aug()
    hs = history["hs300"]

    calc_funcs = [scr.calc_s1, scr.calc_s2, scr.calc_s3, scr.calc_s4, scr.calc_s5,
                  scr.calc_s6, scr.calc_s7, scr.calc_s8, scr.calc_s9, scr.calc_s10,
                  scr.calc_s11, scr.calc_s12]

    print("=" * 88)
    print("Phase 4 事件时点复算 · 李超(浙商宏观)框架 · 数据窗口 2023-08 ~ 2026-07")
    print("=" * 88)
    print("\n[事件复算]（截至该月数据切片，无前视）")

    results = []
    last_sigs = None
    for ym, label, view, extras in EVENTS:
        i = MONTHS.index(ym)
        # 截至该月切片（无前视；None 过滤后传入 screen.py）
        h_cut = {k: [v for v in vals[:i + 1] if v is not None] for k, vals in history.items()}
        sigs = [fn(h_cut, extras) for fn in calc_funcs]
        trig = [s["id"] for s in sigs if s["triggered"]]
        # 前瞻收益（与 V1 完全一致：202607 的 fwd1 用 2026-08 部分月收盘）
        fwd1 = fwd3 = None
        if i + 1 < N and hs[i] and hs[i + 1]:
            fwd1 = (hs[i + 1] / hs[i] - 1) * 100
        if i + 3 < N and hs[i] and hs[i + 3]:
            fwd3 = (hs[i + 3] / hs[i] - 1) * 100
        elif ym == "202607" and hs_aug_val and hs[i]:
            fwd1 = (hs_aug_val / hs[i] - 1) * 100
        detail = {s["id"]: s["detail"] for s in sigs}

        f1 = f"{fwd1:+.1f}%" if fwd1 is not None else "—"
        f3 = f"{fwd3:+.1f}%" if fwd3 is not None else "—"
        gb = history["gb10y"][i]
        print(f"\n[{ym}] {label} | 10Y={gb}% | 触发: {','.join(trig) or '无'}"
              f" | 后1月 {f1} | 后3月 {f3}")
        print(f"  观点: {view}")

        results.append({
            "event": label, "month": ym,
            "view": view, "view_grade": "", "expect": "",
            "triggers": trig,
            "trigger_details": [
                {"id": s["id"], "name": s["name"], "detail": s["detail"],
                 "strength": s["strength"]}
                for s in sigs if s["id"] in trig
            ],
            "align": "n/a",
            "fwd_1m": round(fwd1, 1) if fwd1 is not None else None,
            "fwd_3m": round(fwd3, 1) if fwd3 is not None else None,
            "fwd_unit": FWD_UNIT,
            # 扩展字段（V1 事件表原字段，保留）
            "triggered": trig,
            "gb10y": gb,
            "detail": detail,
        })
        last_sigs = sigs

    # 最新月快照（EVENTS 最后一行 = 最新月 202607，S1-S12 全量触发状态）
    snap = [{"id": s["id"], "name": s["name"], "triggered": s["triggered"],
             "detail": s["detail"], "strength": s["strength"]} for s in last_sigs]

    out = {
        "analyst": ANALYST, "as_of": "2026-07", "fwd_field": FWD_FIELD,
        "fwd_unit": FWD_UNIT, "events": results, "latest_snapshot": snap,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nwrote:", os.path.abspath(args.out))


if __name__ == "__main__":
    main()
