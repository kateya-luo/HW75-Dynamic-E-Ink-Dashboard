#!/usr/bin/env python3
"""HelloWord HW-75 Dynamic compact dashboard client."""

from __future__ import annotations

import json
import os
import base64
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg
import ctypes
from pathlib import Path
from tkinter import messagebox, ttk

from dashboard_host import (
    DashboardTransport,
    Settings,
    fetch_weather,
    send_clock_weather,
    send_pc_status,
    send_refresh,
    send_weather_forecast,
)

import pystray
import requests
from PIL import Image, ImageDraw


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


LEGACY_CONFIG_PATH = app_dir() / "config.json"
CONFIG_PATH = (
    Path(os.environ.get("LOCALAPPDATA", app_dir()))
    / "HW75Dashboard"
    / "config.json"
)
KEY_PLACEHOLDERS = ("请填写", "Web服务KEY", "Web 服务 KEY")
TEMPERATURE_TASK_NAME = "HW75DashboardTemperatureService"


ERROR_ALREADY_EXISTS = 183
_single_instance_handle = None


def acquire_single_instance() -> bool:
    global _single_instance_handle
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_wchar_p,
    )
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.CreateMutexW(
        None, False, "Local\\HW75Dashboard.SingleInstance"
    )
    if not handle:
        return False
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _single_instance_handle = handle
    return True


def default_settings() -> Settings:
    return Settings(serial_port="")


