"""
中国经济高频跟踪页面
=====================
- 月度经济数据: CPI, PPI, PMI, 工业增加值
- 贸易数据: 出口、进口、贸易差额
- 货币数据: M2, 社融, 贷款增长
- 年度同比对比图表
- 经济热度指数卡片
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime


def render():
    st.markdown(
        "<h1 style='font-size: 28px;'>🇨🇳 中国经济高频跟踪</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color: #9CA3AF; font-size: 14px;'>"
        "基于 akshare 数据的中国高频经济指标追踪</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 加载数据 ──
    with st.spinner("正在获取中国宏观经济数据..."):
        indicators = _load_china_indicators()

    # ── 经济热度指数卡片 ──
    st.markdown(
        "<h3 style='font-size: 20px;'>🔥 经济热度概览</h3>",
        unsafe_allow_html=True,
    )

    heat_index = _calculate_heat_index(indicators)
    _render_heat_card(heat_index)

    st.divider()

    # ── 选项卡布局 ──
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 价格指数 (CPI/PPI)",
        "🏭 实体指标",
        "🌏 贸易数据",
        "💰 货币金融",
    ])

    with tab1:
        _render_price_tab(indicators)

    with tab2:
        _render_real_tab(indicators)

    with tab3:
        _render_trade_tab(indicators)

    with tab4:
        _render_money_tab(indicators)

    # ── 数据来源 ──
    st.divider()
    st.markdown(
        "<div style='font-size: 12px; color: #6B7280;'>"
        "数据来源: akshare (中国国家统计局、中国人民银行、海关总署)<br>"
        "更新时间: 缓存 30 分钟 | 指标均为同比 (%) "
        "| PMI 为荣枯线 (50 以上 = 扩张)"
        "</div>",
        unsafe_allow_html=True,
    )


# ═════════════════════════════════════════════════════════════
#  数据加载
# ═════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner="正在获取中国数据...")
def _load_china_indicators():
    from data.fetcher import fetch_china_indicators
    return fetch_china_indicators()


# ═════════════════════════════════════════════════════════════
#  经济热度指数
# ═════════════════════════════════════════════════════════════

def _calculate_heat_index(indicators: dict) -> dict:
    """
    综合多个指标计算一个简化的"经济热度指数"。
    返回 {score, label, details} 用于展示。
    """
    scores = []

    # CPI (温和通胀为正)
    cpi_df = indicators.get("cpi", pd.DataFrame())
    if not cpi_df.empty:
        latest_cpi = cpi_df.iloc[-1, 0] if cpi_df.shape[1] > 0 else None
        if latest_cpi is not None:
            if 0.5 <= latest_cpi <= 3.0:
                scores.append(80)  # 合理通胀
            elif 0 <= latest_cpi < 0.5:
                scores.append(50)  # 偏低
            elif latest_cpi < 0:
                scores.append(30)  # 通缩
            else:
                scores.append(40)  # 高通胀

    # PMI
    pmi_df = indicators.get("pmi", pd.DataFrame())
    if not pmi_df.empty:
        pmi_cols = [c for c in pmi_df.columns if "PMI" in str(c) or "制造业" in str(c)]
        if pmi_cols:
            latest_pmi = pmi_df[pmi_cols[0]].dropna()
            if not latest_pmi.empty:
                val = latest_pmi.iloc[-1]
                if val >= 52:
                    scores.append(85)
                elif val >= 50:
                    scores.append(65)
                elif val >= 48:
                    scores.append(45)
                else:
                    scores.append(25)

    # 工业增加值
    ind_df = indicators.get("industrial", pd.DataFrame())
    if not ind_df.empty:
        val = ind_df.iloc[-1, 0] if ind_df.shape[1] > 0 else None
        if val is not None:
            if val >= 6:
                scores.append(80)
            elif val >= 4:
                scores.append(60)
            elif val >= 2:
                scores.append(40)
            else:
                scores.append(20)

    # 零售
    retail_df = indicators.get("retail", pd.DataFrame())
    if not retail_df.empty:
        val = retail_df.iloc[-1, 0] if retail_df.shape[1] > 0 else None
        if val is not None:
            if val >= 5:
                scores.append(80)
            elif val >= 2:
                scores.append(55)
            elif val >= 0:
                scores.append(35)
            else:
                scores.append(20)

    if not scores:
        return {"score": 50, "label": "数据不足", "details": "部分数据缺失，无法准确评估"}

    avg = np.mean(scores)

    if avg >= 70:
        label = "🔥 经济活跃"
    elif avg >= 55:
        label = "✅ 运行平稳"
    elif avg >= 40:
        label = "⚠️ 偏弱运行"
    else:
        label = "❄️ 需要刺激"

    detail_items = []
    detail_items.append(f"CPI: {scores[0]}/100" if len(scores) > 0 else "")
    detail_items.append(f"PMI: {scores[1]}/100" if len(scores) > 1 else "")
    detail_items.append(f"工业: {scores[2]}/100" if len(scores) > 2 else "")
    detail_items.append(f"零售: {scores[3]}/100" if len(scores) > 3 else "")
    details = " · ".join([d for d in detail_items if d])

    return {"score": round(avg), "label": label, "details": details}


def _render_heat_card(heat: dict):
    """渲染经济热度卡片。"""
    score = heat["score"]
    label = heat["label"]
    details = heat["details"]

    # 颜色映射
    if score >= 70:
        bar_color = "#06D6A0"
    elif score >= 55:
        bar_color = "#00B4D8"
    elif score >= 40:
        bar_color = "#FFB703"
    else:
        bar_color = "#EF476F"

    html = f"""
    <div style="
        background: linear-gradient(135deg, #1A1D24 0%, #222831 100%);
        border: 1px solid #2E3138;
        border-radius: 16px;
        padding: 24px;
        margin-bottom: 16px;
    ">
        <div style="display: flex; align-items: center; gap: 24px;">
            <div style="min-width: 120px; text-align: center;">
                <div style="font-size: 48px; font-weight: 800; color: {bar_color};">
                    {score}
                </div>
                <div style="font-size: 13px; color: #9CA3AF;">综合热度</div>
            </div>
            <div style="flex: 1;">
                <div style="
                    background-color: #0E1117;
                    border-radius: 8px;
                    height: 12px;
                    overflow: hidden;
                ">
                    <div style="
                        width: {score}%;
                        height: 100%;
                        background: linear-gradient(90deg, {bar_color}, {bar_color}dd);
                        border-radius: 8px;
                        transition: width 0.6s ease;
                    "></div>
                </div>
                <div style="
                    font-size: 18px;
                    font-weight: 600;
                    color: {bar_color};
                    margin-top: 8px;
                ">{label}</div>
                <div style="font-size: 12px; color: #6B7280; margin-top: 4px;">
                    {details}
                </div>
            </div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════
#  各选项卡
# ═════════════════════════════════════════════════════════════

def _render_price_tab(indicators: dict):
    """价格指数选项卡: CPI + PPI。"""
    cpi_df = indicators.get("cpi", pd.DataFrame())
    ppi_df = indicators.get("ppi", pd.DataFrame())

    col1, col2 = st.columns(2)

    with col1:
        if not cpi_df.empty:
            fig = _line_chart_simple(
                cpi_df, title="CPI 同比 (%)", ylabel="同比 (%)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("CPI 数据暂不可用。")

    with col2:
        if not ppi_df.empty:
            fig = _line_chart_simple(
                ppi_df, title="PPI 同比 (%)", ylabel="同比 (%)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("PPI 数据暂不可用。")

    # 详细数据
    with st.expander("📋 查看详细数据"):
        tab_cpi, tab_ppi = st.tabs(["CPI 详细数据", "PPI 详细数据"])
        with tab_cpi:
            if not cpi_df.empty:
                _show_table(cpi_df, "cpi_china.csv")
        with tab_ppi:
            if not ppi_df.empty:
                _show_table(ppi_df, "ppi_china.csv")


def _render_real_tab(indicators: dict):
    """实体指标选项卡: PMI, 工业增加值, 固投, 零售。"""
    pmi_df = indicators.get("pmi", pd.DataFrame())
    ind_df = indicators.get("industrial", pd.DataFrame())
    fai_df = indicators.get("fixed_asset", pd.DataFrame())
    retail_df = indicators.get("retail", pd.DataFrame())

    # PMI 折线图
    if not pmi_df.empty:
        pmi_col = pmi_df.columns[0] if len(pmi_df.columns) > 0 else None
        if pmi_col:
            fig = _line_chart_simple(
                pmi_df[[pmi_col]],
                title=f"制造业 PMI (荣枯线 50)",
                ylabel="PMI",
                add_hline=50,
            )
            st.plotly_chart(fig, use_container_width=True)

    # 工业 + 固投 + 零售 三列
    col1, col2, col3 = st.columns(3)

    with col1:
        if not ind_df.empty:
            fig = _line_chart_simple(
                ind_df, title="工业增加值同比 (%)", ylabel="同比 (%)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("工业增加值数据暂不可用。")

    with col2:
        if not fai_df.empty:
            fig = _line_chart_simple(
                fai_df, title="固定资产投资累计同比 (%)", ylabel="同比 (%)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("固定资产投资数据暂不可用。")

    with col3:
        if not retail_df.empty:
            fig = _line_chart_simple(
                retail_df, title="社会消费品零售总额同比 (%)", ylabel="同比 (%)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("零售数据暂不可用。")

    # 详细数据
    with st.expander("📋 查看详细数据"):
        dtab1, dtab2, dtab3, dtab4 = st.tabs(
            ["PMI", "工业增加值", "固投", "零售"]
        )
        with dtab1:
            if not pmi_df.empty:
                _show_table(pmi_df, "pmi_china.csv")
        with dtab2:
            if not ind_df.empty:
                _show_table(ind_df, "industrial_china.csv")
        with dtab3:
            if not fai_df.empty:
                _show_table(fai_df, "fixed_asset_china.csv")
        with dtab4:
            if not retail_df.empty:
                _show_table(retail_df, "retail_china.csv")


def _render_trade_tab(indicators: dict):
    """贸易数据选项卡。"""
    trade_df = indicators.get("trade", pd.DataFrame())

    if trade_df.empty:
        st.info("贸易数据暂不可用。")
        return

    # 确定可用列
    has_export = "export" in trade_df.columns
    has_import = "import" in trade_df.columns
    has_balance = "balance" in trade_df.columns

    # 进出口趋势
    trade_cols = []
    if has_export:
        trade_cols.append("export")
    if has_import:
        trade_cols.append("import")

    if trade_cols:
        plot_df = trade_df[trade_cols].dropna(how="all").copy()
        if not plot_df.empty:
            fig = _line_chart_simple(
                plot_df, title="进出口贸易 (亿美元)", ylabel="亿美元"
            )
            st.plotly_chart(fig, use_container_width=True)

    # 贸易差额
    col1, col2 = st.columns(2)

    with col1:
        if has_balance:
            balance_df = trade_df[["balance"]].dropna()
            if not balance_df.empty:
                fig = _line_chart_simple(
                    balance_df, title="贸易差额 (亿美元)", ylabel="亿美元"
                )
                st.plotly_chart(fig, use_container_width=True)

    with col2:
        # 最新一期数字卡片
        if has_balance:
            latest_balance = trade_df["balance"].dropna()
            if not latest_balance.empty:
                val = latest_balance.iloc[-1]
                _render_simple_card(
                    "最新贸易差额",
                    f"{val:.1f} 亿美元",
                    delta=val,
                )
        if has_export:
            latest_export = trade_df["export"].dropna()
            if not latest_export.empty:
                _render_simple_card(
                    "最新出口额",
                    f"{latest_export.iloc[-1]:.1f} 亿美元",
                )
        if has_import:
            latest_import = trade_df["import"].dropna()
            if not latest_import.empty:
                _render_simple_card(
                    "最新进口额",
                    f"{latest_import.iloc[-1]:.1f} 亿美元",
                )

    # 详细数据
    with st.expander("📋 查看详细贸易数据"):
        _show_table(trade_df, "trade_china.csv")


def _render_money_tab(indicators: dict):
    """货币金融选项卡: M2。"""
    m2_df = indicators.get("money_supply", pd.DataFrame())

    if not m2_df.empty:
        m2_col = "M2_yoy" if "M2_yoy" in m2_df.columns else m2_df.columns[0]
        plot_cols = [m2_col] if m2_col in m2_df.columns else [m2_df.columns[0]]

        fig = _line_chart_simple(
            m2_df[plot_cols], title="M2 货币供应量同比 (%)", ylabel="同比 (%)"
        )
        st.plotly_chart(fig, use_container_width=True)

        latest_val = m2_df[m2_col].dropna()
        if not latest_val.empty:
            _render_simple_card(
                "最新 M2 同比",
                f"{latest_val.iloc[-1]:.1f}%",
            )

        with st.expander("📋 查看详细 M2 数据"):
            _show_table(m2_df, "m2_china.csv")
    else:
        st.info("M2 数据暂不可用。")

    # GDP 数据（如果可用）
    gdp_df = indicators.get("gdp", pd.DataFrame())
    if not gdp_df.empty:
        st.divider()
        st.markdown(
            "<h4 style='font-size: 16px;'>📈 GDP 当季同比</h4>",
            unsafe_allow_html=True,
        )
        fig = _line_chart_simple(
            gdp_df, title="GDP 当季同比 (%)", ylabel="同比 (%)"
        )
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("📋 查看详细 GDP 数据"):
            _show_table(gdp_df, "gdp_china.csv")


# ═════════════════════════════════════════════════════════════
#  工具函数
# ═════════════════════════════════════════════════════════════

def _line_chart_simple(
    df: pd.DataFrame,
    title: str = "",
    ylabel: str = "",
    add_hline: float = None,
) -> "plotly.graph_objects.Figure":
    """简化版折线图封装。"""
    from utils.charts import line_chart as lc

    cols = df.columns.tolist()
    fig = lc(
        df.reset_index(),
        x="index",
        y=cols,
        title=title,
        ylabel=ylabel,
        height=350,
    )

    if add_hline is not None:
        fig.add_hline(
            y=add_hline,
            line_dash="dash",
            line_color="#EF476F",
            opacity=0.6,
            annotation_text=f"荣枯线 {add_hline}",
            annotation_font_size=11,
        )

    return fig


def _show_table(df: pd.DataFrame, filename: str):
    """显示数据框 + CSV 导出。"""
    display = df.copy()
    display.index.name = "period"
    st.dataframe(display, use_container_width=True)

    csv = display.to_csv(encoding="utf-8-sig")
    st.download_button(
        label=f"📥 下载 CSV",
        data=csv,
        file_name=filename,
        mime="text/csv",
    )


def _render_simple_card(label: str, value: str, delta: float = None):
    """渲染一个简单的指标卡片。"""
    delta_html = ""
    if delta is not None:
        arrow = "▲" if delta >= 0 else "▼"
        delta_color = "#06D6A0" if delta >= 0 else "#EF476F"
        delta_html = (
            f"<span style='color:{delta_color}; font-size:13px; margin-left:6px;'>"
            f"{arrow} {abs(delta):.1f}</span>"
        )

    html = f"""
    <div style="
        background-color: #1A1D24;
        border: 1px solid #2E3138;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
        text-align: center;
    ">
        <div style="font-size: 24px; font-weight: 700; color: #00B4D8;">
            {value}{delta_html}
        </div>
        <div style="font-size: 13px; color: #9CA3AF; margin-top: 4px;">
            {label}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


if __name__ == "__main__":
    render()
