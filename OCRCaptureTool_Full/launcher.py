from __future__ import annotations

import ctypes
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from version import APP_VERSION

APP_NAME = "OCRCaptureTool"
APP_TITLE = "OCR 速记器 · 全量版"
PYTHON_LINE = (3, 12)
PYTHON_INSTALL_VERSION = "3.12.10"
PYTHON_BASE_PACK_NAME = "python312_base.zip"
PADDLE_VERSION = "3.2.2"
PADDLEOCR_VERSION = "3.7.0"
RUNTIME_SCHEMA = "offline-wheelhouse-v2"
MODEL_NAMES = ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")
MODEL_PACK_NAME = "ppocrv6_medium_models.zip"
MODEL_CACHE_REVISION = "medium_pack_v2"


def root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_data_root() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def logs_dir() -> Path:
    path = app_data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_error(detail: str) -> Path:
    path = logs_dir() / f"{datetime.now():%Y%m%d_%H%M%S}_launcher.txt"
    path.write_text(detail, encoding="utf-8")
    return path


def hidden_process_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def run_hidden(
    command: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    kwargs = hidden_process_kwargs()
    if capture:
        kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.PIPE})
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        env=env,
        **kwargs,
    )


def run_checked(command: list[str], *, env: dict[str, str] | None = None) -> None:
    result = run_hidden(command, check=False, capture=True, env=env)
    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        raise RuntimeError(
            f"命令执行失败（退出码 {result.returncode}）：\n"
            + " ".join(command)
            + (f"\n\n{output}" if output else "")
        )


