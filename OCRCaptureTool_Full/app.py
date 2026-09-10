from __future__ import annotations

import gc
import json
import os
import shutil
import sys
import time
import traceback
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

APP_NAME = "OCRCaptureTool"
APP_DISPLAY_NAME = "OCR 速记器 · 全量版"

# Source builds read version.py. Portable builds also receive the version from
# the launcher/build environment, so a missing auxiliary version module can
# never prevent the OCR application from starting.
try:
    from version import APP_VERSION as _SOURCE_APP_VERSION
except (ImportError, ModuleNotFoundError):
    _SOURCE_APP_VERSION = "0.0.0"
APP_VERSION = os.environ.get("OCR_CAPTURE_APP_VERSION", _SOURCE_APP_VERSION)
MODEL_NAMES = ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")
MODEL_PACK_NAME = "ppocrv6_medium_models.zip"
MODEL_CACHE_REVISION = "medium_pack_v2"

# Corporate/China networks are usually more reliable with the BOS model source.
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
os.environ.setdefault("FLAGS_allocator_strategy", "auto_growth")
os.environ.setdefault("FLAGS_fraction_of_cpu_memory_to_use", "0.75")


def install_hidden_subprocess_policy() -> None:
    """Prevent short-lived console child processes from flashing on Windows.

    Paddle/PaddleX may probe the local toolchain (for example ccache) through
    subprocesses while an OCR engine is prepared or used. When the GUI itself
    runs under pythonw.exe, those console children can otherwise create a very
    brief black window. Apply the policy before importing Paddle-related code so
    subprocess.run/check_output/Popen calls inherit CREATE_NO_WINDOW.
    """
    if os.name != "nt":
        return

    import subprocess

    if getattr(subprocess.Popen, "_ocr_capture_hidden_console", False):
        return

    original_init = subprocess.Popen.__init__

    def hidden_init(self: Any, *args: Any, **kwargs: Any) -> None:
        creationflags = int(kwargs.get("creationflags", 0) or 0)
        # Respect callers that explicitly request their own new console.
        if not (creationflags & getattr(subprocess, "CREATE_NEW_CONSOLE", 0)):
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            kwargs["creationflags"] = creationflags

            startupinfo = kwargs.get("startupinfo")
            if startupinfo is None:
                startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = startupinfo

        original_init(self, *args, **kwargs)

    hidden_init._ocr_capture_hidden_console = True  # type: ignore[attr-defined]
    subprocess.Popen.__init__ = hidden_init  # type: ignore[method-assign]
    subprocess.Popen._ocr_capture_hidden_console = True  # type: ignore[attr-defined]


install_hidden_subprocess_policy()


