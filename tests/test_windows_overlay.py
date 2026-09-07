"""Exercise the actual Tk/Win32 window that desktop clients need to select."""
import ctypes
import os

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows native window discovery")
def test_borderless_chat_is_a_named_enumerable_window_after_reshow(tmp_path):
    from companion.gui import FriendWindow

    chat = FriendWindow(tmp_path, preview=True)
    try:
        for _ in range(2):
            chat.root.update()
            titles = []

            @chat.game.callback_type
            def observe(handle, _):
                if chat.game.process(handle) == os.getpid() and chat.game.user.IsWindowVisible(handle):
                    title = ctypes.create_unicode_buffer(256)
                    chat.game.user.GetWindowTextW(handle, title, len(title))
                    if title.value == chat.root.title():
                        titles.append(title.value)
                        style = chat.game.user.GetWindowLongPtrW(handle, -20)
                        titles.append(bool(style & 0x40000) and not bool(style & 0x80))
                return True

            chat.game.user.EnumWindows(observe, 0)
            assert titles == ["BG3 Friend · 파티 대화", True]
            assert chat.root.overrideredirect()
            chat.root.withdraw()
            chat.root.deiconify()
            chat.root.update_idletasks()
            chat.game.decorate(chat.root)
    finally:
        chat.root.destroy()
