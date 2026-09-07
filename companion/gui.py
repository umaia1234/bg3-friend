"""Click-to-type party chat below BG3's minimap, with native Korean IME."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time
import uuid
import tkinter as tk
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from companion.game_window import GameWindow, enable_dpi_awareness
from companion.protocol import read_json, write_json

BG, GOLD, MUTED, TEXT = '#191c1a', '#cfb47c', '#9eab9e', '#f0eadc'

class FriendWindow:
    def __init__(self, folder, close_file=None, stop_file=None, preview=False):
        enable_dpi_awareness()
        self.folder, self.close_file, self.stop_file = folder, close_file, stop_file
        self.preview, self.game = preview, GameWindow()
        self.session, self.choice = None, None
        self.members, self.seen = {}, set()
        self.snapshot, self.intro_item, self.review_actor, self.connection_pending = {}, None, None, None
        self.intro_visible = False
        self.editing, self.placeholder, self.visible = False, True, False
        self.geometry, self.last_message, self.scale = None, 0, 0
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title('BG3 Friend · 파티 대화')
        self.root.overrideredirect(True)
        self.root.configure(bg=BG)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', .9)
        self.body_font = tkfont.Font(family='Malgun Gothic', size=-17)
        self.small_font = tkfont.Font(family='Malgun Gothic', size=-14)
        self.name_font = tkfont.Font(family='Malgun Gothic', size=-17, weight='bold')
        self.frame = tk.Frame(self.root, bg=BG, padx=14, pady=8)
        self.frame.pack(fill='both', expand=True)
        head = tk.Frame(self.frame, bg=BG)
        head.pack(fill='x')
        self.dot = tk.Label(head, text='●', bg=BG, fg=MUTED, font=self.small_font)
        self.dot.pack(side='left', padx=(0, 6))
        self.heading = tk.Label(head, text='파티', bg=BG, fg=GOLD, font=self.small_font)
        self.heading.pack(side='left')
        self.hint = tk.Label(head, text='', bg=BG, fg=MUTED, font=self.small_font)
        self.hint.pack(side='left', padx=10)
        self.menu_button = tk.Label(head, text='···', bg=BG, fg=GOLD, cursor='hand2', font=self.name_font)
        self.menu_button.pack(side='right')
        self.menu_button.bind('<Button-1>', self.menu)
        self.heading.bind('<Button-1>', self.menu)
        tk.Frame(self.frame, bg='#776442', height=1).pack(fill='x', pady=(6, 5))
        self.chat = tk.Text(self.frame, height=5, bg=BG, fg=TEXT, wrap='word', font=self.body_font,
                            borderwidth=0, highlightthickness=0, cursor='arrow', spacing1=4, spacing3=7,
                            selectbackground='#514833', takefocus=False)
        self.chat.pack(fill='both', expand=True)
        self.chat.tag_configure('user_name', foreground='#aec3d0', font=self.name_font)
        self.chat.tag_configure('friend_name', foreground=GOLD, font=self.name_font)
        self.chat.configure(state='disabled')
        self.intro_card = tk.Frame(self.frame, bg='#272c26', padx=10, pady=8)
        self.intro_title = tk.Label(self.intro_card, bg='#272c26', fg=GOLD, font=self.name_font, anchor='w')
        self.intro_title.pack(fill='x')
        self.intro_body = tk.Label(self.intro_card, bg='#272c26', fg=TEXT, font=self.small_font,
                                   anchor='w', justify='left', wraplength=305)
        self.intro_body.pack(fill='x', pady=(4, 7))
        buttons = tk.Frame(self.intro_card, bg='#272c26')
        buttons.pack(fill='x')
        self.intro_yes = tk.Button(buttons, text='함께하기', command=lambda: self.choose_introduction('friend'),
                                   bg=GOLD, fg='#191c1a', activebackground='#e0cba0', relief='flat',
                                   font=self.small_font, cursor='hand2', takefocus=False)
        self.intro_yes.pack(side='left', fill='x', expand=True, padx=(0, 5))
        self.intro_no = tk.Button(buttons, text='직접 할게', command=lambda: self.choose_introduction('manual'),
                                  bg='#40463c', fg=TEXT, activebackground='#565b4b', relief='flat',
                                  font=self.small_font, cursor='hand2', takefocus=False)
        self.intro_no.pack(side='left', fill='x', expand=True)
        self.entry_frame = tk.Frame(self.frame, bg='#30352f', highlightthickness=1, highlightbackground='#665b41')
        self.entry_frame.pack(fill='x', pady=(6, 0))
        self.entry = tk.Entry(self.entry_frame, bg='#30352f', fg=MUTED, insertbackground=TEXT,
                              font=self.body_font, relief='flat', borderwidth=0)
        self.entry.pack(side='left', fill='x', expand=True, padx=9, ipady=7)
        self.entry.insert(0, '클릭해서 말 걸기…')
        self.enter = tk.Label(self.entry_frame, text='↵', bg='#30352f', fg=GOLD,
                              font=self.body_font, cursor='hand2', padx=8)
        self.enter.pack(side='right')
        self.enter.bind('<Button-1>', self.send)
        self.entry.bind('<FocusIn>', self.begin_typing)
        self.entry.bind('<Button-1>', self.begin_typing)
        self.entry.bind('<Return>', self.send)
        self.root.bind('<Escape>', self.leave_typing)
        self.root.bind('<FocusOut>', lambda _: self.root.after(100, self.check_focus))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll()

    def control(self):
        return read_json(self.folder / 'control.json') or {}

    def is_enabled(self, control):
        return bool(self.session and control.get('session') == self.session and control.get('enabled') is True)

    def set_enabled(self, enabled):
        old = self.control()
        if not self.session or (enabled and not self.choice):
            return
        write_json(self.folder / 'control.json', old | {'session': self.session, 'enabled': enabled,
                   'companion': self.choice or old.get('companion', ''), 'auto_combat': old.get('auto_combat', True),
                   'revision': old.get('revision', 0) + 1})

    def assign(self, actor, remember=True):
        if remember and self.connection_pending:
            return
        self.choice = actor
        self.set_enabled(True)
        if remember:
            self.request_choice(actor, 'friend', False)
        self.game.focus()

    def request_choice(self, actor, choice, activate):
        intro = getattr(self, 'snapshot', {}).get('introductions') or {}
        if getattr(self, 'connection_pending', None) or actor not in {c['id'] for c in intro.get('candidates', [])}:
            return False
        request = {'id': uuid.uuid4().hex, 'session': self.session, 'actor': actor,
                   'choice': choice, 'activate': activate, 'control_revision': self.control().get('revision', 0)}
        write_json(self.folder / 'connection-request.json', request)
        self.connection_pending = request
        return True

    def choose_introduction(self, mode):
        # Re-read the live observation at the click boundary; a stale card cannot grant control.
        latest = read_json(self.folder / 'snapshot.json') or {}
        intro = latest.get('introductions') or {}
        try:
            fresh = time.time() - (self.folder / 'snapshot.json').stat().st_mtime < 4
        except OSError:
            fresh = False
        actor = (self.intro_item or {}).get('id')
        if not fresh or latest.get('session') != self.session or not intro.get('ready') or self.connection_pending:
            return
        if actor not in {c['id'] for c in intro.get('candidates', [])}:
            return
        self.snapshot = latest
        if mode == 'manual' and self.control().get('companion') == actor:
            self.set_enabled(False)
        self.request_choice(actor, mode, mode == 'friend')
        self.game.focus()

    def review_introduction(self, actor):
        self.review_actor = actor
        self.editing = False
        self.game.focus()

    def waiting_introduction(self, control):
        intro = getattr(self, 'snapshot', {}).get('introductions') or {}
        deferred = intro.get('deferred') or {}
        if deferred.get('session') == self.session and deferred.get('revision') == control.get('revision', 0):
            return next((c for c in intro.get('candidates', []) if c['id'] == deferred.get('actor')), None)
        return None

    def sync_introductions(self, snapshot, control):
        intro = snapshot.get('introductions') or {}
        result = intro.get('result') or {}
        if self.connection_pending and result.get('id') == self.connection_pending['id']:
            self.review_actor = self.connection_pending['actor'] if result.get('status') == 'rejected' else None
            self.connection_pending = None
        try:
            fresh = time.time() - (self.folder / 'snapshot.json').stat().st_mtime < 4
        except OSError:
            fresh = False
        quiet = fresh and intro.get('ready') and not self.editing
        candidates = intro.get('candidates') or []
        deferred = intro.get('deferred') or {}
        eligible = {c['id'] for c in candidates if c.get('in_party') and c['id'] in self.members}
        if quiet and deferred.get('session') == self.session and deferred.get('revision') == control.get('revision', 0):
            if deferred.get('actor') in eligible:
                self.assign(deferred['actor'], remember=False)
        choices = intro.get('choices') or {}
        pending_actor = (self.connection_pending or {}).get('actor')
        available = [c for c in candidates if c['id'] not in choices or c['id'] in (self.review_actor, pending_actor)]
        preferred = self.review_actor or (self.intro_item or {}).get('id')
        item = next((c for c in available if c['id'] == preferred), available[0] if available else None) if quiet else None
        self.intro_item = item
        if item:
            self.intro_title.configure(text=item['name'] + ', 함께할까?')
            detail = 'Codex에 연결해 대화와 행동을 맡겨.' if item.get('in_party') else '파티에 합류하면 Codex로 함께해.'
            if self.is_enabled(control) and control.get('companion') != item['id']:
                detail += '\n지금 함께하는 ' + self.members.get(control.get('companion'), '동료') + ' 대신 맡게 돼.'
            self.intro_body.configure(text=detail)
            status = 'disabled' if self.connection_pending else 'normal'
            self.intro_yes.configure(state=status)
            self.intro_no.configure(state=status)
            if not self.intro_visible:
                self.intro_card.pack(fill='x', before=self.chat, pady=(0, 7))
        elif self.intro_visible:
            self.intro_card.pack_forget()
        self.intro_visible = item is not None

    def menu(self, event):
        control = self.control()
        active = self.is_enabled(control)
        waiting = self.waiting_introduction(control) if not active else None
        menu = tk.Menu(self.root, tearoff=False, bg=BG, fg=TEXT, activebackground='#494534',
                       activeforeground=TEXT, font=self.small_font, borderwidth=0)
        for actor, name in self.members.items():
            menu.add_command(label=('✓  ' if actor == self.choice else '    ') + name,
                             command=lambda actor=actor: self.assign(actor),
                             state='disabled' if self.connection_pending else 'normal')
        candidates = (self.snapshot.get('introductions') or {}).get('candidates') or []
        if candidates:
            review = tk.Menu(menu, tearoff=False, bg=BG, fg=TEXT, font=self.small_font)
            for candidate in candidates:
                review.add_command(label=candidate['name'], command=lambda a=candidate['id']: self.review_introduction(a))
            menu.add_cascade(label='연결 선택 바꾸기', menu=review,
                             state='disabled' if self.connection_pending else 'normal')
        menu.add_separator()
        menu.add_command(label='합류 기다리기 취소' if waiting else ('잠깐 쉬기' if active else '다시 함께하기'),
                         command=lambda: self.set_enabled(False if waiting else not active))
        menu.add_command(label=('✓  ' if control.get('auto_combat', True) else '    ') + '전투도 맡기기',
                         command=self.toggle_combat)
        menu.add_separator()
        menu.add_command(label='대화 종료', command=self.close)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def toggle_combat(self):
        old = self.control()
        write_json(self.folder / 'control.json', old | {'auto_combat': not old.get('auto_combat', True),
                   'revision': old.get('revision', 0) + 1})
        self.game.focus()

    def begin_typing(self, _=None):
        if self.placeholder:
            self.entry.delete(0, 'end')
            self.placeholder = False
        self.editing = True
        self.entry.configure(fg=TEXT)
        self.entry_frame.configure(highlightbackground=GOLD)
        self.entry.focus_set()

    def check_focus(self):
        if self.root.focus_displayof() is None:
            self.editing = False
            self.restore_placeholder()

    def restore_placeholder(self):
        if not self.entry.get():
            self.placeholder = True
            self.entry.insert(0, '클릭해서 말 걸기…')
            self.entry.configure(fg=MUTED)
        self.entry_frame.configure(highlightbackground='#665b41')

    def leave_typing(self, _=None):
        self.editing = False
        self.root.focus_set()
        self.restore_placeholder()
        self.game.focus()
        return 'break'

    def send(self, _=None):
        text = '' if self.placeholder else self.entry.get().strip()
        if not text or not self.session or not self.choice:
            return 'break'
        if not self.is_enabled(self.control()):
            self.set_enabled(True)
        self.request_choice(self.choice, 'friend', False)
        write_json(self.folder / 'inbox' / (str(time.time_ns()) + '.json'),
                   {'session': self.session, 'actor': self.choice, 'text': text[:1000]})
        self.entry.delete(0, 'end')
        self.leave_typing()
        return 'break'

    def layout(self, rect):
        x, y, width, height = rect
        scale = max(.7, min(2.5, height / 1080))
        w, h = round(346 * scale), round((207 + (110 if self.intro_visible else 0)) * scale)
        gx, gy = x + width - w - round(23 * scale), y + round(height * .354)
        geometry = f'{w}x{h}{gx:+d}{gy:+d}'
        if geometry != self.geometry:
            self.root.geometry(geometry)
            self.geometry = geometry
        if scale != self.scale:
            self.scale = scale
            self.body_font.configure(size=-round(14 * scale))
            self.name_font.configure(size=-round(14 * scale))
            self.small_font.configure(size=-round(11 * scale))
            self.intro_body.configure(wraplength=round(305 * scale))

    def poll(self):
        if self.close_file and self.close_file.exists():
            self.close_file.unlink(missing_ok=True)
            self.close(False)
            return
        snapshot = read_json(self.folder / 'snapshot.json') or {}
        runner = read_json(self.folder / 'runner.json') or {}
        control = self.control()
        if snapshot.get('session') != self.session:
            self.session = snapshot.get('session')
            self.seen.clear()
            self.chat.configure(state='normal')
            self.chat.delete('1.0', 'end')
            self.chat.configure(state='disabled')
            self.entry.delete(0, 'end')
            self.restore_placeholder()
            self.intro_item, self.review_actor, self.connection_pending = None, None, None
        self.snapshot = snapshot
        self.members = {m['id']: m['name'] for m in snapshot.get('party', [])
                        if m['id'] != snapshot.get('player', {}).get('id') and m['id'] not in snapshot.get('avatars', {})}
        if control.get('companion') in self.members:
            self.choice = control['companion']
        elif self.choice not in self.members:
            self.choice = next(iter(self.members), None)
        self.sync_introductions(snapshot, control)
        active = self.is_enabled(control)
        connected = time.time() - runner.get('updated', 0) < 8 and runner.get('runner') not in ('stopped', 'error')
        waiting = self.waiting_introduction(control) if not active else None
        self.heading.configure(text='파티  ·  ' + (waiting['name'] if waiting else self.members.get(self.choice, '동료')))
        self.dot.configure(fg='#96bb8a' if active and connected else MUTED)
        hint = ''
        if not connected:
            hint = '연결 끊김'
        elif runner.get('error'):
            hint = '응답 연결 확인'
        elif waiting:
            hint = '합류 기다리는 중'
        elif not active:
            hint = '쉬는 중'
        elif runner.get('runner') == 'thinking':
            hint = '···'
        self.hint.configure(text=hint)
        conversation = read_json(self.folder / 'conversation.json') or {}
        if conversation.get('session') == self.session:
            for event in conversation.get('events', []):
                event_id = event.get('id')
                if not event_id or event_id in self.seen:
                    continue
                self.seen.add(event_id)
                role = event.get('role')
                if role not in ('friend', 'user'):
                    continue
                name = '나' if role == 'user' else event.get('speaker', self.members.get(self.choice, '동료'))
                self.chat.configure(state='normal')
                self.chat.insert('end', name + '  ', role + '_name')
                self.chat.insert('end', event['text'] + '\n')
                self.chat.configure(state='disabled')
                self.chat.see('end')
                self.last_message = time.monotonic()
        rect = (0, 0, 1440, 900) if self.preview else self.game.rect()
        show = rect and (self.preview or self.game.is_foreground())
        try:
            show = show and (self.preview or time.time() - (self.folder / 'snapshot.json').stat().st_mtime < 4)
        except OSError:
            show = False
        if show:
            self.layout(rect)
            if not self.visible:
                self.root.deiconify()
                self.root.update_idletasks()
                self.game.decorate(self.root)
                self.visible = True
            self.root.attributes('-alpha', .96 if self.editing else (.88 if time.monotonic()-self.last_message < 20 else .72))
        elif self.visible:
            self.root.withdraw()
            self.visible = False
            self.editing = False
        self.root.after(200, self.poll)

    def close(self, notify_runner=True):
        self.set_enabled(False)
        if notify_runner and self.stop_file:
            write_json(self.stop_file, {'stop': True})
        self.root.destroy()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--io', type=Path, required=True)
    parser.add_argument('--close-file', type=Path)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    FriendWindow(args.io, args.close_file, args.stop_file, args.preview).root.mainloop()
