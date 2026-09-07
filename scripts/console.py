"""Send a developer command to an already-running BG3 SE console on Windows.

Used only for local integration diagnostics. Model output never reaches this tool.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path


class KeyEvent(c.Structure):
    _fields_ = [("down", w.BOOL), ("repeat", w.WORD), ("key", w.WORD),
                ("scan", w.WORD), ("char", w.WCHAR), ("state", w.DWORD)]


class EventUnion(c.Union):
    _fields_ = [("key", KeyEvent), ("padding", c.c_byte * 16)]


class InputRecord(c.Structure):
    _fields_ = [("type", w.WORD), ("event", EventUnion)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    k = c.WinDLL("kernel32", use_last_error=True)
    k.FreeConsole()
    if not k.AttachConsole(args.pid):
        raise c.WinError(c.get_last_error())
    k.CreateFileW.argtypes = [w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    handle = k.CreateFileW("CONIN$",0xC0000000,3,None,3,0,None)
    if handle == w.HANDLE(-1).value:
        raise c.WinError(c.get_last_error())
    k.WriteConsoleInputW.argtypes = [w.HANDLE,c.POINTER(InputRecord),w.DWORD,c.POINTER(w.DWORD)]
    text = ("\r" if args.activate else "") + args.file.read_text(encoding="utf-8").strip().replace("\n", "\r") + "\r"
    records = (InputRecord * (len(text)*2))()
    for index, char in enumerate(text):
        for offset, down in [(0, True),(1, False)]:
            record = records[index*2+offset]
            record.type = 1
            record.event.key = KeyEvent(down,1,13 if char == "\r" else 0,0,char,0)
    written = w.DWORD()
    if not k.WriteConsoleInputW(handle,records,len(records),c.byref(written)):
        raise c.WinError(c.get_last_error())
    k.CloseHandle.argtypes=[w.HANDLE]
    k.CloseHandle(handle)
    k.FreeConsole()


if __name__ == "__main__":
    main()
