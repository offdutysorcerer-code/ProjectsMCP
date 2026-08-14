using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
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
            var infrastructure = await BuildInfrastructureSnapshotAsync();
            await SendAsync(new
            {
                type = "snapshot",
                generatedAt = DateTimeOffset.UtcNow,
                projectRoot = _projectRoot,
                runtimeRoot,
                stateExists = File.Exists(statePath),
                autoRefresh = _timer.IsEnabled,
                infrastructure,
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

    private async Task<object> BuildInfrastructureSnapshotAsync()
    {
        const int port = 8090;
        var listenerPid = FindListeningPid(port);
        var mcpReady = await ProbeMcpAsync(port);

        var configPath = Path.Combine(_projectRoot, "config.json");
        var config = await ReadJsonObjectAsync(configPath);
        var endpoint = config?["settings"]?["endpoint"] as JsonObject;
        var publicSseUrl = endpoint?["public_sse_url"]?.GetValue<string>() ?? string.Empty;
        var connectorEndpoint = endpoint?["active_connector_endpoint"]?.GetValue<string>() ?? string.Empty;
        var localSseUrl = endpoint?["local_sse_url"]?.GetValue<string>() ?? $"http://127.0.0.1:{port}/sse";

        var tunnelRoot = Path.Combine(Directory.GetParent(_projectRoot)!.FullName, "A0_1-ProjectsMCP_CloudFlareTunnel");
        var runtimeDir = Path.Combine(tunnelRoot, "runtime");
        var runningTunnels = new List<object>();
        if (Directory.Exists(runtimeDir))
        {
            foreach (var pidFile in Directory.GetFiles(runtimeDir, "*.pid").OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
            {
                var profile = Path.GetFileNameWithoutExtension(pidFile);
                if (!int.TryParse((await File.ReadAllTextAsync(pidFile)).Trim(), out var pid) || !IsProcessAlive(pid, "cloudflared"))
                    continue;

                var runtimeConfig = Path.Combine(runtimeDir, profile + ".config.yml");
                var hostConfig = Path.Combine(tunnelRoot, "hosts", profile, "config.yml");
                var tunnelConfig = File.Exists(runtimeConfig) ? runtimeConfig : hostConfig;
                var tunnelId = string.Empty;
                var hostname = string.Empty;
                if (File.Exists(tunnelConfig))
                {
                    var text = await File.ReadAllTextAsync(tunnelConfig);
                    tunnelId = Regex.Match(text, @"(?m)^\s*tunnel:\s*([^\s#]+)").Groups[1].Value.Trim();
                    hostname = Regex.Match(text, @"(?m)^\s*-\s*hostname:\s*([^\s#]+)").Groups[1].Value.Trim();
                }

                runningTunnels.Add(new { profile, pid, tunnelId, hostname, config = tunnelConfig });
            }
        }

        var activeTunnel = runningTunnels.FirstOrDefault();
        return new
        {
            mcp = new
            {
                running = listenerPid.HasValue && mcpReady,
                listenerPid,
                port,
                ready = mcpReady,
                localSseUrl
            },
            cloudflare = new
            {
                running = runningTunnels.Count > 0,
                tunnels = runningTunnels,
                active = activeTunnel
            },
            connector = new
            {
                publicSseUrl,
                connectorEndpoint,
                matchesPublic = !string.IsNullOrWhiteSpace(publicSseUrl) && string.Equals(publicSseUrl, connectorEndpoint, StringComparison.OrdinalIgnoreCase)
            }
        };
    }

    private static int? FindListeningPid(int port)
    {
        try
        {
            var psi = new ProcessStartInfo("netstat.exe", "-ano -p tcp")
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                CreateNoWindow = true
            };
            using var process = Process.Start(psi);
            if (process is null) return null;
            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(1500);
            foreach (var line in output.Split('\n'))
            {
                var parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 5 || !string.Equals(parts[3], "LISTENING", StringComparison.OrdinalIgnoreCase)) continue;
                if (!parts[1].EndsWith(":" + port, StringComparison.OrdinalIgnoreCase)) continue;
                if (int.TryParse(parts[^1], out var pid)) return pid;
            }
        }
        catch { }
        return null;
    }

    private static bool IsProcessAlive(int pid, string expectedName)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            return !process.HasExited && process.ProcessName.Contains(expectedName, StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    private static async Task<bool> ProbeMcpAsync(int port)
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
            using var response = await client.GetAsync($"http://127.0.0.1:{port}/mcp", HttpCompletionOption.ResponseHeadersRead);
            return (int)response.StatusCode < 500;
        }
        catch { return false; }
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
