from __future__ import annotations

import re
import subprocess
import time
import threading
from typing import Any, Dict, List, Optional
import pythoncom
import win32com.client

_VID_PID_RE = re.compile(r"VID_([0-9A-Fa-f]{4}).*PID_([0-9A-Fa-f]{4})")
_SERIAL_FROM_PNP_RE = re.compile(r"^USB\\[^\\]+\\([^\\]+)$", re.IGNORECASE)

# 缓存配置
_CACHE_TTL_SEC = 3.0
_cache_at = 0.0
_cache_only_storage: Optional[bool] = None
_cache_devices: List[Dict[str, Any]] = []

# 用于从描述中提取 USB 版本的正则
_USB_VER_EXTRACT_RE = re.compile(r"(3\.[0-2]|2\.0)", re.IGNORECASE)


def _run_pnputil_direct() -> str:
    """
    Directly run pnputil without PowerShell overhead.
    """
    try:
        # Use default system encoding (often mbcs/cp936 on Chinese Windows)
        p = subprocess.run(
            ["pnputil", "/enum-devices", "/connected", "/properties"],
            capture_output=True,
            text=True,
            errors="replace"
        )
        if p.returncode != 0:
            return ""
        return p.stdout or ""
    except Exception:
        return ""


def _get_wmi_usb_devices() -> List[Dict[str, Any]]:
    """
    Use COM (win32com) to query WMI, which is much faster than spawning PowerShell.
    """
    pythoncom.CoInitialize()
    try:
        wmi = win32com.client.GetObject("winmgmts:")
        # Query for all USB devices.
        # Note: PNPDeviceID LIKE 'USB%' covers standard USB devices.
        query = "SELECT Name, Manufacturer, PNPDeviceID, Service, Description FROM Win32_PnPEntity WHERE PNPDeviceID LIKE 'USB%'"
        items = wmi.ExecQuery(query)

        results = []
        for item in items:
            # WMI items might throw error on access if device disconnects during query
            try:
                res = {
                    "Name": item.Name,
                    "Manufacturer": item.Manufacturer,
                    "PNPDeviceID": item.PNPDeviceID,
                    "Service": item.Service,
                }
                results.append(res)
            except Exception:
                continue
        return results
    except Exception:
        return []
    finally:
        pythoncom.CoUninitialize()


def _norm_instance_id(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return s.strip().upper()


def _parse_vid_pid(pnp_device_id: Optional[str]) -> Dict[str, Optional[str]]:
    if not pnp_device_id:
        return {"vendor_id": None, "product_id": None}
    m = _VID_PID_RE.search(pnp_device_id)
    if not m:
        return {"vendor_id": None, "product_id": None}
    return {"vendor_id": f"0x{m.group(1).lower()}", "product_id": f"0x{m.group(2).lower()}"}


def _parse_serial(pnp_device_id: Optional[str]) -> Optional[str]:
    if not pnp_device_id:
        return None
    m = _SERIAL_FROM_PNP_RE.match(pnp_device_id)
    return m.group(1) if m else None


def _coerce_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s)
    except Exception:
        return None


def _extract_usb_version(text: str) -> Optional[str]:
    """从文本中提取版本号，如 '3.0'"""
    if not text:
        return None
    m = _USB_VER_EXTRACT_RE.search(text)
    return m.group(1) if m else None


