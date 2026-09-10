from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from version import APP_VERSION

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
RELEASE_ROOT = ROOT / "release"
RELEASE_NAME = f"OCRCaptureTool_Full_v{APP_VERSION}"
FINAL_APP_DIR = RELEASE_ROOT / RELEASE_NAME
ZIP_PATH = RELEASE_ROOT / f"{RELEASE_NAME}.zip"
TEMP_ROOT = Path(tempfile.gettempdir()) / "OCRCaptureTool_offline_build"
TEMP_APP_DIR = TEMP_ROOT / RELEASE_NAME
LAUNCHER_DIST = TEMP_ROOT / "launcher_dist"
LAUNCHER_WORK = TEMP_ROOT / "launcher_work"
TEST_RUNTIME = TEMP_ROOT / "offline_test_python"
MODEL_NAMES = ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")
MODEL_PACK_NAME = "ppocrv6_medium_models.zip"
PYTHON_INSTALL_VERSION = "3.12.10"
PYTHON_BASE_PACK_NAME = "python312_base.zip"
PADDLE_VERSION = "3.2.2"
PADDLEOCR_VERSION = "3.7.0"
PADDLE_INDEX = "https://www.paddlepaddle.org.cn/packages/stable/cpu/"
RUNTIME_SCHEMA = "offline-wheelhouse-v2"
PUBLISHER_CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OCRCaptureTool" / "publisher_cache"


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("\n>", " ".join(command))
    subprocess.run(command, cwd=str(cwd or ROOT), env=env, check=True)


def run_capture(command: list[str]) -> str:
    return subprocess.check_output(command, cwd=str(ROOT), text=True, encoding="utf-8").strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def link_or_copy(source: Path, destination: Path) -> None:
    """Materialize a cached artifact cheaply when source/destination share a volume."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def tree_signature(root: Path) -> str:
    """Fast metadata signature; avoids re-hashing hundreds of MB on every publish."""
    items: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(f"{path.relative_to(root).as_posix()}|{stat.st_size}|{stat.st_mtime_ns}")
    return hashlib.sha256("\n".join(items).encode("utf-8", errors="replace")).hexdigest()


def cache_dir(name: str) -> Path:
    path = PUBLISHER_CACHE / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _version_tuple4() -> tuple[int, int, int, int]:
    parts = [int(part) for part in APP_VERSION.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])  # type: ignore[return-value]


def create_windows_version_file(path: Path) -> None:
    major, minor, patch, build = _version_tuple4()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {build}),
    prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'LonzilTools'),
         StringStruct(u'FileDescription', u'OCR Capture Tool'),
         StringStruct(u'FileVersion', u'{version}'),
         StringStruct(u'InternalName', u'OCRCaptureTool'),
         StringStruct(u'OriginalFilename', u'OCRCaptureTool.exe'),
         StringStruct(u'ProductName', u'OCR Capture Tool'),
         StringStruct(u'ProductVersion', u'{version}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
""".format(major=major, minor=minor, patch=patch, build=build, version=APP_VERSION)
    path.write_text(content, encoding="utf-8")


def model_is_complete(path: Path) -> bool:
    required = (path / "inference.json", path / "inference.pdiparams")
    return path.is_dir() and all(item.is_file() and item.stat().st_size > 0 for item in required)


def required_model_entries() -> set[str]:
    return {
        f"{MODEL_NAMES[0]}/inference.json",
        f"{MODEL_NAMES[0]}/inference.pdiparams",
        f"{MODEL_NAMES[1]}/inference.json",
        f"{MODEL_NAMES[1]}/inference.pdiparams",
    }


