# main.py
import functions_framework
from flask import request, jsonify
from datetime import datetime, timezone, timedelta
import openmeteo_requests
import requests_cache
from retry_requests import retry

# ---------- CONFIG ----------
# Cache on disk in /tmp (writable in Cloud Functions; ephemeral but useful on warm containers)
CACHE_PATH = "/tmp/openmeteo_cache"
CACHE_EXPIRE_SECONDS = 900  # 15 minutes
MAX_HOURS = 24

# Which variables we will request
AQ_VARS = ["pm10", "pm2_5", "us_aqi_pm2_5", "us_aqi_pm10", "us_aqi_nitrogen_dioxide"]
WEATHER_VARS = ["temperature_2m", "windspeed_10m", "relative_humidity_2m", "precipitation"]

# Setup client (with cache + retries)
cache_session = requests_cache.CachedSession(CACHE_PATH, expire_after=CACHE_EXPIRE_SECONDS)
retry_session = retry(cache_session, retries=4, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

# ---------- Helpers ----------
def is_in_na(lat, lon):
    return 5.0 <= lat <= 85.0 and -170.0 <= lon <= -50.0

def parse_iso_time(s):
    # Accept ISO like "2025-10-01T15:00:00Z" or without Z
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        raise ValueError("time must be ISO8601 (e.g. 2025-10-01T15:00:00Z)")

def extract_hourly(response, var_list):
    """Return (times_iso_list, {varname: values_list})"""
    hourly = response.Hourly()
    start = datetime.utcfromtimestamp(hourly.Time()).replace(tzinfo=timezone.utc)
    end = datetime.utcfromtimestamp(hourly.TimeEnd()).replace(tzinfo=timezone.utc)
    step = timedelta(seconds=hourly.Interval())

    # Build time axis
    times = []
    t = start
    while t < end:
        times.append(t.isoformat() + "Z")
        t += step

    out = {}
    for idx, var in enumerate(var_list):
        try:
            out[var] = hourly.Variables(idx).ValuesAsNumpy().tolist()
        except Exception:
            out[var] = None

    return times, out


# ---------- Cloud Function ----------
@functions_framework.http
def get_point_data(request):
    try:
        payload = request.get_json(silent=True)
        if not payload:
            payload = request.form or request.args

        lat = float(payload.get("lat"))
        lon = float(payload.get("lon"))
        if not is_in_na(lat, lon):
            return jsonify({"error": "Coordinates outside North America (lat 5..85, lon -170..-50)"}), 400

        time_str = payload.get("time")  # optional ISO string
        hours = int(payload.get("hours", 1))
        hours = max(1, min(hours, MAX_HOURS))

        if time_str:
            dt = parse_iso_time(time_str)
        else:
            dt = datetime.utcnow().replace(tzinfo=timezone.utc)

        start = dt.strftime("%Y-%m-%dT%H:%M")
        end_dt = dt + timedelta(hours=hours)
        end = end_dt.strftime("%Y-%m-%dT%H:%M")

        # Air quality call
        aq_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        aq_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": AQ_VARS,
            "start": start,
            "end": end,
            "timezone": "UTC"
        }
        aq_resp = openmeteo.weather_api(aq_url, params=aq_params)[0]

        # Weather call
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": WEATHER_VARS,
            "start": start,
            "end": end,
            "timezone": "UTC"
        }
        weather_resp = openmeteo.weather_api(weather_url, params=weather_params)[0]

        times_aq, aq_data = extract_hourly(aq_resp, AQ_VARS)
        times_w, weather_data = extract_hourly(weather_resp, WEATHER_VARS)

        # prefer weather times if present (they should match), otherwise fallback
        times = times_w if times_w else times_aq

        result = {
            "status": "ok",
            "lat": lat,
            "lon": lon,
            "requested_start": start + "Z",
            "requested_end": end + "Z",
            "times": times,
            "pollution": aq_data,
            "weather": weather_data
        }
        return jsonify(result)

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": "internal_error", "details": str(e)}), 500