def _get_pnputil_properties_map() -> Dict[str, Dict[str, Any]]:
    """
    解析 pnputil 输出，获取 Address, BusNumber 以及从描述中提取版本。
    """
    text = _run_pnputil_direct()
    if not text.strip():
        return {}

    idx: Dict[str, Dict[str, Any]] = {}

    # 匹配行
    re_inst_id = re.compile(r"^\s*(?:实例|Instance)\s*ID\s*:\s*(.+)", re.IGNORECASE)
    re_desc_line = re.compile(r"^\s*(?:设备描述|Device Description)\s*:\s*(.+)", re.IGNORECASE)

    # 属性名
    re_prop_addr = re.compile(r"DEVPKEY_Device_Address", re.IGNORECASE)
    re_prop_bus = re.compile(r"DEVPKEY_Device_BusNumber", re.IGNORECASE)
    re_prop_bus_desc = re.compile(r"DEVPKEY_Device_BusReportedDeviceDesc", re.IGNORECASE)

    re_hex_val = re.compile(r"(0x[0-9A-Fa-f]+)", re.IGNORECASE)
    re_dec_val = re.compile(r"\((\d+)\)", re.IGNORECASE)

    cur_id_norm: Optional[str] = None
    cur_data: Dict[str, Any] = {}
    expecting = None  # "addr", "bus", "bus_desc"

    lines = text.splitlines()
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # 1. 检查实例 ID
        m_id = re_inst_id.match(line_stripped)
        if m_id:
            if cur_id_norm:
                idx[cur_id_norm] = cur_data
            raw_id = m_id.group(1).strip()
            cur_id_norm = _norm_instance_id(raw_id)
            cur_data = {"address": None, "bus": None, "usb_version_bcd": None}
            expecting = None
            continue

        if not cur_id_norm:
            continue

        # 2. 检查基本的设备描述（这里通常就含有 USB 3.0 字样）
        m_desc = re_desc_line.match(line_stripped)
        if m_desc:
            ver = _extract_usb_version(m_desc.group(1))
            if ver: cur_data["usb_version_bcd"] = ver
            continue

        # 3. 处理属性值行
        if expecting:
            if expecting == "bus_desc":
                # 提取描述中的版本号
                ver = _extract_usb_version(line_stripped)
                if ver: cur_data["usb_version_bcd"] = ver
            else:
                # 数字类
                val = None
                m_hex = re_hex_val.search(line_stripped)
                if m_hex:
                    val = _coerce_int(m_hex.group(1))
                else:
                    m_dec = re_dec_val.search(line_stripped)
                    if m_dec:
                        val = _coerce_int(m_dec.group(1))
                if val is not None:
                    if expecting == "addr":
                        cur_data["address"] = val
                    elif expecting == "bus":
                        cur_data["bus"] = val
            expecting = None
            continue

        # 4. 识别属性名
        if re_prop_addr.search(line_stripped):
            expecting = "addr"
        elif re_prop_bus.search(line_stripped):
            expecting = "bus"
        elif re_prop_bus_desc.search(line_stripped):
            expecting = "bus_desc"

    if cur_id_norm:
        idx[cur_id_norm] = cur_data

    return idx


def list_usb_devices(only_storage: bool = True) -> List[Dict[str, Any]]:
    global _cache_at, _cache_only_storage, _cache_devices
    now = time.time()
    if _cache_only_storage == only_storage and (now - _cache_at) < _CACHE_TTL_SEC:
        return list(_cache_devices)

    # 1. Faster WMI Query
    rows = _get_wmi_usb_devices()

    # 2. Get detailed props from pnputil (this is the slower part, but optimized by removing PS wrapper)
    pnputil_map = {}
    try:
        pnputil_map = _get_pnputil_properties_map()
    except Exception:
        pass

    devices: List[Dict[str, Any]] = []
    for r in rows:
        service = (r.get("Service") or "").upper()
        if only_storage and service != "USBSTOR":
            continue

        name = r.get("Name")
        pnp = r.get("PNPDeviceID")
        norm_key = _norm_instance_id(pnp)

        vidpid = _parse_vid_pid(pnp)
        serial = _parse_serial(pnp)

        bus = None
        address = None
        usb_version_bcd = None

        if norm_key and norm_key in pnputil_map:
            info = pnputil_map[norm_key]
            address = info.get("address")
            bus = info.get("bus")
            usb_version_bcd = info.get("usb_version_bcd")

        # 如果 pnputil 没提取到版本，尝试从 WMI 的 Name 提取
        if not usb_version_bcd and name:
            usb_version_bcd = _extract_usb_version(name)

        devices.append(
            {
                "vendor_id": vidpid["vendor_id"],
                "product_id": vidpid["product_id"],
                "manufacturer": r.get("Manufacturer"),
                "product": name,
                "serial_number": serial,
                "usb_version_bcd": usb_version_bcd,  # 这里存放提取出的版本字符串
                "bus": bus,
                "address": address,
                "pnp_device_id": pnp,
                "service": r.get("Service"),
            }
        )

    _cache_at = now
    _cache_only_storage = only_storage
    _cache_devices = list(devices)
    return devices