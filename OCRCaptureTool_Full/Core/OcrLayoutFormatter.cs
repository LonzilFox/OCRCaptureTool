using System.Collections;
using System.Reflection;
using System.Text;

namespace OCRCaptureTool.Core;

/// <summary>
/// Rebuilds reading order and simple table layouts from RapidOcrNet text-box geometry.
/// This is a geometry-based formatter, not a dedicated table-structure neural model.
/// </summary>
internal static class OcrLayoutFormatter
{
    private sealed record TextLine(string Text, double Left, double Top, double Right, double Bottom)
    {
        public double Width => Math.Max(1, Right - Left);
        public double Height => Math.Max(1, Bottom - Top);
        public double CenterY => (Top + Bottom) / 2;
    }

    private sealed class VisualRow
    {
        public List<TextLine> Items { get; } = [];
        public double Top => Items.Min(x => x.Top);
        public double Bottom => Items.Max(x => x.Bottom);
        public double CenterY => Items.Average(x => x.CenterY);
        public double Height => Math.Max(1, Bottom - Top);
    }

    public static (string Text, bool HasTable) Format(IEnumerable<object> blocks, string fallback)
    {
        var sourceBlocks = blocks.ToList();
        var lines = new List<TextLine>();
        var geometryFailures = 0;
        foreach (var block in sourceBlocks)
        {
            try
            {
                var blockLines = ReadLines(block);
                if (blockLines.Count == 0) geometryFailures++;
                else lines.AddRange(blockLines);
            }
            catch
            {
                geometryFailures++;
            }
        }

        if (lines.Count == 0 || geometryFailures > 0 ||
            lines.Count(x => x.Right > x.Left && x.Bottom > x.Top) < Math.Max(2, lines.Count / 2))
            return (NormalizeFallback(fallback), false);

        var rows = BuildRows(lines);
        if (rows.Count == 0) return (NormalizeFallback(fallback), false);

        var medianHeight = Median(lines.Select(x => x.Height));
        var table = TryBuildTable(rows, medianHeight);
        if (table is not null) return (table, true);

        return (BuildReadingOrder(rows, medianHeight), false);
    }

    private static List<TextLine> ReadLines(object block)
    {
        var type = block.GetType();
        var text = type.GetProperty("Text", BindingFlags.Public | BindingFlags.Instance)?.GetValue(block)?.ToString() ?? "";
        if (string.IsNullOrWhiteSpace(text)) return [];

        // RapidOcrNet can expose character/word polygons when ReturnWordBox is enabled.
        // Group adjacent CJK character boxes into text runs, while preserving wide gaps
        // between table cells on the same visual line.
        var wordResults = type.GetProperty("WordResults", BindingFlags.Public | BindingFlags.Instance)?.GetValue(block);
        if (wordResults is IEnumerable words)
        {
            var wordLines = new List<TextLine>();
            foreach (var word in words)
            {
                if (word is null) continue;
                var wordText = word.GetType().GetProperty("Text")?.GetValue(word)?.ToString() ?? "";
                var bounds = ReadBounds(word, wordText);
                if (bounds is not null && !string.IsNullOrWhiteSpace(wordText)) wordLines.Add(bounds);
            }

            if (wordLines.Count >= 2)
            {
                wordLines = wordLines.OrderBy(x => x.Left).ToList();
                var characterHeight = Median(wordLines.Select(x => x.Height));
                var splitGap = Math.Max(5, characterHeight * 0.9);
                var segments = new List<List<TextLine>>();
                foreach (var wordLine in wordLines)
                {
                    if (segments.Count == 0 || wordLine.Left - segments[^1][^1].Right > splitGap)
                        segments.Add([wordLine]);
                    else
                        segments[^1].Add(wordLine);
                }

                return segments.Select(segment => new TextLine(
                    JoinWordItems(segment), segment.Min(x => x.Left), segment.Min(x => x.Top),
                    segment.Max(x => x.Right), segment.Max(x => x.Bottom))).ToList();
            }
        }

        var line = ReadBounds(block, text);
        return line is null ? [] : [line];
    }

