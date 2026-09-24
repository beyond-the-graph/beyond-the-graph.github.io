import os
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from datetime import date
from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Stock Price Explorer",
    page_icon="📈",
    layout="wide"
)

pio.renderers.default = "browser"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ["NEO4J_DATABASE"]

DATE_MIN = date(2013, 2, 8)
DATE_MAX = date(2018, 2, 7)

# ---------------------------------------------------------------------------
# Neo4j connection
# ---------------------------------------------------------------------------

@st.cache_resource
def get_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    driver.verify_connectivity()
    return driver

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@st.cache_data
def get_symbols(_driver):
    with _driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (s:Stock) RETURN s.symbol AS symbol ORDER BY s.symbol
        """)
        return [r["symbol"] for r in result]


def get_price_history(driver, symbol, start, end):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (s:Stock {symbol: $symbol})-[:HAS_PRICE]->(p:Price)
            WHERE p.date >= date($start) AND p.date <= date($end)
            RETURN p.date  AS date,
                   p.open  AS open,
                   p.high  AS high,
                   p.low   AS low,
                   p.close AS close
            ORDER BY p.date
        """, symbol=symbol,
             start=start.strftime("%Y-%m-%d"),
             end=end.strftime("%Y-%m-%d"))
        df = pd.DataFrame([r.data() for r in result])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"].astype(str))
    return df


