import os
import time

import requests
import streamlit as st
from PIL import Image

# ---------------------------------------------------------
# 1. PAGE SETUP & COLOR THEME CONFIGURATION
# ---------------------------------------------------------
st.set_page_config(
    page_title="EcoHealth Pulse",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* Global Base Canvas */
    .stApp {
        background-color: #FFFAF7;
        color: #19332B;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }

    /* Sidebar Background */
    section[data-testid="stSidebar"] {
        background-color: #F3ECE7;
        border-right: 1px solid #E5DBD4;
    }

    /* Standard Page Typography */
    h1, h2, h3, h4, h5, h6, p, label {
        color: #19332B;
    }

    /* Hero Banner */
    .hero-banner {
        background-color: #FFFFFF;
        border: 1px solid #EAE0D9;
        border-left: 6px solid #176B4D;
        border-radius: 14px;
        padding: 22px 28px;
        margin-bottom: 24px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 4px 16px rgba(25, 51, 43, 0.04);
    }

    .score-badge {
        background: linear-gradient(135deg, #176B4D 0%, #35A77A 100%);
        color: #FFFFFF !important;
        padding: 8px 18px;
        border-radius: 24px;
        font-weight: 700;
        font-size: 0.95rem;
        letter-spacing: 0.03em;
        display: inline-block;
        box-shadow: 0 2px 8px rgba(23, 107, 77, 0.25);
    }

    /* Metric Cards */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #EAE0D9;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 2px 10px rgba(25, 51, 43, 0.03);
    }
    div[data-testid="stMetric"] label {
        color: #35A8C5 !important;
        font-weight: 700 !important;
        font-size: 0.82rem !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #176B4D !important;
        font-weight: 700 !important;
    }

    /* Card Containers */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #FFFFFF !important;
        border: 1px solid #EAE0D9 !important;
        border-radius: 14px;
        box-shadow: 0 3px 12px rgba(25, 51, 43, 0.03);
    }

    /* High-Contrast Action Buttons */
    .stButton>button {
        background-color: #176B4D !important;
        border: 1px solid #11533B !important;
        border-radius: 10px !important;
        padding: 12px 24px !important;
        box-shadow: 0 4px 12px rgba(23, 107, 77, 0.2) !important;
        transition: all 0.2s ease !important;
    }

    .stButton>button p,
    .stButton>button span,
    .stButton>button div {
        color: #FFFFFF !important;
        font-size: 1rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.02em !important;
    }

    .stButton>button:hover {
        background-color: #35A77A !important;
        border-color: #2D946C !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 14px rgba(53, 167, 122, 0.3) !important;
    }

    .stButton>button:hover p,
    .stButton>button:hover span {
        color: #FFFFFF !important;
    }

    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #F0E8E2;
        padding: 6px;
        border-radius: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 8px 18px;
        font-weight: 600;
        color: #19332B !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FFFFFF !important;
        color: #176B4D !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }

    /* Inputs & Selectboxes */
    .stTextInput>div>div>input, .stSelectbox>div>div {
        background-color: #FFFFFF !important;
        color: #19332B !important;
        border: 1px solid #D8CCC4 !important;
        border-radius: 8px;
    }
    .stTextInput>div>div>input:focus {
        border-color: #35A8C5 !important;
    }

    /* Slider Track Accent */
    div[data-baseweb="slider"] div {
        color: #176B4D;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------
# 2. BACKEND CONNECTIVITY CONFIGURATION
# ---------------------------------------------------------
# backend.py is a FastAPI app (uvicorn), not Flask - default port 8000.
# Override with `BACKEND_URL=http://your-host:8000 streamlit run frontend.py`
# if the backend runs somewhere other than localhost.
BACKEND_BASE_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


@st.cache_data(ttl=10)
def check_backend_online(base_url: str) -> bool:
    """Pings the FastAPI root health-check endpoint."""
    try:
        res = requests.get(f"{base_url}/", timeout=2.5)
        return res.status_code == 200
    except Exception:
        return False


def search_cities(query: str, limit: int = 5):
    """Calls GET /api/search-cities on the FastAPI backend."""
    try:
        res = requests.get(
            f"{BACKEND_BASE_URL}/api/search-cities",
            params={"q": query},
            timeout=6,
        )
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.error(f"City search failed: {e}")
        return []


def assess_risk(city: str, conditions, age_group: str, notes: str):
    """Calls POST /api/assess-risk on the FastAPI backend.

    Matches backend's HealthAssessmentRequest schema exactly:
      { "cities": [...], "profile": { "conditions": [...], "age_group": ..., "additional_notes": ... } }
    """
    payload = {
        "cities": [city],
        "profile": {
            "conditions": conditions if conditions else ["General / Health-Conscious"],
            "age_group": age_group or None,
            "additional_notes": notes or None,
        },
    }
    try:
        res = requests.post(
            f"{BACKEND_BASE_URL}/api/assess-risk",
            json=payload,
            timeout=30,
        )
        res.raise_for_status()
        data = res.json()
        results = data.get("results", [])
        return results[0] if results else None
    except Exception as e:
        st.error(f"Backend connection error (assess-risk): {e}")
        return None


def vision_log(image_file, notes: str):
    """Calls POST /api/vision-log on the FastAPI backend.

    Backend expects multipart form fields named exactly "file" and "notes".
    """
    try:
        files = {
            "file": (
                image_file.name,
                image_file.getvalue(),
                image_file.type or "image/jpeg",
            )
        }
        data = {"notes": notes or ""}
        res = requests.post(
            f"{BACKEND_BASE_URL}/api/vision-log",
            files=files,
            data=data,
            timeout=30,
        )
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.error(f"Backend connection error (vision-log): {e}")
        return None


# Risk level -> numeric badge + Streamlit alert styling, for display only.
RISK_TO_SCORE = {"Low": 20, "Moderate": 50, "High": 75, "Severe": 95, "Unknown": 0, "Error": 0}


# Metric classification thresholds - mirrors backend.py's classify_* helpers
# (US EPA AQI bands / WHO 2021 guideline for PM2.5, WHO UV Index scale,
# WHO 8-hr guideline + EU thresholds for ozone, rough NOAA heat-index mapping).
# delta_color: "normal" = green (good), "off" = neutral gray (moderate), "inverse" = red (bad).
def classify_pm25(v):
    if v <= 12:
        return "Good", "normal"
    if v <= 35.4:
        return "Moderate", "off"
    if v <= 55.4:
        return "Unhealthy (Sensitive)", "inverse"
    return "Unhealthy", "inverse"


def classify_uv(v):
    if v <= 2:
        return "Low", "normal"
    if v <= 5:
        return "Moderate", "off"
    if v <= 7:
        return "High", "inverse"
    return "Very High", "inverse"


def classify_ozone(v):
    if v <= 100:
        return "Good", "normal"
    if v <= 180:
        return "Moderate", "off"
    return "High", "inverse"


def classify_heat(v):
    if v < 27:
        return "Comfortable", "normal"
    if v < 32:
        return "Caution", "off"
    if v < 39:
        return "Hot", "inverse"
    return "Danger", "inverse"


# ---------------------------------------------------------
# 3. SIDEBAR: HEALTH RISK PROFILER
# ---------------------------------------------------------
with st.sidebar:
    st.markdown("<h2 style='color:#176B4D; margin-bottom:0;'>🌿 EcoHealth Pulse</h2>", unsafe_allow_html=True)
    st.caption("Personalized Environmental Vulnerability Engine")
    st.markdown("---")

    st.markdown("<span style='color:#176B4D; font-weight:700;'>HEALTH VULNERABILITIES</span>", unsafe_allow_html=True)
    selected_conditions = st.multiselect(
        "Select personal health factors",
        options=[
            "Asthma / Respiratory",
            "Cardiovascular Conditions",
            "Outdoor Labor (Construction, Delivery, Police)",
            "Pregnancy",
            "Parents / Caregivers (Elderly & Pediatric)",
            "Seasonal Allergies",
            "General / Health-Conscious"
        ],
        default=["Asthma / Respiratory", "Outdoor Labor (Construction, Delivery, Police)"],
        label_visibility="collapsed"
    )

    st.markdown("<br><span style='color:#176B4D; font-weight:700;'>DAILY OUTDOOR EXPOSURE</span>", unsafe_allow_html=True)
    outdoor_hours = st.slider("Daily exposure hours", 0.5, 12.0, 4.0, 0.5, format="%.1f hrs", label_visibility="collapsed")

    st.markdown("---")
    st.markdown("<span style='color:#176B4D; font-weight:700;'>MONITORING LOCATION</span>", unsafe_allow_html=True)

    # Backend does live global geocoding (any city), so this is a free-text
    # search against /api/search-cities rather than a fixed dropdown.
    city_query = st.text_input(
        "Search for any city",
        value=st.session_state.get("selected_city", "New York"),
        label_visibility="collapsed",
        placeholder="e.g. Tokyo, São Paulo, Berlin",
    )

    city_options = search_cities(city_query) if len(city_query.strip()) >= 2 else []
    if city_options:
        labels = [
            f"{c['name']}, {c.get('admin1') + ', ' if c.get('admin1') else ''}{c['country']}"
            for c in city_options
        ]
        picked_idx = st.selectbox("Matches", options=range(len(labels)), format_func=lambda i: labels[i], label_visibility="collapsed")
        selected_city = city_options[picked_idx]["name"]
    else:
        selected_city = city_query.strip() or "New York"

    st.session_state["selected_city"] = selected_city

    # Backend Connection Status
    st.markdown("---")
    backend_online = check_backend_online(BACKEND_BASE_URL)
    if backend_online:
        st.markdown(
            f"<span style='color:#176B4D; font-weight:600; font-size:0.85rem;'>● Backend: Connected ({BACKEND_BASE_URL})</span>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<span style='color:#C0392B; font-weight:600; font-size:0.85rem;'>● Backend: Unreachable ({BACKEND_BASE_URL})</span>",
            unsafe_allow_html=True,
        )
        st.caption("Start it with: `python backend.py --server` (or set BACKEND_URL).")


# ---------------------------------------------------------
# 4. MAIN INTERFACE
# ---------------------------------------------------------
if "assessment" not in st.session_state:
    st.session_state["assessment"] = None

result = st.session_state["assessment"]
risk_level = result["risk_level"] if result else "—"
risk_score = RISK_TO_SCORE.get(risk_level, 0)

# Hero Header Banner
st.markdown(f"""
<div class="hero-banner">
    <div>
        <h2 style="margin: 0; color: #176B4D; font-size: 1.6rem; letter-spacing: -0.02em;">Environmental Health Radar</h2>
        <p style="margin: 4px 0 0 0; color: #19332B; font-size: 0.95rem;">
            Active Station: <strong style="color: #35A8C5;">{selected_city}</strong>
        </p>
    </div>
    <div style="text-align: right;">
        <span class="score-badge">RISK LEVEL: {risk_level.upper()}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Navigation Tabs
tab_dashboard, tab_vision = st.tabs([
    "📊 Atmospheric Ingestion & Advisories",
    "📷 Hazard Vision Scanner"
])


# ---------------------------------------------------------
# TAB 1: ENVIRONMENTAL TELEMETRY & ADVISORIES
# ---------------------------------------------------------
with tab_dashboard:
    st.markdown("#### **Real-Time Telemetry**")

    if not backend_online:
        st.warning("Backend is unreachable, so live telemetry can't be pulled right now.")
    else:
        with st.container(border=True):
            st.markdown("<h4 style='color:#176B4D; margin-bottom: 4px;'>AI Clinical Action Engine</h4>", unsafe_allow_html=True)
            st.write("Pulls live weather + air-quality data for the selected city from the backend, then generates a clinically aligned advisory tailored to your health profile.")

            if st.button("Synthesize Risk Analysis", use_container_width=True):
                notes = f"Daily outdoor exposure: {outdoor_hours} hours."
                with st.spinner(f"Contacting backend and resolving {selected_city}..."):
                    st.session_state["assessment"] = assess_risk(
                        selected_city, selected_conditions, None, notes
                    )
                result = st.session_state["assessment"]
                risk_level = result["risk_level"] if result else "—"

        if result:
            env = result["environmental_data"]
            pm_label, pm_color = classify_pm25(env["pm2_5"])
            uv_label, uv_color = classify_uv(env["uv_index"])
            oz_label, oz_color = classify_ozone(env["ozone"])
            heat_label, heat_color = classify_heat(env["apparent_temperature_c"])

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("PM2.5 Particulate", f"{env['pm2_5']} µg/m³", delta=pm_label, delta_color=pm_color)
            with c2:
                st.metric("UV Index", f"{env['uv_index']}", delta=uv_label, delta_color=uv_color)
            with c3:
                st.metric("Ground Ozone (O₃)", f"{env['ozone']} µg/m³", delta=oz_label, delta_color=oz_color)
            with c4:
                st.metric("Apparent Heat", f"{env['apparent_temperature_c']} °C", delta=heat_label, delta_color=heat_color)

            st.caption(
                "Ranges: PM2.5 follows US EPA/WHO air-quality bands · UV follows WHO's UV Index scale · "
                "Ozone follows WHO/EU thresholds · Heat is a rough NOAA heat-index mapping. General guidance, not medical advice."
            )

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(f"**Resolved location:** {result['city']}, {result.get('admin1') or ''} ({result['country']})")

            if risk_level in ("High", "Severe", "Error", "Unknown"):
                st.error(f"**Clinical Advisory**\n\n{result['advisory']}")
            elif risk_level == "Moderate":
                st.warning(f"**Clinical Advisory**\n\n{result['advisory']}")
            else:
                st.success(f"**Clinical Advisory**\n\n{result['advisory']}")
        else:
            st.info("Click **'Synthesize Risk Analysis'** to fetch live data and an advisory for this city.")


# ---------------------------------------------------------
# TAB 2: HAZARD VISION SCANNER
# ---------------------------------------------------------
with tab_vision:
    st.markdown("#### **Environmental Hazard & Symptom Vision Log**")
    st.write("Upload photos of localized exposure hazards (stagnant water pools, industrial exhaust, smoke) or skin/eye symptoms for automated classification via the backend's vision endpoint.")

    col_upload, col_preview = st.columns([1, 1], gap="large")

    with col_upload:
        with st.container(border=True):
            uploaded_img = st.file_uploader(
                "Upload hazard photo (JPG, PNG)",
                type=["jpg", "jpeg", "png"],
                help="Select an image of the environmental hazard or physical symptom."
            )
            vision_notes = st.text_input("Optional notes for the vision model", value="")

            scan_btn = False
            if uploaded_img:
                image = Image.open(uploaded_img)
                st.image(image, caption="Uploaded Image", use_container_width=True)
                scan_btn = st.button("Run Vision Classification", use_container_width=True, disabled=not backend_online)
                if not backend_online:
                    st.caption("Backend is unreachable, so vision classification is disabled.")

    with col_preview:
        with st.container(border=True):
            st.markdown("<h4 style='color:#176B4D; margin-bottom: 4px;'>Vision AI Diagnostic Output</h4>", unsafe_allow_html=True)

            if uploaded_img and scan_btn:
                with st.spinner("Classifying hazard risk with Vision AI..."):
                    result = vision_log(uploaded_img, vision_notes)

                if result and result.get("status") == "unavailable":
                    st.warning(result["message"])
                elif result and "analysis" in result:
                    st.success("Hazard Classified Successfully")
                    st.markdown(f"**File analyzed:** `{result.get('filename', uploaded_img.name)}`")
                    st.markdown(result["analysis"])
                elif result is not None:
                    st.warning("Backend responded but returned an unexpected shape.")
            else:
                st.info("Upload an image on the left and click **'Run Vision Classification'** to view findings.")
