"""
usb_extensions.py
核心逻辑扩展库：负责底层 PowerShell 查询、容量检测和文件操作
"""
import shutil
import os
import subprocess
import json
import re
from typing import List, Dict, Any


def get_disk_space(mount_point: str) -> dict:
    try:
        usage = shutil.disk_usage(mount_point)
        return {
            'total_gb': round(usage.total / (1024**3), 2),
            'free_gb': round(usage.free / (1024**3), 2),
            'percent': round((usage.used / usage.total) * 100, 1)
        }
    except Exception:
        return {'total_gb': 0, 'free_gb': 0, 'percent': 0}


def safe_eject_drive(drive_letter: str):
    clean_letter = drive_letter.replace("\\", "").replace(":", "") + ":"
   
    cmd = f"powershell -command \"(new-object -COM Shell.Application).NameSpace(17).ParseName('{clean_letter}').InvokeVerb('Eject')\""
    subprocess.run(cmd, shell=True)


def get_enhanced_usb_list(only_storage: bool = True) -> List[Dict[str, Any]]:
 
    ps_script = r"""
$ErrorActionPreference = 'Stop';
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;
$pnp = Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -like 'USB*' };
$res = @();
foreach ($d in $pnp) {
    $bcd = 'Unknown';
    
    if ($d.Name -match 'USB 3.') { $bcd = '3.0' }
    elseif ($d.Name -match 'USB 2.') { $bcd = '2.0' }
    elseif ($d.Name -match 'xHCI') { $bcd = '3.x' }
    elseif ($d.Name -match 'EHCI') { $bcd = '2.0' }
    elseif ($d.Name -match 'Hub') { $bcd = 'Hub' }
    
    
    $split = $d.PNPDeviceID.Split('\')
    $bus_sim = if ($split.Count -gt 1) { $split[1] } else { "System" }
    $addr_sim = if ($split.Count -gt 2) { $split[$split.Count - 1] } else { "0" }

    $res += [PSCustomObject]@{
        Name = $d.Name; Manufacturer = $d.Manufacturer;
        PNPDeviceID = $d.PNPDeviceID; Service = $d.Service;
        bcdUSB = $bcd; Address = $addr_sim; Bus = $bus_sim
    }
}
$res | ConvertTo-Json -Depth 2
"""
    try:
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        
        output_str = p.stdout.strip()
        if not output_str: return []
        
        data = json.loads(output_str)
        if isinstance(data, dict): data = [data]
        
        results = []
        for d in data:
            svc = (d.get("Service") or "").upper()
            if only_storage and svc != "USBSTOR": continue
            
            pnp = d.get("PNPDeviceID", "")
            
            vp_match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", pnp, re.IGNORECASE)
            
            results.append({
                "vendor_id": f"0x{vp_match.group(1).lower()}" if vp_match else None,
                "product_id": f"0x{vp_match.group(2).lower()}" if vp_match else None,
                "manufacturer": d.get("Manufacturer"),
                "product": d.get("Name"),
                "serial_number": pnp.split("\\")[-1],
                "usb_version_bcd": d.get("bcdUSB"),
                "bus": d.get("Bus"),               
                "address": d.get("Address"),       
                "pnp_device_id": pnp
            })
        return results
    except Exception:
        return []