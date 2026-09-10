using System.Text;
using System.Windows;
using OCRCaptureTool.Interop;

namespace OCRCaptureTool;

internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        string? readyFile = null;
        string? failureFile = null;
        string? bootstrapLog = null;

        try
        {
            NativeDisplay.EnablePerMonitorV2();

            for (var i = 0; i < args.Length; i++)
            {
                if (string.Equals(args[i], "--ready-file", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                {
                    readyFile = Path.GetFullPath(args[++i]);
                    failureFile = readyFile + ".error";
                    break;
                }
            }

            var logDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "OCRCaptureToolLite", "logs");
            Directory.CreateDirectory(logDir);
            bootstrapLog = Path.Combine(logDir, "bootstrap_trace.log");
            File.WriteAllText(
                bootstrapLog,
                $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] Program.Main entered.\r\n",
                new UTF8Encoding(true));

            var app = new App();
            Trace(bootstrapLog, "App object created.");
            app.InitializeComponent();
            Trace(bootstrapLog, $"App.InitializeComponent completed. StartupUri = {app.StartupUri?.ToString() ?? "<null>"}.");

            // MainWindow requires an injected OcrEngine, so App.xaml must not use
            // StartupUri. WPF does not allow assigning null to StartupUri; verify
            // the invariant instead of trying to clear the property at runtime.
            if (app.StartupUri is not null)
                throw new InvalidOperationException($"App.xaml 不应设置 StartupUri，但当前值为：{app.StartupUri}。请清理 bin/obj 后重新编译。");

            Trace(bootstrapLog, "StartupUri verified as null; entering Application.Run().");
            return app.Run();
        }
        catch (Exception ex)
        {
            var details = ex.ToString();
            try
            {
                if (!string.IsNullOrWhiteSpace(bootstrapLog))
                    Trace(bootstrapLog, "TOP-LEVEL FATAL: " + details);
            }
            catch { }

            try
            {
                if (!string.IsNullOrWhiteSpace(failureFile))
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(failureFile)!);
                    File.WriteAllText(
                        failureFile,
                        $"{ex.GetBaseException().Message}\r\n{bootstrapLog ?? ""}\r\n\r\n{details}",
                        new UTF8Encoding(true));
                }
            }
            catch { }

            try
            {
                MessageBox.Show(
                    $"OCRCaptureTool Lite 启动失败：\n\n{ex.GetBaseException().Message}\n\n启动日志：{bootstrapLog ?? "（日志创建失败）"}",
                    "OCRCaptureTool Lite · 启动失败",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
            }
            catch { }

            return 1;
        }
    }

    private static void Trace(string path, string message)
    {
        File.AppendAllText(
            path,
            $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] {message}\r\n",
            new UTF8Encoding(true));
    }
}
