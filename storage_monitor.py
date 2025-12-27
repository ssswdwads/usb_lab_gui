from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

import pythoncom
import win32com.client


@dataclass(frozen=True)
class DriveEvent:
    action: str  # "inserted" | "removed"
    drive_letter: str  # e.g. "G:"


def get_removable_drives() -> list[str]:
    """
    WMI 查询当前可移动盘
    """
    pythoncom.CoInitialize()
    try:
        wmi = win32com.client.GetObject("winmgmts:")
        items = wmi.ExecQuery("SELECT DeviceID FROM Win32_LogicalDisk WHERE DriveType = 2")
        return [i.DeviceID for i in items]
    except Exception:
        return []
    finally:
        pythoncom.CoUninitialize()


class WmiDriveEventWatcher:
    """
    Win32_VolumeChangeEvent 监听器
    """

    def __init__(self, on_event: Callable[[DriveEvent], None]):
        self.on_event = on_event
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None

        self._service = None
        self._watcher = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="WmiDriveEventWatcher", daemon=True)
        self._thread.start()

    def stop(self, join_timeout_sec: float = 2.0) -> None:
        self._stop.set()

        if self._thread_id is not None:
            try:
                pythoncom.CoCancelCall(self._thread_id, 0)
            except Exception:
                pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout_sec)

        self._service = None
        self._watcher = None
        self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        pythoncom.CoInitialize()
        self._thread_id = threading.get_native_id()

        try:
            locator = win32com.client.DispatchEx("WbemScripting.SWbemLocator")
            service = locator.ConnectServer(".", "root\\cimv2")
            self._service = service

            query = "SELECT * FROM Win32_VolumeChangeEvent WHERE EventType = 2 OR EventType = 3"
            watcher = service.ExecNotificationQuery(query)
            self._watcher = watcher

            while not self._stop.is_set():
                try:
                    evt = watcher.NextEvent(1000)
                except Exception:
                    continue

                drive_name = getattr(evt, "DriveName", None)  # e.g. "G:\"
                if not drive_name or len(drive_name) < 2:
                    continue
                drive_letter = drive_name[:2]

                event_type = int(getattr(evt, "EventType", 0))
                if event_type == 2:
                    action = "inserted"
                elif event_type == 3:
                    action = "removed"
                else:
                    continue

                if action == "inserted":
                    try:
                        items = service.ExecQuery(
                            f"SELECT DriveType FROM Win32_LogicalDisk WHERE DeviceID='{drive_letter}'"
                        )
                        items = list(items)
                        if not items or int(items[0].DriveType) != 2:
                            continue
                    except Exception:
                        continue

                self.on_event(DriveEvent(action=action, drive_letter=drive_letter))

        finally:
            # 释放 COM 引用
            self._watcher = None
            self._service = None

            try:
                import gc
                gc.collect()
            except Exception:
                pass

            pythoncom.CoUninitialize()