def install_windows_app_identity() -> None:
    """Give the real Qt process a stable Windows application identity.

    The published EXE is only a lightweight launcher; the visible window lives
    in pythonw.exe. Setting an explicit AppUserModelID on that process prevents
    Windows from falling back to the generic Python/Qt taskbar identity.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "LonzilTools.OCRCaptureTool"
        )
    except Exception:
        pass


install_windows_app_identity()

from PySide6.QtCore import QObject, QPoint, QRect, QSettings, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizeGrip,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


# ---------- Paths and diagnostics ----------


def app_data_root() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def logs_dir() -> Path:
    path = app_data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_log(title: str, detail: str) -> Path:
    path = logs_dir() / f"{datetime.now():%Y%m%d_%H%M%S}_{title}.txt"
    path.write_text(detail, encoding="utf-8")
    return path


def resource_root() -> Path:
    override = os.environ.get("OCR_CAPTURE_RESOURCE_ROOT")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def model_cache_root() -> Path:
    override = os.environ.get("OCR_CAPTURE_MODEL_CACHE_ROOT")
    if override:
        root = Path(override).resolve()
    else:
        root = app_data_root() / "models" / MODEL_CACHE_REVISION
    root.mkdir(parents=True, exist_ok=True)
    return root


def install_exception_hook() -> None:
    default_hook = sys.excepthook

    def hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        path = write_log("crash", detail)
        try:
            QMessageBox.critical(
                None,
                "程序发生异常",
                f"程序遇到未处理异常，详细日志已保存到：\n{path}",
            )
        except Exception:
            pass
        default_hook(exc_type, exc, tb)

    sys.excepthook = hook


def run_self_test(output_path: str | None) -> int:
    lines = [f"{APP_DISPLAY_NAME} v{APP_VERSION} self-test"]
    try:
        import numpy as np
        import paddle
        import paddleocr
        import paddlex
        import PIL
        import pynput
        import PySide6
        from paddleocr import PaddleOCR

        lines.extend(
            [
                f"Python={sys.version.split()[0]}",
                f"PaddlePaddle={getattr(paddle, '__version__', 'unknown')}",
                f"PaddleOCR={getattr(paddleocr, '__version__', 'unknown')}",
                f"PaddleX={getattr(paddlex, '__version__', 'unknown')}",
                f"PySide6={getattr(PySide6, '__version__', 'unknown')}",
                f"Pillow={getattr(PIL, '__version__', 'unknown')}",
                f"pynput={getattr(pynput, '__version__', 'unknown')}",
            ]
        )

        # Regression test: PaddleOCR returns NumPy arrays for scores/boxes.
        sample_results = [
            {
                "rec_texts": np.asarray(["自检文字"], dtype=object),
                "rec_scores": np.asarray([0.98], dtype=float),
                "rec_boxes": np.asarray([[1, 2, 100, 30]], dtype=float),
            }
        ]
        parsed_text, parsed_score, parsed_lines = OCRService()._extract_text(sample_results)
        if parsed_text != "自检文字" or parsed_score <= 0 or parsed_lines != 1:
            raise RuntimeError("OCR result array parsing regression test failed.")
        lines.append("NumPyResultParsing=OK")

        for icon_name in ("app_icon.ico", "app_icon.png"):
            icon_file = resource_root() / "assets" / icon_name
            if not icon_file.is_file() or icon_file.stat().st_size <= 0:
                raise RuntimeError(f"Application icon is missing: {icon_file}")
        lines.append("ApplicationIcon=OK")

        model_dirs = OCRService._ensure_release_models()
        if model_dirs is not None:
            bundled_det, bundled_rec = model_dirs
            lines.append("BundledMediumArchive=OK")
            lines.append("BundledMediumExtraction=OK")
            for model_dir in (bundled_det, bundled_rec):
                for filename in ("inference.json", "inference.pdiparams"):
                    model_file = model_dir / filename
                    lines.append(
                        f"ModelFile={model_file} | exists={model_file.is_file()} | "
                        f"size={model_file.stat().st_size if model_file.is_file() else 0}"
                    )

            # Packaging self-test validates the portable runtime and the local
            # model files. It intentionally uses compatibility mode: oneDNN is
            # a performance optimization and must not make release generation
            # fail on a machine/CPU combination that needs the safe path.
            kwargs: dict[str, Any] = {
                "text_detection_model_name": MODEL_NAMES[0],
                "text_recognition_model_name": MODEL_NAMES[1],
                "text_detection_model_dir": str(bundled_det),
                "text_recognition_model_dir": str(bundled_rec),
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "device": "cpu",
                "enable_mkldnn": False,
                "mkldnn_cache_capacity": 1,
                "cpu_threads": max(2, min(4, (os.cpu_count() or 4) - 1)),
            }
            try:
                engine = PaddleOCR(**kwargs)
            except TypeError:
                kwargs.pop("mkldnn_cache_capacity", None)
                kwargs.pop("cpu_threads", None)
                engine = PaddleOCR(**kwargs)
            del engine
            gc.collect()
            lines.append("BundledMediumModelInit=OK (compatibility mode)")
        else:
            lines.append("BundledMediumModelInit=SKIPPED (source mode)")

        lines.append("RESULT=OK")
        code = 0
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("RESULT=FAILED")
        code = 1

    output = Path(output_path) if output_path else app_data_root() / "self_test.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return code


# ---------- Persistent history ----------


@dataclass
class HistoryRecord:
    id: str
    created_at: str
    text: str
    avg_score: float
    line_count: int
    image_path: str
    model_tier: str


class HistoryStore:
    def __init__(self) -> None:
        self.root = app_data_root()
        self.capture_dir = self.root / "captures"
        self.history_file = self.root / "history.json"
        self.capture_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[HistoryRecord]:
        if not self.history_file.exists():
            return []
        try:
            raw = json.loads(self.history_file.read_text(encoding="utf-8"))
            return [
                HistoryRecord(
                    id=str(item["id"]),
                    created_at=str(item["created_at"]),
                    text=str(item.get("text", "")),
                    avg_score=float(item.get("avg_score", 0.0)),
                    line_count=int(item.get("line_count", 0)),
                    image_path=str(item.get("image_path", "")),
                    model_tier=str(item.get("model_tier", "medium")),
                )
                for item in raw
            ]
        except Exception:
            detail = traceback.format_exc()
            write_log("history_load", detail)
            broken = self.history_file.with_name(f"history_broken_{datetime.now():%Y%m%d_%H%M%S}.json")
            try:
                self.history_file.replace(broken)
            except OSError:
                pass
            return []

    def save(self, records: list[HistoryRecord]) -> None:
        temp = self.history_file.with_suffix(".tmp")
        temp.write_text(
            json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.history_file)

    def save_capture(self, image: QImage, record_id: str) -> Path:
        path = self.capture_dir / f"{record_id}.png"
        if not image.save(str(path), "PNG"):
            raise RuntimeError("截图保存失败。")
        return path

    @staticmethod
    def remove_capture(image_path: str) -> None:
        try:
            Path(image_path).unlink(missing_ok=True)
        except OSError:
            pass


# ---------- Screen region selection ----------


class ScreenSelectionOverlay(QWidget):
    selected = Signal(QImage)
    canceled = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        screens = QGuiApplication.screens()
        if not screens:
            raise RuntimeError("没有检测到可用屏幕。")

        virtual_geometry = screens[0].geometry()
        for screen in screens[1:]:
            virtual_geometry = virtual_geometry.united(screen.geometry())
        self._virtual_geometry = virtual_geometry
        self.setGeometry(virtual_geometry)

        self._screen_images: list[tuple[QRect, QImage]] = []
        canvas = QImage(virtual_geometry.size(), QImage.Format.Format_RGB32)
        canvas.fill(Qt.GlobalColor.black)
        painter = QPainter(canvas)
        for screen in screens:
            geometry = screen.geometry()
            image = screen.grabWindow(0).toImage().convertToFormat(QImage.Format.Format_RGB32)
            self._screen_images.append((QRect(geometry), image))
            target = QRect(
                geometry.x() - virtual_geometry.x(),
                geometry.y() - virtual_geometry.y(),
                geometry.width(),
                geometry.height(),
            )
            painter.drawImage(target, image)
        painter.end()
        self._canvas = canvas

        self._dimmed_canvas = canvas.copy()
        dim_painter = QPainter(self._dimmed_canvas)
        dim_painter.fillRect(self._dimmed_canvas.rect(), QColor(7, 10, 16, 142))
        dim_painter.end()

        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._dragging = False
        self._completed = False

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        self.setFocus()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            return
        old_rect = self._selection_rect().adjusted(-40, -40, 180, 60)
        self._current = event.position().toPoint()
        new_rect = self._selection_rect().adjusted(-40, -40, 180, 60)
        self.update(old_rect.united(new_rect).intersected(self.rect()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._current = event.position().toPoint()
        self._dragging = False
        rect = self._selection_rect()
        if rect.width() < 6 or rect.height() < 6:
            self._cancel()
            return

        global_rect = QRect(rect)
        global_rect.translate(self._virtual_geometry.topLeft())
        image = self._crop_native_resolution(global_rect)
        self._completed = True
        self.selected.emit(image)
        self.close()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.drawImage(self.rect(), self._dimmed_canvas)
        rect = self._selection_rect()

        if not rect.isNull():
            painter.drawImage(rect, self._canvas, rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#5B8CFF"), 2))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 3, 3)

            size_text = f"{rect.width()} × {rect.height()}"
            label_rect = QRect(rect.left(), max(8, rect.top() - 34), 136, 26)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(18, 23, 34, 235))
            painter.drawRoundedRect(label_rect, 7, 7)
            painter.setPen(QColor("#E8ECF7"))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, size_text)
        else:
            hint = "拖动框选识别区域    右键 / Esc 取消"
            box = QRect(0, 0, 390, 46)
            box.moveCenter(self.rect().center())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(18, 23, 34, 235))
            painter.drawRoundedRect(box, 12, 12)
            painter.setPen(QColor("#E8ECF7"))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, hint)
        painter.end()

    def _selection_rect(self) -> QRect:
        if self._origin is None or self._current is None:
            return QRect()
        return QRect(self._origin, self._current).normalized().intersected(self.rect())

    def _crop_native_resolution(self, global_rect: QRect) -> QImage:
        intersections: list[tuple[QRect, QRect, QImage, float, float]] = []
        output_scale = 1.0

        for screen_geometry, screen_image in self._screen_images:
            intersection = global_rect.intersected(screen_geometry)
            if intersection.isEmpty():
                continue
            scale_x = screen_image.width() / max(1, screen_geometry.width())
            scale_y = screen_image.height() / max(1, screen_geometry.height())
            output_scale = max(output_scale, scale_x, scale_y)
            intersections.append((screen_geometry, intersection, screen_image, scale_x, scale_y))

        if not intersections:
            return self._canvas.copy(self._selection_rect())

        out_width = max(1, round(global_rect.width() * output_scale))
        out_height = max(1, round(global_rect.height() * output_scale))
        output = QImage(QSize(out_width, out_height), QImage.Format.Format_RGB32)
        output.fill(Qt.GlobalColor.white)
        painter = QPainter(output)

        for screen_geometry, intersection, screen_image, scale_x, scale_y in intersections:
            rel_screen = intersection.translated(-screen_geometry.x(), -screen_geometry.y())
            source = QRect(
                round(rel_screen.x() * scale_x),
                round(rel_screen.y() * scale_y),
                max(1, round(rel_screen.width() * scale_x)),
                max(1, round(rel_screen.height() * scale_y)),
            )
            piece = screen_image.copy(source)
            rel_output = intersection.translated(-global_rect.x(), -global_rect.y())
            target = QRect(
                round(rel_output.x() * output_scale),
                round(rel_output.y() * output_scale),
                max(1, round(rel_output.width() * output_scale)),
                max(1, round(rel_output.height() * output_scale)),
            )
            painter.drawImage(target, piece)

        painter.end()
        return output

    def closeEvent(self, event: Any) -> None:
        if not self._completed:
            self._completed = True
            self.canceled.emit()
        super().closeEvent(event)

    def _cancel(self) -> None:
        if self._completed:
            return
        self._completed = True
        self.canceled.emit()
        self.close()


# ---------- OCR worker ----------


class OCRService(QObject):
    finished = Signal(str, str, float, int, str)
    failed = Signal(str, str, str)
    status = Signal(str, str)
    startup_progress = Signal(int, str, str)
    initialized = Signal()
    initialization_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._engine: Any | None = None
        self._engine_tier: str | None = None
        self._compat_mode = False

    @Slot()
    def initialize(self) -> None:
        """Warm the PaddleOCR engine while the startup progress window is visible."""
        try:
            self.startup_progress.emit(8, "正在检查 PP-OCRv6 Medium 模型", "检查检测模型、识别模型以及本地模型缓存…")
            engine = self._get_engine("medium", force_compat=False)
            self.startup_progress.emit(88, "正在预热 Medium 推理管线", "使用小型内存图执行一次 DET/REC 预热，减少首次 F8 等待…")
            try:
                import numpy as np
                warmup = np.full((96, 320, 3), 255, dtype=np.uint8)
                try:
                    list(engine.predict(warmup, text_det_limit_type="max", text_det_limit_side_len=640, text_rec_score_thresh=0.35))
                except TypeError:
                    list(engine.predict(warmup, text_rec_score_thresh=0.35))
            except Exception as warm_error:
                # Warmup is an optimisation; do not block startup if a backend
                # rejects the synthetic blank image.
                write_log("ocr_warmup", repr(warm_error))
            mode = "兼容模式" if self._compat_mode else "CPU 加速模式"
            self.startup_progress.emit(94, "OCR 引擎初始化完成", f"PP-OCRv6 Medium 已就绪 · {mode}")
            self.initialized.emit()
        except Exception as exc:
            detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            log_path = write_log("startup_ocr", detail)
            concise = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.initialization_failed.emit(concise, str(log_path))

    @Slot(str, str, str, float, bool)
    def recognize(
        self,
        job_id: str,
        image_path: str,
        model_tier: str,
        score_threshold: float,
        enhance_small_text: bool,
    ) -> None:
        started = time.perf_counter()
        stage = "engine"
        try:
            self.status.emit("正在准备 OCR 引擎…", "busy")
            engine = self._get_engine(model_tier, force_compat=False)

            stage = "preprocess"
            preprocess_started = time.perf_counter()
            input_data = self._prepare_input(Path(image_path), enhance_small_text)
            preprocess_ms = (time.perf_counter() - preprocess_started) * 1000

            # Keep Medium accuracy, but put a hard ceiling on detection input.
            # Large 4K/multi-monitor selections previously could leave CPU
            # inference running for minutes with no visible progress.
            det_limit = 1280 if enhance_small_text else 1152
            predict_kwargs = {
                "text_rec_score_thresh": score_threshold,
                "text_det_limit_type": "max",
                "text_det_limit_side_len": det_limit,
            }

            stage = "predict"
            self.status.emit(f"正在识别文字… DET 最长边≤{det_limit}px", "busy")
            predict_started = time.perf_counter()
            try:
                try:
                    results = list(engine.predict(input_data, **predict_kwargs))
                except TypeError:
                    results = list(engine.predict(input_data, text_rec_score_thresh=score_threshold))
            except Exception as first_error:
                if not self._should_retry_compat(first_error):
                    raise
                self.status.emit("已自动切换兼容模式，正在重试…", "busy")
                self._dispose_engine()
                engine = self._get_engine(model_tier, force_compat=True)
                try:
                    results = list(engine.predict(input_data, **predict_kwargs))
                except TypeError:
                    results = list(engine.predict(input_data, text_rec_score_thresh=score_threshold))
            predict_ms = (time.perf_counter() - predict_started) * 1000

            stage = "extract"
            text, avg_score, line_count = self._extract_text(results)
            total_ms = (time.perf_counter() - started) * 1000
            write_log(
                "ocr_timing",
                (
                    f"job={job_id} image={image_path} enhance={enhance_small_text} "
                    f"preprocess_ms={preprocess_ms:.1f} predict_ms={predict_ms:.1f} "
                    f"total_ms={total_ms:.1f} lines={line_count} chars={len(text)} "
                    f"compat={self._compat_mode}"
                ),
            )
            mode = "compat" if self._compat_mode else "accelerated"
            self.finished.emit(job_id, text, avg_score, line_count, mode)
        except Exception as exc:
            detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            elapsed = time.perf_counter() - started
            log_path = write_log("ocr", f"stage={stage} elapsed={elapsed:.2f}s\n{detail}")
            concise = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.failed.emit(job_id, concise, str(log_path))

    @staticmethod
    def _model_dir_complete(path: Path) -> bool:
        return (
            path.is_dir()
            and (path / "inference.json").is_file()
            and (path / "inference.pdiparams").is_file()
            and (path / "inference.json").stat().st_size > 0
            and (path / "inference.pdiparams").stat().st_size > 0
        )

    @staticmethod
    def _model_pack_path() -> Path:
        return resource_root() / "model_pack" / MODEL_PACK_NAME

    @classmethod
    def _ensure_release_models(cls) -> tuple[Path, Path] | None:
        archive_path = cls._model_pack_path()
        release_mode = bool(os.environ.get("OCR_CAPTURE_RESOURCE_ROOT"))
        online_release = os.environ.get("OCR_CAPTURE_ONLINE_RELEASE") == "1"
        if not archive_path.is_file():
            # Lightweight published builds intentionally do not bundle the
            # ~hundreds-of-MB OCR model files. PaddleOCR will download the
            # PP-OCRv6 Medium models from BOS on first use and reuse its cache
            # afterwards. Offline/portable builds still fail closed if their
            # declared model pack is missing.
            if release_mode and not online_release:
                raise RuntimeError(
                    "发布包缺少离线 Medium 模型包。请重新运行“Release.bat”生成完整发布包。"
                )
            return None

        cache_root = model_cache_root()
        det_dir = cache_root / MODEL_NAMES[0]
        rec_dir = cache_root / MODEL_NAMES[1]
        if cls._model_dir_complete(det_dir) and cls._model_dir_complete(rec_dir):
            return det_dir, rec_dir

        staging = cache_root.with_name(f"{cache_root.name}_extracting_{uuid.uuid4().hex[:8]}")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        required = {
            f"{MODEL_NAMES[0]}/inference.json",
            f"{MODEL_NAMES[0]}/inference.pdiparams",
            f"{MODEL_NAMES[1]}/inference.json",
            f"{MODEL_NAMES[1]}/inference.pdiparams",
        }
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                bad_file = archive.testzip()
                if bad_file is not None:
                    raise RuntimeError(f"离线模型包校验失败：{bad_file}")
                names = {info.filename.replace("\\", "/").lstrip("/") for info in archive.infolist()}
                missing = sorted(required - names)
                if missing:
                    raise RuntimeError("离线模型包缺少必要文件：" + ", ".join(missing))
                staging_resolved = staging.resolve()
                for info in archive.infolist():
                    relative = Path(info.filename.replace("\\", "/"))
                    target = (staging / relative).resolve()
                    if target != staging_resolved and staging_resolved not in target.parents:
                        raise RuntimeError("离线模型包包含非法路径。")
                    archive.extract(info, staging)

            staged_det = staging / MODEL_NAMES[0]
            staged_rec = staging / MODEL_NAMES[1]
            if not cls._model_dir_complete(staged_det) or not cls._model_dir_complete(staged_rec):
                raise RuntimeError("离线 Medium 模型解压后不完整。")

            cache_root.parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(cache_root, ignore_errors=True)
            try:
                staging.replace(cache_root)
            except OSError:
                shutil.move(str(staging), str(cache_root))

            det_dir = cache_root / MODEL_NAMES[0]
            rec_dir = cache_root / MODEL_NAMES[1]
            if not cls._model_dir_complete(det_dir) or not cls._model_dir_complete(rec_dir):
                raise RuntimeError("离线 Medium 模型安装后校验失败。")
            return det_dir, rec_dir
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _get_engine(self, tier: str, force_compat: bool) -> Any:
        tier = "medium"
        if self._engine is not None and self._engine_tier == tier and self._compat_mode == force_compat:
            return self._engine

        self._dispose_engine()
        self.status.emit("首次使用正在准备精准 OCR 模型…", "busy")
        self.startup_progress.emit(16, "正在加载 PaddlePaddle", "导入 CPU 推理运行时与 oneDNN 组件…")

        import paddle
        self.startup_progress.emit(24, "PaddlePaddle 已加载", f"版本 {getattr(paddle, '__version__', 'unknown')} · 正在加载 PaddleOCR…")
        from paddleocr import PaddleOCR
        self.startup_progress.emit(31, "PaddleOCR 已加载", "正在准备 PP-OCRv6 Medium 检测/识别模型参数…")

        version = self._version_tuple(getattr(paddle, "__version__", "0"))
        safe_for_acceleration = version < (3, 3, 0)
        use_mkldnn = safe_for_acceleration and not force_compat
        threads = max(2, min(8, (os.cpu_count() or 4) - 1))

        kwargs: dict[str, Any] = {
            "text_detection_model_name": MODEL_NAMES[0],
            "text_recognition_model_name": MODEL_NAMES[1],
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "device": "cpu",
            "enable_mkldnn": use_mkldnn,
            "mkldnn_cache_capacity": 4,
            "cpu_threads": threads,
            # Batch recognized lines to reduce serial REC latency on text-dense captures.
            "text_recognition_batch_size": 8,
        }

        self.startup_progress.emit(36, "正在检查 Medium 模型文件", "确认 DET / REC 模型是否已经缓存或需要从离线模型包解压…")
        release_models = self._ensure_release_models()
        if release_models is not None:
            bundled_det, bundled_rec = release_models
            kwargs["text_detection_model_dir"] = str(bundled_det)
            kwargs["text_recognition_model_dir"] = str(bundled_rec)
            self.startup_progress.emit(44, "本地 Medium 模型已就绪", "检测模型与识别模型均从本地缓存加载，不需要联网。")
        elif os.environ.get("OCR_CAPTURE_ONLINE_RELEASE") == "1":
            self.status.emit("首次识别会自动下载 PP-OCRv6 Medium 模型…", "busy")
            self.startup_progress.emit(44, "正在准备官方 Medium 模型", "首次运行可能由 PaddleOCR 下载模型；后续会复用本机缓存。")
        else:
            self.startup_progress.emit(44, "正在使用 PaddleOCR 模型缓存", "源码模式将复用 PaddleOCR 已下载的 PP-OCRv6 Medium 模型。")

        def create_engine(parameters: dict[str, Any]) -> Any:
            try:
                return PaddleOCR(**parameters)
            except TypeError:
                # Some PaddleOCR/PaddleX builds no longer accept these tuning
                # keys. Retry without them, while preserving the model paths.
                reduced = dict(parameters)
                reduced.pop("mkldnn_cache_capacity", None)
                reduced.pop("cpu_threads", None)
                reduced.pop("text_recognition_batch_size", None)
                return PaddleOCR(**reduced)

        try:
            self.startup_progress.emit(52, "正在初始化 PP-OCRv6 Medium", "建立文字检测 DET 与文字识别 REC 推理管线…")
            self._engine = create_engine(kwargs)
            self.startup_progress.emit(86, "Medium DET / REC 已加载", "正在检查 CPU 加速模式与推理线程配置…")
        except Exception as first_error:
            # Earlier builds retried only predict() failures. Local-model initialization can
            # also fail in oneDNN/PIR on particular CPUs, so retry engine creation
            # itself in compatibility mode before surfacing an error.
            if force_compat or not self._should_retry_compat(first_error):
                raise
            self.status.emit("加速模式不兼容，已自动切换稳定模式…", "busy")
            self.startup_progress.emit(68, "正在切换兼容模式", "当前 CPU / oneDNN 初始化不兼容，关闭 MKL-DNN 后重新建立 OCR 引擎…")
            self._dispose_engine()
            compat_kwargs = dict(kwargs)
            compat_kwargs["enable_mkldnn"] = False
            compat_kwargs["mkldnn_cache_capacity"] = 1
            self._engine = create_engine(compat_kwargs)
            use_mkldnn = False
            self.startup_progress.emit(86, "兼容模式 OCR 引擎已加载", "PP-OCRv6 Medium DET / REC 已完成初始化。")

        self._engine_tier = tier
        self._compat_mode = not use_mkldnn
        return self._engine

    def _dispose_engine(self) -> None:
        self._engine = None
        self._engine_tier = None
        gc.collect()

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, int, int]:
        values: list[int] = []
        for part in version.split(".")[:3]:
            digits = "".join(ch for ch in part if ch.isdigit())
            values.append(int(digits or 0))
        while len(values) < 3:
            values.append(0)
        return tuple(values[:3])  # type: ignore[return-value]

    @staticmethod
    def _should_retry_compat(error: Exception) -> bool:
        text = str(error).lower()
        keywords = (
            "onednn",
            "mkldnn",
            "convertpirattribute2runtimeattribute",
            "pir::arrayattribute",
        )
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _prepare_input(input_path: Path, enhance: bool) -> Any:
        import numpy as np
        from PIL import Image, ImageEnhance, ImageOps

        image = Image.open(input_path).convert("RGB")
        width, height = image.size
        pixels = width * height

        # Cap huge desktop regions before they reach PP-OCRv6 Medium DET.
        max_side_cap = 1800 if enhance else 1600
        max_pixels = 2_200_000 if enhance else 1_800_000
        side_scale = max_side_cap / max(width, height) if max(width, height) > max_side_cap else 1.0
        pixel_scale = (max_pixels / max(1, pixels)) ** 0.5 if pixels > max_pixels else 1.0
        downscale = min(1.0, side_scale, pixel_scale)
        if downscale < 0.995:
            width = max(1, round(width * downscale))
            height = max(1, round(height * downscale))
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            pixels = width * height

        # Restrained small-text upscale, still bounded by the pixel budget.
        if enhance and pixels < 1_200_000 and min(width, height) < 520:
            max_scale = (1_200_000 / max(1, pixels)) ** 0.5
            scale = min(1.5, max(1.0, max_scale))
            if scale >= 1.08:
                image = image.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    Image.Resampling.LANCZOS,
                )

        if enhance:
            gray = image.convert("L")
            low, high = gray.getextrema()
            if high - low < 150:
                image = ImageOps.autocontrast(image, cutoff=0.2)
            image = ImageEnhance.Sharpness(image).enhance(1.08)

        return np.asarray(image)

    def _extract_text(self, results: Any) -> tuple[str, float, int]:
        all_items: list[dict[str, Any]] = []
        for result in results:
            data = self._result_to_dict(result)
            texts = self._as_list(data.get("rec_texts"))
            scores_raw = self._as_list(data.get("rec_scores"))
            boxes_value = data.get("rec_boxes")
            if boxes_value is None:
                boxes_value = data.get("rec_polys")
            boxes_raw = self._as_list(boxes_value)

            try:
                scores = [float(value) for value in scores_raw]
            except Exception:
                scores = []
            boxes = [self._normalize_box(value) for value in boxes_raw]

            for index, raw_text in enumerate(texts):
                text = str(raw_text).strip()
                if not text:
                    continue
                score = scores[index] if index < len(scores) else 0.0
                candidate_box = boxes[index] if index < len(boxes) else None
                box = candidate_box if candidate_box is not None and len(candidate_box) >= 4 else None
                all_items.append({"text": text, "score": score, "box": box})

        if not all_items:
            return "", 0.0, 0

        text, line_count = self._layout_text(all_items)
        valid_scores = [item["score"] for item in all_items if item["score"] > 0]
        avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
        return text.strip(), avg_score, line_count

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        """Convert Paddle/NumPy sequence results without boolean evaluation."""
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        try:
            return list(value)
        except (TypeError, ValueError):
            return [value]

    @staticmethod
    def _normalize_box(value: Any) -> list[float] | None:
        """Normalize [x1,y1,x2,y2] or polygon points to a bounding rectangle."""
        try:
            values = OCRService._as_list(value)
            if len(values) >= 4:
                flat_values: list[float] = []
                for item in values[:4]:
                    try:
                        flat_values.append(float(item))
                    except (TypeError, ValueError):
                        flat_values = []
                        break
                if len(flat_values) == 4:
                    return flat_values

            points: list[tuple[float, float]] = []
            for point in values:
                pair = OCRService._as_list(point)
                if len(pair) >= 2:
                    points.append((float(pair[0]), float(pair[1])))
            if not points:
                return None
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            return [min(xs), min(ys), max(xs), max(ys)]
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _result_to_dict(result: Any) -> dict[str, Any]:
        candidates: list[Any] = []
        if isinstance(result, dict):
            candidates.append(result)
        for attr_name in ("json", "res"):
            try:
                attr = getattr(result, attr_name)
                candidates.append(attr() if callable(attr) else attr)
            except Exception:
                pass

        for candidate in candidates:
            if isinstance(candidate, str):
                try:
                    candidate = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
            if isinstance(candidate, dict):
                nested = candidate.get("res")
                return nested if isinstance(nested, dict) else candidate
        try:
            return dict(result)
        except Exception as exc:
            raise RuntimeError("无法解析 OCR 返回结果。") from exc

    @staticmethod
    def _layout_text(items: list[dict[str, Any]]) -> tuple[str, int]:
        if any(item["box"] is None for item in items):
            texts = [item["text"] for item in items]
            return "\n".join(texts), len(texts)

        def box_height(item: dict[str, Any]) -> float:
            box = item["box"]
            return max(1.0, box[3] - box[1])

        ordered = sorted(items, key=lambda item: ((item["box"][1] + item["box"][3]) / 2, item["box"][0]))
        lines: list[list[dict[str, Any]]] = []
        for item in ordered:
            center_y = (item["box"][1] + item["box"][3]) / 2
            height = box_height(item)
            chosen: list[dict[str, Any]] | None = None
            best = float("inf")
            for line in lines:
                line_center = sum((x["box"][1] + x["box"][3]) / 2 for x in line) / len(line)
                line_height = sum(box_height(x) for x in line) / len(line)
                distance = abs(center_y - line_center)
                if distance <= max(height, line_height) * 0.55 and distance < best:
                    chosen = line
                    best = distance
            if chosen is None:
                lines.append([item])
            else:
                chosen.append(item)

        lines.sort(key=lambda line: min(item["box"][1] for item in line))
        output_lines: list[str] = []
        for line in lines:
            line.sort(key=lambda item: item["box"][0])
            chunks: list[str] = []
            previous: dict[str, Any] | None = None
            for item in line:
                if previous is not None and OCRService._needs_space(previous, item):
                    chunks.append(" ")
                chunks.append(item["text"])
                previous = item
            value = "".join(chunks).strip()
            if value:
                output_lines.append(value)
        return "\n".join(output_lines), len(output_lines)

    @staticmethod
    def _needs_space(previous: dict[str, Any], current: dict[str, Any]) -> bool:
        prev_text = previous["text"]
        curr_text = current["text"]
        if not prev_text or not curr_text:
            return False
        prev_box = previous["box"]
        curr_box = current["box"]
        gap = curr_box[0] - prev_box[2]
        height = max(1.0, min(prev_box[3] - prev_box[1], curr_box[3] - curr_box[1]))
        both_ascii = prev_text[-1].isascii() and curr_text[0].isascii()
        return both_ascii or gap > height * 0.45


# ---------- UI helpers ----------


class TitleBar(QWidget):
    def __init__(self, parent: QMainWindow) -> None:
        super().__init__(parent)
        self._window = parent
        self._drag_origin: QPoint | None = None
        self.setObjectName("TitleBar")
        self.setFixedHeight(54)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 10, 8)
        layout.setSpacing(9)

        mark = QLabel()
        mark.setObjectName("AppIcon")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(36, 36)
        icon_pixmap = QPixmap(str(resource_root() / "assets" / "app_icon.png"))
        if not icon_pixmap.isNull():
            mark.setPixmap(
                icon_pixmap.scaled(
                    34,
                    34,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(mark)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(APP_DISPLAY_NAME)
        title.setObjectName("AppTitle")
        subtitle = QLabel("区域识别 · 文本累计")
        subtitle.setObjectName("AppSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)

        self.pin_button = self._window_button("置顶", "PinButton")
        self.min_button = self._window_button("—", "WindowButton")
        self.max_button = self._window_button("□", "WindowButton")
        self.close_button = self._window_button("×", "CloseButton")
        self.pin_button.setCheckable(True)
        self.pin_button.clicked.connect(self._toggle_pin)
        self.min_button.clicked.connect(parent.showMinimized)
        self.max_button.clicked.connect(self._toggle_maximize)
        self.close_button.clicked.connect(parent.close)
        layout.addWidget(self.pin_button)
        layout.addWidget(self.min_button)
        layout.addWidget(self.max_button)
        layout.addWidget(self.close_button)

    @staticmethod
    def _window_button(text: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(30)
        if object_name != "PinButton":
            button.setFixedWidth(34)
        return button

    def set_pinned(self, pinned: bool) -> None:
        self.pin_button.setChecked(pinned)

    def _toggle_pin(self, checked: bool) -> None:
        self._window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self._window.show()
        self._window.raise_()

    def _toggle_maximize(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
            self.max_button.setText("□")
        else:
            self._window.showMaximized()
            self.max_button.setText("❐")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        window_handle = self._window.windowHandle()
        if window_handle is not None and window_handle.startSystemMove():
            self._drag_origin = None
            return
        self._drag_origin = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()


class EditRecordDialog(QDialog):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑本次识别文字")
        self.resize(720, 500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.editor = QPlainTextEdit(text)
        self.editor.setObjectName("DialogEditor")
        layout.addWidget(self.editor)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        save = QPushButton("保存修改")
        save.setObjectName("PrimaryButton")
        save.setDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)

    def text(self) -> str:
        return self.editor.toPlainText()


class HotkeyBridge(QObject):
    activated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.listener: Any | None = None

    def start(self) -> bool:
        try:
            from pynput import keyboard

            self.listener = keyboard.GlobalHotKeys({"<f8>": lambda: self.activated.emit()})
            self.listener.start()
            return True
        except Exception:
            self.listener = None
            write_log("hotkey", traceback.format_exc())
            return False

    def stop(self) -> None:
        if self.listener is not None:
            try:
                self.listener.stop()
            except Exception:
                pass


# ---------- Main window ----------



class ReorderHistoryList(QListWidget):
    """History list with deliberate long-press internal reordering."""

    order_changed = Signal(list)
    drag_state_changed = Signal(str)

    HOLD_DELAY_MS = 220
    HOLD_MOVE_TOLERANCE = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformItemSizes(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setAutoScroll(True)
        self.setAutoScrollMargin(56)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        self._press_pos: QPoint | None = None
        self._press_item: QListWidgetItem | None = None
        self._drag_armed = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(self.HOLD_DELAY_MS)
        self._hold_timer.timeout.connect(self._arm_drag)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        super().mousePressEvent(event)
        self._reset_drag_state(keep_cursor=False)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return
        self._press_pos = event.position().toPoint()
        self._press_item = item
        self._hold_timer.start()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return

        if self._press_pos is None or self._press_item is None:
            return

        distance = (event.position().toPoint() - self._press_pos).manhattanLength()
        if not self._drag_armed:
            if distance > self.HOLD_MOVE_TOLERANCE:
                self._hold_timer.stop()
                self._press_pos = None
                self._press_item = None
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._hold_timer.stop()
        super().mouseReleaseEvent(event)
        self._reset_drag_state()

    def leaveEvent(self, event: Any) -> None:
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self._reset_drag_state()
        super().leaveEvent(event)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        if not self._drag_armed:
            return
        try:
            super().startDrag(supported_actions)
        finally:
            self._reset_drag_state()

    def dropEvent(self, event: Any) -> None:
        before = self._item_ids()
        super().dropEvent(event)
        after = self._item_ids()
        self._reset_drag_state()
        if before != after:
            QTimer.singleShot(0, lambda ids=after: self.order_changed.emit(ids))

    def _arm_drag(self) -> None:
        if self._press_item is None:
            return
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            return
        self._drag_armed = True
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        self.drag_state_changed.emit("拖动到目标位置后松开鼠标即可保存顺序。")

    def _reset_drag_state(self, keep_cursor: bool = False) -> None:
        self._hold_timer.stop()
        was_armed = self._drag_armed
        self._press_pos = None
        self._press_item = None
        self._drag_armed = False
        if not keep_cursor:
            self.viewport().unsetCursor()
        if was_armed:
            self.drag_state_changed.emit("")

    def _item_ids(self) -> list[str]:
        return [
            str(self.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.count())
        ]


class StartupProgressDialog(QDialog):
    """Small deterministic startup window shared by source and published builds."""

    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.setFixedSize(560, 230)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if not icon.isNull():
            self.setWindowIcon(icon)

        surface = QFrame(self)
        surface.setObjectName("StartupSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("OCR 速记器 · 全量版")
        title.setObjectName("StartupTitle")
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("StartupPercent")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title, 1)
        header.addWidget(self.percent_label)
        layout.addLayout(header)

        self.stage_label = QLabel("正在启动…")
        self.stage_label.setObjectName("StartupStage")
        layout.addWidget(self.stage_label)

        self.detail_label = QLabel("检查程序资源与 PP-OCRv6 Medium 运行环境…")
        self.detail_label.setObjectName("StartupDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        layout.addWidget(self.progress_bar)

        hint = QLabel("首次初始化可能需要更久；后续模型与运行库会直接复用。")
        hint.setObjectName("StartupHint")
        layout.addWidget(hint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.addWidget(surface)

        self.setStyleSheet(
            """
            QFrame#StartupSurface {
                background: #171B24;
                border: 1px solid #303644;
                border-radius: 14px;
            }
            QLabel { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; }
            QLabel#StartupTitle { color: #F4F7FF; font-size: 16px; font-weight: 700; }
            QLabel#StartupPercent { color: #7FA9FF; font-size: 14px; font-weight: 700; }
            QLabel#StartupStage { color: #E9EDF7; font-size: 13px; font-weight: 700; }
            QLabel#StartupDetail { color: #AAB4C8; font-size: 12px; }
            QLabel#StartupHint { color: #69758C; font-size: 11px; }
            QProgressBar { background: #252C39; border: none; border-radius: 5px; }
            QProgressBar::chunk { background: #5B8CFF; border-radius: 5px; }
            """
        )

    @Slot(int, str, str)
    def set_progress(self, percent: int, stage: str, detail: str) -> None:
        value = max(0, min(100, int(percent)))
        self.progress_bar.setValue(value)
        self.percent_label.setText(f"{value}%")
        self.stage_label.setText(stage)
        self.detail_label.setText(detail)


class StartupCoordinator(QObject):
    """Own startup completion/failure handling on the Qt GUI thread.

    OCRService lives in a QThread. Connecting its completion signal to a plain
    Python closure can execute UI work from the worker thread depending on the
    binding/connection resolution. Keeping the receiver as a QObject created on
    the main thread guarantees queued delivery before touching any QWidget.
    """

    def __init__(
        self,
        app: QApplication,
        startup: StartupProgressDialog,
        window: "MainWindow",
    ) -> None:
        super().__init__(window)
        self._app = app
        self._startup = startup
        self._window = window
        self._finished = False

    @Slot()
    def on_initialized(self) -> None:
        if self._finished:
            return
        self._startup.set_progress(
            97,
            "正在加载历史记录与快捷键",
            "OCR 引擎已就绪，正在打开主窗口…",
        )
        QTimer.singleShot(80, self._show_main)

    @Slot()
    def _show_main(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        self._startup.set_progress(
            100,
            "准备完成",
            "PP-OCRv6 Medium 已加载，主界面已显示。",
        )
        QTimer.singleShot(100, self._startup.close)

    @Slot(str, str)
    def on_failed(self, message: str, log_path: str) -> None:
        if self._finished:
            return
        self._finished = True
        self._startup.close()
        QMessageBox.critical(
            None,
            "OCRCaptureTool Full 启动失败",
            f"OCR 引擎初始化失败：\n\n{message}\n\n详细日志：{log_path}",
        )
        self._window.close()
        self._app.quit()


class MainWindow(QMainWindow):
    request_ocr = Signal(str, str, str, float, bool)
    request_initialize = Signal()

    MODEL_TIER = "medium"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.resize(1080, 690)
        self.setMinimumSize(900, 570)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.store = HistoryStore()
        self.records = self.store.load()
        self.deleted_stack: list[list[tuple[int, HistoryRecord]]] = []
        self.pending_jobs: dict[str, dict[str, Any]] = {}
        self._ocr_status_timer = QTimer(self)
        self._ocr_status_timer.setInterval(1000)
        self._ocr_status_timer.timeout.connect(self._update_ocr_elapsed_status)
        self.overlay: ScreenSelectionOverlay | None = None
        self.capture_pending = False
        self.settings = QSettings("LonzilTools", APP_NAME)

        self._build_ui()
        self._apply_style()
        self._load_settings()
        self._refresh_all()

        self.ocr_thread = QThread(self)
        self.ocr_service = OCRService()
        self.ocr_service.moveToThread(self.ocr_thread)
        self.request_initialize.connect(self.ocr_service.initialize)
        self.request_ocr.connect(self.ocr_service.recognize)
        self.ocr_service.finished.connect(self._on_ocr_finished)
        self.ocr_service.failed.connect(self._on_ocr_failed)
        self.ocr_service.status.connect(self._set_status)
        self.ocr_thread.start()

        self.hotkey_bridge = HotkeyBridge()
        self.hotkey_bridge.activated.connect(self.start_capture)
        if self.hotkey_bridge.start():
            self._set_status("就绪。按 F8 或点击“截取识别”。", "ready")
        else:
            self._set_status("全局 F8 注册失败，仍可使用窗口按钮或窗口内 F8。", "warning")

    def begin_ocr_initialization(self) -> None:
        self.request_initialize.emit()

    def _build_ui(self) -> None:
        transparent = QWidget()
        outer = QVBoxLayout(transparent)
        outer.setContentsMargins(18, 18, 18, 18)

        self.surface = QFrame()
        self.surface.setObjectName("WindowSurface")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 145))
        self.surface.setGraphicsEffect(shadow)
        outer.addWidget(self.surface)
        self.setCentralWidget(transparent)

        root = QVBoxLayout(self.surface)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(self)
        root.addWidget(self.title_bar)

        body = QWidget()
        body.setObjectName("Body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 12, 16, 12)
        body_layout.setSpacing(12)
        root.addWidget(body, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.capture_button = QPushButton("＋  截取识别    F8")
        self.capture_button.setObjectName("PrimaryButton")
        self.capture_button.setMinimumHeight(38)
        self.capture_button.clicked.connect(self.start_capture)
        action_row.addWidget(self.capture_button)

        actions = (
            ("撤回", self.undo_last_capture),
            ("删除选中", self.delete_selected),
            ("恢复", self.restore_deleted),
            ("复制全部", self.copy_all),
            ("导出 TXT", self.export_txt),
            ("清空", self.clear_all),
        )
        for text, callback in actions:
            button = QPushButton(text)
            button.setObjectName("SecondaryButton")
            button.setMinimumHeight(38)
            button.clicked.connect(callback)
            action_row.addWidget(button)
        action_row.addStretch(1)
        body_layout.addLayout(action_row)

        settings_panel = QFrame()
        settings_panel.setObjectName("SettingsPanel")
        settings_row = QHBoxLayout(settings_panel)
        settings_row.setContentsMargins(12, 8, 12, 8)
        settings_row.setSpacing(10)

        model_label = QLabel("识别模型")
        model_label.setObjectName("MutedLabel")
        settings_row.addWidget(model_label)
        model_badge = QLabel("PP-OCRv6 Medium · 精准中文")
        model_badge.setObjectName("LocalBadge")
        model_badge.setToolTip("当前版本固定使用已验证的 Medium 模型，不再提供不完整的档位切换。")
        settings_row.addWidget(model_badge)

        self.enhance_checkbox = QCheckBox("智能小字增强")
        self.enhance_checkbox.setChecked(True)
        self.enhance_checkbox.setToolTip("只对较小截图进行轻量增强，不再固定放大 2 倍。")
        settings_row.addWidget(self.enhance_checkbox)

        self.header_checkbox = QCheckBox("显示批次标题")
        self.header_checkbox.setChecked(True)
        self.header_checkbox.toggled.connect(self._refresh_combined_text)
        settings_row.addWidget(self.header_checkbox)
        settings_row.addStretch(1)

        local_badge = QLabel("本地识别 · 内容不上传")
        local_badge.setObjectName("LocalBadge")
        settings_row.addWidget(local_badge)
        body_layout.addWidget(settings_panel)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        left_header = QHBoxLayout()
        left_title = QLabel("识别批次")
        left_title.setObjectName("PanelTitle")
        self.count_badge = QLabel("0")
        self.count_badge.setObjectName("CountBadge")
        left_header.addWidget(left_title)
        left_header.addStretch(1)
        left_header.addWidget(self.count_badge)
        left_layout.addLayout(left_header)
        left_hint = QLabel("双击编辑 · 长按拖动排序 · 支持多选删除")
        left_hint.setObjectName("PanelHint")
        left_layout.addWidget(left_hint)
        self.history_list = ReorderHistoryList()
        self.history_list.itemDoubleClicked.connect(self.edit_record)
        self.history_list.order_changed.connect(self._on_history_reordered)
        self.history_list.drag_state_changed.connect(self._on_history_drag_state)
        left_layout.addWidget(self.history_list)

        right_panel = QFrame()
        right_panel.setObjectName("Panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)
        right_title = QLabel("累计识别文字")
        right_title.setObjectName("PanelTitle")
        right_layout.addWidget(right_title)
        right_hint = QLabel("每次框选结果会持续追加，可直接复制或导出")
        right_hint.setObjectName("PanelHint")
        right_layout.addWidget(right_hint)
        self.combined_editor = QPlainTextEdit()
        self.combined_editor.setReadOnly(True)
        self.combined_editor.setUndoRedoEnabled(False)
        self.combined_editor.setPlaceholderText("按 F8 框选屏幕区域，识别结果会累计显示在这里。")
        right_layout.addWidget(self.combined_editor)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([320, 720])
        body_layout.addWidget(splitter, 1)

        status_panel = QFrame()
        status_panel.setObjectName("StatusPanel")
        status_row = QHBoxLayout(status_panel)
        status_row.setContentsMargins(12, 7, 8, 7)
        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("StatusReady")
        self.status_label = QLabel()
        self.status_label.setObjectName("StatusText")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label, 1)
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setObjectName("VersionLabel")
        status_row.addWidget(version_label)
        self.size_grip = QSizeGrip(self.surface)
        self.size_grip.setFixedSize(20, 20)
        status_row.addWidget(self.size_grip)
        body_layout.addWidget(status_panel)

        self.capture_shortcut = QShortcut(QKeySequence("F8"), self)
        self.capture_shortcut.activated.connect(self.start_capture)
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo_last_capture)
        self.delete_shortcut = QShortcut(QKeySequence("Delete"), self)
        self.delete_shortcut.activated.connect(self.delete_selected)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                color: #E9EDF7;
                font-family: "Microsoft YaHei UI", "Microsoft YaHei";
                font-size: 13px;
            }
            QWidget#Body, QWidget#TitleBar { background: transparent; }
            QFrame#WindowSurface {
                background: #171B24;
                border: 1px solid #303644;
                border-radius: 16px;
            }
            QWidget#TitleBar {
                background: #1B202B;
                border-bottom: 1px solid #2B3140;
                border-top-left-radius: 16px;
                border-top-right-radius: 16px;
            }
            QLabel#AppIcon {
                background: transparent;
                border: none;
            }
            QLabel#AppTitle { color: #F5F7FC; font-size: 15px; font-weight: 700; }
            QLabel#AppSubtitle { color: #7E899F; font-size: 11px; }
            QPushButton#WindowButton, QPushButton#CloseButton, QPushButton#PinButton {
                background: transparent;
                color: #AAB3C5;
                border: none;
                border-radius: 7px;
                padding: 4px 8px;
            }
            QPushButton#PinButton { min-width: 44px; }
            QPushButton#WindowButton:hover, QPushButton#PinButton:hover,
            QPushButton#PinButton:checked { background: #2A3140; color: #EEF2FC; }
            QPushButton#CloseButton:hover { background: #E05261; color: white; }
            QPushButton#PrimaryButton {
                background: #4C7DFF;
                color: white;
                border: 1px solid #638FFF;
                border-radius: 9px;
                padding: 8px 15px;
                font-weight: 700;
            }
            QPushButton#PrimaryButton:hover { background: #5B88FF; border-color: #7AA0FF; }
            QPushButton#PrimaryButton:pressed { background: #3E6FEA; }
            QPushButton#SecondaryButton, QDialog QPushButton {
                background: #232936;
                color: #DCE2F0;
                border: 1px solid #343C4D;
                border-radius: 9px;
                padding: 8px 13px;
            }
            QPushButton#SecondaryButton:hover, QDialog QPushButton:hover {
                background: #2A3241;
                border-color: #4B5A73;
                color: #FFFFFF;
            }
            QFrame#SettingsPanel, QFrame#StatusPanel {
                background: #1D222D;
                border: 1px solid #2C3341;
                border-radius: 11px;
            }
            QLabel#MutedLabel, QLabel#PanelHint { color: #8893A8; font-size: 12px; }
            QLabel#LocalBadge {
                color: #8ED9AE;
                background: #1B3027;
                border: 1px solid #2B5440;
                border-radius: 8px;
                padding: 4px 9px;
                font-size: 11px;
            }
            QComboBox {
                background: #141821;
                color: #E9EDF7;
                border: 1px solid #343C4D;
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 22px;
            }
            QComboBox:hover { border-color: #53637E; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView {
                background: #1B202A;
                color: #E9EDF7;
                border: 1px solid #3A4355;
                selection-background-color: #344E84;
                selection-color: white;
                outline: none;
            }
            QCheckBox { spacing: 7px; color: #C9D0DE; }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                background: #141821;
                border: 1px solid #465067;
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                background: #4C7DFF;
                border-color: #6B94FF;
            }
            QFrame#Panel {
                background: #1B202A;
                border: 1px solid #2D3442;
                border-radius: 12px;
            }
            QLabel#PanelTitle { color: #F2F4FA; font-size: 14px; font-weight: 700; }
            QLabel#CountBadge {
                color: #AFC2FF;
                background: #252E43;
                border: 1px solid #36476D;
                border-radius: 8px;
                padding: 3px 8px;
                font-size: 11px;
            }
            QListWidget, QPlainTextEdit {
                background: #11151D;
                color: #E7EBF4;
                border: 1px solid #29303E;
                border-radius: 9px;
                outline: none;
            }
            QListWidget { padding: 5px; }
            QListWidget::item {
                background: #181D27;
                color: #DCE2ED;
                border: 1px solid #252C3A;
                border-radius: 8px;
                padding: 9px;
                margin: 3px 0;
            }
            QListWidget::item:hover { background: #202735; border-color: #3A465D; }
            QListWidget::item:selected {
                background: #253552;
                color: #FFFFFF;
                border-color: #4C7DFF;
            }
            QPlainTextEdit {
                padding: 10px;
                selection-background-color: #4C7DFF;
                selection-color: white;
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Consolas";
                font-size: 14px;
            }
            QSplitter::handle { background: transparent; }
            QSplitter::handle:hover { background: #30394A; border-radius: 3px; }
            QLabel#StatusText { color: #AEB7C8; font-size: 12px; }
            QLabel#StatusReady { color: #79D6A2; font-size: 12px; }
            QLabel#StatusBusy { color: #75A0FF; font-size: 12px; }
            QLabel#StatusWarning { color: #E3B56A; font-size: 12px; }
            QLabel#StatusError { color: #EF7C86; font-size: 12px; }
            QLabel#VersionLabel { color: #647086; font-size: 11px; }
            QScrollBar:vertical {
                background: transparent; width: 10px; margin: 3px;
            }
            QScrollBar::handle:vertical {
                background: #394255; min-height: 28px; border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover { background: #4B5870; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QDialog { background: #171B24; color: #E9EDF7; }
            QPlainTextEdit#DialogEditor { background: #11151D; }
            QMessageBox { background: #171B24; }
            """
        )

    def _load_settings(self) -> None:
        self.enhance_checkbox.setChecked(self.settings.value("enhance", True, type=bool))
        self.header_checkbox.setChecked(self.settings.value("show_headers", True, type=bool))
        pinned = self.settings.value("always_on_top", False, type=bool)
        self.title_bar.set_pinned(pinned)
        if pinned:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    @Slot()
    def start_capture(self) -> None:
        if self.overlay is not None or self.capture_pending:
            return
        if len(self.pending_jobs) >= 2:
            self._set_status("已有识别任务排队，请稍后再截取。", "warning")
            return
        self.capture_pending = True
        self.hide()
        QTimer.singleShot(100, self._open_overlay)

    def _open_overlay(self) -> None:
        self.capture_pending = False
        try:
            self.overlay = ScreenSelectionOverlay()
            self.overlay.selected.connect(self._on_region_selected)
            self.overlay.canceled.connect(self._on_capture_canceled)
            self.overlay.destroyed.connect(self._overlay_destroyed)
            self.overlay.show()
        except Exception as exc:
            self.show()
            self.overlay = None
            QMessageBox.critical(self, "截图失败", str(exc))

    @Slot(QImage)
    def _on_region_selected(self, image: QImage) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

        job_id = uuid.uuid4().hex
        try:
            image_path = self.store.save_capture(image, job_id)
        except Exception as exc:
            QMessageBox.critical(self, "保存截图失败", str(exc))
            return

        tier = self.MODEL_TIER
        self.pending_jobs[job_id] = {
            "image_path": str(image_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "model_tier": tier,
            "started_monotonic": time.monotonic(),
        }
        if not self._ocr_status_timer.isActive():
            self._ocr_status_timer.start()
        self.capture_button.setEnabled(False)
        self._set_status(f"已截取 {image.width()} × {image.height()}，正在识别…", "busy")
        self.request_ocr.emit(
            job_id,
            str(image_path),
            tier,
            0.35,
            self.enhance_checkbox.isChecked(),
        )

    @Slot()
    def _on_capture_canceled(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._set_status("已取消截图。", "ready")

    @Slot()
    def _overlay_destroyed(self) -> None:
        self.overlay = None

    @Slot()
    def _update_ocr_elapsed_status(self) -> None:
        if not self.pending_jobs:
            self._ocr_status_timer.stop()
            return
        oldest = min(
            (float(job.get("started_monotonic", time.monotonic())) for job in self.pending_jobs.values()),
            default=time.monotonic(),
        )
        elapsed = max(0, int(time.monotonic() - oldest))
        if elapsed < 5:
            message = f"正在识别文字… {elapsed}s"
        elif elapsed < 15:
            message = f"正在识别文字… {elapsed}s · Medium 正在处理截图"
        else:
            message = f"仍在识别… {elapsed}s · Medium 已限制为快速输入尺寸"
        self._set_status(message, "busy")

    @Slot(str, str, float, int, str)
    def _on_ocr_finished(
        self,
        job_id: str,
        text: str,
        avg_score: float,
        line_count: int,
        runtime_mode: str,
    ) -> None:
        job = self.pending_jobs.pop(job_id, None)
        if job is None:
            return

        if not text.strip():
            self.store.remove_capture(job["image_path"])
            self._update_busy_state()
            QMessageBox.information(
                self,
                "未识别到文字",
                "该区域没有识别到可信文字。可扩大框选范围、切换精准档，或调整“小字增强”。",
            )
            return

        record = HistoryRecord(
            id=job_id,
            created_at=job["created_at"],
            text=text,
            avg_score=avg_score,
            line_count=line_count,
            image_path=job["image_path"],
            model_tier=job["model_tier"],
        )
        self.records.append(record)
        self.deleted_stack.clear()
        self.store.save(self.records)
        self._append_record_ui(record, len(self.records), select=True)
        self._update_busy_state()
        suffix = "，已使用兼容模式" if runtime_mode == "compat" else ""
        self._set_status(
            f"识别完成：{len(text)} 个字符，平均置信度 {avg_score * 100:.1f}%{suffix}。",
            "ready",
        )

    @Slot(str, str, str)
    def _on_ocr_failed(self, job_id: str, error: str, log_path: str) -> None:
        job = self.pending_jobs.pop(job_id, None)
        if job:
            self.store.remove_capture(job["image_path"])
        self._update_busy_state()
        QMessageBox.critical(
            self,
            "OCR 识别失败",
            f"{error}\n\n详细日志：\n{log_path}",
        )
        self._set_status("识别失败，已生成错误日志。", "error")

    def undo_last_capture(self) -> None:
        if not self.records:
            self._set_status("没有可撤回的识别批次。", "warning")
            return
        index = len(self.records) - 1
        record = self.records.pop()
        self.deleted_stack.append([(index, record)])
        self.store.save(self.records)
        self._refresh_all()
        self._set_status("已撤回最后一次识别，可点击“恢复”。", "ready")

    def delete_selected(self) -> None:
        selected = self.history_list.selectedItems()
        if not selected:
            self._set_status("请先在左侧选择要删除的识别批次。", "warning")
            return
        indexes = sorted(
            {self._record_index_from_item(item) for item in selected if self._record_index_from_item(item) >= 0},
            reverse=True,
        )
        deleted: list[tuple[int, HistoryRecord]] = []
        for index in indexes:
            deleted.append((index, self.records.pop(index)))
        deleted.sort(key=lambda pair: pair[0])
        if deleted:
            self.deleted_stack.append(deleted)
            self.store.save(self.records)
            self._refresh_all()
            self._set_status(f"已删除 {len(deleted)} 个批次，可点击“恢复”。", "ready")

    def restore_deleted(self) -> None:
        if not self.deleted_stack:
            self._set_status("没有可恢复的删除记录。", "warning")
            return
        deleted = self.deleted_stack.pop()
        for index, record in deleted:
            self.records.insert(min(max(0, index), len(self.records)), record)
        self.store.save(self.records)
        select_id = deleted[-1][1].id if deleted else None
        self._refresh_all(select_id=select_id)
        self._set_status(f"已恢复 {len(deleted)} 个批次。", "ready")

    def edit_record(self, item: QListWidgetItem) -> None:
        index = self._record_index_from_item(item)
        if index < 0:
            return
        dialog = EditRecordDialog(self.records[index].text, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.records[index].text = dialog.text().strip()
            self.records[index].line_count = len(self.records[index].text.splitlines())
            self.store.save(self.records)
            self._refresh_all(select_id=self.records[index].id)
            self._set_status("已保存修改。", "ready")

    def copy_all(self) -> None:
        text = self._plain_combined_text()
        if not text:
            self._set_status("没有可复制的文字。", "warning")
            return
        QApplication.clipboard().setText(text)
        self._set_status(f"已复制全部文字，共 {len(text)} 个字符。", "ready")

    def export_txt(self) -> None:
        text = self._plain_combined_text()
        if not text:
            self._set_status("没有可导出的文字。", "warning")
            return
        default_name = f"OCR识别结果_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "导出识别文字", default_name, "文本文件 (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8-sig")
            self._set_status(f"已导出：{path}", "ready")
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def clear_all(self) -> None:
        if not self.records:
            return
        answer = QMessageBox.question(
            self,
            "确认清空",
            "确定清空全部识别记录吗？本次清空仍可通过“恢复”找回。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.deleted_stack.append(list(enumerate(self.records)))
        self.records = []
        self.store.save(self.records)
        self._refresh_all()
        self._set_status("已清空全部记录，可点击“恢复”。", "ready")

    def _on_history_drag_state(self, message: str) -> None:
        if message:
            self._set_status(message, "ready")
        elif not self.pending_jobs:
            self._set_status("就绪。按 F8 或点击“截取识别”。", "ready")

    def _on_history_reordered(self, record_ids: list[str]) -> None:
        if len(record_ids) != len(self.records):
            self._refresh_all()
            return
        by_id = {record.id: record for record in self.records}
        if set(record_ids) != set(by_id):
            self._refresh_all()
            return

        self.records = [by_id[record_id] for record_id in record_ids]
        self.store.save(self.records)
        self._renumber_history_items()
        self._refresh_combined_text()
        self._set_status("识别批次顺序已保存。", "ready")

    def _renumber_history_items(self) -> None:
        by_id = {record.id: record for record in self.records}
        for index in range(self.history_list.count()):
            item = self.history_list.item(index)
            record_id = str(item.data(Qt.ItemDataRole.UserRole))
            record = by_id.get(record_id)
            if record is None:
                continue
            replacement = self._make_record_item(record, index + 1)
            item.setText(replacement.text())
            item.setToolTip(replacement.toolTip())

    def _refresh_all(self, select_id: str | None = None) -> None:
        self.history_list.setUpdatesEnabled(False)
        self.history_list.clear()
        selected_item: QListWidgetItem | None = None
        for index, record in enumerate(self.records, start=1):
            item = self._make_record_item(record, index)
            self.history_list.addItem(item)
            if record.id == select_id:
                selected_item = item
        self.history_list.setUpdatesEnabled(True)
        if selected_item is not None:
            selected_item.setSelected(True)
            self.history_list.scrollToItem(selected_item)
        self.count_badge.setText(str(len(self.records)))
        self._refresh_combined_text()

    def _append_record_ui(self, record: HistoryRecord, index: int, select: bool) -> None:
        item = self._make_record_item(record, index)
        self.history_list.addItem(item)
        if select:
            self.history_list.clearSelection()
            item.setSelected(True)
            self.history_list.scrollToItem(item)
        self.count_badge.setText(str(len(self.records)))

        if self.header_checkbox.isChecked():
            stamp = self._format_time(record.created_at, "%Y-%m-%d %H:%M:%S")
            block = f"【第 {index} 次识别 · {stamp}】\n{record.text.strip()}"
        else:
            block = record.text.strip()
        if self.combined_editor.toPlainText():
            self.combined_editor.appendPlainText("\n" + block)
        else:
            self.combined_editor.setPlainText(block)
        cursor = self.combined_editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.combined_editor.setTextCursor(cursor)

    def _make_record_item(self, record: HistoryRecord, index: int) -> QListWidgetItem:
        stamp = self._format_time(record.created_at, "%m-%d %H:%M:%S")
        score = f"{record.avg_score * 100:.1f}%" if record.avg_score > 0 else "--"
        preview = " ".join(record.text.split())
        if len(preview) > 40:
            preview = preview[:40] + "…"
        label = f"#{index:03d}   {stamp}\n{len(record.text)} 字 · {score}   {preview}"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, record.id)
        tooltip = record.text if len(record.text) <= 600 else record.text[:600] + "\n…"
        item.setToolTip(tooltip)
        return item

    def _refresh_combined_text(self) -> None:
        self.combined_editor.setUpdatesEnabled(False)
        if self.header_checkbox.isChecked():
            blocks = [
                f"【第 {index} 次识别 · {self._format_time(record.created_at, '%Y-%m-%d %H:%M:%S')}】\n{record.text.strip()}"
                for index, record in enumerate(self.records, start=1)
            ]
            text = "\n\n".join(blocks)
        else:
            text = self._plain_combined_text()
        self.combined_editor.setPlainText(text)
        cursor = self.combined_editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.combined_editor.setTextCursor(cursor)
        self.combined_editor.setUpdatesEnabled(True)

    def _plain_combined_text(self) -> str:
        return "\n\n".join(record.text.strip() for record in self.records if record.text.strip())

    def _record_index_from_item(self, item: QListWidgetItem) -> int:
        record_id = item.data(Qt.ItemDataRole.UserRole)
        for index, record in enumerate(self.records):
            if record.id == record_id:
                return index
        return -1

    @staticmethod
    def _format_time(value: str, fmt: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime(fmt)
        except ValueError:
            return value

    @Slot(str, str)
    def _set_status(self, message: str, state: str = "ready") -> None:
        self.status_label.setText(message)
        object_name = {
            "ready": "StatusReady",
            "busy": "StatusBusy",
            "warning": "StatusWarning",
            "error": "StatusError",
        }.get(state, "StatusReady")
        self.status_dot.setObjectName(object_name)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

    def _update_busy_state(self) -> None:
        busy = bool(self.pending_jobs)
        self.capture_button.setEnabled(not busy)
        if busy and not self._ocr_status_timer.isActive():
            self._ocr_status_timer.start()
        elif not busy and self._ocr_status_timer.isActive():
            self._ocr_status_timer.stop()

    def closeEvent(self, event: Any) -> None:
        self.settings.setValue("enhance", self.enhance_checkbox.isChecked())
        self.settings.setValue("show_headers", self.header_checkbox.isChecked())
        self.settings.setValue("always_on_top", self.title_bar.pin_button.isChecked())
        if not self.isMaximized():
            self.settings.setValue("geometry", self.saveGeometry())
        self.hotkey_bridge.stop()
        self.ocr_thread.quit()
        self.ocr_thread.wait(3500)
        super().closeEvent(event)


# ---------- Entrypoint ----------


def main() -> int:
    if "--self-test" in sys.argv:
        index = sys.argv.index("--self-test")
        output = sys.argv[index + 1] if len(sys.argv) > index + 1 else None
        return run_self_test(output)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("LonzilTools")

    app_icon = QIcon(str(resource_root() / "assets" / "app_icon.ico"))
    if app_icon.isNull():
        app_icon = QIcon(str(resource_root() / "assets" / "app_icon.png"))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    app.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, False)
    app.setEffectEnabled(Qt.UIEffect.UI_AnimateTooltip, False)
    install_exception_hook()

    startup = StartupProgressDialog(app_icon)
    startup.set_progress(2, "正在启动 OCR 速记器", "创建界面与 OCR 工作线程…")
    startup.show()
    startup.raise_()
    startup.activateWindow()
    app.processEvents()

    window = MainWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)

    window.ocr_service.startup_progress.connect(startup.set_progress)
    startup_coordinator = StartupCoordinator(app, startup, window)
    # Keep an explicit reference for the entire lifetime of the main window.
    window._startup_coordinator = startup_coordinator  # type: ignore[attr-defined]
    window.ocr_service.initialized.connect(startup_coordinator.on_initialized)
    window.ocr_service.initialization_failed.connect(startup_coordinator.on_failed)
    QTimer.singleShot(0, window.begin_ocr_initialization)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
