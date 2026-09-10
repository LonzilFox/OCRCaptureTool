using OCRCaptureTool.Core;
using System.Text;
using System.Windows;
using System.Windows.Threading;

namespace OCRCaptureTool;

public partial class App : System.Windows.Application
{
    public const string Version = "0.2.1";
    private StartupWindow? _startupWindow;
    private string? _readyFile;
    private string? _failureFile;
    private string? _traceFile;
    private OcrEngine? _pendingOcr;

    protected override void OnStartup(StartupEventArgs e)
    {
        try
        {
            // Install exception hooks before calling into WPF startup logic.
            // This keeps even very-early startup failures inside our diagnostics.
            AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;
            DispatcherUnhandledException += App_DispatcherUnhandledException;
            TaskScheduler.UnobservedTaskException += TaskScheduler_UnobservedTaskException;

            if (StartupUri is not null)
                throw new InvalidOperationException($"App.xaml 不应设置 StartupUri，但当前值为：{StartupUri}。请清理 bin/obj 后重新编译。");

            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            ParseLauncherArguments(e.Args);
            Trace("OnStartup entered; StartupUri verified as null.");

            base.OnStartup(e);
            Trace("base.OnStartup completed.");

            _startupWindow = new StartupWindow();
            MainWindow = _startupWindow;
            _startupWindow.SetProgress(2, "正在启动 OCR 速记器", "创建启动窗口并检查 Full 运行资源…");
            _startupWindow.Show();
            _startupWindow.Activate();
            Trace("Startup progress window shown.");

            Dispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, new Action(() => _ = ContinueStartupAsync()));
        }
        catch (Exception ex)
        {
            HandleFatalStartupException(ex);
        }
    }

    private async Task ContinueStartupAsync()
    {
        try
        {
            Trace("ContinueStartupAsync started.");
            _startupWindow?.SetProgress(6, "正在创建 OCR 引擎", "准备 PP-OCRv6 Medium · RapidOcrNet / ONNX Runtime");
            _pendingOcr = new OcrEngine();

            var progress = new Progress<(int Percent, string Message)>(p =>
            {
                var percent = Math.Clamp(p.Percent, 6, 96);
                _startupWindow?.SetProgress(percent, p.Message, OcrEngine.ProgressDetail(p.Percent));
                Trace($"OCR init progress {percent}%: {p.Message}");
            });

            var initTask = _pendingOcr.InitializeAsync(progress);
            var initWinner = await Task.WhenAny(initTask, Task.Delay(TimeSpan.FromSeconds(90)));
            if (initWinner != initTask)
                throw new TimeoutException("PP-OCRv6 Medium 初始化超过 90 秒，已停止等待。请查看 startup_trace.log。 ");
            await initTask;
            Trace("ONNX OCR engine initialized.");

            _startupWindow?.SetProgress(97, "正在加载历史记录与快捷键", "OCR 引擎已就绪，正在创建与 Full 一致的主界面…");
            await Dispatcher.Yield(DispatcherPriority.Background);

            var main = new OCRCaptureTool.MainWindow(_pendingOcr);
            _pendingOcr = null; // ownership transferred to MainWindow
            Trace("MainWindow constructed.");

            var rendered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            RoutedEventHandler loadedHandler = (_, _) => rendered.TrySetResult(true);
            main.Loaded += loadedHandler;

            MainWindow = main;
            ShutdownMode = ShutdownMode.OnMainWindowClose;
            main.Show();
            main.Activate();
            Trace("MainWindow.Show() called.");

            var winner = await Task.WhenAny(rendered.Task, Task.Delay(5000));
            main.Loaded -= loadedHandler;
            if (winner != rendered.Task || !main.IsVisible)
                throw new InvalidOperationException("主窗口创建后未能正常显示。请查看 startup_trace.log。 ");

            _startupWindow?.SetProgress(100, "准备完成", "PP-OCRv6 Medium 已加载，主界面已显示。 ");
            WriteReadyMarker();
            Trace("READY marker written; main window visible.");
            await Task.Delay(120);

            if (_startupWindow is not null)
            {
                _startupWindow.Close();
                _startupWindow = null;
            }
        }
        catch (Exception ex)
        {
            HandleFatalStartupException(ex);
        }
    }

    private void ParseLauncherArguments(string[] args)
    {
        for (var i = 0; i < args.Length; i++)
        {
            if (string.Equals(args[i], "--ready-file", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
            {
                _readyFile = Path.GetFullPath(args[++i]);
                _failureFile = _readyFile + ".error";
            }
        }

        var logDir = AppPaths.Logs;
        _traceFile = Path.Combine(logDir, "startup_trace.log");
        try
        {
            File.WriteAllText(_traceFile, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] OCRCaptureTool Full v{Version} startup trace\r\n", new UTF8Encoding(true));
        }
        catch { }
    }

    private void Trace(string message)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(_traceFile)) return;
            File.AppendAllText(_traceFile, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] {message}\r\n", new UTF8Encoding(true));
        }
        catch { }
    }

    private void WriteReadyMarker()
    {
        if (string.IsNullOrWhiteSpace(_readyFile)) return;
        Directory.CreateDirectory(Path.GetDirectoryName(_readyFile)!);
        File.WriteAllText(_readyFile, $"READY|{Environment.ProcessId}|{DateTime.Now:O}", new UTF8Encoding(true));
        try { if (File.Exists(_failureFile)) File.Delete(_failureFile); } catch { }
    }

    private void WriteFailureMarker(Exception ex, string log)
    {
        if (string.IsNullOrWhiteSpace(_failureFile)) return;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_failureFile)!);
            File.WriteAllText(_failureFile, $"{ex.GetBaseException().Message}\r\n{log}", new UTF8Encoding(true));
        }
        catch { }
    }

    private void HandleFatalStartupException(Exception ex)
    {
        Trace("FATAL: " + ex);
        _pendingOcr?.Dispose();
        _pendingOcr = null;

        string log;
        try { log = Logs.Write("startup_fatal", ex.ToString()); }
        catch { log = _traceFile ?? "（日志写入失败）"; }
        WriteFailureMarker(ex, log);

        try
        {
            _startupWindow?.SetProgress(100, "启动失败", ex.GetBaseException().Message);
            _startupWindow?.Activate();
        }
        catch { }

        try
        {
            MessageBox.Show(
                $"OCRCaptureTool Full 启动失败：\n\n{ex.GetBaseException().Message}\n\n详细日志：{log}",
                "OCRCaptureTool Full · 启动失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
        catch { }

        try { _startupWindow?.Close(); } catch { }
        _startupWindow = null;
        Shutdown(1);
    }

    private void App_DispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        Trace("DispatcherUnhandledException: " + e.Exception);
        string log;
        try { log = Logs.Write("ui_unhandled", e.Exception.ToString()); } catch { log = _traceFile ?? "（日志写入失败）"; }
        WriteFailureMarker(e.Exception, log);
        try
        {
            MessageBox.Show(
                $"程序发生未处理异常：\n\n{e.Exception.GetBaseException().Message}\n\n详细日志：{log}",
                "OCRCaptureTool Full", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        catch { }
        e.Handled = true;
        Shutdown(2);
    }

    private void CurrentDomain_UnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        var ex = e.ExceptionObject as Exception ?? new Exception(e.ExceptionObject?.ToString() ?? "Unknown AppDomain exception");
        Trace("AppDomain unhandled: " + ex);
        try
        {
            var log = Logs.Write("domain_unhandled", ex.ToString());
            WriteFailureMarker(ex, log);
        }
        catch { }
    }

    private void TaskScheduler_UnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        Trace("Unobserved task exception: " + e.Exception);
        try { Logs.Write("task_unobserved", e.Exception.ToString()); } catch { }
        e.SetObserved();
    }
}
