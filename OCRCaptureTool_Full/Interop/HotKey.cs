using System.Runtime.InteropServices;
using System.Windows.Interop;

namespace OCRCaptureTool.Interop;

public sealed class GlobalHotKey : IDisposable
{
    [DllImport("user32.dll")] private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint modifiers, uint vk);
    [DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    private readonly int _id = 0x0C8;
    private IntPtr _hwnd;
    private HwndSource? _source;
    public event EventHandler? Pressed;

    public void Attach(System.Windows.Window window)
    {
        _hwnd = new WindowInteropHelper(window).Handle;
        _source = HwndSource.FromHwnd(_hwnd);
        _source?.AddHook(Hook);
        RegisterHotKey(_hwnd, _id, 0, 0x77); // F8
    }

    private IntPtr Hook(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == 0x0312 && wParam.ToInt32() == _id) { Pressed?.Invoke(this, EventArgs.Empty); handled = true; }
        return IntPtr.Zero;
    }

    public void Dispose()
    {
        if (_hwnd != IntPtr.Zero) UnregisterHotKey(_hwnd, _id);
        if (_source is not null) _source.RemoveHook(Hook);
    }
}
