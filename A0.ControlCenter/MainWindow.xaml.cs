using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Threading;
using Microsoft.Web.WebView2.Core;

namespace A0.ControlCenter;

public partial class MainWindow : Window
{
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(1) };
    private readonly JsonSerializerOptions _json = new(JsonSerializerDefaults.Web);
    private string _projectRoot = string.Empty;
    private bool _refreshing;

    public MainWindow()
    {
        InitializeComponent();
        Loaded += MainWindow_Loaded;
        Closed += (_, _) => _timer.Stop();
        _timer.Tick += async (_, _) => await SendSnapshotAsync();
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        try
        {
            _projectRoot = FindProjectRoot();
            await WebView.EnsureCoreWebView2Async();
            var webroot = Path.Combine(AppContext.BaseDirectory, "webroot");
            WebView.CoreWebView2.SetVirtualHostNameToFolderMapping(
                "a0.local",
                webroot,
                CoreWebView2HostResourceAccessKind.Allow);
            WebView.CoreWebView2.Settings.AreDevToolsEnabled = true;
            WebView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
            WebView.CoreWebView2.WebMessageReceived += CoreWebView2_WebMessageReceived;
            WebView.NavigationCompleted += async (_, _) =>
            {
                await SendSnapshotAsync();
                _timer.Start();
            };
            WebView.Source = new Uri("https://a0.local/index.html");
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.ToString(), "A0 Control Center 啟動失敗", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private async void CoreWebView2_WebMessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        try
        {
            var message = JsonSerializer.Deserialize<BridgeMessage>(e.WebMessageAsJson, _json);
            switch (message?.Action)
            {
                case "snapshot":
                    await SendSnapshotAsync();
                    break;
                case "setAutoRefresh":
                    if (message.Enabled == false) _timer.Stop();
                    else if (!_timer.IsEnabled) _timer.Start();
                    await SendAsync(new { type = "autoRefresh", enabled = _timer.IsEnabled });
                    break;
            }
        }
        catch (Exception ex)
        {
            await SendAsync(new { type = "error", message = ex.Message });
        }
    }

    private async Task SendSnapshotAsync()
    {
        if (_refreshing || WebView.CoreWebView2 is null) return;
        _refreshing = true;
        try
        {
            var runtimeRoot = Path.Combine(_projectRoot, "artifacts", "runtime");
            var statePath = Path.Combine(runtimeRoot, "state.json");
            var eventsPath = Path.Combine(runtimeRoot, "events");
            var state = await ReadJsonObjectAsync(statePath) ?? EmptyState();
            var events = await ReadRecentEventsAsync(eventsPath, 160);
            await SendAsync(new
            {
                type = "snapshot",
                generatedAt = DateTimeOffset.UtcNow,
                projectRoot = _projectRoot,
                runtimeRoot,
                stateExists = File.Exists(statePath),
                autoRefresh = _timer.IsEnabled,
                state,
                events
            });
        }
        catch (Exception ex)
        {
            await SendAsync(new { type = "error", message = ex.Message });
        }
        finally
        {
            _refreshing = false;
        }
    }

    private static async Task<JsonObject?> ReadJsonObjectAsync(string path)
    {
        if (!File.Exists(path)) return null;
        for (var attempt = 0; attempt < 3; attempt++)
        {
            try
            {
                var text = await File.ReadAllTextAsync(path);
                return JsonNode.Parse(text) as JsonObject;
            }
            catch (IOException) when (attempt < 2)
            {
                await Task.Delay(40);
            }
        }
        return null;
    }

    private static async Task<List<JsonNode?>> ReadRecentEventsAsync(string eventsDirectory, int limit)
    {
        if (!Directory.Exists(eventsDirectory)) return [];
        var files = Directory.GetFiles(eventsDirectory, "*.jsonl")
            .OrderByDescending(x => x, StringComparer.OrdinalIgnoreCase)
            .Take(3)
            .ToArray();
        var result = new List<JsonNode?>();
        foreach (var file in files)
        {
            var lines = await File.ReadAllLinesAsync(file);
            for (var i = lines.Length - 1; i >= 0 && result.Count < limit; i--)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                try { result.Add(JsonNode.Parse(lines[i])); }
                catch (JsonException) { }
            }
            if (result.Count >= limit) break;
        }
        result.Reverse();
        return result;
    }

    private static JsonObject EmptyState() => new()
    {
        ["updatedAt"] = null,
        ["tasks"] = new JsonArray(),
        ["agents"] = new JsonArray(),
        ["toolExecutions"] = new JsonArray(),
        ["claims"] = new JsonArray(),
        ["waits"] = new JsonArray(),
        ["dispatches"] = new JsonArray()
    };

    private string FindProjectRoot()
    {
        var configured = Environment.GetEnvironmentVariable("A0_PROJECTSMCP_ROOT");
        if (!string.IsNullOrWhiteSpace(configured) && Directory.Exists(configured))
            return Path.GetFullPath(configured);

        var current = new DirectoryInfo(AppContext.BaseDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, "server.py")) &&
                File.Exists(Path.Combine(current.FullName, "config.json")))
                return current.FullName;
            current = current.Parent;
        }

        throw new DirectoryNotFoundException(
            "找不到 A0-ProjectsMCP 根目錄。可設定 A0_PROJECTSMCP_ROOT 環境變數指定位置。");
    }

    private Task SendAsync(object payload)
    {
        if (WebView.CoreWebView2 is null) return Task.CompletedTask;
        WebView.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(payload, _json));
        return Task.CompletedTask;
    }

    private sealed class BridgeMessage
    {
        public string Action { get; set; } = string.Empty;
        public bool? Enabled { get; set; }
    }
}
