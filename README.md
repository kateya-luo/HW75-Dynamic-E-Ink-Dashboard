# HW75 Dynamic E-Ink Dashboard
<img width="1467" height="1216" alt="截图_20260612172243" src="https://github.com/user-attachments/assets/4f5492e6-9261-42b6-b379-4e09a900f484" />

## 功能简述
为 HW75 Dynamic 扩展模块制作的双屏信息看板：电子墨水屏负责完整信息展示，OLED 负责三档位置指示，力反馈旋钮则像实体拨钮一样在三个页面之间切换。

<img width="1365" height="749" alt="截图_20260612172333" src="https://github.com/user-attachments/assets/ccb150c6-7551-41fa-a320-f57ba49f80e6" />


## 效果演示


https://github.com/user-attachments/assets/2adea623-e592-4e62-a7af-a70b38c2f355


## 功能亮点

- 三档力反馈页面选择器：顺时针 `55° / 100° / 145°`
- OLED、电子墨水屏和电机档位绝对同步，快速切换也不会累计错位
- OLED 息屏时保持当前页面和电机位置，旋钮与按键仍可直接操作
- 天气时钟：时间、日期、天气、温度、湿度和风力
- 三日天气预报：天气类型、最高/最低温度和降雨概率
- 电脑状态：CPU 占用、真实 CPU 温度、内存和网络
- LibreHardwareMonitor 集成读取 `CPU Package` 温度
- FOCUS 专注计时与力反馈调节
- 惯性滚轮模式，可作为鼠标滚轮使用
- Windows 客户端自动连接、断网静默重试、恢复联网后自动刷新
- 客户端支持托盘运行和登录自启动

## 页面与档位

| 电机位置 | OLED 图标 | 电子墨水屏页面 |
| --- | --- | --- |
| 顺时针 55° | 天气 | 三日天气预报 `2/3` |
| 顺时针 100° | 时钟 | 天气时钟 `1/3` |
| 顺时针 145° | 电脑 | 电脑状态 `3/3` |

从滚轮模式切回 INFO 时，会回到天气时钟和 100° 中间档。OLED 自动息屏不会改变当前档位。

## 快速使用

1. 在 [Releases](./release) 中选择与硬件版本对应的 A 或 B 固件。
2. 将 `.uf2` 文件刷入 HW75。
3. 运行 `release/client/HW75-Dashboard.exe`。
4. 在客户端设置中填写高德 Web 服务 Key、城市和 Adcode
  高德天气API（免费）： https://lbs.amap.com/api/webservice/guide/api-advanced/weatherinfo
<img width="1789" height="848" alt="截图_20260612160508" src="https://github.com/user-attachments/assets/04a194ad-273e-4de0-9999-9e233c56c345" />


首次启用 CPU 温度采集时，Windows 会请求一次管理员权限，用于安装温度采集计划任务。之后登录 Windows 即可静默运行。

## 项目结构

- `firmware/config`：HW75 固件业务代码、设备树、界面和通信协议
- `host`：Windows 客户端及 CPU 温度服务源码
- `tools`：界面预览与字体生成工具
- `release`：可直接使用的客户端和 A/B 固件
- `build.ps1`：完整构建入口
- `build-firmware-fast.ps1`：A/B 固件增量构建入口

## 本地构建

固件基于 Zephyr 3.2.0 与 ZMK。仓库不包含体积较大的 Zephyr、ZMK、HAL 和本地工具链，需要按构建脚本中的目录结构准备依赖。

```powershell
powershell -ExecutionPolicy Bypass -File .\build-firmware-fast.ps1
```

客户端需要 Python 3.11：

```powershell
python -m pip install -r .\host\requirements.txt
pyinstaller --clean --noconfirm .\host\HW75信息看板-FOCUS天气版.spec
```

温度服务使用 .NET 构建，并通过 LibreHardwareMonitorLib 读取传感器。

## 配置与隐私

高德 Key 保存在 `%LOCALAPPDATA%\HW75Dashboard\config.json`，不会写入项目目录。请勿将个人 Key、Token 或本机配置提交到 GitHub。

## License

项目自有代码采用 MIT License。Zephyr、ZMK、LibreHardwareMonitor 及其他第三方依赖遵循各自许可证。
感谢各位大佬
ZMK大佬的优化 https://github.com/xingrz/zmk-config_helloword_hw-75

稚晖君大佬的开源 https://github.com/peng-zhihui/HelloWord-Keyboard

不知名大佬的电脑状态代码 https://github.com/oshi/oshi/issues/2695