def create_model_pack(destination: Path) -> None:
    source_root = Path.home() / ".paddlex" / "official_models"
    sources = {name: source_root / name for name in MODEL_NAMES}
    for name, source in sources.items():
        if not model_is_complete(source):
            raise RuntimeError(
                f"Required Medium model is incomplete: {source}\n"
                "The publisher model prefetch step did not complete."
            )

    signature_payload = "|".join(f"{name}:{tree_signature(source)}" for name, source in sources.items())
    signature = hashlib.sha256(signature_payload.encode()).hexdigest()
    cached = cache_dir("model_packs") / f"{MODEL_PACK_NAME[:-4]}_{signature[:16]}.zip"

    if cached.is_file():
        try:
            verify_model_pack(cached)
            print("Using cached PP-OCRv6 Medium model pack.")
            link_or_copy(cached, destination)
            return
        except Exception:
            cached.unlink(missing_ok=True)

    cached.parent.mkdir(parents=True, exist_ok=True)
    print("Creating verified offline PP-OCRv6 Medium model pack (cache miss)...")
    with zipfile.ZipFile(cached, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for name, source in sources.items():
            for path in sorted(source.rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                archive.write(path, Path(name) / path.relative_to(source))
    verify_model_pack(cached)
    link_or_copy(cached, destination)

def verify_model_pack(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Offline model pack was not generated: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Offline model pack CRC verification failed: {bad}")
        files = {info.filename.replace("\\", "/").lstrip("/"): info for info in archive.infolist()}
        missing = sorted(required_model_entries() - files.keys())
        if missing:
            raise RuntimeError("Offline model pack is missing: " + ", ".join(missing))
        empty = sorted(name for name in required_model_entries() if files[name].file_size <= 0)
        if empty:
            raise RuntimeError("Offline model pack contains empty files: " + ", ".join(empty))


def python_base_source() -> Path:
    code = "import sys;print(sys.base_prefix)"
    base = Path(run_capture([str(VENV_PYTHON), "-c", code]))
    if not (base / "python.exe").is_file() or not (base / "Lib").is_dir() or not (base / "DLLs").is_dir():
        raise RuntimeError(f"Publisher Python 3.12 base is incomplete: {base}")
    return base


def create_python_base_pack(destination: Path) -> None:
    base = python_base_source()
    core_files = [base / "python.exe", base / "pythonw.exe", base / "python312.dll", base / "Lib" / "os.py"]
    core_signature = []
    for item in core_files:
        if not item.is_file():
            raise RuntimeError(f"Publisher Python core file is missing: {item}")
        stat = item.stat()
        core_signature.append(f"{item.name}|{stat.st_size}|{stat.st_mtime_ns}")
    signature = hashlib.sha256(
        f"{PYTHON_INSTALL_VERSION}|".encode() + "|".join(core_signature).encode()
    ).hexdigest()
    cached = cache_dir("python_base") / f"python312_base_{signature[:16]}.zip"

    if cached.is_file():
        try:
            verify_python_base_pack(cached)
            print("Using cached compact Python base pack.")
            link_or_copy(cached, destination)
            return
        except Exception:
            cached.unlink(missing_ok=True)

    print(f"Creating compact Python 3.12 base pack from: {base} (cache miss)")
    skip_top_dirs = {"include", "libs", "scripts", "tcl"}
    skip_lib_dirs = {"site-packages", "test", "tests", "idlelib", "tkinter", "turtledemo", "__pycache__"}
    skip_suffixes = (".pyc", ".pyo", ".pdb", ".lib", ".exp", ".obj")

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.unlink(missing_ok=True)
    with zipfile.ZipFile(cached, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5, allowZip64=True) as archive:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base)
            if rel.parts and rel.parts[0].casefold() in skip_top_dirs:
                continue
            if rel.parts and rel.parts[0].casefold() == "lib":
                if len(rel.parts) >= 2 and rel.parts[1].casefold() in skip_lib_dirs:
                    continue
            if any(part.casefold() == "__pycache__" for part in rel.parts):
                continue
            if path.suffix.casefold() in skip_suffixes:
                continue
            archive.write(path, rel)

    verify_python_base_pack(cached)
    link_or_copy(cached, destination)

def verify_python_base_pack(path: Path) -> None:
    required = {"python.exe", "pythonw.exe", "Lib/os.py", "Lib/ensurepip/__init__.py"}
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Python base pack was not generated: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Python base pack CRC verification failed: {bad}")
        names = {info.filename.replace("\\", "/").lstrip("/") for info in archive.infolist()}
        missing = sorted(required - names)
        if missing:
            raise RuntimeError("Python base pack is missing: " + ", ".join(missing))
        if not any(name.lower().startswith("python3") and name.lower().endswith(".dll") for name in names):
            raise RuntimeError("Python base pack is missing the Python runtime DLL.")


def wheelhouse_fingerprint() -> str:
    payload = bytearray()
    payload.extend(RUNTIME_SCHEMA.encode())
    payload.extend(f"|python={PYTHON_INSTALL_VERSION}|paddle={PADDLE_VERSION}|paddleocr={PADDLEOCR_VERSION}".encode())
    payload.extend((ROOT / "requirements.txt").read_bytes())
    return hashlib.sha256(payload).hexdigest()


def prepare_wheelhouse(destination: Path) -> None:
    PUBLISHER_CACHE.mkdir(parents=True, exist_ok=True)
    fingerprint = wheelhouse_fingerprint()
    cached = PUBLISHER_CACHE / f"wheelhouse_{fingerprint[:16]}"
    marker = cached / "manifest.json"

    valid_cache = False
    if marker.is_file() and any(cached.glob("*.whl")):
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            valid_cache = data.get("fingerprint") == fingerprint
        except Exception:
            valid_cache = False

    if not valid_cache:
        shutil.rmtree(cached, ignore_errors=True)
        cached.mkdir(parents=True, exist_ok=True)
        print("Preparing offline wheelhouse on the publisher PC...")
        run(
            [
                str(VENV_PYTHON),
                "-m",
                "pip",
                "download",
                "--dest",
                str(cached),
                "--only-binary=:all:",
                f"paddlepaddle=={PADDLE_VERSION}",
                "-i",
                PADDLE_INDEX,
            ]
        )
        run(
            [
                str(VENV_PYTHON),
                "-m",
                "pip",
                "download",
                "--dest",
                str(cached),
                "--only-binary=:all:",
                "-r",
                str(ROOT / "requirements.txt"),
            ]
        )
        wheels = sorted(cached.glob("*.whl"))
        if not wheels:
            raise RuntimeError("Offline wheelhouse is empty after download.")
        marker.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "wheel_count": len(wheels),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    for wheel in cached.glob("*.whl"):
        link_or_copy(wheel, destination / wheel.name)
    if not any(destination.glob("*.whl")):
        raise RuntimeError("No wheels were copied into the release package.")


def create_offline_manifest(app_dir: Path) -> None:
    offline = app_dir / "offline"
    python_pack = offline / PYTHON_BASE_PACK_NAME
    wheels = sorted((offline / "wheelhouse").glob("*.whl"))
    manifest = {
        "runtime_schema": RUNTIME_SCHEMA,
        "app_version": APP_VERSION,
        "python": PYTHON_INSTALL_VERSION,
        "paddlepaddle": PADDLE_VERSION,
        "paddleocr": PADDLEOCR_VERSION,
        "python_base_pack": {
            "name": python_pack.name,
            "size": python_pack.stat().st_size,
            "sha256": sha256_file(python_pack),
        },
        "wheel_count": len(wheels),
        "wheel_bytes": sum(path.stat().st_size for path in wheels),
        "wheelhouse_fingerprint": wheelhouse_fingerprint(),
    }
    (offline / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_application_files(app_dir: Path) -> None:
    app = app_dir / "app"
    app.mkdir(parents=True, exist_ok=True)
    for name in ("app.py", "version.py", "requirements.txt"):
        shutil.copy2(ROOT / name, app / name)
    shutil.copytree(ROOT / "assets", app / "assets", dirs_exist_ok=True)
    create_model_pack(app / "model_pack" / MODEL_PACK_NAME)
    shutil.copy2(ROOT / "使用说明.txt", app_dir / "使用说明.txt")
    shutil.copy2(ROOT / "查看错误日志.bat", app_dir / "查看错误日志.bat")

    offline = app_dir / "offline"
    offline.mkdir(parents=True, exist_ok=True)
    create_python_base_pack(offline / PYTHON_BASE_PACK_NAME)
    prepare_wheelhouse(offline / "wheelhouse")
    create_offline_manifest(app_dir)


def build_launcher(app_dir: Path) -> None:
    version_file = LAUNCHER_WORK / "version_info.txt"
    LAUNCHER_DIST.mkdir(parents=True, exist_ok=True)
    LAUNCHER_WORK.mkdir(parents=True, exist_ok=True)
    create_windows_version_file(version_file)
    run(
        [
            str(VENV_PYTHON),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            "OCRCaptureTool",
            "--icon",
            str(ROOT / "assets" / "app_icon.ico"),
            "--version-file",
            str(version_file),
            "--distpath",
            str(LAUNCHER_DIST),
            "--workpath",
            str(LAUNCHER_WORK),
            "--specpath",
            str(LAUNCHER_WORK),
            str(ROOT / "launcher.py"),
        ]
    )
    source = LAUNCHER_DIST / "OCRCaptureTool.exe"
    if not source.is_file():
        raise RuntimeError("Launcher EXE was not generated.")
    shutil.copy2(source, app_dir / "OCRCaptureTool.exe")


def verify_layout(app_dir: Path) -> None:
    required = [
        app_dir / "OCRCaptureTool.exe",
        app_dir / "app" / "app.py",
        app_dir / "app" / "version.py",
        app_dir / "app" / "requirements.txt",
        app_dir / "app" / "model_pack" / MODEL_PACK_NAME,
        app_dir / "app" / "assets" / "app_icon.ico",
        app_dir / "app" / "assets" / "app_icon.png",
        app_dir / "offline" / PYTHON_BASE_PACK_NAME,
        app_dir / "offline" / "manifest.json",
        app_dir / "使用说明.txt",
    ]
    missing = [str(path) for path in required if not path.is_file() or path.stat().st_size <= 0]
    if not (app_dir / "offline" / "wheelhouse").is_dir() or not any((app_dir / "offline" / "wheelhouse").glob("*.whl")):
        missing.append(str(app_dir / "offline" / "wheelhouse"))
    if missing:
        raise RuntimeError("Release is missing required offline files:\n" + "\n".join(missing))
    verify_model_pack(app_dir / "app" / "model_pack" / MODEL_PACK_NAME)


def find_base_python() -> Path:
    code = "import sys;print(sys.base_prefix)"
    base = Path(run_capture([str(VENV_PYTHON), "-c", code]))
    python = base / "python.exe"
    if not python.is_file():
        raise RuntimeError(f"Base Python 3.12 was not found: {python}")
    return python



def runtime_payload_fingerprint(app_dir: Path) -> str:
    manifest = json.loads((app_dir / "offline" / "manifest.json").read_text(encoding="utf-8"))
    wheelhouse = app_dir / "offline" / "wheelhouse"
    wheels = sorted((path.name, path.stat().st_size) for path in wheelhouse.glob("*.whl"))
    model_pack = app_dir / "app" / "model_pack" / MODEL_PACK_NAME
    python_pack = app_dir / "offline" / PYTHON_BASE_PACK_NAME
    payload = {
        "runtime_schema": manifest.get("runtime_schema"),
        "python": manifest.get("python"),
        "paddlepaddle": manifest.get("paddlepaddle"),
        "paddleocr": manifest.get("paddleocr"),
        "wheelhouse_fingerprint": manifest.get("wheelhouse_fingerprint"),
        "wheels": wheels,
        "python_pack_size": python_pack.stat().st_size,
        "model_pack_size": model_pack.stat().st_size,
        "requirements": (app_dir / "app" / "requirements.txt").read_text(encoding="utf-8"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def quick_app_self_test(app_dir: Path) -> None:
    """Fast per-version app test using the already-tested publisher environment."""
    print("\n> Running quick application self-test")
    report = TEMP_ROOT / "quick_app_selftest.txt"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env["OCR_CAPTURE_RESOURCE_ROOT"] = str(app_dir / "app")
    env["OCR_CAPTURE_MODEL_CACHE_ROOT"] = str(Path.home() / ".paddlex" / "official_models")
    env["OCR_CAPTURE_APP_VERSION"] = APP_VERSION
    env["OCR_CAPTURE_ONLINE_RELEASE"] = "0"
    env["PYTHONNOUSERSITE"] = "1"
    env["FLAGS_use_mkldnn"] = "0"
    env["FLAGS_use_onednn"] = "0"
    process = subprocess.run(
        [str(VENV_PYTHON), str(app_dir / "app" / "app.py"), "--self-test", str(report)],
        cwd=str(app_dir),
        env=env,
        check=False,
    )
    text = report.read_text(encoding="utf-8", errors="replace") if report.is_file() else ""
    if process.returncode != 0 or "RESULT=OK" not in text:
        print("\n----- quick self-test report -----")
        print(text or "Quick self-test exited without a report.")
        print("----- end quick self-test report -----\n")
        raise RuntimeError("Quick application self-test failed.")


def offline_runtime_self_test(app_dir: Path) -> None:
    """Fast offline payload validation.

    Previous releases created a brand-new Python tree and physically installed
    every wheel on every publish. That was reliable but unnecessarily slow.
    Here we structurally verify the compact Python/model packs and ask pip to
    resolve the *entire* clean dependency set from the offline wheelhouse using
    --dry-run --ignore-installed. This catches missing/incompatible wheels
    without extracting hundreds of MB during each publish.
    """
    fingerprint = runtime_payload_fingerprint(app_dir)
    validation_dir = cache_dir("runtime_validation")
    marker = validation_dir / f"{fingerprint}.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            if data.get("fingerprint") == fingerprint and data.get("result") == "OK":
                print("\n> Offline runtime payload unchanged; using cached dependency validation.")
                return
        except Exception:
            pass

    print("\n> Validating offline runtime payload (fast dependency resolution; no full reinstall)...")
    python_pack = app_dir / "offline" / PYTHON_BASE_PACK_NAME
    verify_python_base_pack(python_pack)
    verify_model_pack(app_dir / "app" / "model_pack" / MODEL_PACK_NAME)

    wheelhouse = app_dir / "offline" / "wheelhouse"
    command = [
        str(VENV_PYTHON),
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--ignore-installed",
        "--no-index",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--find-links",
        str(wheelhouse),
        f"paddlepaddle=={PADDLE_VERSION}",
        "-r",
        str(app_dir / "app" / "requirements.txt"),
    ]
    run(command)
    marker.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "result": "OK",
                "validation": "pip-dry-run-clean-resolution",
                "validated_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

def directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def zip_release(app_dir: Path) -> None:
    ZIP_PATH.unlink(missing_ok=True)
    print("Creating release ZIP (fast mode: already-compressed payloads are stored, not recompressed)...")
    already_compressed = {".whl", ".zip", ".exe", ".png", ".ico", ".jpg", ".jpeg", ".webp"}
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sorted(app_dir.rglob("*")):
            if not path.is_file():
                continue
            arcname = Path(RELEASE_NAME) / path.relative_to(app_dir)
            if path.suffix.casefold() in already_compressed:
                archive.write(path, arcname, compress_type=zipfile.ZIP_STORED)
            else:
                archive.write(path, arcname, compress_type=zipfile.ZIP_DEFLATED, compresslevel=3)

def verify_zip() -> None:
    required = {
        f"{RELEASE_NAME}/OCRCaptureTool.exe",
        f"{RELEASE_NAME}/app/app.py",
        f"{RELEASE_NAME}/app/version.py",
        f"{RELEASE_NAME}/app/model_pack/{MODEL_PACK_NAME}",
        f"{RELEASE_NAME}/offline/{PYTHON_BASE_PACK_NAME}",
        f"{RELEASE_NAME}/offline/manifest.json",
        f"{RELEASE_NAME}/使用说明.txt",
    }
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Release ZIP CRC verification failed: {bad}")
        names = {item.filename.replace("\\", "/") for item in archive.infolist()}
        missing = sorted(required - names)
        if missing:
            raise RuntimeError("Release ZIP is missing: " + ", ".join(missing))
        if not any(name.startswith(f"{RELEASE_NAME}/offline/wheelhouse/") and name.endswith(".whl") for name in names):
            raise RuntimeError("Release ZIP does not contain the offline wheelhouse.")
        model_entry = f"{RELEASE_NAME}/app/model_pack/{MODEL_PACK_NAME}"
        model_bytes = archive.read(model_entry)
    with zipfile.ZipFile(io.BytesIO(model_bytes), "r") as model_archive:
        bad = model_archive.testzip()
        if bad:
            raise RuntimeError(f"Nested model pack CRC verification failed: {bad}")
        names = {item.filename.replace("\\", "/").lstrip("/") for item in model_archive.infolist()}
        missing = sorted(required_model_entries() - names)
        if missing:
            raise RuntimeError("Nested model pack is missing: " + ", ".join(missing))


def main() -> int:
    if not VENV_PYTHON.is_file():
        raise SystemExit(".venv is missing. Run install_cpu.bat first.")

    run([str(VENV_PYTHON), "-m", "py_compile", str(ROOT / "app.py"), str(ROOT / "launcher.py"), str(ROOT / "version.py")])

    model_cache = Path.home() / ".paddlex" / "official_models"
    if all(model_is_complete(model_cache / name) for name in MODEL_NAMES):
        print("\nPP-OCRv6 Medium publisher cache is complete; skipping model prefetch.")
    else:
        print("\nPreparing PP-OCRv6 Medium models on the publisher PC...")
        run([str(VENV_PYTHON), str(ROOT / "prefetch_models.py")])

    shutil.rmtree(TEMP_ROOT, ignore_errors=True)
    shutil.rmtree(FINAL_APP_DIR, ignore_errors=True)
    ZIP_PATH.unlink(missing_ok=True)
    TEMP_APP_DIR.mkdir(parents=True, exist_ok=True)
    RELEASE_ROOT.mkdir(parents=True, exist_ok=True)

    copy_application_files(TEMP_APP_DIR)
    build_launcher(TEMP_APP_DIR)
    verify_layout(TEMP_APP_DIR)
    quick_app_self_test(TEMP_APP_DIR)
    offline_runtime_self_test(TEMP_APP_DIR)

    report = [
        f"Application version: {APP_VERSION}",
        f"Build time: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "Packaging mode: offline wheelhouse bootstrap",
        "Receiver internet required: NO",
        "Expanded Python Lib bundled: NO",
        "Bundled compact Python base fallback: YES (used only when exact system OCR environment is unavailable)",
        "Bundled offline wheels: YES",
        "Bundled PP-OCRv6 Medium model: YES",
        "Existing exact Python 3.12 + OCR environment: reused when available",
        "Otherwise compact Python + wheels are installed under LOCALAPPDATA from bundled files only",
        f"Release folder size before ZIP: {directory_size(TEMP_APP_DIR) / 1024 / 1024:.1f} MB",
        "The receiver should fully extract the ZIP and run OCRCaptureTool.exe.",
    ]
    (TEMP_APP_DIR / "发布报告.txt").write_text("\n".join(report), encoding="utf-8-sig")

    shutil.move(str(TEMP_APP_DIR), str(FINAL_APP_DIR))
    verify_layout(FINAL_APP_DIR)
    zip_release(FINAL_APP_DIR)
    verify_zip()

    print("\nOffline release completed successfully.")
    print("Folder:", FINAL_APP_DIR)
    print("ZIP:   ", ZIP_PATH)
    print(f"ZIP size: {ZIP_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
