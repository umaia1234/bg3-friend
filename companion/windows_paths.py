"""Read the user's folder without inheriting an MSIX launcher's private folder."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import uuid


def _known_folder(identifier: str) -> str:
    # NO_PACKAGE_REDIRECTION returns the normal user path.
    # https://learn.microsoft.com/windows/win32/api/shlobj_core/ne-shlobj_core-known_folder_flag
    folder_id = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(identifier).bytes_le)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoUninitialize.argtypes = []
    initialized = ole.CoInitializeEx(None, 0)
    pointer = ctypes.c_void_p()
    try:
        result = shell.SHGetKnownFolderPath(ctypes.byref(folder_id), 0x00014000, None, ctypes.byref(pointer))
        if result < 0 or not pointer.value:
            raise OSError("Windows 사용자 데이터 폴더를 확인하지 못했습니다.")
        return ctypes.wstring_at(pointer.value)
    finally:
        ole.CoTaskMemFree(pointer)
        if initialized >= 0:
            ole.CoUninitialize()


def local_appdata() -> Path:
    value = _known_folder("f1b32785-6fba-4fcf-9d55-7b8e7f157091") if os.name == "nt" else os.environ.get("LOCALAPPDATA", "")
    if not value or not Path(value).is_absolute():
        raise OSError("Windows 사용자 데이터 폴더를 확인하지 못했습니다.")
    return Path(value)


def user_state_dir() -> Path:
    # Saved Games is outside AppData write virtualization, including when the
    # launcher is an MSIX desktop app. Settings and rollback history stay shared.
    if os.name == "nt":
        value = _known_folder("4c5c32ff-bb9d-43b0-b5b4-2d72e54eaaa4")
        if not value or not Path(value).is_absolute():
            raise OSError("Windows 게임 데이터 폴더를 확인하지 못했습니다.")
        return Path(value) / "BG3Friend"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "bg3-friend"
