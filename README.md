# USB 总线与挂载设备测试 GUI (Windows 版)

本项目为 **北京理工大学《汇编语言与接口技术》大作业 - 实验二** 的实现方案。基于 Python 语言和 Tkinter 框架开发，旨在通过 GUI 界面直观地展示 USB 总线的属性、设备挂载机制、热插拔检测以及文件交互功能。

## 🚀 主要功能

- **用户信息识别**：自动显示当前系统登录的用户名。
- **深度设备检测**：
    - 扫描系统中所有连接的 USB 设备。
    - 提取关键信息：VID (Vendor ID)、PID (Product ID)、制造商、产品名称、序列号、挂载总线编号 (Bus Number) 及 端口地址 (Address)。
    - **USB 版本探测**：通过解析 `pnputil` 属性，识别设备支持的 USB 版本（如 3.0/2.1/2.0）。
- **实时热插拔监听**：
    - 基于 WMI 事件驱动机制，实时捕获 U 盘的插入与拔出动作。
    - 自动刷新盘符列表及设备信息。
- **文件系统交互**：
    - **文件列表浏览**：支持查看 U 盘内所有文件，可选显示系统隐藏文件。
    - **数据写入**：支持向 U 盘指定路径写入测试文本。
    - **文件删除**：支持删除 U 盘中的文件或文件夹。
    - **带进度的文件拷贝**：支持从本地向 U 盘传输大文件，并提供**实时传输速率 (MB/s)**、**进度条百分比**及**预计剩余时间**显示。

## 🛠️ 技术栈

- **开发语言**：Python 3.x
- **GUI 框架**：Tkinter / ttk
- **底层驱动接口**：
    - **WMI (Windows Management Instrumentation)**：用于监听 `Win32_VolumeChangeEvent` 及查询 `Win32_PnPEntity`。
    - **pnputil (系统工具)**：用于获取 WMI 无法直接提供的 Bus/Address 等硬件拓扑属性。
    - **pywin32**：处理 Windows COM 对象的生命周期。
- **多线程模型**：UI 线程、WMI 监控线程、后台文件 IO 线程分工协作，确保拷贝大文件时界面不卡死。

## 📂 文件结构

```text
.
├── app.py              # 程序主入口，负责 GUI 布局与逻辑调度
├── usb_info.py         # 硬件信息采集模块（WMI + pnputil 解析）
├── storage_monitor.py  # U 盘插拔监控模块（WMI 事件监听）
├── file_ops.py         # 文件操作封装模块（包含带回调的拷贝逻辑）
└── README.md           # 项目说明文档
```

## ⚙️ 环境配置与运行

### 1. 依赖安装
本项目依赖 `pywin32` 库以调用 Windows API。
```bash
pip install pywin32
```

### 2. 运行程序
请确保在 **Windows 操作系统** 下运行，并建议以 **管理员权限** 运行（部分硬件拓扑信息的获取需要 `pnputil` 权限）。
```bash
python app.py
```

## 📝 核心实现原理说明

1.  **USB 属性关联**：标准的 WMI 查询无法直接给出 USB 版本。本项目通过 `pnputil /enum-devices` 获取硬件属性，利用正则表达式从设备描述中提取版本特征，并根据 `InstanceID` 将其与 `Win32_PnPEntity` 的基础信息进行关联。
2.  **异步 IO 进度**：在 `file_ops.py` 中实现了分块读取的拷贝函数，通过计算 `delta_bytes / delta_time` 获得瞬时速率，并利用 `app.after()` 机制将进度安全地推送到主 UI 线程进行渲染。

## ⚖️ 许可证

本项目仅用于北京理工大学课程实验教学，遵循 MIT 开源协议。
