# app.py â€” Sharjah Air-Lens (clean, professional, judge-ready UI)
import streamlit as st
import pandas as pd
import numpy as np
import math, time
from datetime import datetime
from streamlit_folium import st_folium
import folium
import plotly.graph_objects as go
import plotly.express as px
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

# -------------------- Config & state --------------------
st.set_page_config(page_title="Sharjah Air-Lens", layout="wide", initial_sidebar_state="expanded")
if "theme" not in st.session_state: st.session_state.theme = "dark"
if "scheme" not in st.session_state: st.session_state.scheme = "classic"

def toggle_theme():
    st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"

# -------------------- Color schemes --------------------
SCHEMES = {
    "classic": {
        "bg_start":"#0f172a","bg_end":"#071029",
        "card":"rgba(255,255,255,0.03)","muted":"#9fb0d4",
        "good":"#10B981","mod":"#F59E0B","bad":"#EF4444",
        "accent":"#2b7df0"
    },
    "teal": {
        "bg_start":"#082327","bg_end":"#032b2a",
        "card":"rgba(255,255,255,0.03)","muted":"#9fd6d1",
        "good":"#06b6d4","mod":"#f59e0b","bad":"#ef4444",
        "accent":"#06b6d4"
    },
    "minimal": {
        "bg_start":"#f5f7fb","bg_end":"#eef3fb",
        "card":"rgba(0,0,0,0.03)","muted":"#4b5563",
        "good":"#10B981","mod":"#F59E0B","bad":"#EF4444",
        "accent":"#374151"
    }
}

scheme = SCHEMES.get(st.session_state.scheme, SCHEMES["classic"])

