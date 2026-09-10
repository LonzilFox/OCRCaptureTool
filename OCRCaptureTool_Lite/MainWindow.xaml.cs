using OCRCaptureTool.Core;
using OCRCaptureTool.Interop;
using System.Collections.ObjectModel;
using System.Drawing.Imaging;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace OCRCaptureTool;

public sealed class HistoryItemView
{
    public required HistoryRecord Record { get; init; }
    public string DisplayText { get; set; } = "";
}

public partial class MainWindow : Window
{
    private readonly HistoryStore _store = new();
    private readonly ObservableCollection<HistoryItemView> _items = [];
    private readonly Stack<List<(int Index, HistoryRecord Record)>> _deleted = new();
    private readonly OcrEngine _ocr;
    private readonly GlobalHotKey _hotKey = new();
    private System.Windows.Point _dragStart;
    private DateTime _mouseDownAt;
    private HistoryItemView? _dragItem;
    private bool _ready;
    private bool _captureInProgress;

    public MainWindow(OcrEngine ocr)
    {
        _ocr = ocr ?? throw new ArgumentNullException(nameof(ocr));
        InitializeComponent();
        HistoryList.ItemsSource = _items;
        foreach (var record in _store.Load()) _items.Add(new HistoryItemView { Record = record });
        RefreshViews();
        _ready = true;
        SetStatus("就绪。按 F8 或点击“截取识别”。", "ready");
        Loaded += (_, _) =>
        {
            _hotKey.Attach(this);
            _hotKey.Pressed += (_, _) => Dispatcher.Invoke(StartCapture);
        };
        Closed += (_, _) => { _hotKey.Dispose(); _ocr.Dispose(); };
    }

