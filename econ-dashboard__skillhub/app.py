"""
EconDashboard — 交互式经济数据看板
=====================================
Streamlit 多页面应用，侧边栏导航，暗色主题。
首页展示关键经济指标卡片（GDP、CPI、PMI、失业率）。
"""

import sys
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

# ── 必须在任何其他 st 命令之前设置页面配置 ──
st.set_page_config(
    page_title="EconDashboard — 经济数据看板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═════════════════════════════════════════════════════════════
#  全局暗色主题 CSS
# ═════════════════════════════════════════════════════════════

DARK_CSS = """
<style>
    /* 主背景 */
    .stApp {
        background-color: #0E1117;
    }

    /* 侧边栏 */
    section[data-testid="stSidebar"] {
        background-color: #1A1D24;
        border-right: 1px solid #2E3138;
    }
    section[data-testid="stSidebar"] .st-emotion-cache-1gulkj5 {
        background-color: #1A1D24;
    }

    /* 标题 */
    h1, h2, h3 {
        color: #E0E0E0 !important;
    }

    /* 指标卡片容器 */
    div[data-testid="metric-container"] {
        background-color: #1A1D24;
        border: 1px solid #2E3138;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    div[data-testid="metric-container"] label {
        color: #9CA3AF !important;
    }
    div[data-testid="metric-container"] div[data-testid="metric-value"] {
        color: #00B4D8 !important;
    }

    /* 数据框表格 */
    .stDataFrame {
        background-color: #1A1D24;
        border-radius: 8px;
    }
    .stDataFrame table {
        color: #E0E0E0;
    }

    /* 按钮 */
    .stButton button {
        background-color: #00B4D8;
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
    }
    .stButton button:hover {
        background-color: #0098B8;
    }

    /* 选择框 */
    .stSelectbox label, .stMultiSelect label {
        color: #E0E0E0 !important;
    }

    /* 分割线 */
    hr {
        border-color: #2E3138;
    }

    /* 页脚留白 */
    .main .block-container {
        padding-top: 2rem;
    }
</style>
"""


# ═════════════════════════════════════════════════════════════
#  缓存数据加载
# ═════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner="正在获取全球经济数据...")
def load_latest_indicators():
    """加载首页卡片需要的最新指标数据（缓存1小时）。"""
    from data.fetcher import fetch_latest_indicators
    return fetch_latest_indicators()


@st.cache_data(ttl=3600, show_spinner="正在获取 GDP 数据...")
def load_gdp_data(years=10):
    """加载 GDP 数据。"""
    from data.fetcher import fetch_gdp_data
    return fetch_gdp_data(years=years)


@st.cache_data(ttl=3600, show_spinner="正在获取 CPI 数据...")
def load_cpi_data(years=10):
    """加载 CPI 数据。"""
    from data.fetcher import fetch_cpi_data
    return fetch_cpi_data(years=years)


@st.cache_data(ttl=1800, show_spinner="正在获取中国 PMI 数据...")
def load_pmi_data():
    """加载中国 PMI 数据。"""
    from data.fetcher import fetch_pmi_data
    return fetch_pmi_data()


@st.cache_data(ttl=3600, show_spinner="正在获取美国 FRED 数据...")
def load_fred_series(series_id):
    """加载 FRED 时间序列。"""
    from data.fetcher import fetch_fred_series
    return fetch_fred_series(series_id)


# ═════════════════════════════════════════════════════════════
#  应用布局
# ═════════════════════════════════════════════════════════════

def main():
    # ── 注入暗色主题 CSS ──
    st.markdown(DARK_CSS, unsafe_allow_html=True)

    # ── 侧边栏导航 ──
    with st.sidebar:
        st.markdown(
            "<h1 style='text-align: center; color: #00B4D8; font-size: 28px;'>"
            "📊 EconDashboard</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align: center; color: #9CA3AF; font-size: 12px;'>"
            "交互式经济数据看板</p>",
            unsafe_allow_html=True,
        )
        st.divider()

        # 页面选择
        page = st.radio(
            "**导航**",
            ["🏠 首页概览", "📈 宏观概览", "🇨🇳 中国经济高频跟踪", "🌍 跨国比较"],
            label_visibility="collapsed",
        )

        st.divider()

        # 自动刷新按钮
        col1, col2 = st.columns([1, 1])
        with col1:
            refresh = st.button("🔄 刷新数据", use_container_width=True)
        with col2:
            st.link_button("📖 文档", "https://github.com", use_container_width=True)

        if refresh:
            st.cache_data.clear()
            st.rerun()

        # 数据状态指示
        st.markdown(
            f"<div style='font-size: 11px; color: #6B7280; text-align: center; "
            f"margin-top: 20px;'>"
            f"数据自动刷新 (1h 缓存)</div>",
            unsafe_allow_html=True,
        )

    # ── 页面路由 ──
    if page == "🏠 首页概览":
        render_home()
    elif page == "📈 宏观概览":
        # 导入并渲染宏观概览页
        from pages.page_01_macro_overview import render
        render()
    elif page == "🇨🇳 中国经济高频跟踪":
        from pages.page_02_china_tracker import render
        render()
    elif page == "🌍 跨国比较":
        from pages.page_03_comparison import render
        render()


# ═════════════════════════════════════════════════════════════
#  首页渲染
# ═════════════════════════════════════════════════════════════

def render_home():
    st.markdown(
        "<h1 style='font-size: 32px;'>🏠 全球经济指标概览</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color: #9CA3AF; font-size: 14px;'>"
        "覆盖中美日德英印 6 大经济体 · 数据来源: World Bank, FRED, akshare</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 加载数据 ──
    with st.spinner("正在加载最新经济数据..."):
        indicators = load_latest_indicators()

    # ── 指标行 1: GDP ──
    st.markdown(
        "<h3 style='font-size: 20px; margin-top: 24px;'>💰 国内生产总值 (GDP)</h3>",
        unsafe_allow_html=True,
    )

    gdp_latest = indicators.get("GDP_latest", {})
    gdp_growth = indicators.get("GDP_growth_latest", {})

    if gdp_latest:
        cols = st.columns(len(gdp_latest))
        for i, (country, value) in enumerate(gdp_latest.items()):
            with cols[i]:
                growth = gdp_growth.get(country)
                _render_metric_card(country, f"${value:.1f}B", growth)
    else:
        st.info("GDP 数据暂不可用，请稍后刷新重试。")

    # ── 指标行 2: CPI + US Unemployment + China PMI ──
    st.markdown(
        "<h3 style='font-size: 20px; margin-top: 32px;'>📊 关键指标速览</h3>",
        unsafe_allow_html=True,
    )

    cpi_data = indicators.get("CPI_latest", {})

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        us_cpi = cpi_data.get("US")
        _render_metric_card("美国 CPI", f"{us_cpi:.1f}%" if us_cpi is not None else "N/A")

    with col2:
        unemp = indicators.get("US_unemployment")
        _render_metric_card("美国失业率", f"{unemp:.1f}%" if unemp is not None else "N/A")

    with col3:
        china_cpi = cpi_data.get("China")
        _render_metric_card("中国 CPI", f"{china_cpi:.1f}%" if china_cpi is not None else "N/A")

    with col4:
        pmi = indicators.get("China_PMI")
        _render_metric_card("中国 PMI", f"{pmi:.1f}" if pmi is not None else "N/A",
                           delta=pmi - 50 if pmi else None)

    # ── 第二行 ──
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        jp_cpi = cpi_data.get("Japan")
        _render_metric_card("日本 CPI", f"{jp_cpi:.1f}%" if jp_cpi is not None else "N/A")

    with col2:
        de_cpi = cpi_data.get("Germany")
        _render_metric_card("德国 CPI", f"{de_cpi:.1f}%" if de_cpi is not None else "N/A")

    with col3:
        uk_cpi = cpi_data.get("UK")
        _render_metric_card("英国 CPI", f"{uk_cpi:.1f}%" if uk_cpi is not None else "N/A")

    with col4:
        in_cpi = cpi_data.get("India")
        _render_metric_card("印度 CPI", f"{in_cpi:.1f}%" if in_cpi is not None else "N/A")

    # ── GDP 增长率表格 ──
    st.divider()
    st.markdown(
        "<h3 style='font-size: 20px;'>📋 最新 GDP 增长率对比</h3>",
        unsafe_allow_html=True,
    )

    if gdp_growth:
        growth_df = pd.DataFrame(
            list(gdp_growth.items()),
            columns=["国家", "GDP 增长率 (%)"],
        )
        growth_df.index = range(1, len(growth_df) + 1)
        st.dataframe(growth_df, use_container_width=True, hide_index=False)
    else:
        st.info("GDP 增长率数据暂不可用。")

    # ── 数据来源说明 ──
    st.divider()
    st.markdown(
        "<div style='font-size: 12px; color: #6B7280; padding: 12px;'>"
        "数据来源: World Bank API · FRED (Federal Reserve Economic Data) · akshare (中国国家统计局)<br>"
        "更新时间: 自动缓存 1 小时 | "
        f"访问时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_metric_card(
    label: str,
    value: str,
    delta: float = None,
):
    """渲染自定义指标卡片。"""
    delta_text = ""
    if delta is not None:
        arrow = "▲" if delta >= 0 else "▼"
        delta_color = "#06D6A0" if delta >= 0 else "#EF476F"
        delta_text = (
            f"<span style='font-size:13px; color:{delta_color}; margin-left:6px;'>"
            f"{arrow} {abs(delta):.1f}</span>"
        )

    card = f"""
    <div style="
        background-color: #1A1D24;
        border: 1px solid #2E3138;
        border-radius: 12px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        margin-bottom: 8px;
    ">
        <div style="font-size: 24px; font-weight: 700; color: #00B4D8;">
            {value}{delta_text}
        </div>
        <div style="font-size: 13px; color: #9CA3AF; margin-top: 4px;">
            {label}
        </div>
    </div>
    """
    st.markdown(card, unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════
#  入口
# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from datetime import datetime
    import pandas as pd

    main()
