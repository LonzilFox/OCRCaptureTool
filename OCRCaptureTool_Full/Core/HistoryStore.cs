using System.Text.Json;

namespace OCRCaptureTool.Core;

public sealed class HistoryRecord
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public DateTime CreatedAt { get; set; } = DateTime.Now;
    public string Text { get; set; } = "";
    public double Score { get; set; }
    public int LineCount { get; set; }
    public string ImagePath { get; set; } = "";
}

public static class AppPaths
{
    public static string Root => Ensure(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "OCRCaptureTool"));
    public static string Captures => Ensure(Path.Combine(Root, "captures"));
    public static string Logs => Ensure(Path.Combine(Root, "logs"));
    private static string Ensure(string path) { Directory.CreateDirectory(path); return path; }
}

public static class Logs
{
    public static string Write(string name, string text)
    {
        var path = Path.Combine(AppPaths.Logs, $"{DateTime.Now:yyyyMMdd_HHmmss}_{name}.txt");
        File.WriteAllText(path, text);
        return path;
    }
}

public sealed class HistoryStore
{
    private readonly string _path = Path.Combine(AppPaths.Root, "history.json");
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public List<HistoryRecord> Load()
    {
        try
        {
            if (!File.Exists(_path)) return [];
            return JsonSerializer.Deserialize<List<HistoryRecord>>(File.ReadAllText(_path), JsonOptions) ?? [];
        }
        catch { return []; }
    }

    public void Save(IEnumerable<HistoryRecord> records)
    {
        var temp = _path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(records, JsonOptions));
        File.Move(temp, _path, true);
    }
}
