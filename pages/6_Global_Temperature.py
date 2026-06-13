"""Global Earth temperature trend visualization using NASA GISTEMP data."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import StringIO

st.set_page_config(page_title="Global Temperature Trend", page_icon="\U0001f30d", layout="wide")
st.title("\U0001f30d Global Temperature Trend")
st.caption(
    "Monthly global surface temperature anomalies — NASA GISTEMP (1880–present) "
    "and NOAA GCAG (1850–present)"
)

DATA_URL = (
    "https://raw.githubusercontent.com/datasets/global-temp/master/data/monthly.csv"
)


@st.cache_data(ttl=86400, show_spinner="Fetching global temperature data…")
def load_data() -> dict[str, pd.DataFrame]:
    resp = requests.get(DATA_URL, timeout=30)
    resp.raise_for_status()
    raw = pd.read_csv(StringIO(resp.text))
    raw["Date"] = pd.to_datetime(raw["Year"], format="%Y-%m")
    raw["Anomaly"] = pd.to_numeric(raw["Mean"], errors="coerce")
    result = {}
    for src, grp in raw.groupby("Source"):
        df = grp[["Date", "Anomaly"]].dropna().sort_values("Date").reset_index(drop=True)
        df["Roll12"] = df["Anomaly"].rolling(12, center=True, min_periods=6).mean()
        df["Roll60"] = df["Anomaly"].rolling(60, center=True, min_periods=30).mean()
        result[src] = df
    return result


try:
    datasets = load_data()
except Exception as e:
    st.error(f"Could not load temperature data: {e}")
    st.stop()

# ── Dataset selector ───────────────────────────────────────────────────────────
src_label = st.radio(
    "Data source",
    options=["GISTEMP (NASA, 1880–present)", "GCAG (NOAA, 1850–present)"],
    horizontal=True,
    help="GISTEMP: NASA Goddard Institute.  GCAG: NOAA Global Carbon Action Group.",
)
src_key = "GISTEMP" if src_label.startswith("GISTEMP") else "GCAG"
df = datasets[src_key]

# ── Summary metrics ────────────────────────────────────────────────────────────
latest_year = df["Date"].dt.year.max()
current_anomaly = df[df["Date"].dt.year == latest_year]["Anomaly"].mean()

annual = df.groupby(df["Date"].dt.year)["Anomaly"].mean()
warmest_year = int(annual.idxmax())
warmest_val = annual.max()

x_days = (df["Date"] - df["Date"].min()).dt.days.values.astype(float)
coeffs = np.polyfit(x_days, df["Anomaly"].values, 1)
warming_per_decade = coeffs[0] * 365.25 * 10

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    f"{latest_year} Avg Anomaly",
    f"+{current_anomaly:.2f} °C" if current_anomaly >= 0 else f"{current_anomaly:.2f} °C",
    help="Mean anomaly for the most recent complete year, relative to 1951–1980 baseline.",
)
col2.metric(
    "Warmest Year on Record",
    str(warmest_year),
    f"+{warmest_val:.2f} °C",
    help="Year with the highest annual mean temperature anomaly.",
)
col3.metric(
    "Warming Rate",
    f"+{warming_per_decade:.2f} °C / decade",
    help="Linear trend computed over the full record.",
)
col4.metric(
    "Data Points",
    f"{len(df):,}",
    help="Monthly global mean temperature measurements plotted.",
)

st.markdown("---")

# ── Plotly figure ──────────────────────────────────────────────────────────────
fig = go.Figure()

# Monthly anomaly bars — colored on RdBu_r scale
fig.add_trace(
    go.Bar(
        x=df["Date"],
        y=df["Anomaly"],
        marker=dict(
            color=df["Anomaly"],
            colorscale="RdBu_r",
            cmin=-1.0,
            cmax=1.8,
            colorbar=dict(
                title=dict(text="Anomaly (°C)", side="right"),
                thickness=14,
                len=0.65,
                tickformat="+.1f",
            ),
            line=dict(width=0),
        ),
        opacity=0.55,
        name="Monthly anomaly",
        hovertemplate="<b>%{x|%b %Y}</b><br>Anomaly: %{y:+.2f} °C<extra></extra>",
    )
)

# 12-month rolling mean
fig.add_trace(
    go.Scatter(
        x=df["Date"],
        y=df["Roll12"],
        mode="lines",
        line=dict(color="rgba(255,220,50,0.8)", width=1.5),
        name="12-month mean",
        hovertemplate="<b>%{x|%b %Y}</b><br>12-mo mean: %{y:+.2f} °C<extra></extra>",
    )
)

# 5-year rolling mean — primary trend
fig.add_trace(
    go.Scatter(
        x=df["Date"],
        y=df["Roll60"],
        mode="lines",
        line=dict(color="rgba(255,80,30,1.0)", width=3),
        name="5-year trend",
        hovertemplate="<b>%{x|%b %Y}</b><br>5-yr trend: %{y:+.2f} °C<extra></extra>",
    )
)

# Baseline
fig.add_hline(
    y=0,
    line=dict(color="rgba(200,200,200,0.45)", width=1, dash="dot"),
    annotation_text="Baseline (1951–1980 avg)",
    annotation_position="bottom right",
    annotation_font=dict(color="rgba(180,180,180,0.7)", size=10),
)

# Paris 1.5 °C target
fig.add_hline(
    y=1.5,
    line=dict(color="rgba(255,100,100,0.7)", width=1.5, dash="dash"),
    annotation_text="1.5 °C Paris target",
    annotation_position="top right",
    annotation_font=dict(color="rgba(255,150,150,0.9)", size=10),
)

fig.update_layout(
    template="plotly_dark",
    title=dict(
        text=f"Global Surface Temperature Anomaly — {src_label}",
        font=dict(size=18),
        x=0.02,
    ),
    xaxis=dict(
        title="Year",
        type="date",
        rangeslider=dict(visible=True, thickness=0.05),
        rangeselector=dict(
            buttons=[
                dict(count=20, label="20 y", step="year", stepmode="backward"),
                dict(count=50, label="50 y", step="year", stepmode="backward"),
                dict(count=100, label="100 y", step="year", stepmode="backward"),
                dict(step="all", label="All time"),
            ],
            bgcolor="rgba(40,40,40,0.9)",
            activecolor="rgba(255,80,30,0.6)",
            font=dict(color="white"),
        ),
    ),
    yaxis=dict(
        title="Temperature Anomaly (°C)",
        tickformat="+.2f",
        zeroline=False,
    ),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
        bgcolor="rgba(0,0,0,0)",
    ),
    height=580,
    margin=dict(l=60, r=20, t=80, b=90),
    hovermode="x unified",
    bargap=0,
)

st.plotly_chart(fig, use_container_width=True)

# ── Striped climate visualization ─────────────────────────────────────────────
st.subheader("Climate Stripes")
st.caption(
    "Each stripe is one year's mean anomaly. Blue = cooler than baseline, red = warmer. "
    "Inspired by Ed Hawkins' #ShowYourStripes."
)

annual_df = annual.reset_index()
annual_df.columns = ["Year", "Anomaly"]

stripe_fig = go.Figure(
    go.Bar(
        x=annual_df["Year"],
        y=[1] * len(annual_df),
        marker=dict(
            color=annual_df["Anomaly"],
            colorscale="RdBu_r",
            cmin=-1.2,
            cmax=1.8,
            line=dict(width=0),
        ),
        hovertemplate="<b>%{x}</b><br>Annual anomaly: %{marker.color:+.2f} °C<extra></extra>",
        showlegend=False,
    )
)
stripe_fig.update_layout(
    template="plotly_dark",
    height=110,
    margin=dict(l=10, r=10, t=10, b=30),
    xaxis=dict(title="", tickformat="d", showgrid=False),
    yaxis=dict(visible=False),
    bargap=0,
    plot_bgcolor="black",
    paper_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(stripe_fig, use_container_width=True)

# ── About ──────────────────────────────────────────────────────────────────────
with st.expander("About this data"):
    st.markdown(
        """
**Sources**
- **GISTEMP**: [NASA GISS Surface Temperature Analysis v4](https://data.giss.nasa.gov/gistemp/) —
  monthly global Land+Ocean anomalies, 1880–present. Combines GHCN-v4 land stations with NOAA
  ERSST v5 sea-surface temperatures.
- **GCAG**: NOAA Global Carbon Action Group — monthly anomalies, 1850–present.

Both are served from the [datasets/global-temp](https://github.com/datasets/global-temp) open-data
mirror on GitHub, updated monthly.

**Baseline**: Values are anomalies (differences) from the **1951–1980** mean for that calendar month.
+1.0 °C means that month was 1 degree warmer than its 1951–1980 average.

**Why monthly, not daily?** Compiling a reliable *daily global average* requires dense station coverage
across every ocean and land area. Before the satellite era (1979) and the expansion of weather buoys,
daily global means are scientifically incomplete. Monthly averages are the internationally accepted
standard for long-term climate records. These datasets contain every reliably measured global monthly
temperature on record.

**Trend lines**: Yellow = 12-month centred rolling mean. Red = 5-year (60-month) centred rolling mean.
        """
    )