def python_version_ok(python_exe: Path) -> bool:
    try:
        result = run_hidden(
            [str(python_exe), "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture=True,
        )
        return result.stdout.strip() == f"{PYTHON_LINE[0]}.{PYTHON_LINE[1]}"
    except Exception:
        return False


def resolve_python_from_launcher() -> Path | None:
    launcher = shutil.which("py")
    if not launcher:
        return None
    try:
        result = run_hidden(
            [launcher, "-3.12", "-c", "import sys;print(sys.executable)"],
            capture=True,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return None
        candidate = Path(lines[-1])
        return candidate if candidate.is_file() and python_version_ok(candidate) else None
    except Exception:
        return None


def find_python312() -> Path | None:
    candidates: list[Path] = []
    via_launcher = resolve_python_from_launcher()
    if via_launcher:
        candidates.append(via_launcher)

    for command in ("python", "python3"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("ProgramFiles", ""))
    if local:
        candidates.append(local / "Programs" / "Python" / "Python312" / "python.exe")
    if program_files:
        candidates.append(program_files / "Python312" / "python.exe")

    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve()).casefold()
        except OSError:
            key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file() and python_version_ok(candidate):
            return candidate
    return None


def pythonw_for(python_exe: Path) -> Path | None:
    candidate = python_exe.with_name("pythonw.exe")
    return candidate if candidate.is_file() else None


def offline_dir(root: Path) -> Path:
    return root / "offline"


def wheelhouse_dir(root: Path) -> Path:
    return offline_dir(root) / "wheelhouse"


def offline_manifest_path(root: Path) -> Path:
    return offline_dir(root) / "manifest.json"


def validate_offline_payload(root: Path) -> None:
    python_pack = offline_dir(root) / PYTHON_BASE_PACK_NAME
    wheelhouse = wheelhouse_dir(root)
    manifest = offline_manifest_path(root)
    required = [
        root / "app" / "app.py",
        root / "app" / "requirements.txt",
        root / "app" / "model_pack" / "ppocrv6_medium_models.zip",
        python_pack,
        manifest,
    ]
    missing = [str(path) for path in required if not path.is_file() or path.stat().st_size <= 0]
    if not wheelhouse.is_dir() or not any(wheelhouse.glob("*.whl")):
        missing.append(str(wheelhouse))
    if missing:
        raise RuntimeError(
            "发布包不完整，缺少离线运行组件。请让发布者重新运行“Release.bat”。\n\n"
            + "\n".join(missing)
        )
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("离线组件清单损坏。") from exc
    if data.get("runtime_schema") != RUNTIME_SCHEMA:
        raise RuntimeError("离线组件版本与程序不匹配，请使用同一版本的完整发布包。")


def local_python_root() -> Path:
    return runtime_dir() / "python"


def local_python() -> Path:
    return local_python_root() / "python.exe"


def local_pythonw() -> Path:
    return local_python_root() / "pythonw.exe"


def install_portable_python(root: Path, status) -> Path:
    archive_path = offline_dir(root) / PYTHON_BASE_PACK_NAME
    if not archive_path.is_file():
        raise RuntimeError(f"发布包缺少 Python 便携运行包：{archive_path}")

    import zipfile
    import uuid

    destination = local_python_root()
    staging = destination.with_name(f"python_extracting_{uuid.uuid4().hex[:8]}")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    status("正在准备 Python 运行组件", "正在校验内置 Python 3.12 运行包…", 16)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            bad = archive.testzip()
            if bad is not None:
                raise RuntimeError(f"Python 便携运行包校验失败：{bad}")
            members = archive.infolist()
            total = max(1, len(members))
            staging_resolved = staging.resolve()
            for index, info in enumerate(members, start=1):
                relative = Path(info.filename.replace("\\", "/"))
                target = (staging / relative).resolve()
                if target != staging_resolved and staging_resolved not in target.parents:
                    raise RuntimeError("Python 便携运行包包含非法路径。")
                archive.extract(info, staging)
                if index == 1 or index == total or index % max(1, total // 18) == 0:
                    percent = 17 + int(index / total * 13)
                    name = relative.name or str(relative)
                    status(
                        "正在解压 Python 运行组件",
                        f"{index}/{total} · {name}",
                        percent,
                    )

        py = staging / "python.exe"
        pyw = staging / "pythonw.exe"
        if not py.is_file() or not pyw.is_file():
            raise RuntimeError("Python 便携运行包解压后不完整。")
        (staging / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
        (staging / "python312._pth").write_text(
            ".\nLib\nLib\\site-packages\nDLLs\nimport site\n", encoding="utf-8"
        )
        shutil.rmtree(destination, ignore_errors=True)
        try:
            staging.replace(destination)
        except OSError:
            shutil.move(str(staging), str(destination))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    status("正在校验 Python 运行组件", "检查 Python 3.12 是否可以正常启动…", 31)
    if not local_python().is_file() or not python_version_ok(local_python()):
        raise RuntimeError("本地 Python 运行组件准备后校验失败。")
    return local_python()

def requirements_fingerprint(root: Path) -> str:
    """Fingerprint only the runtime ABI/dependency set, not the app version.

    This lets 0.1.x UI/logic updates reuse an already prepared OCR runtime as
    long as Python/Paddle/PaddleOCR/requirements are unchanged.
    """
    requirements = root / "app" / "requirements.txt"
    manifest = offline_manifest_path(root)
    payload = bytearray()
    payload.extend(RUNTIME_SCHEMA.encode())
    payload.extend(f"|python={PYTHON_LINE[0]}.{PYTHON_LINE[1]}".encode())
    payload.extend(f"|paddle={PADDLE_VERSION}|paddleocr={PADDLEOCR_VERSION}".encode())
    if requirements.is_file():
        payload.extend(requirements.read_bytes())
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            runtime_only = {
                "runtime_schema": data.get("runtime_schema"),
                "python": data.get("python"),
                "paddlepaddle": data.get("paddlepaddle"),
                "paddleocr": data.get("paddleocr"),
                "python_base_pack": data.get("python_base_pack"),
                "wheel_count": data.get("wheel_count"),
                "wheel_bytes": data.get("wheel_bytes"),
                "wheelhouse_fingerprint": data.get("wheelhouse_fingerprint"),
            }
            payload.extend(json.dumps(runtime_only, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        except Exception:
            pass
    return hashlib.sha256(payload).hexdigest()

def runtime_dir() -> Path:
    return app_data_root() / "runtime"


def runtime_marker() -> Path:
    return runtime_dir() / "runtime.json"


def verify_imports(python_exe: Path) -> bool:
    code = (
        "import sys,numpy,paddle,paddleocr,PySide6,PIL,pynput;"
        f"ok=(sys.version_info[:2]==(3,12) and paddle.__version__=='{PADDLE_VERSION}' "
        f"and paddleocr.__version__=='{PADDLEOCR_VERSION}');"
        "raise SystemExit(0 if ok else 7)"
    )
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    try:
        result = run_hidden([str(python_exe), "-c", code], check=False, env=env)
        return result.returncode == 0
    except Exception:
        return False


def read_ready_pythonw(root: Path) -> Path | None:
    marker = runtime_marker()
    if not marker.is_file():
        # Upgrade path: older releases may have a prepared portable runtime but
        # a marker format/fingerprint that no longer matches. Reuse it if the
        # actual environment is still healthy.
        py = local_python()
        pyw = local_pythonw()
        if py.is_file() and pyw.is_file() and verify_imports(py):
            write_runtime_marker(root, py, pyw, "portable")
            return pyw
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    python = Path(str(data.get("python", "")))
    pythonw = Path(str(data.get("pythonw", "")))
    if python.is_file() and pythonw.is_file() and verify_imports(python):
        expected = requirements_fingerprint(root)
        if data.get("fingerprint") != expected:
            write_runtime_marker(root, python, pythonw, str(data.get("mode") or "portable"))
        return pythonw

    # Last chance for old portable runtime locations recorded incorrectly.
    py = local_python()
    pyw = local_pythonw()
    if py.is_file() and pyw.is_file() and verify_imports(py):
        write_runtime_marker(root, py, pyw, "portable")
        return pyw
    return None

def write_runtime_marker(root: Path, python: Path, pythonw: Path, mode: str) -> None:
    runtime_dir().mkdir(parents=True, exist_ok=True)
    runtime_marker().write_text(
        json.dumps(
            {
                "fingerprint": requirements_fingerprint(root),
                "mode": mode,
                "python": str(python),
                "pythonw": str(pythonw),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )



def _friendly_subprocess_line(line: str) -> str | None:
    text = line.strip()
    if not text:
        return None
    lower = text.lower()
    # Suppress noisy build/runtime warnings that are not useful to the user.
    if "warning" in lower and ("ccache" in lower or "pip" in lower):
        return None
    if text.startswith("Processing "):
        value = text[len("Processing "):].strip()
        return "正在读取组件：" + Path(value).name
    if text.startswith("Collecting "):
        return "正在检查依赖：" + text[len("Collecting "):].strip()
    if text.startswith("Installing collected packages:"):
        value = text.split(":", 1)[1].strip()
        if len(value) > 95:
            value = value[:92] + "…"
        return "正在安装：" + value
    if text.startswith("Successfully installed"):
        return "组件安装完成，正在整理运行环境…"
    if text.startswith("Requirement already satisfied"):
        return "检测到已有组件，正在复用…"
    if text.startswith("Looking in links:"):
        return "正在读取发布包内的离线组件…"
    if text.startswith("Using cached"):
        return "正在复用本地缓存组件…"
    if len(text) > 120:
        text = text[:117] + "…"
    return text


def run_streamed(
    command: list[str],
    status,
    title: str,
    progress: int,
    progress_end: int | None = None,
    *,
    env: dict[str, str] | None = None,
) -> None:
    kwargs = hidden_process_kwargs()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **kwargs,
    )
    tail: list[str] = []
    current_progress = progress
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.rstrip()
        if line:
            tail.append(line)
            tail = tail[-30:]
        friendly = _friendly_subprocess_line(line)
        if friendly:
            if progress_end is not None and (line.startswith("Processing ") or line.startswith("Collecting ")):
                current_progress = min(progress_end - 1, current_progress + 1)
            status(title, friendly, current_progress)
    code = process.wait()
    if code != 0:
        raise RuntimeError(
            f"命令执行失败（退出码 {code}）：\n"
            + " ".join(command)
            + ("\n\n" + "\n".join(tail) if tail else "")
        )


def model_cache_destination() -> Path:
    return app_data_root() / "models" / MODEL_CACHE_REVISION


def model_cache_complete(path: Path | None = None) -> bool:
    root = path or model_cache_destination()
    for name in MODEL_NAMES:
        model = root / name
        for filename in ("inference.json", "inference.pdiparams"):
            file = model / filename
            if not file.is_file() or file.stat().st_size <= 0:
                return False
    return True


def prepare_model_cache(root: Path, status) -> Path:
    destination = model_cache_destination()
    if model_cache_complete(destination):
        status("PP-OCRv6 Medium 模型已就绪", "检测到完整本地模型，无需再次解压。", 96)
        return destination

    archive_path = root / "app" / "model_pack" / MODEL_PACK_NAME
    if not archive_path.is_file() or archive_path.stat().st_size <= 0:
        raise RuntimeError(f"发布包缺少 PP-OCRv6 Medium 模型包：{archive_path}")

    import uuid
    import zipfile

    staging = destination.with_name(f"{destination.name}_extracting_{uuid.uuid4().hex[:8]}")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    status("正在准备 PP-OCRv6 Medium 模型", "正在校验模型包完整性…", 88)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f"模型包校验失败：{bad}")
            members = [item for item in archive.infolist() if not item.is_dir()]
            total = max(1, len(members))
            staging_resolved = staging.resolve()
            for index, info in enumerate(members, start=1):
                relative = Path(info.filename.replace("\\", "/"))
                target = (staging / relative).resolve()
                if target != staging_resolved and staging_resolved not in target.parents:
                    raise RuntimeError("模型包包含非法路径。")
                archive.extract(info, staging)
                if index == 1 or index == total or index % max(1, total // 12) == 0:
                    percent = 89 + int(index / total * 6)
                    status(
                        "正在解压 PP-OCRv6 Medium 模型",
                        f"{index}/{total} · {relative.name}",
                        percent,
                    )
        if not model_cache_complete(staging):
            raise RuntimeError("PP-OCRv6 Medium 模型解压后文件不完整。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(destination, ignore_errors=True)
        try:
            staging.replace(destination)
        except OSError:
            shutil.move(str(staging), str(destination))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    status("PP-OCRv6 Medium 模型已就绪", "模型已保存到本机，后续启动不会重复准备。", 96)
    return destination


def prepare_runtime(root: Path, status) -> Path:
    status("正在检查运行环境", "检查是否已经准备过 OCR 组件…", 5)
    ready = read_ready_pythonw(root)
    if ready is not None:
        status("正在复用已有 OCR 环境", "Python / PaddleOCR 已经就绪，不会重复安装。", 84)
        prepare_model_cache(root, status)
        status("准备完成", "正在启动 OCR 速记器…", 99)
        return ready

    status("正在检查发布包", "校验离线 Python、OCR 组件和模型文件…", 8)
    validate_offline_payload(root)

    # If the receiver already has the exact tested OCR stack, reuse it and do
    # not install/copy another runtime.
    status("正在检查本机 Python", "寻找可以直接复用的 Python 3.12 + PaddleOCR 环境…", 11)
    system_python = find_python312()
    if system_python is not None and verify_imports(system_python):
        system_pythonw = pythonw_for(system_python)
        if system_pythonw is not None:
            status("检测到可直接复用的 OCR 环境", str(system_python), 84)
            write_runtime_marker(root, system_python, system_pythonw, "system")
            prepare_model_cache(root, status)
            status("准备完成", "正在启动 OCR 速记器…", 99)
            return system_pythonw

    # Otherwise use the bundled compact Python base. Unlike previous releases,
    # app version changes do not invalidate a healthy OCR runtime.
    python_exe = local_python()
    if not python_exe.is_file() or not python_version_ok(python_exe):
        shutil.rmtree(local_python_root(), ignore_errors=True)
        python_exe = install_portable_python(root, status)
    else:
        status("正在复用本地 Python", "已找到之前准备的 Python 3.12 运行组件。", 31)

    pythonw_exe = local_pythonw()
    if not pythonw_exe.is_file():
        raise RuntimeError("本地 Python GUI 运行组件缺失。")

    if not verify_imports(python_exe):
        status("正在初始化 Python 包管理器", "准备离线安装组件，不访问网络。", 34)
        run_streamed(
            [str(python_exe), "-m", "ensurepip", "--upgrade"],
            status,
            "正在初始化 Python 包管理器",
            37,
            40,
        )
        common = [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--only-binary=:all:",
            "--find-links",
            str(wheelhouse_dir(root)),
        ]
        status("正在安装 OCR 核心引擎", f"PaddlePaddle {PADDLE_VERSION}", 42)
        run_streamed(
            common + [f"paddlepaddle=={PADDLE_VERSION}"],
            status,
            "正在安装 OCR 核心引擎",
            43,
            58,
        )
        status("OCR 核心引擎安装完成", "正在准备界面与识别组件…", 58)

        requirements = root / "app" / "requirements.txt"
        run_streamed(
            common + ["-r", str(requirements)],
            status,
            "正在安装 OCR 与界面组件",
            60,
            82,
        )
        status("OCR 与界面组件安装完成", "正在进行最终运行环境检查…", 82)

    status("正在校验 OCR 运行环境", "检查 PaddleOCR、Qt、图像处理组件…", 85)
    if not verify_imports(python_exe):
        raise RuntimeError("离线 OCR 运行组件安装后校验失败，请查看启动日志。")

    write_runtime_marker(root, python_exe, pythonw_exe, "portable")
    # Remove the previous v0.1.4 venv if it exists; it is no longer used and
    # can consume a large amount of disk space.
    shutil.rmtree(runtime_dir() / "venv", ignore_errors=True)
    prepare_model_cache(root, status)
    status("准备完成", "正在启动 OCR 速记器…", 99)
    return pythonw_exe

def launch_app(root: Path, pythonw: Path) -> None:
    app_script = root / "app" / "app.py"
    if not app_script.is_file():
        raise RuntimeError(f"发布包不完整，缺少：{app_script}")

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
    env["PYTHONNOUSERSITE"] = "1"
    env["OCR_CAPTURE_RESOURCE_ROOT"] = str(root / "app")
    env["OCR_CAPTURE_APP_VERSION"] = APP_VERSION
    env["OCR_CAPTURE_ONLINE_RELEASE"] = "0"

    subprocess.Popen(
        [str(pythonw), str(app_script), *sys.argv[1:]],
        cwd=str(root),
        env=env,
        close_fds=True,
        **hidden_process_kwargs(),
    )


def show_fatal(detail: str) -> None:
    path = log_error(detail)
    message = (
        "离线运行环境准备失败。\n\n"
        "这个发布版不需要联网。请先确认 ZIP 已完整解压，且安全软件没有删除 offline/app 目录中的文件。\n\n"
        f"详细日志：\n{path}"
    )
    try:
        ctypes.windll.user32.MessageBoxW(None, message, f"{APP_TITLE}启动失败", 0x10)
    except Exception:
        pass


class BootstrapWindow:
    def __init__(self, root: Path) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._root_dir = root
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.window = tk.Tk()
        self.window.title(f"{APP_TITLE} v{APP_VERSION}")
        self.window.geometry("560x248")
        self.window.resizable(False, False)
        self.window.configure(bg="#151922")
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        try:
            ico = root / "app" / "assets" / "app_icon.ico"
            if ico.is_file():
                self.window.iconbitmap(str(ico))
        except Exception:
            pass

        frame = tk.Frame(self.window, bg="#151922", padx=26, pady=22)
        frame.pack(fill="both", expand=True)

        header = tk.Frame(frame, bg="#151922")
        header.pack(fill="x")
        self.title = tk.Label(
            header,
            text="正在准备本地 OCR 环境",
            bg="#151922",
            fg="#F4F7FF",
            font=("Microsoft YaHei UI", 14, "bold"),
            anchor="w",
        )
        self.title.pack(side="left", fill="x", expand=True)
        self.percent = tk.Label(
            header,
            text="0%",
            bg="#151922",
            fg="#7FA9FF",
            font=("Microsoft YaHei UI", 11, "bold"),
            anchor="e",
        )
        self.percent.pack(side="right")

        self.detail = tk.Label(
            frame,
            text="正在检查已安装环境。首次运行会从发布包本地准备组件，全程不需要联网。",
            bg="#151922",
            fg="#AAB4C8",
            font=("Microsoft YaHei UI", 9),
            anchor="w",
            justify="left",
            wraplength=500,
        )
        self.detail.pack(fill="x", pady=(10, 16))

        style = ttk.Style(self.window)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "OCR.Horizontal.TProgressbar",
            troughcolor="#242B38",
            background="#5B8CFF",
            bordercolor="#242B38",
            lightcolor="#5B8CFF",
            darkcolor="#5B8CFF",
            thickness=10,
        )
        self.bar = ttk.Progressbar(
            frame,
            mode="determinate",
            maximum=100,
            value=0,
            style="OCR.Horizontal.TProgressbar",
            length=500,
        )
        self.bar.pack(fill="x")

        self.hint = tk.Label(
            frame,
            text="第一次准备完成后，后续版本只要 OCR 依赖没变化就会直接复用，不会重复安装。",
            bg="#151922",
            fg="#69758C",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
            justify="left",
            wraplength=500,
        )
        self.hint.pack(fill="x", pady=(12, 0))

    def status(self, title: str, detail: str, progress: int | float | None = None) -> None:
        value = None if progress is None else max(0, min(100, int(progress)))
        self._events.put(("status", (title, detail, value)))

    def worker(self) -> None:
        try:
            pythonw = prepare_runtime(self._root_dir, self.status)
            self.status("正在启动 OCR 速记器", "运行环境和 PP-OCRv6 Medium 模型均已准备完成。", 100)
            launch_app(self._root_dir, pythonw)
            self._events.put(("done", None))
        except Exception:
            self._events.put(("error", traceback.format_exc()))

    def poll(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "status":
                    title, detail, progress = payload  # type: ignore[misc]
                    self.title.configure(text=title)
                    self.detail.configure(text=detail)
                    if progress is not None:
                        self.bar.configure(value=progress)
                        self.percent.configure(text=f"{progress}%")
                elif kind == "done":
                    self.window.after(180, self.window.destroy)
                    return
                elif kind == "error":
                    detail = str(payload)
                    self.window.destroy()
                    show_fatal(detail)
                    return
        except queue.Empty:
            pass
        self.window.after(80, self.poll)

    def run(self) -> None:
        threading.Thread(target=self.worker, daemon=True).start()
        self.window.after(80, self.poll)
        self.window.mainloop()

def main() -> int:
    root = root_dir()
    ready = read_ready_pythonw(root)
    if ready is not None and model_cache_complete():
        try:
            launch_app(root, ready)
            return 0
        except Exception:
            pass

    # Show the bootstrap window if either runtime or model cache still needs
    # work, so the first-run delay is visible instead of looking frozen.
    BootstrapWindow(root).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
