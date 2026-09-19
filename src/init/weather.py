#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Weather forecasts fetched from Python using Open-Meteo."""

from src.init.lang import tr
import json
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .config import load_config, save_config


CONDITIONS = {
    0: tr('weather.clear_sky'), 1: tr('weather.mainly_clear'), 2: tr('weather.partly_cloudy'), 3: "overcast",
    45: "fog", 48: tr('weather.rime_fog'), 51: tr('weather.light_drizzle'), 53: tr('weather.moderate_drizzle'),
    55: tr('weather.dense_drizzle'), 56: tr('weather.light_freezing_drizzle'), 57: tr('weather.dense_freezing_drizzle'),
    61: tr('weather.slight_rain'), 63: tr('weather.moderate_rain'), 65: tr('weather.heavy_rain'),
    66: tr('weather.light_freezing_rain'), 67: tr('weather.heavy_freezing_rain'),
    71: tr('weather.slight_snow'), 73: tr('weather.moderate_snow'), 75: tr('weather.heavy_snow'), 77: tr('weather.snow_grains'),
    80: tr('weather.slight_rain_showers'), 81: tr('weather.moderate_rain_showers'), 82: tr('weather.violent_rain_showers'),
    85: tr('weather.slight_snow_showers'), 86: tr('weather.heavy_snow_showers'), 95: "thunderstorm",
    96: tr('weather.thunderstorm_with_slight_hail'), 99: tr('weather.thunderstorm_with_heavy_hail'),
}
PERIODS = {"day": (0, 24), "morning": (6, 12), "afternoon": (12, 18),
           "evening": (18, 24), "night": (0, 6)}


def set_weather_location(location: str) -> str:
    """Save the user's explicitly chosen default weather city, preferably with country."""
    from .brain import geocode_city

    try:
        if not location.strip():
            return tr('weather.error_specify_a_city_and_country')
        place = geocode_city(location)
        if place is None:
            return tr('weather.error_location_not_found', location=location)
        config = load_config()
        config["weather_location"] = location.strip()
        save_config(config)
        return json.dumps({"saved_location": location.strip(), "resolved_location": place["name"]}, ensure_ascii=False)
    except Exception as error:
        return tr('weather.error_saving_weather_location', error=error)


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
            return tr('weather.error_days_ahead_must_be_an_integer_from_0_to_15')
        if period not in PERIODS:
            return tr('weather.error_unknown_forecast_period')
        city = location.strip() or load_config().get("weather_location", "")
        if not city:
            return tr('weather.location_required_ask_the_user_which_city_do_not_infer_it_from_t')
        place = geocode_city(city)
        if place is None:
            return tr('weather.error_location_not_found_33dcc9', city=city)
        url = "https://api.open-meteo.com/v1/forecast?" + urlencode({
            "latitude": place["latitude"], "longitude": place["longitude"],
            "timezone": "auto", "temperature_unit": "celsius", "forecast_days": 16,
            "hourly": "temperature_2m,weather_code,precipitation_probability",
            "daily": "temperature_2m_min,temperature_2m_max",
        })
        data = request_json(url)
        if data.get("error"):
            return tr('weather.weather_api_error', value0=data.get('reason', tr('weather.unknown_error')))
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
            return tr('weather.no_forecast_available_for_on', value0=place['name'], target=target, period=period)
        daily = data["daily"]
        index = daily["time"].index(target)
        return json.dumps({
            "location": place["name"], "date": target, "timezone": data["timezone"],
            "period": period, "local_hours": tr('weather.00_00_end_exclusive', start=start, end=end),
            "period_min_c": min(hour["temperature_c"] for hour in hours),
            "period_max_c": max(hour["temperature_c"] for hour in hours),
            "daily_min_c": daily["temperature_2m_min"][index],
            "daily_max_c": daily["temperature_2m_max"][index],
            "complete_period": len(hours) == end - start,
            "hourly": hours, "source": "Open-Meteo", "source_url": "https://open-meteo.com/",
        }, ensure_ascii=False)
    except Exception as error:
        return tr('weather.error_fetching_weather_forecast', error=error)
