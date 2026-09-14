"""Weather forecasts fetched from Python using Open-Meteo."""

import json
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .config import load_config, save_config


CONDITIONS = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 53: "moderate drizzle",
    55: "dense drizzle", 56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers", 95: "thunderstorm",
    96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}
PERIODS = {"day": (0, 24), "morning": (6, 12), "afternoon": (12, 18),
           "evening": (18, 24), "night": (0, 6)}


def set_weather_location(location: str) -> str:
    """Save the user's explicitly chosen default weather city, preferably with country."""
    from .brain import geocode_city

    try:
        if not location.strip():
            return "Error: specify a city and country"
        place = geocode_city(location)
        if place is None:
            return f"Error: location not found: {location}"
        config = load_config()
        config["weather_location"] = location.strip()
        save_config(config)
        return json.dumps({"saved_location": location.strip(), "resolved_location": place["name"]}, ensure_ascii=False)
    except Exception as error:
        return f"Error saving weather location: {error}"


def get_weather(location: str = "", days_ahead: int = 0,
                period: Literal["day", "morning", "afternoon", "evening", "night"] = "day") -> str:
    """Get forecast for a city and local day (0=today, 1=tomorrow, up to 15).

    Empty location uses weather_location from user config. Morning is 06–12,
    afternoon 12–18, evening 18–24, night 00–06, in the destination timezone.
    Returns hourly conditions, period temperatures and separately daily extremes.
    Requires Internet; no API key or additional Python package is needed.
    """
    from .brain import geocode_city, request_json

    try:
        if type(days_ahead) is not int or not 0 <= days_ahead <= 15:
            return "Error: days_ahead must be an integer from 0 to 15"
        if period not in PERIODS:
            return "Error: unknown forecast period"
        city = location.strip() or load_config().get("weather_location", "")
        if not city:
            return "Location required: ask the user which city; do not infer it from the PC timezone"
        place = geocode_city(city)
        if place is None:
            return f"Error: location not found: {city}"
        url = "https://api.open-meteo.com/v1/forecast?" + urlencode({
            "latitude": place["latitude"], "longitude": place["longitude"],
            "timezone": "auto", "temperature_unit": "celsius", "forecast_days": 16,
            "hourly": "temperature_2m,weather_code,precipitation_probability",
            "daily": "temperature_2m_min,temperature_2m_max",
        })
        data = request_json(url)
        if data.get("error"):
            return f"Weather API error: {data.get('reason', 'unknown error')}"
        target = (datetime.now(ZoneInfo(data["timezone"])) + timedelta(days=days_ahead)).date().isoformat()
        start, end = PERIODS[period]
        hourly = data["hourly"]
        hours = []
        for index, stamp in enumerate(hourly["time"]):
            if stamp[:10] != target or not start <= int(stamp[11:13]) < end:
                continue
            temperature = hourly["temperature_2m"][index]
            code = hourly["weather_code"][index]
            if temperature is None or code is None:
                continue
            hours.append({"time": stamp, "temperature_c": temperature,
                          "condition": CONDITIONS.get(code, "unknown"),
                          "precipitation_probability_percent": hourly["precipitation_probability"][index]})
        if not hours:
            return f"No forecast available for {place['name']} on {target} ({period})"
        daily = data["daily"]
        index = daily["time"].index(target)
        return json.dumps({
            "location": place["name"], "date": target, "timezone": data["timezone"],
            "period": period, "local_hours": f"{start:02}:00–{end:02}:00 (end exclusive)",
            "period_min_c": min(hour["temperature_c"] for hour in hours),
            "period_max_c": max(hour["temperature_c"] for hour in hours),
            "daily_min_c": daily["temperature_2m_min"][index],
            "daily_max_c": daily["temperature_2m_max"][index],
            "complete_period": len(hours) == end - start,
            "hourly": hours, "source": "Open-Meteo", "source_url": "https://open-meteo.com/",
        }, ensure_ascii=False)
    except Exception as error:
        return f"Error fetching weather forecast: {error}"
