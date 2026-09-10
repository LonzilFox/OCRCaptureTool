using System.Runtime.InteropServices;

namespace OCRCaptureTool.Interop;

internal static class NativeDisplay
{
    internal const int SmXVirtualScreen = 76;
    internal const int SmYVirtualScreen = 77;
    internal const int SmCxVirtualScreen = 78;
    internal const int SmCyVirtualScreen = 79;

    // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    private static readonly nint PerMonitorAwareV2 = new(-4);

    [StructLayout(LayoutKind.Sequential)]
    internal struct Point
    {
        public int X;
        public int Y;
    }

    [DllImport("user32.dll")]
    private static extern bool SetProcessDpiAwarenessContext(nint value);

    [DllImport("user32.dll")]
    internal static extern int GetSystemMetrics(int index);

    [DllImport("user32.dll")]
    internal static extern bool GetCursorPos(out Point point);

    internal static void EnablePerMonitorV2()
    {
        try { _ = SetProcessDpiAwarenessContext(PerMonitorAwareV2); }
        catch { /* Older Windows / already configured: WPF can continue. */ }
    }
}