    private static TextLine? ReadBounds(object item, string text)
    {
        var pointsObject = item.GetType().GetProperty("BoxPoints", BindingFlags.Public | BindingFlags.Instance)?.GetValue(item);
        if (pointsObject is not IEnumerable points) return null;

        var xs = new List<double>();
        var ys = new List<double>();
        foreach (var point in points)
        {
            if (point is null) continue;
            var pointType = point.GetType();
            var x = pointType.GetProperty("X")?.GetValue(point) ?? pointType.GetField("X")?.GetValue(point);
            var y = pointType.GetProperty("Y")?.GetValue(point) ?? pointType.GetField("Y")?.GetValue(point);
            if (x is null || y is null) continue;
            try { xs.Add(Convert.ToDouble(x)); ys.Add(Convert.ToDouble(y)); }
            catch { }
        }
        if (xs.Count < 4 || ys.Count < 4) return null;
        return new TextLine(text.Trim(), xs.Min(), ys.Min(), xs.Max(), ys.Max());
    }

    private static string JoinWordItems(List<TextLine> items)
    {
        var sb = new StringBuilder(items[0].Text);
        for (var i = 1; i < items.Count; i++)
        {
            var previous = items[i - 1];
            var current = items[i];
            var gap = current.Left - previous.Right;
            if (NeedsWordSpace(previous.Text, current.Text) && gap > 2) sb.Append(' ');
            sb.Append(current.Text);
        }
        return sb.ToString();
    }

    private static List<VisualRow> BuildRows(List<TextLine> lines)
    {
        var result = new List<VisualRow>();
        foreach (var line in lines.OrderBy(x => x.CenterY).ThenBy(x => x.Left))
        {
            VisualRow? best = null;
            var bestDistance = double.MaxValue;
            foreach (var row in result.TakeLast(8))
            {
                var overlap = Math.Max(0, Math.Min(row.Bottom, line.Bottom) - Math.Max(row.Top, line.Top));
                var overlapRatio = overlap / Math.Max(1, Math.Min(row.Height, line.Height));
                var distance = Math.Abs(row.CenterY - line.CenterY);
                var tolerance = Math.Max(row.Height, line.Height) * 0.45;
                if (overlapRatio >= 0.38 || distance <= tolerance)
                {
                    if (distance < bestDistance) { best = row; bestDistance = distance; }
                }
            }
            if (best is null) { best = new VisualRow(); result.Add(best); }
            best.Items.Add(line);
        }

        foreach (var row in result) row.Items.Sort((a, b) => a.Left.CompareTo(b.Left));
        return result.OrderBy(x => x.Top).ToList();
    }

    private static string BuildReadingOrder(List<VisualRow> rows, double medianHeight)
    {
        var output = new StringBuilder();
        VisualRow? previous = null;
        foreach (var row in rows)
        {
            if (previous is not null)
            {
                var verticalGap = row.Top - previous.Bottom;
                output.Append(verticalGap > medianHeight * 1.35 ? "\n\n" : "\n");
            }
            output.Append(JoinLineItems(row.Items));
            previous = row;
        }
        return output.ToString().Trim();
    }

    private static string JoinLineItems(List<TextLine> items)
    {
        if (items.Count == 1) return items[0].Text;
        var sb = new StringBuilder(items[0].Text);
        for (var i = 1; i < items.Count; i++)
        {
            var previous = items[i - 1];
            var current = items[i];
            var gap = current.Left - previous.Right;
            var leftText = previous.Text;
            var rightText = current.Text;
            if (gap > Math.Max(previous.Height, current.Height) * 1.15) sb.Append("    ");
            else if (NeedsWordSpace(leftText, rightText) && gap > 2) sb.Append(' ');
            sb.Append(rightText);
        }
        return sb.ToString();
    }

    private static bool NeedsWordSpace(string left, string right)
    {
        if (left.Length == 0 || right.Length == 0) return false;
        var a = left[^1]; var b = right[0];
        return (char.IsAsciiLetterOrDigit(a) && char.IsAsciiLetterOrDigit(b)) ||
               (char.IsAsciiLetterOrDigit(a) && b > 127) || (a > 127 && char.IsAsciiLetterOrDigit(b));
    }

