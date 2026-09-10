using RapidOcrNet;

namespace OCRCaptureTool.Core;

public sealed record OcrResult(string Text, double AverageScore, int LineCount);

public sealed class OcrEngine : IDisposable
{
    private RapidOcr? _ocr;
    private readonly string _modelDir = Path.Combine(AppContext.BaseDirectory, "Models", "v6");

    public static string ProgressDetail(int percent) => percent switch
    {
        <= 12 => "检查 PP-OCRv6 Small 检测/识别模型与 v6 字典",
        <= 24 => "加载 RapidOcrNet、ONNX Runtime 与 SkiaSharp 图像处理组件",
        <= 42 => "检测模型：PP-OCRv6_det_small.onnx",
        <= 70 => "识别模型：PP-OCRv6_rec_small.onnx",
        <= 90 => "中文字典：ppocrv6_small_dict.txt · 复用 v5 方向分类器",
        < 100 => "使用 PP-OCRv6 专用预处理参数校验 OCR 管线",
        _ => "PP-OCRv6 Small · RapidOcrNet 已就绪"
    };

    public async Task InitializeAsync(IProgress<(int Percent, string Message)>? progress = null)
    {
        await Task.Run(() =>
        {
            progress?.Report((8, "正在检查 PP-OCRv6 Small 模型文件"));
            var detPath = Path.Combine(_modelDir, "PP-OCRv6_det_small.onnx");
            var recPath = Path.Combine(_modelDir, "PP-OCRv6_rec_small.onnx");
            var dictPath = Path.Combine(_modelDir, "ppocrv6_small_dict.txt");
            foreach (var path in new[] { detPath, recPath, dictPath })
            {
                if (!File.Exists(path))
                    throw new FileNotFoundException($"OCR 模型文件缺失：{path}\n源码运行请先执行 prepare_models.bat；发布包应自带这些文件。", path);
            }

            progress?.Report((20, "正在加载 RapidOcrNet / ONNX Runtime"));
            Directory.SetCurrentDirectory(AppContext.BaseDirectory);
            var engine = new RapidOcr();
            var transferred = false;

            try
            {
                progress?.Report((34, "正在加载 PP-OCRv6 Small 检测模型"));
                var modelSet = RapidOcrModelSet.PPOCRv6Small with
                {
                    DetModelPath = detPath,
                    RecModelPath = recPath,
                    KeysPath = dictPath,
                };

                progress?.Report((58, "正在加载 PP-OCRv6 Small 识别模型"));
                engine.InitModels(modelSet);
                progress?.Report((86, "Small DET / REC 与方向分类器已加载"));

                // Keep the official v6 preprocessing preset in the live path.
                // No inference is forced here: startup stays fast and the first
                // real screenshot uses the exact same pipeline as later ones.
                _ = RapidOcrOptions.PPOCRv6;
                _ocr = engine;
                transferred = true;
                progress?.Report((96, "正在校验 PP-OCRv6 专用预处理参数"));
                progress?.Report((100, "OCR 引擎已就绪"));
            }
            finally
            {
                if (!transferred) engine.Dispose();
            }
        });
    }

    public async Task<OcrResult> RecognizeAsync(string imagePath, bool enhanceSmallText = true)
    {
        if (_ocr is null) throw new InvalidOperationException("OCR engine has not been initialized.");
        if (!File.Exists(imagePath)) throw new FileNotFoundException("截图文件不存在。", imagePath);

        return await Task.Run(() =>
        {
            // PP-OCRv6 must use the dedicated PPOCRv6 preset. The old hand-written
            // pipeline mixed a Medium recognizer with a v5 dictionary and could
            // therefore decode valid class IDs into gibberish characters.
            var options = RapidOcrOptions.PPOCRv6 with
            {
                LimitSideLen = enhanceSmallText ? 960 : 736,
                MaxSideLen = enhanceSmallText ? 2200 : 1800,
                TextScore = 0.35f,
            };

            var raw = _ocr.Detect(imagePath, options);
            var text = (raw.StrRes ?? string.Empty).Trim();
            var lineCount = 0;
            double scoreSum = 0;
            var scoreCount = 0;

            foreach (var block in raw.TextBlocks)
            {
                lineCount++;
                if (block.CharScores is null) continue;
                foreach (var score in block.CharScores)
                {
                    scoreSum += score;
                    scoreCount++;
                }
            }

            var average = scoreCount > 0 ? scoreSum / scoreCount : 0.0;
            return new OcrResult(text, average, lineCount);
        });
    }

    public void Dispose()
    {
        _ocr?.Dispose();
        _ocr = null;
    }
}
