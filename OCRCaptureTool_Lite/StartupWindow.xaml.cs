using System.Windows;

namespace OCRCaptureTool;

public partial class StartupWindow : Window
{
    public StartupWindow()
    {
        InitializeComponent();
    }

    public void SetProgress(int percent, string stage, string detail)
    {
        percent = Math.Clamp(percent, 0, 100);
        Progress.Value = percent;
        PercentText.Text = $"{percent}%";
        StageText.Text = stage;
        DetailText.Text = detail;
    }
}
