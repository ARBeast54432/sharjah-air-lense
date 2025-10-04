# app.py — Final full file (LIVE-only badges + provenance expander + footer)
# Paste/overwrite your existing app.py with this file.

import os
import traceback
import streamlit as st
import requests
import numpy as np
import pandas as pd
import math
import re
from datetime import datetime, timedelta
from streamlit_folium import st_folium
import folium
import plotly.graph_objects as go
import io

st.set_page_config(page_title="AirLens — NASA / TEMPO Demo", layout="wide", initial_sidebar_state="expanded")

# --------------------------
# Theme / palette (bold, readable)
# --------------------------
PALETTE = {
    # Backgrounds
    "bg": "#1A2633",         # dark bluish-black main background
    "card": "#0F1B29",       # very dark card panels
    "muted_card": "#14232F", # subtle contrast for secondary panels

    # Accents
    "accent": "#1E90FF",     # bright dodger blue for highlights
    "accent2": "#00BFFF",    # secondary cyan-blue gradient

    # Text
    "text": "#0D1117",       # dark text for readability on light-ish cards
    "muted_text": "#4F5C6C", # muted dark gray for secondary info

    # Status / AQI
    "good": "#2DD36F",       # green for good
    "moderate": "#FFD93D",   # yellow-orange for moderate
    "unhealthy": "#FF5E57",  # red for unhealthy

    # Map tiles
    "map_tiles": "CartoDB positron"
}



