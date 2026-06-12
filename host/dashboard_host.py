#!/usr/bin/env python3
"""HelloWord HW-75 Dynamic dashboard host."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import requests
import hid

WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NETWORK_CACHE_SECONDS = 300
TEMPERATURE_CACHE_SECONDS = 30
TEMPERATURE_DATA_MAX_AGE_SECONDS = 30

ACTION_VERSION = 1
ACTION_UPDATE_CLOCK_WEATHER = 12
ACTION_UPDATE_PC_STATUS = 13
ACTION_REFRESH_CURRENT_PAGE = 14
ACTION_UPDATE_WEATHER_FORECAST = 15

HW75_USB_VID = 0x1D50
HW75_USB_PID = 0x615E
HW75_USB_USAGE_PAGE = 0xFF14
HID_REPORT_ID = 1
HID_REPORT_SIZE = 64
HID_CHUNK_SIZE = 62


def encode_varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def protobuf_varint(field: int, value: int) -> bytes:
    return encode_varint(field << 3) + encode_varint(value)


def protobuf_bytes(field: int, value: str | bytes) -> bytes:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return encode_varint((field << 3) | 2) + encode_varint(len(data)) + data


def display_text(value: object, max_bytes: int) -> str:
    text = str(value).encode("ascii", errors="replace")[:max_bytes]
    return text.decode("ascii")


def protobuf_message(action: int, payload_field: int, payload: bytes) -> bytes:
    envelope = protobuf_varint(1, action) + protobuf_bytes(payload_field, payload)
    return encode_varint(len(envelope)) + envelope


@dataclass
class Settings:
    serial_port: str
    baud_rate: int = 115200
    city: str = "杭州"
    city_adcode: str = "330106"
    amap_key: str = ""
    pc_refresh_seconds: int = 30
    weather_refresh_minutes: int = 20

    @classmethod
    def load(cls, path: Path) -> "Settings":
        settings = cls(**json.loads(path.read_text(encoding="utf-8")))
        settings.pc_refresh_seconds = max(30, settings.pc_refresh_seconds)
        return settings


class DashboardTransport:
    def __init__(self, port: str = "", baud_rate: int = 115200) -> None:
        del port, baud_rate
        matches = [
            item
            for item in hid.enumerate(HW75_USB_VID, HW75_USB_PID)
            if item.get("usage_page") == HW75_USB_USAGE_PAGE
        ]
        if not matches:
            raise RuntimeError(
                "没有找到 HW-75 Dynamic USB HID。请直接连接扩展模块 USB，并确认已烧录新版固件。"
            )
        self.device = hid.device()
        self.device.open_path(matches[0]["path"])
        self.device.set_nonblocking(0)
        self.lock = threading.Lock()

    def send(self, action: int, payload_field: int, payload: bytes = b"") -> None:
        with self.lock:
            message = protobuf_message(action, payload_field, payload)
            offset = 0
            while offset < len(message):
                chunk = message[offset : offset + HID_CHUNK_SIZE]
                report = (
                    bytes((HID_REPORT_ID, len(chunk)))
                    + chunk
                    + bytes(HID_REPORT_SIZE - 2 - len(chunk))
                )
                if self.device.write(report) != HID_REPORT_SIZE:
                    raise RuntimeError("HW-75 USB HID 写入不完整。")
                offset += len(chunk)
            if len(message) % HID_CHUNK_SIZE == 0:
                report = bytes((HID_REPORT_ID, 0)) + bytes(HID_REPORT_SIZE - 2)
                if self.device.write(report) != HID_REPORT_SIZE:
                    raise RuntimeError("HW-75 USB HID 结束帧写入失败。")

            response = bytearray()
            while True:
                report = bytes(self.device.read(HID_REPORT_SIZE, 2000))
                if len(report) != HID_REPORT_SIZE or report[0] != HID_REPORT_ID:
                    raise RuntimeError("扩展模块没有返回有效确认，请确认烧录的是新版固件。")
                chunk_len = report[1]
                response.extend(report[2 : 2 + chunk_len])
                if chunk_len < HID_CHUNK_SIZE:
                    break

            acknowledged_action, applied = decode_dashboard_response(bytes(response))
            if acknowledged_action != action:
                raise RuntimeError(
                    f"扩展模块确认 action={acknowledged_action}，预期 action={action}。"
                )
            if not applied:
                raise RuntimeError(
                    "扩展模块已连接，但当前固件不支持信息看板 USB 协议。请重新烧录本发布包中的固件。"
                )

    def close(self) -> None:
        self.device.close()


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        current = data[offset]
        offset += 1
        value |= (current & 0x7F) << shift
        if not current & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            break
    raise ValueError("无效的 protobuf varint。")


def decode_dashboard_response(response: bytes) -> tuple[int, bool]:
    message_len, offset = decode_varint(response)
    message = response[offset : offset + message_len]
    if len(message) != message_len:
        raise RuntimeError("扩展模块返回的 protobuf 长度不完整。")
    action = -1
    applied = False
    offset = 0
    while offset < len(message):
        key, offset = decode_varint(message, offset)
        field = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            value, offset = decode_varint(message, offset)
            if field == 1:
                action = value
        elif wire_type == 2:
            length, offset = decode_varint(message, offset)
            value = message[offset : offset + length]
            offset += length
            if field == 10:
                applied = value == b"\x08\x01"
        else:
            raise RuntimeError("扩展模块返回了不支持的 protobuf 字段。")
    if action < 0:
        raise RuntimeError("扩展模块返回包缺少 action 字段。")
    return action, applied


def send_clock_weather(
    transport: DashboardTransport,
    settings: Settings,
    weather: dict[str, object],
) -> None:
    transport.send(
        ACTION_UPDATE_CLOCK_WEATHER,
        10,
        encode_weather(settings, weather),
    )


def send_pc_status(transport: DashboardTransport) -> None:
    transport.send(ACTION_UPDATE_PC_STATUS, 11, encode_pc_status())


def send_refresh(transport: DashboardTransport) -> None:
    transport.send(ACTION_REFRESH_CURRENT_PAGE, 12)


def send_weather_forecast(
    transport: DashboardTransport, forecast: list[dict[str, object]]
) -> None:
    transport.send(
        ACTION_UPDATE_WEATHER_FORECAST,
        13,
        encode_weather_forecast(forecast),
    )


WEATHER_SUNNY = 0
WEATHER_PARTLY_CLOUDY = 1
WEATHER_CLOUDY = 2
WEATHER_OVERCAST = 3
WEATHER_WINDY = 4
WEATHER_FOG = 5
WEATHER_LIGHT_RAIN = 6
WEATHER_MODERATE_RAIN = 7
WEATHER_HEAVY_RAIN = 8
WEATHER_SHOWER = 9
WEATHER_THUNDERSTORM = 10
WEATHER_SLEET = 11
WEATHER_SNOW = 12
WEATHER_HEAVY_SNOW = 13
WEATHER_HAIL = 14
WEATHER_CLEAR_NIGHT = 15
WEATHER_CLOUDY_NIGHT = 16
WEATHER_SAND_DUST = 17

WEATHER_CODES = {
    0: ("SUNNY", WEATHER_SUNNY),
    1: ("SUNNY", WEATHER_SUNNY),
    2: ("PARTLY CLOUDY", WEATHER_PARTLY_CLOUDY),
    3: ("OVERCAST", WEATHER_OVERCAST),
    45: ("FOG", WEATHER_FOG),
    48: ("FOG", WEATHER_FOG),
    51: ("LIGHT RAIN", WEATHER_LIGHT_RAIN),
    53: ("RAIN", WEATHER_MODERATE_RAIN),
    55: ("HEAVY RAIN", WEATHER_HEAVY_RAIN),
    56: ("SLEET", WEATHER_SLEET),
    57: ("SLEET", WEATHER_SLEET),
    61: ("LIGHT RAIN", WEATHER_LIGHT_RAIN),
    63: ("RAIN", WEATHER_MODERATE_RAIN),
    65: ("HEAVY RAIN", WEATHER_HEAVY_RAIN),
    66: ("SLEET", WEATHER_SLEET),
    67: ("SLEET", WEATHER_SLEET),
    71: ("SNOW", WEATHER_SNOW),
    73: ("SNOW", WEATHER_SNOW),
    75: ("HEAVY SNOW", WEATHER_HEAVY_SNOW),
    77: ("HAIL", WEATHER_HAIL),
    80: ("SHOWER", WEATHER_SHOWER),
    81: ("SHOWER", WEATHER_SHOWER),
    82: ("HEAVY RAIN", WEATHER_HEAVY_RAIN),
    85: ("SNOW", WEATHER_SNOW),
    86: ("HEAVY SNOW", WEATHER_HEAVY_SNOW),
    95: ("THUNDER", WEATHER_THUNDERSTORM),
    96: ("THUNDER", WEATHER_THUNDERSTORM),
    99: ("THUNDER", WEATHER_THUNDERSTORM),
}


AMAP_WEATHER_TYPES = {
    "晴": ("SUNNY", WEATHER_SUNNY),
    "少云": ("SUNNY", WEATHER_SUNNY),
    "晴间多云": ("PARTLY CLOUDY", WEATHER_PARTLY_CLOUDY),
    "多云": ("CLOUDY", WEATHER_CLOUDY),
    "阴": ("OVERCAST", WEATHER_OVERCAST),
    "有风": ("WINDY", WEATHER_WINDY),
    "平静": ("SUNNY", WEATHER_SUNNY),
    "微风": ("WINDY", WEATHER_WINDY),
    "和风": ("WINDY", WEATHER_WINDY),
    "清风": ("WINDY", WEATHER_WINDY),
    "强风/劲风": ("WINDY", WEATHER_WINDY),
    "疾风": ("WINDY", WEATHER_WINDY),
    "大风": ("WINDY", WEATHER_WINDY),
    "烈风": ("WINDY", WEATHER_WINDY),
    "风暴": ("WINDY", WEATHER_WINDY),
    "狂爆风": ("WINDY", WEATHER_WINDY),
    "飓风": ("WINDY", WEATHER_WINDY),
    "热带风暴": ("WINDY", WEATHER_WINDY),
    "霾": ("FOG", WEATHER_FOG),
    "中度霾": ("FOG", WEATHER_FOG),
    "重度霾": ("FOG", WEATHER_FOG),
    "严重霾": ("FOG", WEATHER_FOG),
    "雾": ("FOG", WEATHER_FOG),
    "浓雾": ("FOG", WEATHER_FOG),
    "强浓雾": ("FOG", WEATHER_FOG),
    "轻雾": ("FOG", WEATHER_FOG),
    "大雾": ("FOG", WEATHER_FOG),
    "特强浓雾": ("FOG", WEATHER_FOG),
    "阵雨": ("SHOWER", WEATHER_SHOWER),
    "雷阵雨": ("THUNDER", WEATHER_THUNDERSTORM),
    "雷阵雨并伴有冰雹": ("HAIL", WEATHER_HAIL),
    "小雨": ("LIGHT RAIN", WEATHER_LIGHT_RAIN),
    "中雨": ("RAIN", WEATHER_MODERATE_RAIN),
    "大雨": ("HEAVY RAIN", WEATHER_HEAVY_RAIN),
    "暴雨": ("HEAVY RAIN", WEATHER_HEAVY_RAIN),
    "大暴雨": ("HEAVY RAIN", WEATHER_HEAVY_RAIN),
    "特大暴雨": ("HEAVY RAIN", WEATHER_HEAVY_RAIN),
    "雨夹雪": ("SLEET", WEATHER_SLEET),
    "阵雪": ("SNOW", WEATHER_SNOW),
    "小雪": ("SNOW", WEATHER_SNOW),
    "中雪": ("SNOW", WEATHER_SNOW),
    "大雪": ("HEAVY SNOW", WEATHER_HEAVY_SNOW),
    "暴雪": ("HEAVY SNOW", WEATHER_HEAVY_SNOW),
    "冰雹": ("HAIL", WEATHER_HAIL),
    "浮尘": ("SAND/DUST", WEATHER_SAND_DUST),
    "扬沙": ("SAND/DUST", WEATHER_SAND_DUST),
    "沙尘暴": ("SAND/DUST", WEATHER_SAND_DUST),
    "强沙尘暴": ("SAND/DUST", WEATHER_SAND_DUST),
}

AMAP_CITY_LABELS = {
    "110000": "BEIJING",
    "310000": "SHANGHAI",
    "330106": "HANGZHOU",
    "330100": "HANGZHOU",
    "440100": "GUANGZHOU",
    "440300": "SHENZHEN",
    "320100": "NANJING",
    "510100": "CHENGDU",
    "420100": "WUHAN",
    "500000": "CHONGQING",
    "120000": "TIANJIN",
}

AMAP_WIND_DIRECTIONS = {
    "无风向": "",
    "旋转不定": "VAR",
    "北": "N",
    "东北": "NE",
    "东": "E",
    "东南": "SE",
    "南": "S",
    "西南": "SW",
    "西": "W",
    "西北": "NW",
}


def display_city_name(settings: Settings, api_city: str) -> str:
    configured = display_text(settings.city, 31).replace("?", "").strip()
    if configured:
        return configured.upper()
    return AMAP_CITY_LABELS.get(settings.city_adcode, display_text(api_city, 31))


def map_amap_weather(description: str) -> tuple[str, int]:
    if description in AMAP_WEATHER_TYPES:
        return AMAP_WEATHER_TYPES[description]
    if "雨" in description:
        return "RAIN", WEATHER_MODERATE_RAIN
    if "雪" in description:
        return "SNOW", WEATHER_SNOW
    if "云" in description:
        return "CLOUDY", WEATHER_CLOUDY
    return "CLOUDY", WEATHER_CLOUDY


def fetch_weather(settings: Settings) -> dict[str, object]:
    if not settings.amap_key.strip():
        raise ValueError("请在设置中填写高德天气 API KEY。")
    if not settings.city_adcode.strip():
        raise ValueError("请在设置中填写城市 Adcode。")

    response = requests.get(
        "https://restapi.amap.com/v3/weather/weatherInfo",
        params={
            "city": settings.city_adcode,
            "key": settings.amap_key,
            "extensions": "base",
            "output": "JSON",
        },
        timeout=10,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    payload = response.json()
    if str(payload.get("status")) != "1":
        raise RuntimeError(payload.get("info") or "高德天气接口返回失败。")
    lives = payload.get("lives") or []
    if not lives:
        raise RuntimeError("高德天气接口没有返回实况数据。")

    current = lives[0]
    description = str(current.get("weather") or "--")
    weather_text, weather_type = map_amap_weather(description)
    wind_direction = AMAP_WIND_DIRECTIONS.get(
        str(current.get("winddirection") or ""), ""
    )
    wind_power = str(current.get("windpower") or "--").replace("≤", "")
    wind = f"{wind_direction}{wind_power}" if wind_direction else wind_power

    result = {
        "city": display_city_name(settings, str(current.get("city") or "")),
        "weather": weather_text,
        "weather_type": weather_type,
        "temperature": round(float(current.get("temperature") or 0)),
        "humidity": round(float(current.get("humidity") or 0)),
        "wind": wind,
    }

    forecast_response = requests.get(
        "https://restapi.amap.com/v3/weather/weatherInfo",
        params={
            "city": settings.city_adcode,
            "key": settings.amap_key,
            "extensions": "all",
            "output": "JSON",
        },
        timeout=10,
    )
    forecast_response.raise_for_status()
    forecast_response.encoding = "utf-8"
    forecast_payload = forecast_response.json()
    forecasts = forecast_payload.get("forecasts") or []
    casts = forecasts[0].get("casts", []) if forecasts else []
    result["forecast"] = [encode_amap_forecast_day(item) for item in casts[:3]]
    return result


def rain_probability(weather_type: int) -> int:
    if weather_type in (WEATHER_HEAVY_RAIN, WEATHER_THUNDERSTORM):
        return 80
    if weather_type in (WEATHER_MODERATE_RAIN, WEATHER_SHOWER, WEATHER_SLEET):
        return 60
    if weather_type in (WEATHER_LIGHT_RAIN, WEATHER_SNOW, WEATHER_HEAVY_SNOW):
        return 40
    if weather_type in (WEATHER_CLOUDY, WEATHER_OVERCAST):
        return 20
    return 10


def encode_amap_forecast_day(item: dict[str, object]) -> dict[str, object]:
    date_text = str(item.get("date") or "")
    description = str(item.get("dayweather") or item.get("nightweather") or "--")
    weather_text, weather_type = map_amap_weather(description)
    try:
        weekday = dt.datetime.strptime(date_text, "%Y-%m-%d").strftime("%a").upper()
    except ValueError:
        weekday = "---"
    return {
        "weekday": weekday,
        "date": date_text[5:].replace("-", "/") if len(date_text) >= 10 else "--/--",
        "weather": weather_text,
        "weather_type": weather_type,
        "high": round(float(item.get("daytemp") or 0)),
        "low": round(float(item.get("nighttemp") or 0)),
        "rain_percent": rain_probability(weather_type),
    }


_network_cache = ("UNKNOWN", 0.0)
_temperature_cache = (0, 0.0)
_cache_lock = threading.Lock()


def current_network_name() -> str:
    global _network_cache
    if platform.system() != "Windows":
        return "UNKNOWN"

    now = time.monotonic()
    with _cache_lock:
        if now - _network_cache[1] < NETWORK_CACHE_SECONDS:
            return _network_cache[0]

    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )
        match = re.search(r"^\s*SSID\s*:\s*(.+)$", result.stdout, re.MULTILINE)
        value = match.group(1).strip() if match else "WIRED/OFFLINE"
    except (OSError, subprocess.SubprocessError):
        value = "UNKNOWN"

    with _cache_lock:
        _network_cache = (value, now)
    return value


def cpu_temperature() -> int:
    global _temperature_cache
    now = time.monotonic()
    with _cache_lock:
        if now - _temperature_cache[1] < TEMPERATURE_CACHE_SECONDS:
            return _temperature_cache[0]

    if platform.system() != "Windows":
        temperatures = psutil.sensors_temperatures()
        values = [item.current for entries in temperatures.values() for item in entries]
        value = round(max(values)) if values else 0
        with _cache_lock:
            _temperature_cache = (value, now)
        return value

    value = 0
    data_path = (
        Path(os.environ.get("LOCALAPPDATA", Path.home()))
        / "HW75Dashboard"
        / "cpu-temperature.json"
    )
    try:
        reading = json.loads(data_path.read_text(encoding="utf-8"))
        temperature = float(reading.get("temperature", 0))
        updated_at = float(reading.get("updated_at", 0))
        if 1 <= temperature <= 125 and time.time() - updated_at <= TEMPERATURE_DATA_MAX_AGE_SECONDS:
            value = round(temperature)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    if value:
        with _cache_lock:
            _temperature_cache = (value, now)
        return value

    try:
        import wmi

        for namespace in (r"root\LibreHardwareMonitor", r"root\OpenHardwareMonitor"):
            try:
                connection = wmi.WMI(namespace=namespace)
                values = []
                for sensor in connection.Sensor():
                    if str(sensor.SensorType).lower() != "temperature":
                        continue
                    name = str(sensor.Name).lower()
                    identifier = str(getattr(sensor, "Identifier", "")).lower()
                    if (
                        "cpu" in name
                        or "core max" in name
                        or identifier.startswith("/intelcpu/")
                        or identifier.startswith("/amdcpu/")
                    ):
                        current = float(sensor.Value)
                        if 1 <= current <= 125:
                            values.append(current)
                if values:
                    value = round(max(values))
                    break
            except Exception:
                continue
    except ImportError:
        pass

    with _cache_lock:
        _temperature_cache = (value, now)
    return value


def encode_weather(settings: Settings, cached_weather: dict[str, object]) -> bytes:
    now = dt.datetime.now()
    return b"".join(
        [
            protobuf_bytes(1, display_text(cached_weather["city"], 31)),
            protobuf_bytes(2, display_text(cached_weather["weather"], 31)),
            protobuf_varint(3, int(cached_weather["temperature"])),
            protobuf_varint(4, int(cached_weather["humidity"])),
            protobuf_bytes(5, display_text(cached_weather["wind"], 31)),
            protobuf_bytes(6, now.strftime("%m/%d")),
            protobuf_bytes(7, now.strftime("%a").upper()),
            protobuf_bytes(8, now.strftime("%H:%M")),
            protobuf_varint(
                9, int(cached_weather.get("weather_type", WEATHER_CLOUDY))
            ),
        ]
    )


def encode_pc_status() -> bytes:
    memory = psutil.virtual_memory()
    used_memory = max(0, memory.total - memory.available)
    return b"".join(
        [
            protobuf_varint(1, round(psutil.cpu_percent(interval=None))),
            protobuf_varint(2, cpu_temperature()),
            protobuf_varint(3, round(used_memory / 1024 / 1024)),
            protobuf_varint(4, round(memory.total / 1024 / 1024)),
            protobuf_bytes(5, display_text(current_network_name(), 63)),
        ]
    )


def encode_weather_forecast(forecast: list[dict[str, object]]) -> bytes:
    payload = bytearray()
    for day in forecast[:3]:
        encoded_day = b"".join(
            [
                protobuf_bytes(1, display_text(day["weekday"], 7)),
                protobuf_bytes(2, display_text(day["date"], 7)),
                protobuf_bytes(3, display_text(day["weather"], 19)),
                protobuf_varint(4, int(day["weather_type"])),
                protobuf_varint(5, int(day["high"])),
                protobuf_varint(6, int(day["low"])),
                protobuf_varint(7, int(day["rain_percent"])),
            ]
        )
        payload.extend(protobuf_bytes(1, encoded_day))
    return bytes(payload)


def run(settings: Settings, once: bool) -> None:
    transport = DashboardTransport(settings.serial_port, settings.baud_rate)
    cached_weather: dict[str, object] = {
        "city": settings.city,
        "weather": "UNAVAILABLE",
        "weather_type": WEATHER_CLOUDY,
        "temperature": 0,
        "humidity": 0,
        "wind": "--",
    }
    next_weather_fetch = next_clock_send = next_pc_send = 0.0
    forecast_dirty = False

    try:
        while True:
            now = time.monotonic()
            if now >= next_weather_fetch:
                try:
                    cached_weather = fetch_weather(settings)
                    forecast_dirty = True
                except requests.RequestException as error:
                    print(f"weather update failed: {error}")
                next_weather_fetch = now + settings.weather_refresh_minutes * 60

            if now >= next_clock_send:
                send_clock_weather(transport, settings, cached_weather)
                if forecast_dirty:
                    send_weather_forecast(transport, cached_weather.get("forecast", []))
                    forecast_dirty = False
                seconds_to_next_minute = 60.0 - (time.time() % 60.0)
                next_clock_send = time.monotonic() + seconds_to_next_minute + 0.1

            if now >= next_pc_send:
                send_pc_status(transport)
                next_pc_send = now + settings.pc_refresh_seconds

            if once:
                send_refresh(transport)
                return
            time.sleep(0.25)
    finally:
        transport.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--port", help="Override serial_port from config")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings.load(args.config)
    if args.port:
        settings.serial_port = args.port
    run(settings, args.once)


if __name__ == "__main__":
    main()
