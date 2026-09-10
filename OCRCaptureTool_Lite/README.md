# OCRCaptureTool Lite

当前版本：**v0.2.0**

OCRCaptureTool Lite 是一个 Windows 区域截图 OCR 工具。按 **F8** 框选屏幕区域后，使用 **PP-OCRv6 Small + RapidOcrNet/ONNX Runtime** 在本地识别中文，并将结果持续累计到历史记录中。

## 主要功能

- F8 全局快捷键框选 OCR
- PP-OCRv6 Small 中文识别
- 与 Full 对齐的主界面与交互
- 识别历史、编辑、删除、撤回、恢复与拖动排序
- 复制全部与导出 TXT
- 本地处理，截图内容不上传
- 模型/启动进度显示

## 使用

正常启动：

```text
run.bat
```

调试启动：

```text
run_debug.bat
```

检查或准备 PP-OCRv6 Small 模型：

```text
prepare_models.bat
```

生成 self-contained Windows x64 发布包：

```text
Release.bat
```

发布产物位于 `release/`，该目录不会提交到 Git。

## 技术栈

- .NET 8 / WPF
- RapidOcrNet 3.0.0
- ONNX Runtime
- PP-OCRv6 Small

## Full / Lite

Lite 与 Full 保持同一套 UI 和主要功能，只更换 OCR 后端与模型档位。Lite 重点降低发布体积和运行环境复杂度；Full 使用 PP-OCRv6 Medium + PaddleOCR 作为高精度基准版本。