    private void Capture_Click(object sender, RoutedEventArgs e) => StartCapture();
    private async void StartCapture()
    {
        if (!_ready) { SetStatus("OCR 模型仍在加载", "busy"); return; }
        if (_captureInProgress) return;

        _captureInProgress = true;
        CaptureButton.IsEnabled = false;
        System.Drawing.Bitmap? image = null;
        Exception? captureError = null;
        try
        {
            Hide();
            await Task.Delay(100);

            var overlay = new CaptureOverlay();
            image = await overlay.CaptureAsync();
            captureError = overlay.CaptureError;
        }
        catch (Exception ex)
        {
            captureError = ex;
        }
        finally
        {
            Show();
            Activate();
            _captureInProgress = false;
        }

        if (image is null)
        {
            CaptureButton.IsEnabled = true;
            if (captureError is not null)
            {
                var log = Logs.Write("capture", captureError.ToString());
                SetStatus("截图失败", "error");
                MessageBox.Show(this, $"{captureError.Message}\n\n详细日志：{log}", "截图失败", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            else
            {
                SetStatus("已取消截图", "ready");
            }
            return;
        }

        using (image)
        {
        var id = Guid.NewGuid().ToString("N");
        var imagePath = Path.Combine(AppPaths.Captures, id + ".png");
        image.Save(imagePath, ImageFormat.Png);
        CaptureButton.IsEnabled = false; SetStatus("正在识别文字…", "busy");
        try
        {
            var result = await _ocr.RecognizeAsync(imagePath, EnhanceCheck.IsChecked == true);
            if (string.IsNullOrWhiteSpace(result.Text)) { File.Delete(imagePath); SetStatus("未识别到可信文字", "warning"); return; }
            var record = new HistoryRecord { Id=id, CreatedAt=DateTime.Now, Text=result.Text, Score=result.AverageScore, LineCount=result.LineCount, ImagePath=imagePath };
            _items.Add(new HistoryItemView { Record=record }); _deleted.Clear(); SaveAndRefresh();
            HistoryList.SelectedItem = _items.Last(); HistoryList.ScrollIntoView(_items.Last());
            SetStatus($"识别完成 · {result.Text.Length} 字", "ready");
        }
        catch (Exception ex)
        {
            try { File.Delete(imagePath); } catch { }
            var log = Logs.Write("ocr", ex.ToString()); SetStatus("识别失败", "error");
            MessageBox.Show(this, $"{ex.Message}\n\n详细日志：{log}", "OCR 识别失败", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally { CaptureButton.IsEnabled = true; }
        }
    }

    private void Undo_Click(object sender, RoutedEventArgs e)
    {
        if (_items.Count == 0) return; var index=_items.Count-1; var rec=_items[index].Record; _items.RemoveAt(index); _deleted.Push([(index,rec)]); SaveAndRefresh();
    }
    private void Delete_Click(object sender, RoutedEventArgs e)
    {
        var selected = HistoryList.SelectedItems.Cast<HistoryItemView>().ToList(); if (selected.Count==0) return;
        var deleted=new List<(int,HistoryRecord)>(); foreach(var item in selected.OrderByDescending(x=>_items.IndexOf(x))) { var i=_items.IndexOf(item); deleted.Add((i,item.Record)); _items.RemoveAt(i); }
        deleted.Reverse(); _deleted.Push(deleted); SaveAndRefresh();
    }
    private void Restore_Click(object sender, RoutedEventArgs e)
    {
        if(_deleted.Count==0)return; var group=_deleted.Pop(); foreach(var (index,rec) in group) _items.Insert(Math.Clamp(index,0,_items.Count), new HistoryItemView{Record=rec}); SaveAndRefresh();
    }
    private void Copy_Click(object sender, RoutedEventArgs e) { var t=PlainText(); if(t.Length>0) Clipboard.SetText(t); SetStatus("已复制全部文字", "ready"); }
    private void Export_Click(object sender, RoutedEventArgs e)
    {
        var dialog=new Microsoft.Win32.SaveFileDialog{Filter="文本文件 (*.txt)|*.txt",FileName=$"OCR识别结果_{DateTime.Now:yyyyMMdd_HHmmss}.txt"}; if(dialog.ShowDialog(this)==true) File.WriteAllText(dialog.FileName,PlainText());
    }
    private void Clear_Click(object sender, RoutedEventArgs e)
    {
        if(_items.Count==0)return; if(MessageBox.Show(this,"确定清空全部识别记录吗？可以使用“恢复最近删除”恢复。","确认清空",MessageBoxButton.YesNo)!=MessageBoxResult.Yes)return;
        var group=_items.Select((x,i)=>(i,x.Record)).ToList(); _items.Clear(); _deleted.Push(group); SaveAndRefresh();
    }

    private void History_MouseDown(object sender, MouseButtonEventArgs e)
    {
        _dragStart=e.GetPosition(HistoryList); _mouseDownAt=DateTime.Now; _dragItem=ItemFromPoint(_dragStart);
    }
    private void History_MouseMove(object sender, System.Windows.Input.MouseEventArgs e)
    {
        if(e.LeftButton!=MouseButtonState.Pressed||_dragItem is null)return;
        var p=e.GetPosition(HistoryList); if((DateTime.Now-_mouseDownAt).TotalMilliseconds<220)return;
        if(Math.Abs(p.X-_dragStart.X)<5&&Math.Abs(p.Y-_dragStart.Y)<5)return;
        DragDrop.DoDragDrop(HistoryList,_dragItem,DragDropEffects.Move); _dragItem=null;
    }
    private void History_Drop(object sender, System.Windows.DragEventArgs e)
    {
        if(!e.Data.GetDataPresent(typeof(HistoryItemView)))return; var source=(HistoryItemView)e.Data.GetData(typeof(HistoryItemView))!; var target=ItemFromPoint(e.GetPosition(HistoryList));
        if(target is null||ReferenceEquals(source,target))return; var old=_items.IndexOf(source); var index=_items.IndexOf(target); _items.Move(old,index); SaveAndRefresh(); HistoryList.SelectedItem=source;
    }
    private void History_DragOver(object sender, System.Windows.DragEventArgs e)
    {
        var p=e.GetPosition(HistoryList); if(HistoryList.Template.FindName("",HistoryList) is not null){}
        if(p.Y<35) Scroll(-35); else if(p.Y>HistoryList.ActualHeight-35) Scroll(35); e.Effects=DragDropEffects.Move; e.Handled=true;
    }
    private void Scroll(double delta)
    {
        var viewer=FindVisualChild<ScrollViewer>(HistoryList); viewer?.ScrollToVerticalOffset(viewer.VerticalOffset+delta);
    }
    private HistoryItemView? ItemFromPoint(System.Windows.Point p)
    {
        var element=HistoryList.InputHitTest(p) as DependencyObject; while(element is not null && element is not ListBoxItem) element=VisualTreeHelper.GetParent(element); return (element as ListBoxItem)?.DataContext as HistoryItemView;
    }
    private static T? FindVisualChild<T>(DependencyObject obj) where T:DependencyObject { for(int i=0;i<VisualTreeHelper.GetChildrenCount(obj);i++){var c=VisualTreeHelper.GetChild(obj,i); if(c is T t)return t; var r=FindVisualChild<T>(c); if(r is not null)return r;} return null; }

    private void History_DoubleClick(object sender, MouseButtonEventArgs e)
    {
        if(HistoryList.SelectedItem is not HistoryItemView item)return;
        var dlg=new Window{Owner=this,Title="编辑本次识别文字",Width=700,Height=480,WindowStartupLocation=WindowStartupLocation.CenterOwner,Background=(Brush)FindResource("Bg")};
        var grid=new Grid{Margin=new Thickness(12)}; grid.RowDefinitions.Add(new RowDefinition()); grid.RowDefinitions.Add(new RowDefinition{Height=GridLength.Auto});
        var tb=new System.Windows.Controls.TextBox{Text=item.Record.Text,AcceptsReturn=true,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto}; grid.Children.Add(tb);
        var btn=new Button{Content="保存",Margin=new Thickness(0,10,0,0),HorizontalAlignment=HorizontalAlignment.Right,Width=80,Style=(Style)FindResource("SecondaryButtonStyle")}; Grid.SetRow(btn,1); grid.Children.Add(btn); btn.Click+=(_,_)=>{item.Record.Text=tb.Text.Trim();item.Record.LineCount=item.Record.Text.Split('\n').Length;dlg.DialogResult=true;}; dlg.Content=grid;
        if(dlg.ShowDialog()==true) SaveAndRefresh();
    }

    private void Headers_Changed(object sender, RoutedEventArgs e) { if(IsLoaded) RefreshCombined(); }
    private void SaveAndRefresh() { _store.Save(_items.Select(x=>x.Record)); RefreshViews(); }
    private void RefreshViews()
    {
        for(int i=0;i<_items.Count;i++)
        {
            var r = _items[i].Record;
            var score = r.Score > 0 ? $"{r.Score * 100:F1}%" : "--";
            var preview = r.Text.Replace("\r", " ").Replace("\n", " ").Trim();
            if (preview.Length > 40) preview = preview[..40] + "…";
            _items[i].DisplayText = $"#{i + 1:000}   {r.CreatedAt:MM-dd HH:mm:ss}{Environment.NewLine}{r.Text.Length} 字 · {score}   {preview}";
        }
        HistoryList.Items.Refresh(); RefreshCombined(); CountBadge.Text=$"{_items.Count}";
    }
    private void RefreshCombined()
    {
        CombinedText.Text = HeadersCheck.IsChecked==true
            ? string.Join(Environment.NewLine+Environment.NewLine,_items.Select((x,i)=>$"【第 {i+1} 次识别 · {x.Record.CreatedAt:yyyy-MM-dd HH:mm:ss}】{Environment.NewLine}{x.Record.Text.Trim()}"))
            : PlainText();
        CombinedText.ScrollToEnd();
    }
    private string PlainText()=>string.Join(Environment.NewLine+Environment.NewLine,_items.Select(x=>x.Record.Text.Trim()).Where(x=>x.Length>0));

    private void SetStatus(string text, string state = "ready")
    {
        StatusText.Text = text;
        StatusDot.Foreground = state switch
        {
            "busy" => (Brush)FindResource("Busy"),
            "warning" => (Brush)FindResource("Warning"),
            "error" => (Brush)FindResource("Error"),
            _ => (Brush)FindResource("Green")
        };
    }

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e){ if(e.ClickCount==2){Max_Click(sender,e);return;} if(e.ButtonState==MouseButtonState.Pressed)DragMove(); }
    private void Pin_Click(object sender, RoutedEventArgs e)
    {
        Topmost = !Topmost;
        // Full keeps the label as “置顶”; only the checked chrome changes.
        // Do not change the text to “取消置顶”, otherwise the button box
        // becomes wider than Full and the title-bar layout visibly shifts.
        PinButton.Content = "置顶";
        PinButton.Foreground = Topmost ? new SolidColorBrush(Color.FromRgb(238, 242, 252)) : new SolidColorBrush(Color.FromRgb(170, 179, 197));
        PinButton.Background = Topmost ? new SolidColorBrush(Color.FromRgb(42, 49, 64)) : Brushes.Transparent;
        Activate();
    }

    private void Min_Click(object sender,RoutedEventArgs e)=>WindowState=WindowState.Minimized;
    private void Max_Click(object sender,RoutedEventArgs e)
    {
        WindowState = WindowState==WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
        MaxButton.Content = WindowState==WindowState.Maximized ? "❐" : "□";
    }
    private void Close_Click(object sender,RoutedEventArgs e)=>Close();
}
