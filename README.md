# OCRCaptureTool

A Windows screen-capture OCR tool offered in two independent editions. Both editions use the same dark interface, F8 region selection, history editing and rearrangement, undo/restore, text accumulation, clipboard copying, and TXT export. OCR processing runs locally.

| Edition | OCR model | Best for |
| --- | --- | --- |
| [OCRCaptureTool_Full](OCRCaptureTool_Full/) | PP-OCRv6 Medium | Higher-capacity model, more memory and disk usage |
| [OCRCaptureTool_Lite](OCRCaptureTool_Lite/) | PP-OCRv6 Small | Smaller footprint and quicker model setup |

## Start

Each edition contains exactly two batch entry points: `run-dev.bat` for development and `build-release.bat` for publishing.

Open either edition's folder and run `run-dev.bat`. Model weights, dictionaries, NuGet packages and any missing .NET SDK components are prepared on demand. The first run needs internet access if they are not already cached; subsequent launches reuse local files.

For error diagnostics, run `run-dev.bat debug` in Command Prompt. To create a standalone Windows x64 package for someone else, use `build-release.bat` in the corresponding edition. Release packages include the required OCR models and .NET desktop runtime; recipients do not need a development SDK.

## Repository and distribution

This repository intentionally contains **no ONNX model weights, recognition dictionaries, build output, logs or downloaded SDK files**. Both model installers validate downloaded artifacts with SHA-256 and can reuse matching local caches. Model downloads and package restoration are the first-run costs, not part of the initial source archive.

The source archive has an unversioned `OCRCaptureTool/` root containing this README and the `OCRCaptureTool_Full/` and `OCRCaptureTool_Lite/` projects. Only the outer source ZIP carries a version number.

## Disk space

Large generated directories are excluded from version control. `bin/` and `obj/` contain .NET build files; `publish_tmp/` is temporary; `release/` contains the final portable ZIP; `.dotnet/` is only used if a private SDK is needed. NuGet also maintains a shared package cache outside the repository. Source execution uses a **single copy** of each downloaded model, and each release is zipped directly from its publish directory without first making an additional full-size release folder.

After closing the app, you can manually remove `bin/`, `obj/`, and `publish_tmp/` to free build-intermediate space while keeping the cached OCR models. The next developer launch rebuilds as necessary.
