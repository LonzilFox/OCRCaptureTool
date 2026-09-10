using OCRCaptureTool.Interop;
using DrawingBitmap = System.Drawing.Bitmap;
using DrawingCopyPixelOperation = System.Drawing.CopyPixelOperation;
using DrawingGraphics = System.Drawing.Graphics;
using DrawingPixelFormat = System.Drawing.Imaging.PixelFormat;
using MediaBrushes = System.Windows.Media.Brushes;
using MediaColor = System.Windows.Media.Color;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;

namespace OCRCaptureTool.Core;

/// <summary>
/// Full-screen selection overlay.
///
/// IMPORTANT: this window is intentionally non-modal. Calling Hide() on a
/// Window that is running inside ShowDialog() ends the modal loop before the
/// asynchronous screen capture finishes, so the caller sees the selection as
/// cancelled. CaptureAsync() keeps its own TaskCompletionSource instead.
/// </summary>
public sealed class CaptureOverlay : Window
{
    private readonly int _virtualLeftPx;
    private readonly int _virtualTopPx;
    private readonly int _virtualWidthPx;
    private readonly int _virtualHeightPx;
    private readonly Canvas _canvas = new();
    private readonly System.Windows.Shapes.Rectangle _selection = new()
    {
        Stroke = new SolidColorBrush(MediaColor.FromRgb(76, 125, 255)),
        StrokeThickness = 2,
        Fill = new SolidColorBrush(MediaColor.FromArgb(28, 76, 125, 255)),
        Visibility = Visibility.Collapsed,
        IsHitTestVisible = false,
    };

    private readonly TaskCompletionSource<DrawingBitmap?> _completion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    private System.Windows.Point _startDip;
    private NativeDisplay.Point _startPx;
    private bool _dragging;
    private bool _finishing;
    private bool _completed;

    public Exception? CaptureError { get; private set; }

    public CaptureOverlay()
    {
        _virtualLeftPx = NativeDisplay.GetSystemMetrics(NativeDisplay.SmXVirtualScreen);
        _virtualTopPx = NativeDisplay.GetSystemMetrics(NativeDisplay.SmYVirtualScreen);
        _virtualWidthPx = Math.Max(1, NativeDisplay.GetSystemMetrics(NativeDisplay.SmCxVirtualScreen));
        _virtualHeightPx = Math.Max(1, NativeDisplay.GetSystemMetrics(NativeDisplay.SmCyVirtualScreen));

        WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.NoResize;
        Topmost = true;
        ShowInTaskbar = false;
        AllowsTransparency = true;
        Background = MediaBrushes.Transparent;
        WindowStartupLocation = WindowStartupLocation.Manual;
        Left = SystemParameters.VirtualScreenLeft;
        Top = SystemParameters.VirtualScreenTop;
        Width = SystemParameters.VirtualScreenWidth;
        Height = SystemParameters.VirtualScreenHeight;
        Cursor = Cursors.Cross;

        // Keep the real desktop visible under a translucent dim layer. This
        // avoids stretching a pre-captured virtual-desktop bitmap through WPF
        // DIPs on mixed-DPI / multi-monitor systems.
        _canvas.Background = new SolidColorBrush(MediaColor.FromArgb(112, 0, 0, 0));
        _canvas.Children.Add(_selection);
        Content = _canvas;

        MouseLeftButtonDown += (_, e) => BeginDrag(e.GetPosition(_canvas));
        MouseMove += (_, e) =>
        {
            if (_dragging)
                UpdateDrag(e.GetPosition(_canvas));
        };
        MouseLeftButtonUp += async (_, e) => await CompleteDragAsync(e.GetPosition(_canvas));
        MouseRightButtonDown += (_, _) => Cancel();
        KeyDown += (_, e) =>
        {
            if (e.Key == Key.Escape)
                Cancel();
        };
        Loaded += (_, _) =>
        {
            Activate();
            Focus();
        };
        Closed += (_, _) =>
        {
            if (!_completed)
            {
                _completed = true;
                _completion.TrySetResult(null);
            }
        };
    }

