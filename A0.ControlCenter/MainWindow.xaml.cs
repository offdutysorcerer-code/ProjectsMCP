using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
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
    private string _environment = "MAIN";
    private string _configPath = string.Empty;
    private string _runtimeRoot = string.Empty;
    private bool _refreshing;
    private object? _cachedInfrastructure;
    private DateTimeOffset _infrastructureCachedAt = DateTimeOffset.MinValue;

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
            ResolveRuntimeProfile();
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
                await SendSnapshotAsync(forceInfrastructure: true);
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
                    await SendSnapshotAsync(forceInfrastructure: true);
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

    private async Task SendSnapshotAsync(bool forceInfrastructure = false)
    {
        if (_refreshing || WebView.CoreWebView2 is null) return;
        _refreshing = true;
        try
        {
            var runtimeRoot = _runtimeRoot;
            var statePath = Path.Combine(runtimeRoot, "state.json");
            var eventsPath = Path.Combine(runtimeRoot, "events");
            var state = await ReadJsonObjectAsync(statePath) ?? EmptyState();
            var events = await ReadRecentEventsAsync(eventsPath, 160);
            var infrastructure = await GetInfrastructureSnapshotAsync(forceInfrastructure);
            await SendAsync(new
            {
                type = "snapshot",
                generatedAt = DateTimeOffset.UtcNow,
                projectRoot = _projectRoot,
                environment = _environment,
                configPath = _configPath,
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
            var lines = await ReadTailLinesAsync(file, Math.Max(limit - result.Count, 1) * 2);
            for (var i = lines.Count - 1; i >= 0 && result.Count < limit; i--)
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

    private static async Task<List<string>> ReadTailLinesAsync(
        string path,
        int limit,
        int maxScanBytes = 4 * 1024 * 1024)
    {
        const int chunkSize = 64 * 1024;
        await using var stream = new FileStream(
            path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete,
            chunkSize, FileOptions.Asynchronous | FileOptions.RandomAccess);
        var chunks = new List<byte[]>();
        var position = stream.Length;
        var newlineCount = 0;
        var scanned = 0;
        while (position > 0 && scanned < maxScanBytes && newlineCount <= limit)
        {
            var count = (int)Math.Min(Math.Min(chunkSize, position), maxScanBytes - scanned);
            position -= count;
            stream.Seek(position, SeekOrigin.Begin);
            var chunk = new byte[count];
            var read = 0;
            while (read < count)
            {
                var current = await stream.ReadAsync(chunk.AsMemory(read, count - read));
                if (current == 0) break;
                read += current;
            }
            if (read != count) Array.Resize(ref chunk, read);
            newlineCount += chunk.Count(value => value == (byte)'\n');
            chunks.Add(chunk);
            scanned += read;
            if (read == 0) break;
        }

        chunks.Reverse();
        var bytes = new byte[chunks.Sum(chunk => chunk.Length)];
        var offset = 0;
        foreach (var chunk in chunks)
        {
            Buffer.BlockCopy(chunk, 0, bytes, offset, chunk.Length);
            offset += chunk.Length;
        }
        var start = 0;
        if (position > 0)
        {
            var firstNewline = Array.IndexOf(bytes, (byte)'\n');
            if (firstNewline < 0) return [];
            start = firstNewline + 1;
        }
        return Encoding.UTF8.GetString(bytes, start, bytes.Length - start)
            .Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .TakeLast(limit)
            .Select(line => line.TrimEnd('\r'))
            .ToList();
    }

    private async Task<object> GetInfrastructureSnapshotAsync(bool forceRefresh)
    {
        var now = DateTimeOffset.UtcNow;
        if (!forceRefresh &&
            _cachedInfrastructure is not null &&
            now - _infrastructureCachedAt < TimeSpan.FromSeconds(5))
            return _cachedInfrastructure;

        _cachedInfrastructure = await BuildInfrastructureSnapshotAsync();
        _infrastructureCachedAt = now;
        return _cachedInfrastructure;
    }

    private async Task<object> BuildInfrastructureSnapshotAsync()
    {
        var config = await ReadJsonObjectAsync(_configPath);
        var endpoint = config?["settings"]?["endpoint"] as JsonObject;
        var publicSseUrl = endpoint?["public_sse_url"]?.GetValue<string>() ?? string.Empty;
        var connectorEndpoint = endpoint?["active_connector_endpoint"]?.GetValue<string>() ?? string.Empty;
        var configuredLocalSseUrl = endpoint?["local_sse_url"]?.GetValue<string>() ?? string.Empty;
        if (!Uri.TryCreate(configuredLocalSseUrl, UriKind.Absolute, out var localSseUri) ||
            (localSseUri.Scheme != Uri.UriSchemeHttp && localSseUri.Scheme != Uri.UriSchemeHttps))
            localSseUri = new Uri("http://127.0.0.1:8090/sse");

        var localSseUrl = localSseUri.ToString();
        var port = localSseUri.Port;
        var listenerPid = FindListeningPid(port);
        var mcpReady = await ProbeMcpAsync(localSseUri);

        var tunnelRoot = Path.Combine(Directory.GetParent(_projectRoot)!.FullName, "A0_1-ProjectsMCP_CloudFlareTunnel");
        var runtimeDir = Path.Combine(tunnelRoot, "runtime");
        var runningTunnels = new List<TunnelSnapshot>();
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

                runningTunnels.Add(new TunnelSnapshot(profile, pid, tunnelId, hostname, tunnelConfig));
            }
        }

        var publicHostname = Uri.TryCreate(publicSseUrl, UriKind.Absolute, out var publicUri)
            ? publicUri.Host
            : string.Empty;
        var activeTunnel = runningTunnels.FirstOrDefault(tunnel =>
                !string.IsNullOrWhiteSpace(publicHostname) &&
                string.Equals(tunnel.Hostname, publicHostname, StringComparison.OrdinalIgnoreCase))
            ?? runningTunnels.FirstOrDefault();
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
                matchesPublic = !string.IsNullOrWhiteSpace(publicSseUrl) && EndpointEquals(publicSseUrl, connectorEndpoint),
                verification = "configuration_only"
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

    private static async Task<bool> ProbeMcpAsync(Uri localSseUri)
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
            using var response = await client.GetAsync(localSseUri, HttpCompletionOption.ResponseHeadersRead);
            var mediaType = response.Content.Headers.ContentType?.MediaType;
            return response.IsSuccessStatusCode &&
                   string.Equals(mediaType, "text/event-stream", StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    private static bool EndpointEquals(string left, string right)
    {
        if (!Uri.TryCreate(left, UriKind.Absolute, out var leftUri) ||
            !Uri.TryCreate(right, UriKind.Absolute, out var rightUri))
            return false;

        return string.Equals(leftUri.Scheme, rightUri.Scheme, StringComparison.OrdinalIgnoreCase) &&
               string.Equals(leftUri.Host, rightUri.Host, StringComparison.OrdinalIgnoreCase) &&
               leftUri.Port == rightUri.Port &&
               string.Equals(
                   leftUri.AbsolutePath.TrimEnd('/'),
                   rightUri.AbsolutePath.TrimEnd('/'),
                   StringComparison.OrdinalIgnoreCase);
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

    private void ResolveRuntimeProfile()
    {
        var requestedEnvironment = Environment.GetEnvironmentVariable("A0_PROJECTSMCP_ENVIRONMENT")
            ?? Environment.GetEnvironmentVariable("PROJECTSMCP_ENVIRONMENT")
            ?? string.Empty;
        var configOverride = Environment.GetEnvironmentVariable("PROJECTSMCP_CONFIG_PATH") ?? string.Empty;
        var artifactsOverride = Environment.GetEnvironmentVariable("PROJECTSMCP_ARTIFACTS_DIR") ?? string.Empty;
        var isDev = string.Equals(requestedEnvironment.Trim(), "DEV", StringComparison.OrdinalIgnoreCase) ||
                    (!string.IsNullOrWhiteSpace(configOverride) &&
                     string.Equals(Path.GetFileName(configOverride), "config.dev.json", StringComparison.OrdinalIgnoreCase));

        _environment = isDev ? "DEV" : "MAIN";
        _configPath = !string.IsNullOrWhiteSpace(configOverride)
            ? Path.GetFullPath(configOverride)
            : Path.Combine(_projectRoot, isDev ? "config.dev.json" : "config.json");
        var artifactsRoot = !string.IsNullOrWhiteSpace(artifactsOverride)
            ? Path.GetFullPath(artifactsOverride)
            : Path.Combine(_projectRoot, "artifacts", isDev ? "dev" : string.Empty);
        _runtimeRoot = Path.Combine(artifactsRoot, "runtime");
    }

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

    private sealed record TunnelSnapshot(
        string Profile,
        int Pid,
        string TunnelId,
        string Hostname,
        string Config);

    private sealed class BridgeMessage
    {
        public string Action { get; set; } = string.Empty;
        public bool? Enabled { get; set; }
    }
}
