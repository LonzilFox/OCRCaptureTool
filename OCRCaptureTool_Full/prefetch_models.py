from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")

MODEL_NAMES = ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")


def model_is_complete(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "inference.json").is_file()
        and (path / "inference.pdiparams").is_file()
    )


def main() -> int:
    cache = Path.home() / ".paddlex" / "official_models"

    # PaddleX treats an existing directory as cached even when a previous
    # download/copy was interrupted. Remove incomplete folders first so the
    # official downloader can rebuild them instead of reusing broken content.
    for name in MODEL_NAMES:
        path = cache / name
        if path.exists() and not model_is_complete(path):
            print(f"Removing incomplete model cache: {path}")
            shutil.rmtree(path, ignore_errors=True)

    from paddleocr import PaddleOCR

    kwargs = {
        "text_detection_model_name": MODEL_NAMES[0],
        "text_recognition_model_name": MODEL_NAMES[1],
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "device": "cpu",
        # Model preparation only needs to verify the downloaded local files;
        # use the safe CPU path so publishing is not blocked by oneDNN/PIR.
        "enable_mkldnn": False,
        "mkldnn_cache_capacity": 4,
        "cpu_threads": max(2, min(8, (os.cpu_count() or 4) - 1)),
    }
    try:
        engine = PaddleOCR(**kwargs)
    except TypeError:
        kwargs.pop("mkldnn_cache_capacity", None)
        kwargs.pop("cpu_threads", None)
        engine = PaddleOCR(**kwargs)
    del engine

    invalid = [cache / name for name in MODEL_NAMES if not model_is_complete(cache / name)]
    if invalid:
        print("Medium model preparation failed. Missing required inference files:")
        for path in invalid:
            print("  ", path)
        return 2

    print("PP-OCRv6 Medium detection and recognition models are complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
