# OCRCaptureTool Full

当前版本：**v0.2.1**

Windows 区域截图 OCR 工具。按 **F8** 框选区域后，本地识别文字并持续累计历史。

## 技术栈

- .NET 8 / WPF（可由 .NET 8/9/10+ SDK 构建）
- RapidOcrNet 3.0.0
- ONNX Runtime + SkiaSharp
- PP-OCRv6 Medium

Medium：模型更大，优先识别精度。

## 运行

直接双击 `run.bat`。无需先执行安装脚本：

1. 自动检查 OCR 模型；缺失时自动修复。
2. 自动查找任意 **>= .NET 8 SDK**；已安装 .NET 9/10 会直接使用。
3. 如果完全没有可用 SDK，自动安装工程私有 `.dotnet` SDK。
4. 自动 restore/build；源码没变化时复用编译缓存。
5. 启动主程序。

调试启动：`run_debug.bat`。模型手动修复：`prepare_models.bat`。生成朋友版：`Release.bat`。

## GitHub

`.gitignore` 已排除 `.dotnet/`、`.cache/`、`bin/`、`obj/`、`logs/`、`release/` 等生成内容。