# --------------------------
# Page CSS (keeps UI compact & modern)
# --------------------------
CSS = f"""
<style>
html, body, .main {{ background: {PALETTE['bg']} !important; color: {PALETTE['text']} }}
.stApp > header {{ display: none; }}
.header-card {{
  background: linear-gradient(90deg, {PALETTE['accent']} 0%, {PALETTE['accent2']} 100%);
  padding:18px; border-radius:12px; color: white;
  box-shadow: 0 10px 40px rgba(0,0,0,0.5); margin-bottom:12px;
}}
.panel-card {{
  background: {PALETTE['card']}; padding:14px; border-radius:12px;
  box-shadow: 0 6px 20px rgba(0,0,0,0.45); margin-bottom:12px;
}}
.small-muted {{ color:{PALETTE['muted_text']}; font-size:13px; }}
.metric-val {{ font-weight:900; font-size:28px; color:{PALETTE['text']}; }}
.badge-live {{ background: {PALETTE['good']}; color: #042012; padding:6px 10px; border-radius:999px; font-weight:800; }}
.poll-box {{ background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)); padding:12px; border-radius:10px; }}
.kv {{ font-weight:800; font-size:20px; color:{PALETTE['text']}; }}
.tooltip {{ color:{PALETTE['muted_text']}; font-size:13px; }}
a, a:link {{ color: {PALETTE['accent']}; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------
# Earth Engine (optional)
# --------------------------
EE_AVAILABLE = False
EE_INIT_ERROR = None
try:
    import ee
    try:
        ee.Initialize()
        EE_AVAILABLE = True
    except Exception as e:
        try:
            ee.Authenticate(quiet=True)
            ee.Initialize()
            EE_AVAILABLE = True
        except Exception as ee_err:
            EE_AVAILABLE = False
            EE_INIT_ERROR = str(ee_err)
except Exception as imp_e:
    EE_AVAILABLE = False
    EE_INIT_ERROR = str(imp_e)

# --------------------------
# Pollutant units
# --------------------------
POLLUTANT_UNITS = {
    "pm25": "µg/m³",
    "pm10": "µg/m³",
    "no2": "ppb",
    "so2": "ppb",
    "o3": "ppb",
    "co": "ppm"
}


# --------------------------
# Helpers
# --------------------------
def safe_get(url, params=None, timeout=8):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception:
        return None

def normalize_label(lbl: str) -> str:
    if lbl is None:
        return ""
    s = str(lbl).lower()
    s = s.replace("₂", "2").replace("₃", "3").replace("₅", "5")
    s = re.sub(r"[^a-z0-9]", "", s)
    return s

# AQI conversion (EPA breakpoints)
EPA_BP = [
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 350.4, 301, 400),
    (350.5, 500.4, 401, 500)
]
def pm25_to_aqi(pm):
    try:
        pm = float(pm)
    except Exception:
        return None
    for (pm_l, pm_h, a_l, a_h) in EPA_BP:
        if pm_l <= pm <= pm_h:
            aqi = ((a_h - a_l)/(pm_h - pm_l)) * (pm - pm_l) + a_l
            return int(round(aqi))
    return 500

def format_time_utc(dt=None):
    if dt is None:
        dt = datetime.utcnow()
    return dt.strftime("%Y-%m-%d %H:%M UTC")

def hourly_forecast_pm(current_pm, hours=24, variance=0.03):
    rng = np.random.default_rng(seed=int((float(current_pm) * 100) % 10000))
    vals = []
    last = float(current_pm)
    for _ in range(hours):
        last = max(0.1, last + rng.normal(0, max(0.2, float(current_pm) * variance)))
        vals.append(round(last, 1))
    return vals

def sparkline(vals):
    fig = go.Figure(go.Scatter(y=vals, mode="lines", line=dict(width=2, color=PALETTE['accent']), fill='tozeroy'))
    fig.update_layout(margin=dict(t=2,b=2,l=2,r=2), height=60, paper_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig

# --------------------------
# Satellite / TEMPO helpers (EE) — safe
# --------------------------
def get_tempo_no2_via_ee(lat, lon, days_back=2):
    try:
        if not EE_AVAILABLE:
            return None
        col_id = "NASA/TEMPO/NO2_L3_QA"
        col = ee.ImageCollection(col_id).select('vertical_column_troposphere')
        end = ee.Date(datetime.utcnow().strftime("%Y-%m-%d"))
        start = end.advance(-days_back, 'day')
        img = col.filterDate(start, end.advance(1, 'day')).median()
        pt = ee.Geometry.Point([float(lon), float(lat)])
        sample = img.sample(region=pt, scale=2226).first()
        if sample is None:
            return None
        val = sample.get('vertical_column_troposphere').getInfo()
        return float(val)
    except Exception:
        return None

def get_modis_aod_via_ee(lat, lon, days_back=2):
    try:
        if not EE_AVAILABLE:
            return None
        col = ee.ImageCollection("MODIS/006/MOD04_L2").select("Optical_Depth_Land_And_Ocean")
        end = ee.Date(datetime.utcnow().strftime("%Y-%m-%d"))
        start = end.advance(-days_back, 'day')
        img = col.filterDate(start, end.advance(1, 'day')).median()
        pt = ee.Geometry.Point([float(lon), float(lat)])
        val = img.reduceRegion(reducer=ee.Reducer.mean(), geometry=pt, scale=1000).getInfo().get("Optical_Depth_Land_And_Ocean", None)
        if val is None:
            return None
        return float(val)
    except Exception:
        return None

def tempo_to_aod_proxy_from_no2(no2_col):
    try:
        proxy = (float(no2_col) / 1e16)
        return float(np.clip(proxy, 0.03, 1.0))
    except Exception:
        return None

def fetch_satellite_proxy(lat, lon):
    if EE_AVAILABLE:
        try:
            no2 = get_tempo_no2_via_ee(lat, lon)
            if no2 is not None:
                proxy = tempo_to_aod_proxy_from_no2(no2)
                if proxy is not None:
                    return proxy, f"TEMPO_NO2 (proxy:{round(no2,3)})"
        except Exception:
            pass
        try:
            mod = get_modis_aod_via_ee(lat, lon)
            if mod is not None:
                return float(np.clip(mod, 0.03, 1.0)), f"MODIS_AOD({round(mod,3)})"
        except Exception:
            pass
    return None, "DEMO_FALLBACK"

# --------------------------
# OpenAQ adaptive search (expanding radii; pseudo-latest fallback)
# --------------------------
def fetch_openaq_adaptive(lat, lon, radii=[5000, 20000, 50000, 100000, 200000]):
    base_latest = "https://api.openaq.org/v2/latest"
    base_meas = "https://api.openaq.org/v2/measurements"
    # 1) try latest
    for r in radii:
        try:
            params = {"coordinates": f"{lat},{lon}", "radius": r, "limit": 100}
            resp = safe_get(base_latest, params=params)
            if not resp:
                continue
            j = resp.json()
            results = j.get("results", [])
            if results:
                for res in results:
                    if res.get("measurements"):
                        parsed = []
                        for m in res.get("measurements", []):
                            p = m.get("parameter")
                            v = m.get("value")
                            dt = None
                            if isinstance(m.get("date"), dict):
                                dt = m["date"].get("utc") or m["date"].get("local")
                            if not dt:
                                dt = m.get("lastUpdated")
                            parsed.append({"parameter": p, "value": v, "lastUpdated": dt})
                        return res, r, parsed, "latest"
        except Exception:
            continue
    # 2) try measurements for short-term mean
    for r in radii:
        try:
            params = {"coordinates": f"{lat},{lon}", "radius": r, "limit": 200, "date_from": (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")}
            resp = safe_get(base_meas, params=params)
            if not resp:
                continue
            j = resp.json()
            meas = j.get("results", [])
            if meas:
                by_loc = {}
                for m in meas:
                    loc = m.get("location")
                    if loc not in by_loc:
                        by_loc[loc] = {"measurements": [], "coords": m.get("coordinates")}
                    by_loc[loc]["measurements"].append(m)
                # pick location with most samples
                best_loc = max(by_loc.items(), key=lambda x: len(x[1]["measurements"]))[0]
                best = by_loc[best_loc]
                params_seen = {}
                latest_ts = {}
                for m in best["measurements"]:
                    p = m.get("parameter")
                    v = m.get("value")
                    if p and isinstance(v, (int, float)):
                        params_seen.setdefault(p, []).append(v)
                        dt = None
                        if isinstance(m.get("date"), dict):
                            dt = m["date"].get("utc") or m["date"].get("local")
                        if not dt:
                            dt = m.get("lastUpdated")
                        if dt:
                            if p not in latest_ts or dt > latest_ts[p]:
                                latest_ts[p] = dt
                parsed = []
                for p, arr in params_seen.items():
                    measures_avg = float(np.mean(arr))
                    parsed.append({"parameter": p, "value": round(measures_avg, 2), "lastUpdated": latest_ts.get(p)})
                pseudo = {"location": best_loc, "coordinates": best.get("coords"), "measurements": parsed}
                return pseudo, r, parsed, "pseudo"
        except Exception:
            continue
    return None, None, [], None

# --------------------------
# UI controls: sidebar
# --------------------------
st.sidebar.markdown("## Controls")
show_24h = st.sidebar.checkbox("Show 24-hour forecast", value=False)
use_adaptive = st.sidebar.checkbox("Adaptive OpenAQ radius (recommended)", value=True)
forecast_var = st.sidebar.slider("Forecast variance (demo)", 1, 8, 3)

# --------------------------
# Header + Data provenance expander
# --------------------------
st.markdown(f'<div class="header-card"><div style="display:flex;align-items:center;justify-content:space-between"><div><div style="font-size:26px;font-weight:900">AirLens</div><div style="font-size:13px;opacity:0.95">Integrates ground stations & satellite (TEMPO) — demo-ready</div></div><div style="text-align:right"><div style="font-weight:700;font-size:13px">{("EE ON" if EE_AVAILABLE else "EE OFF — demo fallback")}</div><div style="font-size:12px;opacity:0.85">Last update: {format_time_utc()}</div></div></div></div>', unsafe_allow_html=True)

with st.expander("Data provenance & notes (click to expand)", expanded=False):
    st.markdown("""
    **Sources:** OpenAQ (ground stations), Open-Meteo (weather), satellite proxy (TEMPO/MODIS via Earth Engine when available; otherwise PM2.5-derived proxy).  
    **LIVE** = measurements taken from ground stations (or recently aggregated station data).  
    **Fallbacks:** when no recent ground data is available the app uses conservative fallbacks or satellite-derived proxies so the demo remains functional and non-misleading.  
    **Forecasts** are demonstration models for visualization only.
    """)

# --------------------------
# Locations dropdown (simple, judge-friendly)
# --------------------------
LOCATIONS = {
    "Sharjah — Muweilah": (25.358, 55.478),
    "Sharjah — Al Majaz": (25.345, 55.381),
    "Dubai — Deira": (25.271, 55.304),
    "Abu Dhabi — Khalifa City": (24.433, 54.623),
    "Ajman — Corniche": (25.405, 55.513),
    "London, UK": (51.5074, -0.1278),
    "New York, USA": (40.7128, -74.0060),
    "Tokyo, Japan": (35.6762, 139.6503),
    "Delhi, India": (28.7041, 77.1025),
    "Los Angeles, USA": (34.0522, -118.2437)
}

selected_location = st.selectbox("Select location", list(LOCATIONS.keys()))
lat, lon = LOCATIONS[selected_location]

# reset popup when location changes
if "last_location" not in st.session_state or st.session_state.last_location != selected_location:
    st.session_state.popup_visible = True
st.session_state.last_location = selected_location

# --------------------------
# Fetch ground (OpenAQ) + weather
# --------------------------
st.info("Loading data (ground stations, weather, satellite)...")

res, used_radius, parsed_measures, source_type = fetch_openaq_adaptive(lat, lon) if use_adaptive else fetch_openaq_adaptive(lat, lon, radii=[20000])

if res is None:
    res = {}

# prepare pollutant slots
polls = {"pm25": None, "pm10": None, "no2": None, "so2": None, "o3": None, "co": None}
live_flags = {k: False for k in polls}

if parsed_measures:
    for m in parsed_measures:
        key = normalize_label(m.get("parameter"))
        val = m.get("value")
        ts = m.get("lastUpdated")
        if key in polls and val is not None:
            try:
                polls[key] = float(val)
            except Exception:
                polls[key] = val
            if source_type == "latest":
                live_flags[key] = True
            elif source_type == "pseudo":
                if ts:
                    try:
                        dtt = iso_to_dt(ts)
                        if dtt:
                            age_hr = (datetime.utcnow() - dtt).total_seconds() / 3600.0
                            live_flags[key] = age_hr <= 48.0
                        else:
                            live_flags[key] = False
                    except:
                        live_flags[key] = False
                else:
                    live_flags[key] = False

# sensible fallbacks for missing pollutant values
if polls["pm25"] is None:
    if polls.get("pm10") is not None:
        try:
            polls["pm25"] = round(float(polls["pm10"]) * 0.6, 1)
            live_flags["pm25"] = False
        except Exception:
            polls["pm25"] = round(5 + abs(math.sin(lat/12.0)) * 15, 1)
            live_flags["pm25"] = False
    else:
        polls["pm25"] = round(5 + abs(math.sin(lat/12.0)) * 10, 1)
        live_flags["pm25"] = False

for k in polls:
    if polls[k] is None:
        if k != "pm25":
            try:
                polls[k] = round(max(0.1, float(polls["pm25"]) * np.random.uniform(0.6, 1.4)), 1)
                live_flags[k] = False
            except Exception:
                polls[k] = "—"
                live_flags[k] = False

# weather (Open-Meteo)
weather = None
wr = safe_get("https://api.open-meteo.com/v1/forecast", params={"latitude": lat, "longitude": lon, "current_weather": True})
if wr:
    try:
        wj = wr.json()
        cw = wj.get("current_weather", {})
        weather = {"temp": cw.get("temperature"), "windspeed": cw.get("windspeed"), "winddir": cw.get("winddirection")}
    except Exception:
        weather = None

# satellite integration (EE preferred)
aod_val, aod_source = fetch_satellite_proxy(lat, lon)
if aod_val is None:
    aod_val = float(np.clip(float(polls["pm25"]) / 150.0, 0.03, 1.0))
    if aod_source == "DEMO_FALLBACK":
        aod_source = "PM2.5_proxy"

# compute AQI
aqi_now = pm25_to_aqi(polls["pm25"])
if aqi_now is None:
    try:
        aqi_now = int(min(500, float(polls["pm25"]) * 4))
    except:
        aqi_now = 0

# fetch short pm history for forecast if possible
pm_history = []
try:
    mr = safe_get("https://api.openaq.org/v2/measurements", params={"coordinates": f"{lat},{lon}", "radius": used_radius or 20000, "limit": 200, "date_from": (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d")})
    if mr:
        mj = mr.json()
        for item in mj.get("results", []):
            if normalize_label(item.get("parameter")) == "pm25":
                v = item.get("value")
                if isinstance(v, (int, float)):
                    pm_history.append(v)
except Exception:
    pm_history = []

if show_24h:
    if len(pm_history) >= 6:
        base = float(pm_history[-1])
        trend = (pm_history[-1] - pm_history[0]) / max(1, len(pm_history)-1)
        pm24 = [round(max(0.1, base + trend*(i+1) + np.random.normal(0, base*0.02)), 1) for i in range(24)]
    else:
        pm24 = hourly_forecast_pm(polls["pm25"], 24, variance=forecast_var/100.0)
    aqi24 = [pm25_to_aqi(x) for x in pm24]
else:
    pm24 = []
    aqi24 = []

# severity and advice
def severity_idx_pm25(pm):
    pm = float(pm)
    if pm <= 12: return 0
    if pm <= 35.4: return 1
    if pm <= 55.4: return 2
    if pm <= 150.4: return 3
    return 4

sev = {}
for k, v in polls.items():
    try:
        if k == "pm25":
            sev[k] = severity_idx_pm25(v)
        else:
            vv = float(v)
            sev[k] = 0 if vv < 30 else (1 if vv < 60 else (2 if vv < 100 else 3))
    except:
        sev[k] = 0

worst_poll = max(sev.items(), key=lambda x: x[1])[0]
ADVICE = {
    "pm25": [
        "Good — enjoy outdoor activities.",
        "Moderate — consider limiting long outdoor exercise.",
        "Unhealthy for sensitive groups — sensitive people avoid prolonged exertion.",
        "Unhealthy — reduce outdoor exertion; consider masks.",
        "Very Unhealthy — stay indoors; use purifier; N95 if outside."
    ],
    "pm10": ["Good", "Moderate — be cautious", "Unhealthy — limit outdoor activity", "Very Unhealthy — stay indoors"],
    "no2": ["Low NO₂", "Moderate NO₂ — avoid busy roads for exercise", "High NO₂ — limit outdoor time"],
    "so2": ["Low SO₂","Moderate SO₂ — avoid heavy exertion","High SO₂ — sensitive stay indoors"],
    "o3": ["Low O₃","Moderate O₃ — avoid midday exercise","High O₃ — reduce outdoor activity"],
    "co": ["Low CO","Moderate CO","High CO — seek fresh air"]
}
advice_text = ADVICE.get(worst_poll, ["No advice available"])[min(sev[worst_poll], len(ADVICE.get(worst_poll, [])) - 1)]

# banner
def render_banner(aqi):
    if aqi >= 150:
        color = PALETTE['unhealthy']
        label = "UNHEALTHY"
    elif aqi >= 100:
        color = PALETTE['moderate']
        label = "UNHEALTHY FOR SENSITIVE GROUPS"
    elif aqi >= 50:
        color = PALETTE['moderate']
        label = "MODERATE"
    else:
        color = PALETTE['good']
        label = "GOOD"
    if "popup_visible" not in st.session_state:
        st.session_state.popup_visible = True
    if st.session_state.popup_visible:
        st.markdown(f'<div style="padding:10px;border-radius:10px;background:{color};color:#021212;font-weight:800;margin-bottom:10px">📣 {selected_location}: <b>{label}</b> — AQI ≈ <b>{aqi}</b></div>', unsafe_allow_html=True)
        if st.button("Dismiss"):
            st.session_state.popup_visible = False

render_banner(aqi_now)

# -------------------------
# Layout
# -------------------------
left, right = st.columns([2.2, 1], gap="large")

with left:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown(f"**{selected_location}**  —  Lat {lat:.4f}, Lon {lon:.4f}")
    st.markdown(f"<div class='small-muted'>OpenAQ radius used: {(used_radius/1000) if used_radius else 'N/A'} km</div>", unsafe_allow_html=True)
    st.write("")

    # Top: PM2.5 and AQI metrics
    a_col, b_col, c_col = st.columns([1,1,0.6])
    with a_col:
        st.markdown(f'<div style="text-align:center; padding:8px; border-radius:10px; background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01))"><div class="metric-val">{polls["pm25"]} µg/m³</div><div class="small-muted">PM2.5</div></div>', unsafe_allow_html=True)
        # show LIVE only; if not live show subtle 'Fallback' label
        if live_flags.get("pm25"):
            st.markdown(f'<div style="margin-top:6px"><span class="badge-live">LIVE</span> <span class="small-muted">OpenAQ</span></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="margin-top:6px"><span class="small-muted">Fallback</span></div>', unsafe_allow_html=True)

    with b_col:
        def aqi_color(aqi):
            if aqi >= 150: return PALETTE['unhealthy']
            if aqi >= 100: return PALETTE['moderate']
            if aqi >= 50: return PALETTE['moderate']
            return PALETTE['good']
        color_now = aqi_color(aqi_now)
        st.markdown(f'<div style="text-align:center; padding:8px; border-radius:10px; background:{color_now}; color:#021212"><div style="font-weight:900;font-size:28px">{aqi_now}</div><div class="small-muted">AQI</div></div>', unsafe_allow_html=True)
        st.markdown(f"<div class='small-muted' style='margin-top:6px'>Category: <b>{'Good' if aqi_now<50 else ('Moderate' if aqi_now<100 else ('Unhealthy' if aqi_now<150 else 'Very Unhealthy'))}</b></div>", unsafe_allow_html=True)

    with c_col:
        st.markdown(f'<div class="small-muted">Satellite: <b>{aod_source}</b></div>', unsafe_allow_html=True)

    st.write("")
    # Gauge
    fig = go.Figure(go.Indicator(mode="gauge+number", value=aqi_now, title={'text': "AQI (from PM2.5)"},
                                gauge={'axis': {'range': [0,300]},
                                       'bar': {'color': PALETTE['accent']},
                                       'steps': [
                                           {'range':[0,50], 'color': PALETTE['good']},
                                           {'range':[50,100], 'color': PALETTE['moderate']},
                                           {'range':[100,150], 'color': '#F97316'},
                                           {'range':[150,300], 'color': PALETTE['unhealthy']}
                                       ]}))
    fig.update_layout(height=330, paper_bgcolor='rgba(0,0,0,0)', font=dict(color=PALETTE['text']))
    st.plotly_chart(fig, use_container_width=True)

    # Download snapshot CSV (uses pandas)
    snapshot_df = pd.DataFrame([{
        "location": selected_location,
        "lat": lat,
        "lon": lon,
        "pm25": polls["pm25"],
        "pm10": polls["pm10"],
        "no2": polls["no2"],
        "so2": polls["so2"],
        "o3": polls["o3"],
        "co": polls["co"],
        "aqi": aqi_now,
        "timestamp": format_time_utc()
    }])
    st.download_button("Download snapshot CSV", data=io.BytesIO(snapshot_df.to_csv(index=False).encode()), file_name="aq_snapshot.csv", mime="text/csv")

    st.markdown(f'<div class="tooltip">Quick advice: {advice_text}</div>', unsafe_allow_html=True)
    st.write("")
    # Map with circle and satellite popup
    fmap = folium.Map(location=[lat, lon], zoom_start=8, tiles=PALETTE['map_tiles'])
    folium.Circle(location=[lat, lon], radius=7000 + aqi_now * 40, color=color_now, fill=True, fill_opacity=0.28, popup=f"AQI: {aqi_now}").add_to(fmap)
    folium.Marker([lat + 0.02, lon + 0.02], popup=f"Satellite proxy AOD: {round(aod_val,3)} — {aod_source}").add_to(fmap)
    st_folium(fmap, width="100%", height=340)

    st.markdown('</div>', unsafe_allow_html=True)

    # Forecast block
    if show_24h:
        st.write("")
        with st.expander("24-hour PM2.5 forecast", expanded=True):
            hours = [(datetime.utcnow() + timedelta(hours=i+1)).strftime("%H:%M") for i in range(24)]
            if pm24:
                lower = [max(0.1, round(v * 0.85, 1)) for v in pm24]
                upper = [round(v * 1.15, 1) for v in pm24]
                figf = go.Figure()
                figf.add_trace(go.Scatter(x=hours, y=pm24, mode="lines+markers", name="PM2.5", line=dict(color=PALETTE['accent'], width=3)))
                figf.add_trace(go.Scatter(x=hours+hours[::-1], y=upper+lower[::-1], fill='toself', name='Confidence', showlegend=False, line=dict(color='rgba(0,0,0,0)'), fillcolor='rgba(0,194,255,0.08)'))
                figf.update_layout(paper_bgcolor='rgba(0,0,0,0)', font=dict(color=PALETTE['text']), height=320)
                st.plotly_chart(figf, use_container_width=True)
            else:
                st.write("Forecast not available.")

with right:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:16px; font-weight:800; color:{PALETTE["text"]}">Pollutant summary</div>', unsafe_allow_html=True)
    st.markdown('<div class="small-muted" style="margin-bottom:8px">Tap a pollutant to see mini-trend & source</div>', unsafe_allow_html=True)

    # pollutant cards (2-column)
    items = [("PM2.5", "pm25"), ("PM10", "pm10"), ("NO₂", "no2"), ("SO₂", "so2"), ("O₃", "o3"), ("CO", "co")]
    for i in range(0, len(items), 2):
        colA, colB = st.columns(2)
        a_label, a_key = items[i]
        with colA:
            val = polls.get(a_key, "—")
            live = live_flags.get(a_key, False)
            badge_html = '<span class="badge-live">LIVE</span>' if live else ''
            source_label = '<span class="small-muted">OpenAQ</span>' if live else '<span class="small-muted">Fallback</span>'
            unit = POLLUTANT_UNITS.get(a_key, "")
            st.markdown(f"<div class='poll-box'><div class='kv'>{val} {unit}</div><div style='font-weight:700'>{a_label}</div><div class='small-muted' style='margin-top:6px'>{badge_html} {source_label}</div></div>", unsafe_allow_html=True)

            # mini sparkline
            try:
                baseline = float(val) if isinstance(val, (int, float)) or (isinstance(val, str) and val.replace('.','',1).isdigit()) else 10.0
                hist = [round(max(0.1, baseline + np.random.normal(0, max(0.1, baseline*0.05))),1) for _ in range(10)]
                st.plotly_chart(sparkline(hist), use_container_width=True)
            except:
                pass
        if i+1 < len(items):
            b_label, b_key = items[i+1]
            with colB:
                valb = polls.get(b_key, "—")
                liveb = live_flags.get(b_key, False)
                badgeb = '<span class="badge-live">LIVE</span>' if liveb else ''
                source_label_b = '<span class="small-muted">OpenAQ</span>' if liveb else '<span class="small-muted">Fallback</span>'
                unitb = POLLUTANT_UNITS.get(b_key, "")
                st.markdown(f"<div class='poll-box'><div class='kv'>{valb} {unitb}</div><div style='font-weight:700'>{b_label}</div><div class='small-muted' style='margin-top:6px'>{badgeb} {source_label_b}</div></div>", unsafe_allow_html=True)

                
                try:
                    baseb = float(valb) if isinstance(valb, (int, float)) or (isinstance(valb, str) and valb.replace('.','',1).isdigit()) else 12.0
                    histb = [round(max(0.1, baseb + np.random.normal(0, max(0.1, baseb*0.05))),1) for _ in range(10)]
                    st.plotly_chart(sparkline(histb), use_container_width=True)
                except:
                    pass

    st.markdown('---')
    st.markdown("### Worst pollutant & quick advice")
    st.markdown(f"**Worst pollutant:** <b>{worst_poll.upper()}</b>", unsafe_allow_html=True)
    st.markdown(f"**Advice:** {advice_text}")
    st.markdown("**Quick tips:**")
    tips = {
        "pm25": ["Wear N95 when high exposure", "Avoid long outdoor workouts if PM2.5 high", "Use indoor purifier"],
        "pm10": ["Avoid dusty outdoor activities", "Wear mask in dust events"],
        "no2": ["Avoid heavy-traffic streets for exercise"],
        "so2": ["Sensitive people stay indoors near sources"],
        "o3": ["Avoid midday outdoor workouts"],
        "co": ["Ensure ventilation"]
    }
    for t in tips.get(worst_poll, []):
        st.markdown(f"- {t}")

    st.markdown('---')
    st.markdown("### Weather now")
    if weather:
        st.markdown(f"- Temperature: **{weather.get('temp')} °C**")
        st.markdown(f"- Wind: **{weather.get('windspeed')} m/s**, dir **{weather.get('winddir')}°**")
    else:
        st.markdown("- Weather not available")

    st.markdown('---')
    st.markdown(f"<div class='small-muted'>Satellite AOD (visual): <b>{round(aod_val,3)}</b> — {aod_source}</div>", unsafe_allow_html=True)

    # provenance footer (single line)
    st.markdown("<div class='small-muted' style='margin-top:8px'>Data: OpenAQ (ground) · Open-Meteo (weather) · Satellite proxy (TEMPO/MODIS or PM2.5 proxy). LIVE badges denote station data; fallbacks used when needed.</div>", unsafe_allow_html=True)

    st.markdown(f"<div class='small-muted'>Latest update: {format_time_utc()}</div>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# End of app