# -------------------- CSS --------------------
CSS = f"""
<style>
:root {{ --card-bg: {scheme['card']}; --muted: {scheme['muted']}; --accent: {scheme['accent']}; }}
.stApp {{ background: linear-gradient(180deg, {scheme['bg_start']} 0%, {scheme['bg_end']} 80%); color: #e6eef8; }}
.header-title {{ font-size:40px; font-weight:800; margin:0; }}
.header-sub {{ color:var(--muted); margin-top:6px; margin-bottom:10px; }}
.card {{ background: var(--card-bg); border-radius:12px; padding:14px; box-shadow: 0 6px 20px rgba(2,6,23,0.6); }}
.small-muted {{ color:var(--muted); font-size:13px; }}
.poll-grid {{ display:grid; grid-template-columns: repeat(2, 1fr); gap:10px; }}
.poll-card {{ background: rgba(255,255,255,0.02); padding:10px; border-radius:10px; }}
.top-right {{ display:flex; justify-content:flex-end; }}
input.searchbox {{ width:100%; padding:8px; border-radius:8px; border:1px solid rgba(255,255,255,0.06); background:transparent; }}
.footer {{ color:var(--muted); font-size:12px; margin-top:12px; }}
body { font-family: "Segoe UI", Roboto, Arial, sans-serif; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# -------------------- Load data --------------------
@st.cache_data
def load_data(path="aod_sample.csv"):
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date")
    return df

try:
    df = load_data()
except Exception:
    st.error("Missing aod_sample.csv. Put it next to app.py.")
    st.stop()

# -------------------- Sidebar controls --------------------
with st.sidebar:
    st.markdown("## Settings")
    if st.button("Toggle Light/Dark"):
        toggle_theme(); st.experimental_rerun()
    st.selectbox("Color scheme", ["classic","teal","minimal"], index=["classic","teal","minimal"].index(st.session_state.scheme),
                 key="scheme_select", on_change=lambda: st.session_state.update({"scheme": st.session_state.scheme_select}) )
    st.markdown("---")
    st.markdown("Data & export")
    st.write("Sample CSV (demo). Real app uses NASA MODIS via GEE.")
    st.download_button("Download CSV", df.to_csv(index=False), "sharjah_aod_sample.csv", "text/csv")
    st.markdown("---")
    st.markdown("Tips:")
    st.markdown("- Use search to choose a place.")
    st.markdown("- Explain proxies in your submission (AODâ†’pollutants).")

# user changed scheme? update and rerun for CSS to apply
if st.session_state.scheme != st.session_state.get("scheme_select", st.session_state.scheme):
    st.session_state.scheme = st.session_state.get("scheme_select", st.session_state.scheme)
    st.experimental_rerun()

scheme = SCHEMES.get(st.session_state.scheme, SCHEMES["classic"])

# -------------------- Header + search --------------------
header_col, right_col = st.columns([8,1])
with header_col:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div style="display:flex; flex-direction:column;">', unsafe_allow_html=True)
    st.markdown('<div class="header-title">AIR QUALITY MONITOR</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="header-sub">Real-time air pollution in your area</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right_col:
    # small status or placeholder
    st.write("")

st.markdown('</div>', unsafe_allow_html=True)

# search bar row
search_col, preset_col = st.columns([4,1])
with search_col:
    location_text = st.text_input("Search location (city, address or landmark)", value="Sharjah, UAE", key="loc_text")
with preset_col:
    preset = st.selectbox("", ["Sharjah - Muweilah","Sharjah - Al Majaz","Dubai - Deira","Ajman - Corniche"])

# -------------------- Geocode (Nominatim) --------------------
def geocode(text, retries=1):
    geo = Nominatim(user_agent="sharjah_air_lens_demo")
    try:
        return geo.geocode(text, timeout=8)
    except Exception:
        if retries>0:
            time.sleep(1); return geocode(text, retries-1)
        return None

lat, lon = 25.3, 56.2
try_search = st.button("Search")

if try_search and location_text.strip():
    loc = geocode(location_text)
    if loc:
        lat, lon = loc.latitude, loc.longitude
        st.success(f"Found: {loc.address}")
    else:
        st.error("Not found â€” using preset.")
        try_search = False

if not try_search:
    if preset == "Sharjah - Muweilah": lat, lon = 25.358, 55.478
    if preset == "Sharjah - Al Majaz": lat, lon = 25.345, 55.381
    if preset == "Dubai - Deira": lat, lon = 25.271, 55.304
    if preset == "Ajman - Corniche": lat, lon = 25.405, 55.513

# -------------------- controls row --------------------
ctrl1, ctrl2 = st.columns([2,1])
with ctrl1:
    min_d = df["date"].min().date(); max_d = df["date"].max().date()
    start = st.date_input("Start date", min_d)
    end = st.date_input("End date", max_d)
    if start> end: st.error("Start must be before End")
with ctrl2:
    smooth = st.slider("Smoothing days", 1, 7, 3)

# -------------------- data filtering & proxies --------------------
mask = (df["date"].dt.date >= start) & (df["date"].dt.date <= end)
view = df.loc[mask].copy()
if view.empty:
    st.warning("No data in range â€” showing latest sample.")
    view = df.copy()
view["rolling"] = view["aod"].rolling(smooth, min_periods=1).mean()
latest = view.iloc[-1]
aod_val = float(latest["rolling"])

# proxy conversions (demo)
pm25 = max(1, round(aod_val * 90, 1))
pm10 = max(1, round(pm25 * 1.6, 1))
no2  = max(1, round(aod_val * 40 + 5, 1))
co2  = max(300, round(400 + aod_val * 30, 1))
o3   = max(1, round(aod_val * 20 + 10, 1))
so2  = max(1, round(aod_val * 5 + 1, 1))

def pm25_status(v):
    if v<=12: return ("Good","ðŸŸ¢",scheme["good"])
    if v<=35.4: return ("Moderate","ðŸŸ¡",scheme["mod"])
    if v<=55.4: return ("Unhealthy for sensitive","ðŸŸ ",scheme["bad"])
    return ("Unhealthy","ðŸ”´",scheme["bad"])

pm25_s, pm25_e, pm25_c = pm25_status(pm25)

# -------------------- layout: left gauge & map, right pollutants --------------------
left_col, right_col = st.columns([2,1], gap="large")

# LEFT: Gauge + map + timeseries
with left_col:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f"**Location:** {location_text if try_search else preset}   â€”   Lat {lat:.4f}, Lon {lon:.4f}")
    # AQI proxy scaling (0-100)
    aqi_score = min(100, round((pm25 / 150) * 100, 1))
    # semicircle pie + needle
    fig = go.Figure()
    fig.add_trace(go.Pie(values=[33,33,34], hole=0.55, rotation=180,
                         marker_colors=[scheme["good"], scheme["mod"], scheme["bad"]],
                         textinfo='none', hoverinfo='none', showlegend=False))
    ang = 180 - (aqi_score*180/100)
    r = 0.4
    ang_rad = math.radians(ang)
    xh = 0.5 + r*math.cos(ang_rad); yh = 0.5 + r*math.sin(ang_rad)
    needle_color = "#111827" if st.session_state.theme=="light" else "#ffffff"
    fig.update_layout(shapes=[
        dict(type='line', x0=0.5, y0=0.5, x1=xh, y1=yh, xref='paper', yref='paper', line=dict(color=needle_color, width=4)),
        dict(type='circle', xref='paper', yref='paper', x0=0.49, y0=0.49, x1=0.51, y1=0.51, fillcolor=needle_color, line_color=needle_color)
    ], margin=dict(t=10,b=10,l=10,r=10), height=340)
    if st.session_state.theme=="dark":
        fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', font_color='white')
    else:
        fig.update_layout(paper_bgcolor='rgba(255,255,255,0)', font_color='black')
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(f"**AQI (proxy):** {aqi_score} â€” derived from PM2.5 proxy. ", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### Map")
    fmap = folium.Map(location=[lat, lon], zoom_start=11, tiles="CartoDB positron")
    folium.Circle(location=[lat, lon], radius=7000 + aod_val*30000,
                  color=scheme["bad"] if aod_val>0.5 else (scheme["mod"] if aod_val>0.3 else scheme["good"]),
                  fill=True, fill_opacity=0.35, popup=f"AOD (3d avg): {aod_val:.2f}").add_to(fmap)
    st_folium(fmap, width="100%", height=300)
    st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### Recent AOD")
    fig_ts = px.line(view, x="date", y="aod", markers=True)
    fig_ts.add_scatter(x=view["date"], y=view["rolling"], mode="lines", name=f"{smooth}-day avg",
                       line=dict(color=scheme["accent"], width=3))
    fig_ts.update_layout(template="plotly_dark" if st.session_state.theme=="dark" else None, height=240, margin=dict(t=10,b=10))
    st.plotly_chart(fig_ts, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

# RIGHT: pollutants grid
with right_col:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### Pollutants (proxy)")
    # grid 2 columns x 3 rows
    pols = [
        ("PM2.5", f"{pm25} Âµg/mÂ³", pm25_e, pm25_s, pm25_c),
        ("PM10", f"{pm10} Âµg/mÂ³", "ðŸŸ¦", "â€”", scheme["accent"]),
        ("NOâ‚‚", f"{no2} ppb", "ðŸ§ª", "â€”", scheme["accent"]),
        ("SOâ‚‚", f"{so2} ppb", "ðŸ”¥", "â€”", scheme["accent"]),
        ("Oâ‚ƒ", f"{o3} ppb", "ðŸŒ¤ï¸", "â€”", scheme["accent"]),
        ("COâ‚‚", f"{co2} ppm", "ðŸ«", "â€”", scheme["accent"]),
    ]
    rows = []
    for i in range(0, len(pols), 2):
        c1, c2 = st.columns(2)
        p1 = pols[i]
        with c1:
            st.markdown(f"<div class='poll-card'><b>{p1[0]}</b><div class='small-muted'>{p1[1]}</div>"
                        f"<div style='margin-top:8px'><span style='padding:6px 10px;border-radius:999px;background:{p1[4]};color:white;font-weight:700'>{p1[2]} {p1[3]}</span></div></div>", unsafe_allow_html=True)
        if i+1 < len(pols):
            p2 = pols[i+1]
            with c2:
                st.markdown(f"<div class='poll-card'><b>{p2[0]}</b><div class='small-muted'>{p2[1]}</div>"
                            f"<div style='margin-top:8px'><span style='padding:6px 10px;border-radius:999px;background:{p2[4]};color:white;font-weight:700'>{p2[2]} {p2[3]}</span></div></div>", unsafe_allow_html=True)

    st.markdown("---")
    sel = st.selectbox("Details for", [p[0] for p in pols])
    for p in pols:
        if p[0] == sel:
            st.markdown(f"**{p[0]} â€” {p[1]}**")
            st.markdown(f"Status: {p[2]} {p[3]}")
            st.markdown("- Health advice: " + ("Limit outdoor exercise if not Good." if p[3] != "Good" else "Air quality is good."))
            break

    st.markdown("---")
    st.markdown(f"**Latest data point:** {latest['date'].strftime('%Y-%m-%d')}")
    st.markdown(f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    st.markdown("</div>", unsafe_allow_html=True)

# footer
st.markdown(f"<div class='footer'>Demo uses sample AOD CSV. Pollutant values are proxy estimates derived from AOD for UI/demo purposes. Full pipeline uses NASA MODIS via Google Earth Engine and calibrated sensors for accurate AQI mapping.</div>", unsafe_allow_html=True)