@st.cache_data
def get_performance(_driver):
    with _driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (s:Stock)-[:HAS_PRICE]->(p:Price)
            WITH s.symbol AS symbol,
                 min(p.date) AS first_date,
                 max(p.date) AS last_date
            MATCH (s:Stock {symbol: symbol})-[:HAS_PRICE]->(first:Price {date: first_date})
            MATCH (s)-[:HAS_PRICE]->(last:Price {date: last_date})
            WITH symbol,
                 first.close AS first_price,
                 last.close  AS last_price,
                 round((last.close - first.close) / first.close * 100, 2) AS pct_change
            RETURN symbol, first_price, last_price, pct_change
            ORDER BY pct_change DESC
        """)
        return pd.DataFrame([r.data() for r in result])

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.title("Stock Price Explorer")
st.caption(
    "Temporal queries on S&P 500 stock price data, powered by Neo4j."
)

driver  = get_driver()
symbols = get_symbols(driver)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Controls")

    symbol = st.selectbox("Symbol", symbols,
                          index=symbols.index("AAPL") if "AAPL" in symbols else 0)

    st.markdown("**Date range**")
    start_date = st.date_input("From", value=DATE_MIN,
                                min_value=DATE_MIN, max_value=DATE_MAX)
    end_date   = st.date_input("To",   value=DATE_MAX,
                                min_value=DATE_MIN, max_value=DATE_MAX)

    bucket_days = st.slider("Candlestick bucket (days)", 1, 30, 5)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["Candlestick", "Moving Average", "Performance"])

# ---------------------------------------------------------------------------
# Tab 1: Candlestick
# ---------------------------------------------------------------------------

with tab1:
    st.subheader(f"{symbol} -- Candlestick Chart")

    if start_date >= end_date:
        st.warning("Start date must be before end date.")
    else:
        with st.spinner("Fetching price data..."):
            price_df = get_price_history(driver, symbol, start_date, end_date)

        if price_df.empty:
            st.info(f"No price data found for {symbol} in the selected range.")
        else:
            # OHLC bucketing
            ohlc_df = (
                price_df
                .set_index("date")
                .resample(f"{bucket_days}D")
                .agg(
                    open=("open",   "first"),
                    high=("high",   "max"),
                    low=("low",    "min"),
                    close=("close", "last")
                )
                .dropna()
                .reset_index()
            )

            col1, col2, col3 = st.columns(3)
            col1.metric("Trading days", len(price_df))
            col2.metric("First close", f"${price_df['close'].iloc[0]:.2f}")
            col3.metric("Last close",  f"${price_df['close'].iloc[-1]:.2f}")

            fig = go.Figure(go.Candlestick(
                x=ohlc_df["date"],
                open=ohlc_df["open"],
                high=ohlc_df["high"],
                low=ohlc_df["low"],
                close=ohlc_df["close"],
                name=symbol
            ))
            fig.update_xaxes(
                type="category",
                tickangle=-45,
                tickvals=ohlc_df["date"][::max(1, len(ohlc_df)//12)].astype(str).tolist()
            )
            fig.update_layout(
                title=f"{symbol} candlestick ({bucket_days}-day buckets)",
                yaxis_title="Price (USD)",
                height=500
            )
            st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------------------
# Tab 2: Moving Average
# ---------------------------------------------------------------------------

with tab2:
    st.subheader(f"{symbol} -- Moving Average")

    if start_date >= end_date:
        st.warning("Start date must be before end date.")
    else:
        with st.spinner("Fetching price data..."):
            ma_df = get_price_history(driver, symbol, start_date, end_date)

        if ma_df.empty:
            st.info(f"No price data found for {symbol} in the selected range.")
        else:
            ma_df["ma_20"] = ma_df["close"].rolling(window=20).mean()
            ma_df["ma_50"] = ma_df["close"].rolling(window=50).mean()

            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=ma_df["date"], y=ma_df["close"],
                name="Close", line=dict(color="#636EFA", width=1)
            ))
            fig2.add_trace(go.Scatter(
                x=ma_df["date"], y=ma_df["ma_20"],
                name="20-day MA", line=dict(color="#EF553B", width=1.5)
            ))
            fig2.add_trace(go.Scatter(
                x=ma_df["date"], y=ma_df["ma_50"],
                name="50-day MA", line=dict(color="#00CC96", width=1.5)
            ))
            fig2.update_layout(
                title=f"{symbol} closing price with moving averages",
                xaxis_title="Date",
                yaxis_title="Price (USD)",
                height=480,
                legend=dict(x=0.01, y=0.99)
            )
            st.plotly_chart(fig2, width="stretch")

# ---------------------------------------------------------------------------
# Tab 3: Performance
# ---------------------------------------------------------------------------

with tab3:
    st.subheader("Best and Worst Performers (full period)")
    st.caption("Percentage price change from first to last trading day for each symbol.")

    with st.spinner("Computing performance..."):
        perf_df = get_performance(driver)

    if perf_df.empty:
        st.info("No performance data available.")
    else:
        top10    = perf_df.head(10).copy()
        bottom10 = perf_df.tail(10).copy()
        chart_df = pd.concat([top10, bottom10])
        chart_df["color"] = chart_df["pct_change"].apply(
            lambda x: "#00CC96" if x >= 0 else "#EF553B"
        )

        fig3 = go.Figure(go.Bar(
            x=chart_df["symbol"],
            y=chart_df["pct_change"],
            marker_color=chart_df["color"].tolist(),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Change: %{y:.2f}%<extra></extra>"
            )
        ))
        fig3.update_layout(
            title="Top 10 and bottom 10 performers",
            xaxis_title="Symbol",
            yaxis_title="Price change (%)",
            height=420
        )
        st.plotly_chart(fig3, width="stretch")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Top 10**")
            st.dataframe(
                top10[["symbol", "first_price", "last_price", "pct_change"]]
                .rename(columns={
                    "symbol": "Symbol",
                    "first_price": "First ($)",
                    "last_price": "Last ($)",
                    "pct_change": "Change (%)"
                })
                .reset_index(drop=True),
                hide_index=True,
                width="stretch"
            )
        with col2:
            st.markdown("**Bottom 10**")
            st.dataframe(
                bottom10[["symbol", "first_price", "last_price", "pct_change"]]
                .rename(columns={
                    "symbol": "Symbol",
                    "first_price": "First ($)",
                    "last_price": "Last ($)",
                    "pct_change": "Change (%)"
                })
                .reset_index(drop=True),
                hide_index=True,
                width="stretch"
            )