def import_legacy_weather() -> dict[str, object]:
    candidates = [
        app_dir() / "e-ink-clock-settings.json",
        app_dir().parent / "e-ink-clock-settings.json",
        Path(r"C:\Users\LZ\Desktop\ElectronBotEInkClock_v1\e-ink-clock-settings.json"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            weather = json.loads(path.read_text(encoding="utf-8")).get("Weather", {})
            return {
                "city": weather.get("CityName", "杭州"),
                "city_adcode": str(weather.get("CityAdcode", "330106")),
                "amap_key": weather.get("AmapKey", ""),
                "weather_refresh_minutes": int(weather.get("UpdateMinutes", 20)),
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return {}


class DashboardClient:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("HW-75 信息看板")
        self.root.geometry("460x315")
        self.root.resizable(False, False)

        self.transport: DashboardTransport | None = None
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.settings = self._load_settings()
        self._save_settings()
        self.tray_icon: pystray.Icon | None = None
        self.exiting = False

        self.device_status = tk.StringVar(value="未连接")
        self.sync_status = tk.StringVar(value="未启动")
        self.weather_status = tk.StringVar(value="等待同步")
        self.pc_status = tk.StringVar(value="等待同步")

        self._build_ui()
        if "--startup" in sys.argv:
            self.root.withdraw()
        self._register_startup()
        self._ensure_temperature_service()
        self._create_tray_icon()
        self.root.after(500, self._poll_messages)
        self.root.after(1000, self._connect_silently)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(outer)
        header.pack(fill=tk.X)
        ttk.Label(header, text="HW-75 信息看板", style="Title.TLabel").pack(
            side=tk.LEFT
        )
        ttk.Button(header, text="设置", command=self._open_settings, width=8).pack(
            side=tk.RIGHT
        )

        ttk.Separator(outer).pack(fill=tk.X, pady=(12, 14))

        status = ttk.Frame(outer)
        status.pack(fill=tk.X)
        self._status_row(status, 0, "设备", self.device_status)
        self._status_row(status, 1, "同步", self.sync_status)
        self._status_row(status, 2, "天气", self.weather_status)
        self._status_row(status, 3, "电脑", self.pc_status)
        status.columnconfigure(1, weight=1)

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X, pady=(18, 8))
        self.connect_button = ttk.Button(
            controls, text="连接设备", command=self._toggle_connection
        )
        self.connect_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        self.auto_button = ttk.Button(
            controls,
            text="开始同步",
            command=self._toggle_auto,
            state=tk.DISABLED,
        )
        self.auto_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
        self.update_button = ttk.Button(
            controls,
            text="立即更新",
            command=self._update_now,
            state=tk.DISABLED,
        )
        self.update_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

        ttk.Label(
            outer,
            text="扩展模块通过 USB HID 直连，无需选择 COM 口或外接 USB-UART。",
            style="Hint.TLabel",
        ).pack(anchor=tk.W, pady=(8, 0))

    @staticmethod
    def _status_row(parent: ttk.Frame, row: int, name: str, value: tk.StringVar) -> None:
        ttk.Label(parent, text=name, width=8).grid(
            row=row, column=0, sticky=tk.W, pady=6
        )
        ttk.Label(parent, textvariable=value, style="Value.TLabel").grid(
            row=row, column=1, sticky=tk.W, pady=6
        )

    def _load_settings(self) -> Settings:
        base = default_settings().__dict__.copy()
        base.update(import_legacy_weather())
        config_path = CONFIG_PATH if CONFIG_PATH.exists() else LEGACY_CONFIG_PATH
        if config_path.exists():
            try:
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                saved_key = str(saved.get("amap_key", ""))
                if any(marker in saved_key for marker in KEY_PLACEHOLDERS):
                    saved.pop("amap_key", None)
                base.update(saved)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        allowed = Settings.__dataclass_fields__.keys()
        filtered = {key: base[key] for key in allowed if key in base}
        settings = Settings(**filtered)
        settings.pc_refresh_seconds = max(30, settings.pc_refresh_seconds)
        settings.weather_refresh_minutes = max(1, settings.weather_refresh_minutes)
        return settings

    def _save_settings(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(self.settings.__dict__, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _connect(self) -> None:
        self.transport = DashboardTransport()
        self.device_status.set("USB HID 已连接")
        self.connect_button.configure(text="断开设备")
        self.auto_button.configure(state=tk.NORMAL)
        self.update_button.configure(state=tk.NORMAL)
        self._toggle_auto()

    def _connect_silently(self) -> None:
        if self.exiting or self.transport is not None:
            return
        try:
            self._connect()
        except Exception:
            self.transport = None
            self.device_status.set("等待扩展模块")
            self.root.after(3000, self._connect_silently)

    def _open_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("信息看板设置")
        window.geometry("500x390")
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()

        frame = ttk.Frame(window, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        variables = {
            "city": tk.StringVar(value=self.settings.city),
            "city_adcode": tk.StringVar(value=self.settings.city_adcode),
            "amap_key": tk.StringVar(value=self.settings.amap_key),
            "pc_refresh_seconds": tk.StringVar(
                value=str(self.settings.pc_refresh_seconds)
            ),
            "weather_refresh_minutes": tk.StringVar(
                value=str(self.settings.weather_refresh_minutes)
            ),
        }

        fields = [
            ("城市显示名", "city"),
            ("高德城市 Adcode", "city_adcode"),
            ("高德天气 KEY", "amap_key"),
            ("电脑状态间隔（秒）", "pc_refresh_seconds"),
            ("天气间隔（分钟）", "weather_refresh_minutes"),
        ]

        for row, (label, name) in enumerate(fields):
            ttk.Label(frame, text=label).grid(
                row=row, column=0, sticky=tk.W, pady=6, padx=(0, 12)
            )
            entry = ttk.Entry(
                frame,
                textvariable=variables[name],
                show="*" if name == "amap_key" else "",
            )
            entry.grid(row=row, column=1, sticky=tk.EW, pady=6)

        frame.columnconfigure(1, weight=1)
        ttk.Label(
            frame,
            text="Adcode 示例：杭州西湖区 330106。KEY 使用高德 Web 服务类型。",
            style="Hint.TLabel",
        ).grid(row=len(fields), column=0, columnspan=2, sticky=tk.W, pady=(8, 14))

        buttons = ttk.Frame(frame)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=2, sticky=tk.E)

        def save() -> None:
            try:
                new_settings = Settings(
                    serial_port="",
                    baud_rate=115200,
                    city=variables["city"].get().strip(),
                    city_adcode=variables["city_adcode"].get().strip(),
                    amap_key=variables["amap_key"].get().strip(),
                    pc_refresh_seconds=max(
                        30, int(variables["pc_refresh_seconds"].get())
                    ),
                    weather_refresh_minutes=max(
                        1, int(variables["weather_refresh_minutes"].get())
                    ),
                )
                if not new_settings.amap_key or any(
                    marker in new_settings.amap_key for marker in KEY_PLACEHOLDERS
                ):
                    raise ValueError("请填写有效的高德 Web 服务 KEY。")
                self.settings = new_settings
                self._save_settings()
                window.destroy()
                self.weather_status.set(f"{new_settings.city} · 等待同步")
                if self.transport is not None:
                    self._disconnect(reconnect=True)
                    messagebox.showinfo("设置已保存", "连接参数已改变，请重新连接。")
            except Exception as error:
                messagebox.showerror("设置错误", str(error), parent=window)

        ttk.Button(buttons, text="取消", command=window.destroy).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(buttons, text="保存", command=save).pack(side=tk.LEFT, padx=5)

    def _toggle_connection(self) -> None:
        if self.transport is not None:
            self._disconnect()
            return
        try:
            self._connect()
            return
            self.transport = DashboardTransport()
            self.device_status.set("USB HID 已确认")
            self.connect_button.configure(text="断开设备")
            self.auto_button.configure(state=tk.NORMAL)
            self.update_button.configure(state=tk.NORMAL)
            self._toggle_auto()
        except Exception as error:
            self.transport = None
            messagebox.showerror("连接失败", str(error))

    def _disconnect(self, reconnect: bool = False) -> None:
        self.stop_event.set()
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        self.transport = None
        self.device_status.set("未连接")
        self.sync_status.set("未启动")
        self.connect_button.configure(text="连接设备")
        self.auto_button.configure(text="开始同步", state=tk.DISABLED)
        self.update_button.configure(state=tk.DISABLED)
        if reconnect and not self.exiting:
            self.root.after(3000, self._connect_silently)

    def _toggle_auto(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.auto_button.configure(text="开始同步")
            self.sync_status.set("正在停止")
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._auto_loop, daemon=True)
        self.worker.start()
        self.auto_button.configure(text="停止同步")
        self.sync_status.set("运行中")

    def _auto_loop(self) -> None:
        settings = self.settings
        next_weather_fetch = next_clock_send = next_pc_send = 0.0
        weather = None
        forecast_dirty = False
        while not self.stop_event.is_set():
            try:
                transport = self.transport
                if transport is None:
                    return
                now = time.monotonic()
                if weather is None or now >= next_weather_fetch:
                    try:
                        weather = fetch_weather(settings)
                        next_weather_fetch = (
                            now + settings.weather_refresh_minutes * 60
                        )
                        forecast_dirty = True
                        self.messages.put(("weather", weather))
                    except requests.RequestException:
                        next_weather_fetch = now + 10
                        self.messages.put(("network_wait", ""))
                    except Exception as error:
                        next_weather_fetch = now + 60
                        self.messages.put(("weather_error", str(error)))
                if weather is not None and now >= next_clock_send:
                    send_clock_weather(transport, settings, weather)
                    if forecast_dirty:
                        send_weather_forecast(transport, weather.get("forecast", []))
                        forecast_dirty = False
                    seconds_to_next_minute = 60.0 - (time.time() % 60.0)
                    next_clock_send = time.monotonic() + seconds_to_next_minute + 0.1
                if now >= next_pc_send:
                    send_pc_status(transport)
                    next_pc_send = now + settings.pc_refresh_seconds
                    self.messages.put(("pc", time.strftime("%H:%M:%S")))
            except Exception as error:
                self.messages.put(("device_lost", str(error)))
                return
            self.stop_event.wait(1.0)
        self.messages.put(("stopped", ""))

    def _update_now(self) -> None:
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self) -> None:
        try:
            transport = self.transport
            if transport is None:
                raise RuntimeError("设备尚未连接。")
            weather = fetch_weather(self.settings)
            send_clock_weather(transport, self.settings, weather)
            send_weather_forecast(transport, weather.get("forecast", []))
            send_pc_status(transport)
            send_refresh(transport)
            self.messages.put(("weather", weather))
            self.messages.put(("pc", time.strftime("%H:%M:%S")))
        except Exception as error:
            self.messages.put(("error", str(error)))

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, data = self.messages.get_nowait()
                if kind == "network_wait":
                    self.weather_status.set("等待网络")
                    continue
                if kind == "device_lost":
                    self._disconnect(reconnect=True)
                    continue
                if kind == "weather_error":
                    self.weather_status.set(str(data))
                    continue
                if kind == "weather":
                    weather = data
                    self.weather_status.set(
                        f"{self.settings.city} · {weather['weather']} "
                        f"{weather['temperature']}°C"
                    )
                elif kind == "pc":
                    self.pc_status.set(f"已更新 · {data}")
                elif kind == "error":
                    self.sync_status.set("已停止")
                    self.stop_event.set()
                    self.auto_button.configure(text="开始同步")
                    error_text = str(data)
                    if "INVALID_USER_KEY" in error_text:
                        error_text = (
                            "高德天气 KEY 无效。请打开“设置”，填写高德开放平台创建的"
                            " Web 服务 Key。"
                        )
                    messagebox.showerror("同步错误", error_text)
                elif kind == "stopped":
                    self.sync_status.set("未启动")
                    self.auto_button.configure(text="开始同步")
        except queue.Empty:
            pass
        self.root.after(500, self._poll_messages)

    def _on_close(self) -> None:
        if not self.exiting:
            self.root.withdraw()

    def _register_startup(self) -> None:
        if sys.platform != "win32":
            return
        if getattr(sys, "frozen", False):
            command = f'"{sys.executable}" --startup'
        else:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            command = f'"{pythonw}" "{Path(__file__).resolve()}" --startup'
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, "HW75Dashboard", 0, winreg.REG_SZ, command)
        except OSError:
            pass

    def _ensure_temperature_service(self) -> None:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return

        helper = app_dir() / "temperature-helper" / "HW75TemperatureService.exe"
        if not helper.exists():
            return

        query = subprocess.run(
            ["schtasks", "/Query", "/TN", TEMPERATURE_TASK_NAME, "/XML"],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if query.returncode == 0 and str(helper).casefold() in query.stdout.casefold():
            subprocess.run(
                ["schtasks", "/Run", "/TN", TEMPERATURE_TASK_NAME],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            return

        helper_path = str(helper).replace("'", "''")
        script = (
            f"Get-ScheduledTask -TaskName '{TEMPERATURE_TASK_NAME}' -ErrorAction SilentlyContinue | Stop-ScheduledTask;"
            f"$action=New-ScheduledTaskAction -Execute '{helper_path}';"
            "$trigger=New-ScheduledTaskTrigger -AtLogOn;"
            "$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
            "-ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew;"
            "$principal=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) "
            "-LogonType Interactive -RunLevel Highest;"
            f"Register-ScheduledTask -TaskName '{TEMPERATURE_TASK_NAME}' -Action $action -Trigger $trigger "
            "-Settings $settings -Principal $principal -Description 'HW75 CPU temperature reader' -Force | Out-Null;"
            f"Start-ScheduledTask -TaskName '{TEMPERATURE_TASK_NAME}'"
        )
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        parameters = f'-NoProfile -WindowStyle Hidden -EncodedCommand "{encoded}"'
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "powershell.exe", parameters, None, 0
        )

    def _create_tray_icon(self) -> None:
        image = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 5, 59, 59), radius=12, outline="black", width=5)
        draw.ellipse((20, 20, 44, 44), outline="black", width=5)
        menu = pystray.Menu(
            pystray.MenuItem(
                "显示窗口",
                lambda icon, item: self.root.after(0, self._show_window),
                default=True,
            ),
            pystray.MenuItem(
                "退出", lambda icon, item: self.root.after(0, self._exit_app)
            ),
        )
        self.tray_icon = pystray.Icon(
            "HW75Dashboard", image, "HW-75 信息看板", menu
        )
        self.tray_icon.run_detached()

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _exit_app(self) -> None:
        self.exiting = True
        self._disconnect()
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.root.destroy()


def main() -> None:
    if not acquire_single_instance():
        return
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.15)
    except tk.TclError:
        pass
    DashboardClient(root)
    root.mainloop()


if __name__ == "__main__":
    main()