    private static string? TryBuildTable(List<VisualRow> rows, double medianHeight)
    {
        var multiRows = rows.Where(x => x.Items.Count >= 2).ToList();
        if (multiRows.Count < 2) return null;

        var starts = multiRows.SelectMany(x => x.Items).Select(x => x.Left).OrderBy(x => x).ToList();
        var tolerance = Math.Max(8, medianHeight * 0.75);
        var anchors = new List<double>();
        foreach (var x in starts)
        {
            if (anchors.Count == 0 || Math.Abs(x - anchors[^1]) > tolerance) anchors.Add(x);
            else anchors[^1] = (anchors[^1] + x) / 2;
        }
        if (anchors.Count < 2 || anchors.Count > 8) return null;

        var validRows = multiRows.Count(row => row.Items.Select(item => NearestAnchor(item.Left, anchors)).Distinct().Count() >= 2);
        if (validRows < 2 || validRows / (double)multiRows.Count < 0.75) return null;

        var first = rows.IndexOf(multiRows.First());
        var last = rows.IndexOf(multiRows.Last());
        var tableRows = new List<string[]>();
        var previousVisualRow = (VisualRow?)null;

        for (var rowIndex = first; rowIndex <= last; rowIndex++)
        {
            var row = rows[rowIndex];
            var cells = Enumerable.Repeat("", anchors.Count).ToArray();
            foreach (var item in row.Items)
            {
                var column = NearestAnchor(item.Left, anchors);
                cells[column] = AppendCell(cells[column], item.Text);
            }

            var populated = cells.Count(x => x.Length > 0);
            if (populated >= 2)
            {
                tableRows.Add(cells);
            }
            else if (populated == 1 && tableRows.Count > 0 && previousVisualRow is not null)
            {
                var gap = row.Top - previousVisualRow.Bottom;
                if (gap <= medianHeight * 2.8)
                {
                    var column = Array.FindIndex(cells, x => x.Length > 0);
                    tableRows[^1][column] = AppendCell(tableRows[^1][column], cells[column]);
                }
                else tableRows.Add(cells);
            }
            else if (populated > 0) tableRows.Add(cells);

            previousVisualRow = row;
        }

        if (tableRows.Count < 3) return null;
        var sb = new StringBuilder();
        // Keep text above the table (usually a title) in normal reading order.
        if (first > 0)
        {
            sb.Append(BuildReadingOrder(rows.Take(first).ToList(), medianHeight));
            sb.Append("\n\n");
        }

        sb.Append('|').Append(string.Join("|", Enumerable.Range(0, anchors.Count).Select(i => $" Column {i + 1} "))).AppendLine("|");
        sb.Append('|').Append(string.Join("|", anchors.Select(_ => " --- "))).AppendLine("|");
        foreach (var row in tableRows)
        {
            sb.Append('|');
            foreach (var cell in row) sb.Append(' ').Append(EscapeCell(cell)).Append(" |");
            sb.AppendLine();
        }

        if (last < rows.Count - 1)
        {
            sb.AppendLine();
            sb.Append(BuildReadingOrder(rows.Skip(last + 1).ToList(), medianHeight));
        }
        return sb.ToString().Trim();
    }

    private static int NearestAnchor(double x, List<double> anchors)
    {
        var best = 0; var distance = double.MaxValue;
        for (var i = 0; i < anchors.Count; i++)
        {
            var d = Math.Abs(x - anchors[i]);
            if (d < distance) { distance = d; best = i; }
        }
        return best;
    }

    private static string AppendCell(string current, string value) =>
        string.IsNullOrEmpty(current) ? value.Trim() : current + " <br> " + value.Trim();

    private static string EscapeCell(string value) => value.Replace("|", "\\|").Replace("\r", "").Replace("\n", " <br> ");

    private static double Median(IEnumerable<double> values)
    {
        var sorted = values.Where(x => x > 0).OrderBy(x => x).ToArray();
        if (sorted.Length == 0) return 16;
        var mid = sorted.Length / 2;
        return sorted.Length % 2 == 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
    }

    private static string NormalizeFallback(string text)
    {
        var lines = (text ?? "").Replace("\r\n", "\n").Replace('\r', '\n')
            .Split('\n').Select(x => x.TrimEnd()).ToList();
        var output = new List<string>();
        var blank = false;
        foreach (var line in lines)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                if (!blank && output.Count > 0) output.Add("");
                blank = true;
            }
            else { output.Add(line); blank = false; }
        }
        return string.Join(Environment.NewLine, output).Trim();
    }
}
