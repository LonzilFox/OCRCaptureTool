# OCRCaptureTool Full

当前版本：**v0.2.0**

OCRCaptureTool Full 是一个 Windows 区域截图 OCR 工具。按 **F8** 框选屏幕区域后，使用 **PP-OCRv6 Medium + PaddleOCR/PaddlePaddle** 在本地识别中文，并将结果持续累计到历史记录中。

## 主要功能

- F8 全局快捷键框选 OCR
- PP-OCRv6 Medium 中文识别
- 小字增强与大截图输入限制
- 识别历史、编辑、删除、撤回、恢复与拖动排序
- 复制全部与导出 TXT
- 本地处理，截图内容不上传
- 启动/模型初始化进度显示

## 使用

源码环境首次运行：

```text
install_cpu.bat
run.bat
```

调试启动：

```text
run_debug.bat
```

生成给其他 Windows 用户使用的离线发布包：

```text
Release.bat
```

发布产物位于 `release/`，该目录不会提交到 Git。

## 技术栈

- Python 3.12
- PySide6
- PaddlePaddle 3.2.2 CPU
- PaddleOCR 3.7.0
- PP-OCRv6 Medium

## Full / Lite

Full 优先保持 PaddleOCR 官方推理链路和识别精度，用作高精度/基准版本。Lite 使用 .NET/WPF + RapidOcrNet + PP-OCRv6 Small，重点降低体积并简化运行环境。