    /// <summary>
    /// Shows the selector and completes only after a real crop has been
    /// captured, the user cancels, or capture fails.
    /// </summary>
    public Task<DrawingBitmap?> CaptureAsync()
    {
        Show();
        Activate();
        Focus();
        return _completion.Task;
    }

    private void BeginDrag(System.Windows.Point point)
    {
        if (_finishing || _completed)
            return;

        _startDip = point;
        if (!NativeDisplay.GetCursorPos(out _startPx))
            _startPx = DipToPhysical(point);

        _dragging = true;
        _selection.Visibility = Visibility.Visible;
        UpdateDrag(point);
        Mouse.Capture(this, CaptureMode.SubTree);
    }

    private void UpdateDrag(System.Windows.Point point)
    {
        var x = Math.Min(_startDip.X, point.X);
        var y = Math.Min(_startDip.Y, point.Y);
        var w = Math.Abs(point.X - _startDip.X);
        var h = Math.Abs(point.Y - _startDip.Y);
        Canvas.SetLeft(_selection, x);
        Canvas.SetTop(_selection, y);
        _selection.Width = w;
        _selection.Height = h;
    }

    private async Task CompleteDragAsync(System.Windows.Point point)
    {
        if (!_dragging || _finishing || _completed)
            return;

        _dragging = false;
        _finishing = true;
        Mouse.Capture(null);
        UpdateDrag(point);

        if (_selection.Width < 6 || _selection.Height < 6)
        {
            Cancel();
            return;
        }

        if (!NativeDisplay.GetCursorPos(out var endPx))
            endPx = DipToPhysical(point);

        var left = Math.Min(_startPx.X, endPx.X);
        var top = Math.Min(_startPx.Y, endPx.Y);
        var right = Math.Max(_startPx.X, endPx.X);
        var bottom = Math.Max(_startPx.Y, endPx.Y);

        left = Math.Clamp(left, _virtualLeftPx, _virtualLeftPx + _virtualWidthPx - 1);
        top = Math.Clamp(top, _virtualTopPx, _virtualTopPx + _virtualHeightPx - 1);
        right = Math.Clamp(right, left + 1, _virtualLeftPx + _virtualWidthPx);
        bottom = Math.Clamp(bottom, top + 1, _virtualTopPx + _virtualHeightPx);

        var width = right - left;
        var height = bottom - top;
        if (width < 4 || height < 4)
        {
            Cancel();
            return;
        }

        try
        {
            // Non-modal Hide() is safe here: it no longer terminates a
            // ShowDialog() call. Yield one render pass plus a short delay so
            // DWM has removed the dim overlay before CopyFromScreen runs.
            Hide();
            await System.Windows.Threading.Dispatcher.Yield(DispatcherPriority.ApplicationIdle);
            await Task.Delay(70);

            var bitmap = new DrawingBitmap(width, height, DrawingPixelFormat.Format32bppArgb);
            using (var graphics = DrawingGraphics.FromImage(bitmap))
            {
                graphics.CopyFromScreen(
                    left,
                    top,
                    0,
                    0,
                    new System.Drawing.Size(width, height),
                    DrawingCopyPixelOperation.SourceCopy);
            }

            Complete(bitmap);
        }
        catch (Exception ex)
        {
            CaptureError = ex;
            Complete(null);
        }
    }

    private void Complete(DrawingBitmap? bitmap)
    {
        if (_completed)
        {
            bitmap?.Dispose();
            return;
        }

        _completed = true;
        _completion.TrySetResult(bitmap);
        try { Close(); } catch { }
    }

    private void Cancel()
    {
        if (_completed)
            return;

        _dragging = false;
        _finishing = true;
        Mouse.Capture(null);
        Complete(null);
    }

    private NativeDisplay.Point DipToPhysical(System.Windows.Point localPoint)
    {
        var sx = _virtualWidthPx / Math.Max(1.0, ActualWidth);
        var sy = _virtualHeightPx / Math.Max(1.0, ActualHeight);
        return new NativeDisplay.Point
        {
            X = _virtualLeftPx + (int)Math.Round(localPoint.X * sx),
            Y = _virtualTopPx + (int)Math.Round(localPoint.Y * sy)
        };
    }
}
