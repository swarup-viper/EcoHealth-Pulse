import argparse
import asyncio
import base64
import io
import os
import sys
from typing import List, Optional, Union

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, Field

# ------------------------------------------------------------------------------
# API Configuration & Global Setup
# ------------------------------------------------------------------------------
# AI is an OPTIONAL enhancement layer, not a dependency. The deterministic,
# no-API-key-required engine further down always runs first and is a complete,
# correct answer on its own. If OPENAI_API_KEY is configured and the call
# succeeds, its text is used instead; if it fails or isn't configured, nothing
# breaks - the deterministic result is what the user sees.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except ImportError:
    openai_client = None  # `openai` package not installed - AI upgrade is just skipped


def generate_ai_text(prompt: str, image: Optional[Image.Image] = None) -> Optional[str]:
    """Calls OpenAI if configured. Never raises - returns None if unconfigured or
    the call fails, so callers can always fall back to the deterministic engine
    instead of surfacing a raw error to the user."""
    if not openai_client:
        return None
    try:
        if image is not None:
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            b64_image = base64.b64encode(buf.getvalue()).decode()
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}},
                ],
            }]
        else:
            messages = [{"role": "user", "content": prompt}]
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL_NAME, messages=messages
        )
        text = (response.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        return None  # OpenAI is having problems - caller falls back to the deterministic engine

app = FastAPI(
    title="EcoHealth Pulse API",
    description="Backend engine supporting dynamic city searching, multi-city risk evaluation, and health assessments.",
    version="2.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------------------
# Data Schemas
# ------------------------------------------------------------------------------
class HealthProfile(BaseModel):
    conditions: List[str] = Field(
        ..., json_schema_extra={"example": ["asthma", "hypertension"]}
    )
    age_group: Optional[str] = Field(
        None, json_schema_extra={"example": "elderly"}
    )
    additional_notes: Optional[str] = Field(
        None, json_schema_extra={"example": "Pregnant"}
    )


class HealthAssessmentRequest(BaseModel):
    cities: Union[str, List[str]] = Field(
        ..., json_schema_extra={"example": ["London", "Cairo", "San Francisco"]}
    )
    profile: HealthProfile


class EnvironmentalMetrics(BaseModel):
    temperature_c: float
    apparent_temperature_c: float
    uv_index: float
    pm2_5: float
    pm10: float
    ozone: float
    european_aqi: float


class CityAssessmentResult(BaseModel):
    city: str
    country: str
    admin1: Optional[str] = None
    latitude: float
    longitude: float
    environmental_data: EnvironmentalMetrics
    advisory: str
    risk_level: str


class MultiCityAssessmentResponse(BaseModel):
    total_cities: int
    results: List[CityAssessmentResult]


class CitySearchResult(BaseModel):
    id: int
    name: str
    country: str
    admin1: Optional[str] = None
    latitude: float
    longitude: float


# ------------------------------------------------------------------------------
# Health-Based Classification Thresholds (WHO / US EPA / EU air-quality standards)
# ------------------------------------------------------------------------------
def classify_pm25(value: float):
    """PM2.5 (µg/m³) tiers - US EPA AQI breakpoints, aligned with WHO's 2021 guideline."""
    if value <= 12:
        return "Good", 0
    if value <= 35.4:
        return "Moderate", 1
    if value <= 55.4:
        return "Unhealthy for Sensitive Groups", 2
    if value <= 150.4:
        return "Unhealthy", 2
    return "Hazardous", 3


def classify_uv(value: float):
    """UV Index tiers - WHO's global UV Index scale."""
    if value <= 2:
        return "Low", 0
    if value <= 5:
        return "Moderate", 1
    if value <= 7:
        return "High", 2
    if value <= 10:
        return "Very High", 2
    return "Extreme", 3


def classify_ozone(value: float):
    """Ground-level ozone (µg/m³) tiers - WHO 8-hr guideline (100 µg/m³) and EU info/alert thresholds."""
    if value <= 100:
        return "Good", 0
    if value <= 180:
        return "Moderate", 1
    if value <= 240:
        return "High", 2
    return "Very High", 3


def classify_heat(value: float):
    """Apparent temperature (°C) tiers - rough mapping from the NOAA heat index scale."""
    if value < 27:
        return "Comfortable", 0
    if value < 32:
        return "Caution", 1
    if value < 39:
        return "Hot", 2
    if value < 51:
        return "Danger", 3
    return "Extreme Danger", 3


# Maps a health vulnerability to (a) which environmental factors matter for it, and
# (b) the plain-language warning to surface when one of those factors is elevated.
# Matched by keyword against the profile text, so it works for both the structured
# conditions list from the API and freeform text typed into the CLI.
CONDITION_RISK_MAP = [
    (
        ["asthma", "respiratory"],
        ["pm25", "ozone"],
        "Poor air quality can trigger airway inflammation - keep a reliever inhaler handy and avoid outdoor exertion while pollution is elevated.",
    ),
    (
        ["cardiovascular", "heart"],
        ["pm25", "heat"],
        "Fine particulates and heat both add strain on the heart - pace yourself outdoors and stay well hydrated.",
    ),
    (
        ["outdoor labor", "construction", "delivery", "police"],
        ["uv", "heat", "ozone", "pm25"],
        "Since you're outdoors for long stretches, take shaded breaks, hydrate often, and mask up if pollution is high.",
    ),
    (
        ["pregnan"],
        ["pm25", "ozone", "heat"],
        "Pollutant exposure and overheating are best minimized during pregnancy - limit time outdoors and stay cool and hydrated.",
    ),
    (
        ["elderly", "pediatric", "caregiver", "parent"],
        ["pm25", "uv", "heat"],
        "Children and older adults are more sensitive to pollution, sun, and heat - limit their outdoor time in the worst hours and use sunscreen.",
    ),
    (
        ["allerg"],
        ["ozone", "pm25"],
        "Elevated ozone and particulates can worsen allergy symptoms - antihistamines and keeping windows closed during peak hours can help.",
    ),
]


# ------------------------------------------------------------------------------
# Dynamic Global Geocoding & Environmental Data Services
# ------------------------------------------------------------------------------
async def search_cities_online(query: str, limit: int = 5) -> List[dict]:
    """Dynamically searches any city worldwide using Open-Meteo Geocoding API."""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": query.strip(),
        "count": limit,
        "language": "en",
        "format": "json"
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, params=params, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                results = data.get("results", [])
                cities = []
                for item in results:
                    cities.append({
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "country": item.get("country", "Unknown"),
                        "admin1": item.get("admin1", ""),
                        "latitude": item.get("latitude"),
                        "longitude": item.get("longitude"),
                    })
                return cities
        except Exception as e:
            raise HTTPException(
                status_code=503, detail=f"Geocoding service error: {str(e)}"
            )
    return []


async def get_city_coordinates(city_name: str) -> dict:
    """Resolves any user-entered city string into geographical coordinates."""
    # Attempt direct search
    cities = await search_cities_online(city_name, limit=1)
    
    # Fallback: handle inputs like "Paris, France" or "Austin, TX" by splitting by comma
    if not cities and "," in city_name:
        clean_name = city_name.split(",")[0].strip()
        cities = await search_cities_online(clean_name, limit=1)

    if cities:
        top = cities[0]
        admin_str = f", {top['admin1']}" if top.get("admin1") else ""
        return {
            "city": top["name"],
            "country": top["country"],
            "admin1": top.get("admin1", ""),
            "full_name": f"{top['name']}{admin_str}, {top['country']}",
            "latitude": top["latitude"],
            "longitude": top["longitude"],
        }

    raise HTTPException(
        status_code=404,
        detail=f"City '{city_name}' could not be resolved. Check spelling or try a major nearby city.",
    )


async def fetch_environmental_data(lat: float, lon: float) -> EnvironmentalMetrics:
    """Fetches real-time weather and air pollution metrics for target coordinates."""
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,apparent_temperature,uv_index"
    air_quality_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=pm10,pm2_5,ozone,european_aqi"

    async with httpx.AsyncClient() as client:
        try:
            w_res = await client.get(weather_url, timeout=5.0)
            a_res = await client.get(air_quality_url, timeout=5.0)

            w_data = w_res.json().get("current", {})
            a_data = a_res.json().get("current", {})

            return EnvironmentalMetrics(
                temperature_c=w_data.get("temperature_2m", 0.0),
                apparent_temperature_c=w_data.get("apparent_temperature", 0.0),
                uv_index=w_data.get("uv_index", 0.0),
                pm2_5=a_data.get("pm2_5", 0.0),
                pm10=a_data.get("pm10", 0.0),
                ozone=a_data.get("ozone", 0.0),
                european_aqi=a_data.get("european_aqi", 0.0),
            )
        except Exception as e:
            raise HTTPException(
                status_code=503, detail=f"Environmental API error: {str(e)}"
            )


def build_deterministic_advisory(location_info: dict, env_data: EnvironmentalMetrics, profile_summary: str):
    """Rule-based risk level + plain-language advisory. No API key or network
    dependency beyond the environmental data already fetched - this always
    works and is what the AI layer above may optionally upgrade or fall back to.
    Uses the classify_* helpers (WHO / US EPA / EU bands) and CONDITION_RISK_MAP."""
    pm_label, pm_sev = classify_pm25(env_data.pm2_5)
    uv_label, uv_sev = classify_uv(env_data.uv_index)
    oz_label, oz_sev = classify_ozone(env_data.ozone)
    heat_label, heat_sev = classify_heat(env_data.apparent_temperature_c)

    severity = max(pm_sev, uv_sev, oz_sev, heat_sev)
    risk_level = ["Low", "Moderate", "High", "Severe"][severity]

    # Plain-language summary - only mention factors that actually stand out.
    standout = []
    if pm_sev >= 1:
        standout.append(f"air quality is {pm_label.lower()} (PM2.5 {env_data.pm2_5} µg/m³)")
    if uv_sev >= 1:
        standout.append(f"UV is {uv_label.lower()} (index {env_data.uv_index})")
    if oz_sev >= 1:
        standout.append(f"ozone is {oz_label.lower()}")
    if heat_sev >= 1:
        standout.append(f"it feels {heat_label.lower()} ({env_data.apparent_temperature_c}°C)")

    if standout:
        summary = f"Right now in {location_info['city']}, " + ", and ".join(standout) + "."
    else:
        summary = f"Conditions in {location_info['city']} look good across the board right now."

    if severity == 0:
        return risk_level, f"{summary} It's a good day to be outside as usual."

    # Tie warnings to the specific conditions the person actually listed, and
    # only surface a condition's warning if a factor relevant to it is elevated.
    sev_map = {"pm25": pm_sev, "uv": uv_sev, "ozone": oz_sev, "heat": heat_sev}
    profile_text = profile_summary.lower()

    matched_condition = False
    condition_warnings = []
    for keywords, factors, warning in CONDITION_RISK_MAP:
        if any(k in profile_text for k in keywords):
            matched_condition = True
            if any(sev_map[f] >= 1 for f in factors):
                condition_warnings.append(warning)

    if condition_warnings:
        advisory = summary + "\n\n" + "\n\n".join(f"⚠️ {w}" for w in condition_warnings)
    elif matched_condition:
        advisory = f"{summary} Nothing here specifically affects the conditions you listed, but it's still worth taking it easy outdoors."
    else:
        tip = "Consider limiting time outdoors, especially around midday, and keep any rescue medication (like an inhaler) on hand."
        advisory = f"{summary} {tip}"

    return risk_level, advisory


# ------------------------------------------------------------------------------
# Core Assessment Engine
# ------------------------------------------------------------------------------
async def run_city_assessment(
    city_name: str, profile_summary: str
) -> CityAssessmentResult:
    """Dynamically resolves any city name, fetches live data, and generates a health report.

    The deterministic engine always runs and is a complete, correct result on its
    own. AI (if configured) is only attempted as an optional upgrade on top of it -
    if every configured provider fails or none are configured, the deterministic
    result is used as-is, so this endpoint never breaks because of an AI provider."""
    location_info = await get_city_coordinates(city_name)
    env_data = await fetch_environmental_data(
        location_info["latitude"], location_info["longitude"]
    )

    risk_level, advisory = build_deterministic_advisory(location_info, env_data, profile_summary)

    prompt = f"""
    You are a clinical environmental health advisor.
    Analyze environmental metrics for the city against the user's personal health profile.

    Target City: {location_info['full_name']}
    Coordinates: Lat {location_info['latitude']}, Lon {location_info['longitude']}
    Health Profile: {profile_summary}

    Real-time Environmental Data:
    - Temperature: {env_data.temperature_c}°C (Feels like: {env_data.apparent_temperature_c}°C)
    - UV Index: {env_data.uv_index}
    - Air Quality - PM2.5: {env_data.pm2_5} µg/m³
    - Air Quality - PM10: {env_data.pm10} µg/m³
    - Ozone (O3): {env_data.ozone} µg/m³
    - European Air Quality Index (AQI): {env_data.european_aqi}

    Format response as:
    RISK_LEVEL: <Low / Moderate / High / Severe>
    ADVISORY: <2-3 short sentences in plain, everyday language a non-medical person can easily understand
    (avoid clinical jargon, no raw data dumps). For each condition in the Health Profile, explicitly call out
    if today's data poses a specific risk to it (e.g. "Since you have asthma, ..."); skip a condition if it
    isn't affected today. Tailor everything specifically to {location_info['city']}.>
    """

    ai_output = generate_ai_text(prompt)
    if ai_output and "RISK_LEVEL:" in ai_output and "ADVISORY:" in ai_output:
        parts = ai_output.split("ADVISORY:")
        ai_risk = parts[0].replace("RISK_LEVEL:", "").strip()
        ai_advisory = parts[1].strip()
        if ai_risk and ai_advisory:
            risk_level, advisory = ai_risk, ai_advisory
    # else: AI unavailable/failed/malformed - the deterministic result above stands, silently.

    return CityAssessmentResult(
        city=location_info["city"],
        country=location_info["country"],
        admin1=location_info["admin1"],
        latitude=location_info["latitude"],
        longitude=location_info["longitude"],
        environmental_data=env_data,
        advisory=advisory,
        risk_level=risk_level,
    )


# ------------------------------------------------------------------------------
# REST API Endpoints
# ------------------------------------------------------------------------------
@app.get("/")
def health_check():
    return {"status": "online", "service": "EcoHealth Pulse Dynamic Multi-City Engine"}


@app.get("/api/search-cities", response_model=List[CitySearchResult])
async def search_cities_endpoint(
    q: str = Query(..., description="Search query for any global city (e.g., 'Tokyo', 'São Paulo', 'Berlin')")
):
    """Autocomplete search endpoint for any city globally."""
    if len(q.strip()) < 2:
        return []
    return await search_cities_online(q.strip(), limit=5)


@app.post("/api/assess-risk", response_model=MultiCityAssessmentResponse)
async def assess_risk_api(request: HealthAssessmentRequest):
    """Accepts any single city name or array of city names dynamically."""
    city_list = (
        [request.cities] if isinstance(request.cities, str) else request.cities
    )

    if not city_list:
        raise HTTPException(
            status_code=400, detail="Please provide at least one city name."
        )

    profile_summary = (
        f"Conditions: {', '.join(request.profile.conditions)}. "
        f"Age: {request.profile.age_group or 'Unspecified'}. "
        f"Notes: {request.profile.additional_notes or 'None'}"
    )

    tasks = [run_city_assessment(c.strip(), profile_summary) for c in city_list if c.strip()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_results = []
    for city_name, res in zip(city_list, results):
        if isinstance(res, CityAssessmentResult):
            valid_results.append(res)
        elif isinstance(res, Exception):
            valid_results.append(
                CityAssessmentResult(
                    city=city_name,
                    country="Unknown",
                    latitude=0.0,
                    longitude=0.0,
                    environmental_data=EnvironmentalMetrics(
                        temperature_c=0, apparent_temperature_c=0, uv_index=0, pm2_5=0, pm10=0, ozone=0, european_aqi=0
                    ),
                    advisory=f"Could not resolve city '{city_name}': {str(res)}",
                    risk_level="Unknown",
                )
            )

    return MultiCityAssessmentResponse(
        total_cities=len(valid_results), results=valid_results
    )


@app.post("/api/vision-log")
async def vision_log_api(
    file: UploadFile = File(...), notes: Optional[str] = Form(None)
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400, detail="Uploaded file must be an image."
        )

    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes))

    prompt = (
        "Analyze this image in an environmental health context. Identify hazards "
        f"(smog, standing water, vector risks, mold) or health exposure symptoms. Notes: {notes or 'None'}. "
        "Answer in 2-3 short, plain, non-clinical sentences."
    )
    analysis = generate_ai_text(prompt, image=image)

    if analysis:
        return {"filename": file.filename, "analysis": analysis}

    # No AI provider configured, or every configured one failed - fail gracefully
    # rather than surfacing a raw error, since vision classification has no
    # deterministic equivalent to fall back to.
    return {
        "status": "unavailable",
        "message": (
            "Image received, but automated vision analysis isn't available right now. "
            "Set OPENAI_API_KEY, or try again shortly."
        ),
    }


# ------------------------------------------------------------------------------
# Interactive CLI Execution
# ------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="EcoHealth Pulse Engine")
    parser.add_argument(
        "--cities",
        type=str,
        default=None,
        help="Comma-separated city names (e.g. 'Kyoto, Toronto, Mumbai')",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Health conditions summary",
    )
    parser.add_argument(
        "--server", action="store_true", help="Launch FastAPI web server"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to run server on"
    )

    args = parser.parse_args()

    if args.server:
        print(f"🚀 Launching EcoHealth Pulse server on http://localhost:{args.port}")
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        raw_cities = args.cities
        profile = args.profile

        if not raw_cities:
            raw_cities = input(
                "Enter any city name(s) (e.g. Kyoto, Mumbai, San Francisco): "
            ).strip()
            if not raw_cities:
                raw_cities = "New York"

        if not profile:
            profile = input(
                "Enter health conditions (e.g., asthma, pregnancy): "
            ).strip()
            if not profile:
                profile = "asthma"

        city_list = [c.strip() for c in raw_cities.split(",") if c.strip()]

        async def run_cli():
            print(f"\nEvaluating health risk for {len(city_list)} city/cities...")
            for city in city_list:
                try:
                    res = await run_city_assessment(city, profile)
                    print("\n" + "=" * 50)
                    print(f"📍 City: {res.city}, {res.admin1 or ''} ({res.country})")
                    print(f"🌐 Coordinates: {res.latitude}, {res.longitude}")
                    print(f"📊 Metrics: {res.environmental_data.model_dump()}")
                    print(f"⚠️ Risk Level: {res.risk_level}")
                    print(f"💡 Advisory:\n{res.advisory}")
                except Exception as e:
                    print(f"\n❌ Error evaluating '{city}': {str(e)}")

        asyncio.run(run_cli())


if __name__ == "__main__":
    sys.exit(main())
