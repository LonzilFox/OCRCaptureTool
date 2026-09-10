OCRCaptureTool Lite 模型目录

Lite v0.2.0 使用 PP-OCRv6 Small + RapidOcrNet。
需要：
  Models\v6\PP-OCRv6_det_small.onnx
  Models\v6\PP-OCRv6_rec_small.onnx
  Models\v6\ppocrv6_small_dict.txt

prepare_models.bat 的顺序：
1. 校验工程内模型；
2. 自动搜索同级/附近 ScreenAssistant，找到相同且 SHA-256 正确的 Small 模型就直接复制，不联网；
3. 仅在本机完全找不到可复用模型时才联网修复。

朋友版发布包会把准备好的模型直接打进去。
