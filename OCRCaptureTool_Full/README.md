# OCRCaptureTool Full

Windows screen-region capture and offline text recognition with a dark desktop UI.

## OCR engine

- .NET 8 / WPF + RapidOcrNet 3.0.0 + ONNX Runtime
- PP-OCRv6 **Medium** detection and recognition models (approximately 130-140 MB before other runtime dependencies)
- Local inference; screenshots and recognized text are not uploaded for OCR
- Same interface and features as the other edition; only the OCR model profile differs

## Run from source

Only two Windows batch entry points are included: `run-dev.bat` and `build-release.bat`.

Double-click **`run-dev.bat`**. It automatically checks the OCR model files and a .NET SDK (version 8 or newer), downloads only what is missing, restores NuGet dependencies when required, builds the app, and opens the window. Run **`run-dev.bat debug`** from Command Prompt to retain diagnostic output if startup fails (no separate debug BAT is needed).

The first source run requires internet access if no compatible models or dependencies are already cached. Model downloads are verified with SHA-256 and stored once in `Models/v6/`; model weights and dictionaries are deliberately excluded from the Git repository. The developer launcher automatically validates and repairs this cache; no separate model setup batch file is needed.

## Usage

Press **F8** to select a screen region. The OCR result is added to a persistent history. The interface supports editing, reordering and deleting captures, undo/restore, copying the accumulated text, and exporting it to a text file.

## Create a portable release

Double-click **`build-release.bat`** to produce a Windows x64, self-contained release ZIP in `release/`. The release includes the required ONNX models and .NET desktop runtime, so recipients do not need the source SDK or a separate model download. Its internal folder name does not include the version.

## Disk usage

Source builds read models directly from `Models/v6/`, rather than copying them to `bin/`. Publication streams the final ZIP directly from one temporary publish directory, instead of keeping another complete release folder. `bin/`, `obj/`, `publish_tmp/`, `.dotnet/`, `.cache/`, `release/` and `logs/` are generated local data and are ignored by Git. After closing the app, you may manually delete `bin/`, `obj/`, and `publish_tmp/` to clear build intermediates without removing the downloaded models. NuGet's global cache is managed by .NET and is not removed.

## Requirements

- Windows 10/11 x64
- Internet access for first-time model and NuGet/SDK downloads, unless already cached
- A supported .NET SDK for source builds; `run-dev.bat` can bootstrap one if missing
