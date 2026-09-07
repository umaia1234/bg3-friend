"""Per-user desktop settings and read-only discovery. Nothing is installed here."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re

from .model import find_codex
from .protocol import write_json
from .windows_paths import local_appdata, user_state_dir


class ConfigurationError(ValueError):
    pass


def state_root() -> Path:
    try:
        return user_state_dir()
    except OSError as exc:
        raise ConfigurationError(str(exc)) from exc


@dataclass
class Settings:
    version: int = 1
    game: str = ""
    profile: str = ""
    codex: str = ""
    model: str = "gpt-6-astra"
    timeout: float = 45.0
    consent: bool = False

    @property
    def io(self) -> Path:
        if not self.profile:
            raise ConfigurationError("게임 프로필 폴더를 먼저 선택해 주세요.")
        return Path(self.profile) / "Script Extender/BG3Friend"

    def validate(self) -> None:
        if self.version != 1:
            raise ConfigurationError("이 설정은 다른 버전용입니다. 맞는 버전의 앱을 사용해 주세요.")
        if not all(isinstance(value, str) for value in (self.game, self.profile, self.codex, self.model)):
            raise ConfigurationError("설정의 경로 또는 모델 이름 형식이 올바르지 않습니다.")
        if not self.model.strip() or len(self.model) > 100 or any(c.isspace() for c in self.model):
            raise ConfigurationError("모델 이름을 공백 없이 입력해 주세요.")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)) or not 5 <= self.timeout <= 180:
            raise ConfigurationError("응답 제한 시간은 5–180초여야 합니다.")
        if not isinstance(self.consent, bool):
            raise ConfigurationError("모델 연결 동의 설정이 올바르지 않습니다.")
        for label, value in (("게임", self.game), ("프로필", self.profile), ("Codex", self.codex)):
            if value and not Path(value).is_absolute():
                raise ConfigurationError(f"{label} 경로는 전체 경로여야 합니다.")


def load_settings(root: Path | None = None) -> Settings:
    path = (root or state_root()) / "settings.json"
    if not path.exists():
        return discover_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or set(data) - set(Settings.__dataclass_fields__):
            raise ValueError("unexpected settings")
        result = Settings(**data)
        result.validate()
        return result
    except (OSError, TypeError, ValueError) as exc:
        raise ConfigurationError("설정을 읽지 못했습니다. settings.json을 보관한 뒤 설정을 다시 작성해 주세요.") from exc


def save_settings(settings: Settings, root: Path | None = None) -> None:
    settings.validate()
    write_json((root or state_root()) / "settings.json", asdict(settings))


def steam_roots() -> list[Path]:
    roots = []
    if os.name == "nt":
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
        for variable in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(variable):
                roots.append(Path(os.environ[variable]) / "Steam")
    return list(dict.fromkeys(roots))


def discover_games(roots: list[Path] | None = None) -> list[Path]:
    libraries = list(roots if roots is not None else steam_roots())
    for root in list(libraries):
        try:
            data = (root / "steamapps/libraryfolders.vdf").read_text(encoding="utf-8-sig")
            for value in re.findall(r'"path"\s*"((?:\\.|[^"\\])*)"', data):
                libraries.append(Path(value.replace("\\\\", "\\")))
        except (OSError, UnicodeError):
            pass
    games = []
    for library in dict.fromkeys(libraries):
        directory = "Baldurs Gate 3"
        try:
            manifest = (library / "steamapps/appmanifest_1086940.acf").read_text(encoding="utf-8-sig")
            match = re.search(r'"installdir"\s*"([^"/\\]+)"', manifest)
            if match:
                directory = match.group(1)
        except (OSError, UnicodeError):
            pass
        candidate = library / "steamapps/common" / directory
        if any((candidate / "bin" / name).is_file() for name in ("bg3_dx11.exe", "bg3.exe")):
            games.append(candidate)
    return list(dict.fromkeys(games))


def discover_settings() -> Settings:
    games = discover_games()
    try:
        local = local_appdata()
    except OSError:
        local = None
    return Settings(game=str(games[0]) if len(games) == 1 else "",
                    profile=str(Path(local) / "Larian Studios/Baldur's Gate 3") if local else "",
                    codex=find_codex() or "")
