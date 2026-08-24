"""
宏观概览页面
=============
- 折线图: 主要经济体 GDP 增长率对比 (5年)
- 柱状图: 当前 GDP 水平对比
- CPI 通胀趋势叠加图
- 交互式年份范围选择器
- 数据表格 + CSV 导出
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime


def render():
    st.markdown(
        "<h1 style='font-size: 28px;'>📈 宏观概览</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color: #9CA3AF; font-size: 14px;'>"
        "主要经济体 GDP 增长率与通胀趋势对比分析</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 年份范围选择器 ──
    current_year = datetime.now().year
    col1, col2 = st.columns([1, 3])

    with col1:
        selected_years = st.slider(
            "选择年份范围",
            min_value=2010,
            max_value=current_year,
            value=(current_year - 9, current_year),
            step=1,
        )
    with col2:
        st.markdown(
            f"<div style='padding-top: 28px; color: #6B7280;'>"
            f"已选择: {selected_years[0]} — {selected_years[1]} 年"
            f"（共 {selected_years[1] - selected_years[0]} 年）</div>",
            unsafe_allow_html=True,
        )

    num_years = selected_years[1] - selected_years[0]

    # ── 加载数据 ──
    gdp_data = _load_gdp(num_years)
    cpi_data = _load_cpi(num_years)

    # ── 第1行: GDP 增长趋势折线图 + GDP 对比柱状图 ──
    st.markdown(
        "<h3 style='font-size: 20px; margin-top: 16px;'>💰 GDP 分析</h3>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        gdp_growth = gdp_data.get("gdp_growth", pd.DataFrame())
        if not gdp_growth.empty and not gdp_growth.dropna(how="all").empty:
            # 只显示选择了年份范围内的数据
            gdp_growth_filtered = gdp_growth[
                gdp_growth.index >= selected_years[0]
            ] if selected_years[0] > gdp_growth.index.min() else gdp_growth

            fig = _line_chart(
                gdp_growth_filtered.reset_index(),
                x="year",
                y=gdp_growth_filtered.columns.tolist(),
                title="GDP 年增长率对比 (%)",
                ylabel="增长率 (%)",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("GDP 增长率数据暂不可用。")

    with col2:
        gdp_usd = gdp_data.get("gdp_usd", pd.DataFrame())
        if not gdp_usd.empty and not gdp_usd.dropna(how="all").empty:
            gdp_usd_filtered = gdp_usd[
                gdp_usd.index >= selected_years[0]
            ] if selected_years[0] > gdp_usd.index.min() else gdp_usd

            latest_year = gdp_usd_filtered.index.max()
            latest_gdp = gdp_usd_filtered.loc[latest_year].dropna()

            if not latest_gdp.empty:
                bar_df = pd.DataFrame({
                    "country": latest_gdp.index,
                    "gdp": latest_gdp.values,
                }).sort_values("gdp", ascending=True)

                fig = _bar_chart(
                    bar_df,
                    x="country",
                    y="gdp",
                    title=f"{latest_year} 年 GDP 对比 (亿美元)",
                    ylabel="GDP (亿美元)",
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("GDP 数据暂不可用。")
        else:
            st.info("GDP 数据暂不可用。")

    # ── 第2行: CPI 趋势 ──
    st.markdown(
        "<h3 style='font-size: 20px; margin-top: 24px;'>📊 CPI 通胀率趋势</h3>",
        unsafe_allow_html=True,
    )

    if not cpi_data.empty and not cpi_data.dropna(how="all").empty:
        cpi_filtered = cpi_data[
            cpi_data.index >= selected_years[0]
        ] if selected_years[0] > cpi_data.index.min() else cpi_data

        fig = _line_chart(
            cpi_filtered.reset_index(),
            x="year",
            y=cpi_filtered.columns.tolist(),
            title="CPI 通胀率 (%)",
            ylabel="通胀率 (%)",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("CPI 数据暂不可用。")

    # ── 第3行: 详细数据表格 + CSV 导出 ──
    st.divider()
    st.markdown(
        "<h3 style='font-size: 20px;'>📋 详细数据</h3>",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["GDP 增长率", "GDP 总量", "CPI 通胀率"])

    with tab1:
        if not gdp_growth.empty:
            _show_data_table_with_export(gdp_growth, "gdp_growth.csv", "GDP_增长率")
        else:
            st.info("无数据。")

    with tab2:
        if not gdp_usd.empty:
            _show_data_table_with_export(gdp_usd, "gdp_usd.csv", "GDP_总量")
        else:
            st.info("无数据。")

    with tab3:
        if not cpi_data.empty:
            _show_data_table_with_export(cpi_data, "cpi.csv", "CPI_通胀率")
        else:
            st.info("无数据。")

    # ── 数据说明 ──
    st.divider()
    st.markdown(
        "<div style='font-size: 12px; color: #6B7280;'>"
        "数据来源: World Bank API — GDP (NY.GDP.MKTP.CD, NY.GDP.MKTP.KD.ZG), CPI (FP.CPI.TOTL.ZG)<br>"
        f"数据范围: {selected_years[0]} — {selected_years[1]} | "
        "GDP 单位为亿美元 (当前美元计值) | 增长率与通胀率为百分比 (%)"
        "</div>",
        unsafe_allow_html=True,
    )


# ═════════════════════════════════════════════════════════════
#  数据加载 (缓存的)
# ═════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner="正在获取 GDP 数据...")
def _load_gdp(years=10):
    from data.fetcher import fetch_gdp_data
    return fetch_gdp_data(years=years)


@st.cache_data(ttl=3600, show_spinner="正在获取 CPI 数据...")
def _load_cpi(years=10):
    from data.fetcher import fetch_cpi_data
    return fetch_cpi_data(years=years)


# ═════════════════════════════════════════════════════════════
#  图表辅助
# ═════════════════════════════════════════════════════════════

def _line_chart(df, x, y, title, ylabel=""):
    """简易折线图封装。"""
    from utils.charts import line_chart as lc
    return lc(df, x, y, title=title, ylabel=ylabel, height=400)


def _bar_chart(df, x, y, title, ylabel=""):
    """简易柱状图封装。"""
    from utils.charts import bar_chart as bc
    return bc(df, x, y, title=title, ylabel=ylabel, height=400)


def _show_data_table_with_export(df: pd.DataFrame, filename: str, tab_name: str):
    """显示数据框并提供 CSV 下载按钮。"""
    display_df = df.copy()
    display_df.index.name = "year"

    # 显示
    st.dataframe(display_df, use_container_width=True)

    # CSV 导出
    csv = display_df.to_csv(encoding="utf-8-sig")
    st.download_button(
        label=f"📥 下载 {tab_name} CSV",
        data=csv,
        file_name=filename,
        mime="text/csv",
        use_container_width=False,
    )


if __name__ == "__main__":
    render()
