"""Visible Windows setup and session control for the portable companion app."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import queue
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import webbrowser

from . import __version__
from .configuration import ConfigurationError, Settings, discover_settings, load_settings, save_settings, state_root
from .diagnostics import bundle_package, game_running, runtime_status, setup_checks, support_report
from .game_window import enable_dpi_awareness
from .installation import apply_plan, check_recovery, plan_install, plan_uninstall
from .lifecycle import request_stop, runner_claim_active, start_worker
from .protocol import read_json, write_json

BG, PANEL, GOLD, TEXT, MUTED, GREEN = "#121915", "#1b2520", "#dbc28e", "#f2eee4", "#a9b5ac", "#a5ceaa"


class DesktopApp:
    def __init__(self, config_root: Path | None = None, *, smoke: bool = False):
        enable_dpi_awareness()
        self.config_root = config_root or state_root()
        self.root = tk.Tk()
        self.root.title("BG3 Friend")
        self.root.configure(bg=BG)
        self.root.geometry(f"860x{min(870, self.root.winfo_screenheight() - 100)}")
        self.root.minsize(760, 620)
        self.root.option_add("*Font", ("Malgun Gothic", 10))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.queue = queue.Queue()
        self.busy, self.closing, self.worker = False, False, None
        self.worker_io, self.start_pending, self.start_generation = None, False, 0
        self.stop_pending = False
        self.checks, self.buttons = [], []
        self.invalid_settings = False
        try:
            settings = load_settings(self.config_root)
        except ConfigurationError:
            settings, self.invalid_settings = discover_settings(), True
        self.settings = settings
        self.fields = {key: tk.StringVar(value=getattr(settings, key)) for key in ("game", "profile", "codex", "model")}
        self.extender = tk.StringVar()
        self.consent = tk.BooleanVar(value=settings.consent)
        self.status = tk.StringVar(value="동료와 모험할 준비를 해 주세요")
        self.detail = tk.StringVar(value="설치와 로그인을 확인한 뒤 파티 대화를 연결합니다.")
        self.notice = tk.StringVar(value="기존 설정을 읽지 못했습니다. 저장하면 원본을 백업한 뒤 새 설정을 만듭니다." if self.invalid_settings else "")
        self.build_ui()
        self.root.after(150, self.poll)
        if not smoke:
            self.root.after(200, self.check)

    def label(self, parent, text, *, size=11, color=TEXT, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color,
                        font=("Malgun Gothic", size, "bold" if bold else "normal"), **kwargs)

    def button(self, parent, text, command, *, primary=False, track=True):
        button = tk.Button(parent, text=text, command=command, bg=GOLD if primary else "#2b3930",
                           fg=BG if primary else TEXT, activebackground="#e6d4ac" if primary else "#3b4c40",
                           activeforeground=BG if primary else TEXT, relief="flat", borderwidth=0,
                           padx=15, pady=9, cursor="hand2", disabledforeground="#768279")
        if track:
            self.buttons.append(button)
        return button

    def build_ui(self):
        page = tk.Frame(self.root, bg=BG, padx=30, pady=22)
        page.pack(fill="both", expand=True)
        header = tk.Frame(page, bg=BG)
        header.pack(fill="x")
        self.label(header, "BG3 FRIEND", size=12, color=GOLD, bold=True).pack(side="left")
        self.label(header, f"v{__version__}  ·  WINDOWS", size=9, color=MUTED).pack(side="right")
        self.label(page, "함께하는 모험, 가까운 대화.", size=23, bold=True, anchor="w").pack(fill="x", pady=(10, 4))
        self.label(page, "동료 한 명과 나누는 파티 대화 · 게임 속 선택은 직접 결정하세요.", size=10, color=MUTED, anchor="w").pack(fill="x")
        hero = tk.Frame(page, bg=PANEL, padx=18, pady=13)
        hero.pack(fill="x", pady=(18, 15))
        tk.Label(hero, textvariable=self.status, bg=PANEL, fg=GREEN,
                 font=("Malgun Gothic", 14, "bold"), anchor="w").pack(fill="x")
        tk.Label(hero, textvariable=self.detail, bg=PANEL, fg=MUTED, anchor="w", justify="left",
                 wraplength=750).pack(fill="x", pady=(5, 0))
        # Keep session actions visible on a small laptop; only setup fields scroll.
        footer = tk.Frame(page, bg=BG)
        footer.pack(fill="x", side="bottom", pady=(10, 0))
        scroll_area = tk.Frame(page, bg=BG)
        scroll_area.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_area, bg=BG, borderwidth=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        page = tk.Frame(canvas, bg=BG)
        content = canvas.create_window((0, 0), window=page, anchor="nw")
        page.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content, width=event.width))
        self.root.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units"))
        settings = tk.Frame(page, bg=BG)
        settings.pack(fill="x")
        settings.grid_columnconfigure(1, weight=1)
        labels = {"game": "게임 폴더", "profile": "게임 프로필", "codex": "Codex 실행 파일", "model": "모델"}
        for row, (key, variable) in enumerate(self.fields.items()):
            self.label(settings, labels[key], size=10, color=MUTED, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 14), pady=4)
            tk.Entry(settings, textvariable=variable, bg=PANEL, fg=TEXT, insertbackground=GOLD,
                     relief="flat", highlightthickness=1, highlightbackground="#354339", highlightcolor=GOLD,
                     width=48).grid(row=row, column=1, sticky="ew", ipady=6, pady=4)
            if key != "model":
                self.button(settings, "찾기", lambda k=key: self.browse(k)).grid(row=row, column=2, padx=(8, 0), pady=4)
        row = 4
        self.label(settings, "Extender DLL", size=10, color=MUTED, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 14), pady=4)
        tk.Entry(settings, textvariable=self.extender, bg=PANEL, fg=TEXT, insertbackground=GOLD, relief="flat",
                 highlightthickness=1, highlightbackground="#354339").grid(row=row, column=1, sticky="ew", ipady=6, pady=4)
        self.button(settings, "찾기", lambda: self.browse("extender")).grid(row=row, column=2, padx=(8, 0), pady=4)
        self.label(page, "Extender가 이미 설치되어 있으면 DLL을 다시 선택할 필요가 없습니다.", size=9, color=MUTED, anchor="w").pack(fill="x", pady=(2, 8))
        self.label(page, "선택한 동료·주변 상황·최근 대화를 로그인한 Codex로 보냅니다. 계정 사용량이 발생하며,\n대화 기록은 이 PC의 게임 프로필에 저장됩니다.", size=9, color=MUTED, justify="left", anchor="w").pack(fill="x")
        tk.Checkbutton(page, text="내용을 확인했으며 Codex 연결에 동의합니다.", variable=self.consent,
                       bg=BG, fg=TEXT, selectcolor=PANEL, activebackground=BG, activeforeground=TEXT,
                       anchor="w", padx=0, command=self.consent_changed).pack(fill="x", pady=(3, 9))
        actions = tk.Frame(page, bg=BG)
        actions.pack(fill="x")
        for label, action in (("자동 찾기", self.detect), ("설정 저장", self.save), ("상태 확인", self.check),
                              ("모드 설치·업데이트", self.install)):
            self.button(actions, label, action).pack(side="left", padx=(0, 7))
        self.check_text = tk.Text(page, height=3, bg=BG, fg=MUTED, relief="flat", wrap="word",
                                  font=("Malgun Gothic", 9), highlightthickness=0, state="disabled")
        self.check_text.pack(fill="x", pady=(10, 5))
        tk.Label(footer, textvariable=self.notice, bg=BG, fg=GOLD, anchor="w", justify="left", wraplength=780,
                 font=("Malgun Gothic", 9)).pack(fill="x", pady=(0, 8))
        session = tk.Frame(footer, bg=BG)
        session.pack(fill="x")
        self.start_button = self.button(session, "파티 대화 시작", self.start, primary=True)
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = self.button(session, "대화 중지", self.stop, track=False)
        self.stop_button.pack(side="left", padx=(0, 8))
        self.button(session, "게임 실행", self.launch_game).pack(side="left")
        self.button(session, "진단 저장", self.export_report).pack(side="right")
        links = tk.Frame(footer, bg=BG)
        links.pack(fill="x", pady=(10, 0))
        for text, command in (("사용 안내", lambda: webbrowser.open("https://github.com/umaia1234/bg3-friend#readme")),
                              ("Script Extender 받기", lambda: webbrowser.open("https://github.com/Norbyte/bg3se/releases")),
                              ("Codex 설치·로그인", lambda: webbrowser.open("https://developers.openai.com/codex/cli/")),
                              ("모드 제거", self.uninstall)):
            link = tk.Label(links, text=text, bg=BG, fg=MUTED, cursor="hand2", font=("Malgun Gothic", 9, "underline"))
            link.pack(side="left", padx=(0, 20))
            link.bind("<Button-1>", lambda event, c=command: c())

    def current(self) -> Settings:
        settings = Settings(**{key: variable.get().strip() for key, variable in self.fields.items()},
                            timeout=self.settings.timeout, consent=self.consent.get())
        settings.validate()
        return settings

    def browse(self, key):
        if key in ("game", "profile"):
            value = filedialog.askdirectory(parent=self.root, title="게임 설치 폴더" if key == "game" else "Baldur's Gate 3 프로필 폴더")
        else:
            value = filedialog.askopenfilename(parent=self.root, title="Script Extender의 DWrite.dll" if key == "extender" else "Codex 실행 파일",
                filetypes=[("실행 파일", "*.dll" if key == "extender" else "*.exe")])
        if value:
            (self.extender if key == "extender" else self.fields[key]).set(value)

    def detect(self):
        found = discover_settings()
        for key in ("game", "profile", "codex"):
            if getattr(found, key):
                self.fields[key].set(getattr(found, key))
        self.notice.set("찾은 경로를 표시했습니다. 확인 후 설정을 저장해 주세요.")

    def save(self, quiet=False):
        try:
            settings = self.current()
            active_folder = self.worker_io or (self.settings.io if self.settings.profile else None)
            active = (self.worker and self.worker.poll() is None) or (active_folder and runtime_status(active_folder)["running"])
            if active and settings != self.settings:
                raise ConfigurationError("실행 중에는 설정을 바꾸지 않습니다. 대화를 중지한 뒤 저장해 주세요.")
            if self.invalid_settings:
                original = self.config_root / "settings.json"
                if original.exists():
                    shutil.copy2(original, original.with_name(f"settings.invalid-{time.time_ns()}.json"))
                self.invalid_settings = False
            save_settings(settings, self.config_root)
            self.settings = settings
            if not quiet:
                self.notice.set("설정을 저장했습니다.")
            return settings
        except (ValueError, OSError) as exc:
            self.error(exc)
            return None

    def error(self, exc):
        self.notice.set(str(exc)[:350])

    def consent_changed(self):
        if self.consent.get():
            return
        try:
            self.stop()
        except (OSError, ValueError) as exc:
            self.error(exc)
        self.settings.consent = False
        try:
            save_settings(self.settings, self.config_root)
        except (OSError, ValueError) as exc:
            self.error(exc)
        else:
            self.notice.set("Codex 연결 동의를 해제했습니다. 진행 중인 대화와 응답을 중지합니다.")

    def job(self, operation, success):
        if self.busy or self.closing:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")

        def run():
            try:
                self.queue.put((success, operation(), None))
            except Exception as exc:
                self.queue.put((success, None, exc))

        # A normal window close must not tear down an installation transaction.
        try:
            threading.Thread(target=run, name="bg3-friend-setup", daemon=False).start()
        except Exception as exc:
            self.busy = False
            self.start_pending = False
            for button in self.buttons:
                button.configure(state="normal")
            self.error(exc)

    def show_checks(self, checks):
        self.checks = checks
        self.check_text.configure(state="normal")
        self.check_text.delete("1.0", "end")
        self.check_text.insert("end", "   ·   ".join(("✓ " if c.ok else "○ ") + c.detail for c in checks))
        self.check_text.configure(state="disabled")
        missing = [c.detail for c in checks if c.required and not c.ok]
        self.notice.set("확인이 필요합니다: " + ", ".join(missing) if missing else "설정 확인 완료. 게임에서 세이브를 불러온 뒤 맡길 동료를 선택해 주세요.")

    def check(self):
        try:
            settings = self.current()
        except ValueError as exc:
            return self.error(exc)
        self.job(lambda: self.checked_setup(settings), self.show_checks)

    def checked_setup(self, settings):
        check_recovery(self.config_root / "install")
        return setup_checks(settings)

    def installation_check(self):
        if (self.worker and self.worker.poll() is None) or (self.settings.profile and
                (runtime_status(self.settings.io)["running"] or runner_claim_active(self.settings.io))):
            raise ValueError("파티 대화를 먼저 중지해 주세요. 설치·제거는 게임과 대화를 종료한 뒤 진행합니다.")
        return game_running()

    def install(self):
        if self.busy:
            return
        settings = self.save(quiet=True)
        if settings is None:
            return
        extender = self.extender.get().strip()

        def plan():
            package, manifest = bundle_package()
            return plan_install(Path(settings.game), Path(settings.profile), package, self.config_root / "install",
                version=manifest["version"], package_sha256=manifest["package"]["sha256"],
                game_running=self.installation_check, extender=Path(extender) if extender else None)

        self.job(plan, self.review_plan)

    def uninstall(self):
        if not self.busy:
            self.job(lambda: plan_uninstall(self.config_root / "install", game_running=self.installation_check), self.review_plan)

    def review_plan(self, plan):
        if not plan.changed:
            self.notice.set("이미 이 버전으로 설치되어 있습니다. 변경할 파일이 없습니다.")
            return
        popup = tk.Toplevel(self.root)
        popup.title("모드 변경 확인")
        popup.configure(bg=BG)
        height = min(520, self.root.winfo_screenheight() - 100)
        x = max(0, self.root.winfo_rootx() + (self.root.winfo_width() - 740) // 2)
        y = max(0, self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2)
        popup.geometry(f"740x{height}+{x}+{y}")
        popup.minsize(620, 400)
        popup.transient(self.root)
        popup.grab_set()
        self.label(popup, "적용할 변경을 확인해 주세요", size=16, bold=True).pack(anchor="w", padx=24, pady=(20, 8))
        self.label(popup, "기존 파일은 백업합니다. 적용 중 실패하면 이번 변경을 되돌립니다.", size=10, color=MUTED).pack(anchor="w", padx=24)
        # Reserve the footer before allowing the change list to expand.
        buttons = tk.Frame(popup, bg=BG)
        buttons.pack(fill="x", side="bottom", padx=24, pady=(0, 20))
        body = tk.Frame(popup, bg=PANEL)
        body.pack(fill="both", expand=True, padx=24, pady=15)
        text = tk.Text(body, height=8, bg=PANEL, fg=TEXT, wrap="word", relief="flat", padx=12, pady=12)
        scrollbar = tk.Scrollbar(body, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        words = {"create": "새로 설치", "replace": "교체", "remove": "제거"}
        for change in plan.to_dict()["changes"]:
            text.insert("end", f"{words[change['operation']]} · {change['role']}\n{change['path']}\n\n")
        text.insert("end", f"백업·복구 기록\n{plan.state_root}\n\n게임 세이브는 변경하지 않습니다.")
        text.configure(state="disabled")

        def apply():
            popup.destroy()
            self.job(lambda: apply_plan(plan, game_running=self.installation_check),
                     lambda result: (self.notice.set("변경을 완료했습니다. 상태를 다시 확인해 주세요."), self.check()))

        self.button(buttons, "적용하기", apply, primary=True, track=False).pack(side="right")
        self.button(buttons, "취소", popup.destroy, track=False).pack(side="right", padx=10)

    def start(self):
        if self.busy or self.closing:
            return
        settings = self.save(quiet=True)
        if settings is None:
            return
        self.start_generation += 1
        generation = self.start_generation
        self.start_pending = True

        def ready(checks):
            self.start_pending = False
            if generation != self.start_generation or self.closing:
                return
            if self.current() != settings:
                self.notice.set("점검 중 설정이 바뀌었습니다. 현재 설정을 확인하고 다시 시작해 주세요.")
                return
            self.show_checks(checks)
            if any(not c.ok for c in checks if c.required):
                return
            if runtime_status(settings.io)["running"]:
                self.notice.set("기존 파티 대화가 실행 중입니다. 게임으로 돌아가 주세요.")
                return
            write_json(self.config_root / "worker-error.json", {})
            self.worker = start_worker(self.config_root)
            self.worker_io = settings.io
            self.stop_pending = False
            self.notice.set("대화를 연결하고 있습니다. 이 창을 최소화하고 게임으로 돌아가세요.")

        self.job(lambda: self.checked_setup(settings), ready)

    def stop(self):
        self.start_generation += 1
        self.start_pending = False
        self.stop_pending = bool(self.worker and self.worker.poll() is None)
        folder = self.worker_io or (self.settings.io if self.settings.profile else None)
        try:
            stopped = folder and request_stop(folder)
        except (OSError, ValueError) as exc:
            self.error(exc)
            return
        if stopped or self.stop_pending:
            self.notice.set("대화를 중지하고 동료 제어를 돌려드리고 있습니다.")
        else:
            self.notice.set("이 앱에서 관리하는 실행이 없습니다. 이전 버전은 파티 대화 메뉴에서 종료해 주세요.")

    def launch_game(self):
        if os.name == "nt":
            os.startfile("steam://rungameid/1086940")
            self.notice.set("Steam에서 게임을 실행합니다. 런처에서 플레이를 누르고 세이브를 불러와 주세요.")

    def export_report(self):
        destination = filedialog.asksaveasfilename(parent=self.root, title="개인 정보 없는 진단 저장", defaultextension=".json",
                                                  initialfile="BG3Friend-diagnostics.json", filetypes=[("JSON", "*.json")])
        if destination:
            write_json(Path(destination), support_report(self.settings, self.checks))
            self.notice.set("진단을 저장했습니다. 대화·계정 정보·개인 경로는 포함하지 않았습니다.")

    def poll(self):
        if self.closing:
            return
        try:
            callback, result, error = self.queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in self.buttons:
                button.configure(state="normal")
            if error:
                self.start_pending = False
                self.error(error)
            else:
                try:
                    callback(result)
                except Exception as exc:
                    self.start_pending = False
                    self.error(exc)
        folder = self.worker_io or (self.settings.io if self.settings.profile else None)
        if getattr(self, "stop_pending", False) and folder and self.worker and self.worker.poll() is None:
            try:
                request_stop(folder)
            except (OSError, ValueError) as exc:
                self.error(exc)
        status = runtime_status(folder) if folder else {"running": False}
        if status["running"]:
            if not status["game_connected"]:
                self.status.set("게임에서 모험을 불러와 주세요")
                self.detail.set("파티 대화가 기다리고 있습니다. 세이브를 불러오면 게임 오른쪽에 대화창이 나타납니다.")
            elif not status["enabled"]:
                self.status.set("동료를 선택해 주세요")
                self.detail.set("게임 속 파티 대화에서 맡길 동료를 고르고 ‘함께하기’를 눌러 주세요. 쉬는 중이라면 다시 연결할 수 있습니다.")
            else:
                self.status.set((status.get("companion") or "동료") + "와 함께하고 있습니다")
                meanings = {"thinking": "답변을 생각하고 있습니다.", "cancelling": "상황이 바뀌어 이전 응답을 취소하고 있습니다.",
                            "retrying": "연결 오류로 잠시 기다린 뒤 다시 시도합니다.", "error": "응답을 중지했습니다. 계정·모델 설정을 확인한 뒤 새 메시지로 다시 시도해 주세요."}
                self.detail.set(meanings.get(status["status"], "게임으로 돌아가 대화해 보세요. 중지하면 동료 제어를 돌려드립니다."))
        else:
            self.status.set("파티 대화가 꺼져 있습니다")
            self.detail.set("설치를 확인한 뒤 대화를 시작해 주세요. 게임과 대화는 각각 실행할 수 있습니다.")
        worker_running = self.worker and self.worker.poll() is None
        self.stop_button.configure(state="normal" if status["running"] or self.start_pending or worker_running else "disabled")
        if not self.busy:
            self.start_button.configure(state="disabled" if status["running"] or (self.worker and self.worker.poll() is None) else "normal")
        if self.worker and self.worker.poll() is not None:
            error = read_json(self.config_root / "worker-error.json") or {}
            if error.get("message"):
                self.notice.set(error["message"])
            self.worker = None
            self.worker_io = None
            self.stop_pending = False
        self.root.after(200, self.poll)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.start_generation += 1
        self.start_pending = False
        if self.worker and self.worker.poll() is None:
            try:
                request_stop(self.worker_io or self.settings.io)
            except (OSError, ValueError) as exc:
                self.error(exc)
        self.status.set("진행 중인 작업을 마치고 있습니다")
        deadline = time.monotonic() + 8

        def finish():
            if self.busy:
                try:
                    _, _, error = self.queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self.busy = False
                    if error:
                        self.error(error)
            worker_running = self.worker and self.worker.poll() is None
            if worker_running:
                try:
                    request_stop(self.worker_io or self.settings.io)
                except (OSError, ValueError) as exc:
                    self.error(exc)
            if self.busy or (worker_running and time.monotonic() < deadline):
                self.root.after(100, finish)
            else:
                self.root.destroy()

        self.root.after(100, finish)
