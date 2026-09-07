"""Windows HUD attachment; never injects game input."""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import os

class GameWindow:
    def __init__(self):
        self.handle = self.pid = None
        self.user = c.WinDLL('user32', use_last_error=True) if os.name == 'nt' else None
        if not self.user:
            return
        u = self.user
        self.callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        u.EnumWindows.argtypes = [self.callback_type, w.LPARAM]
        u.GetForegroundWindow.restype = w.HWND
        u.GetAncestor.argtypes = [w.HWND, w.UINT]
        u.GetAncestor.restype = w.HWND
        u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
        u.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]
        u.IsIconic.argtypes = u.IsWindow.argtypes = u.IsWindowVisible.argtypes = [w.HWND]
        u.SetForegroundWindow.argtypes = [w.HWND]
        u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
        u.SetWindowTextW.argtypes = [w.HWND, w.LPCWSTR]
        u.SetWindowTextW.restype = w.BOOL
        u.GetWindowLongPtrW.argtypes = [w.HWND, c.c_int]
        u.GetWindowLongPtrW.restype = c.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [w.HWND, c.c_int, c.c_ssize_t]
        u.SetWindowLongPtrW.restype = c.c_ssize_t
        u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]

    def process(self, handle):
        pid = w.DWORD()
        self.user.GetWindowThreadProcessId(handle, c.byref(pid))
        return pid.value

    def find(self):
        if not self.user:
            return False
        if self.handle and self.user.IsWindow(self.handle):
            return True
        self.handle = None
        @self.callback_type
        def visit(handle, _):
            title = c.create_unicode_buffer(512)
            self.user.GetWindowTextW(handle, title, len(title))
            if title.value.startswith("Baldur's Gate 3 (") and self.user.IsWindowVisible(handle):
                self.handle, self.pid = handle, self.process(handle)
                return False
            return True
        self.user.EnumWindows(visit, 0)
        return bool(self.handle)

    def rect(self):
        if not self.find() or self.user.IsIconic(self.handle):
            return None
        rect, origin = w.RECT(), w.POINT()
        if not self.user.GetClientRect(self.handle, c.byref(rect)):
            return None
        self.user.ClientToScreen(self.handle, c.byref(origin))
        return origin.x, origin.y, rect.right, rect.bottom

    def is_foreground(self, include_overlay=True):
        if not self.find():
            return False
        pid = self.process(self.user.GetForegroundWindow())
        return pid == self.pid or (include_overlay and pid == os.getpid())

    def focus(self):
        if self.find():
            self.user.SetForegroundWindow(self.handle)

    def decorate(self, widget):
        if not self.user:
            return
        handle = self.user.GetAncestor(widget.winfo_id(), 2)
        # Tk's override-redirect wrapper has no native caption. Keep the HUD
        # borderless, but expose its real title and an ordinary application
        # window so accessibility tools can select the chat independently.
        self.user.SetWindowTextW(handle, widget.title())
        style = self.user.GetWindowLongPtrW(handle, -20)
        self.user.SetWindowLongPtrW(handle, -20, (style | 0x40000) & ~0x80)
        self.user.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x33)


def enable_dpi_awareness():
    if os.name == 'nt':
        try:
            c.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            c.windll.user32.SetProcessDPIAware()
