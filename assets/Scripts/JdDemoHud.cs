using UnityEngine;

/// <summary>High-contrast runtime HUD for the JD sensor demo acceptance metrics.</summary>
public sealed class JdDemoHud : MonoBehaviour
{
    [SerializeField] private JdDemoInteractionController demoController;
    [SerializeField] private NetworkClient networkClient;
    [SerializeField] private bool showHud = false;

    private Texture2D _bg;
    private Texture2D _panel;
    private Texture2D _accent;
    private GUIStyle _title;
    private GUIStyle _session;
    private GUIStyle _label;
    private GUIStyle _value;
    private GUIStyle _ok;
    private GUIStyle _warn;
    private GUIStyle _error;
    private GUIStyle _small;
    private GUIStyle _smallValue;

    private void Awake()
    {
        if (demoController == null)
            demoController = GetComponent<JdDemoInteractionController>();
        if (networkClient == null)
            networkClient = GetComponent<NetworkClient>();
    }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.F2))
            showHud = !showHud;
    }

    private void OnGUI()
    {
        if (!showHud || demoController == null)
            return;

        EnsureResources();

        float scale = Mathf.Clamp(Screen.height / 720f, 0.82f, 1.05f);
        float w = Mathf.Min(390f * scale, Screen.width - 32f);
        float h = Mathf.Min(530f * scale, Screen.height - 32f);
        float x = Screen.width - w - 16f;
        float y = 16f;

        DrawRect(new Rect(x, y, w, h), _bg);
        DrawRect(new Rect(x, y, 5f, h), _accent);

        float pad = 13f * scale;
        float line = 24f * scale;
        float cx = x + pad;
        float cy = y + 12f * scale;
        float cw = w - pad * 2f;

        GUI.Label(new Rect(cx, cy, cw, line), "JD Demo HUD", _title);
        cy += line;

        string session = demoController.SessionId;
        DrawSessionBlock(cx, cy, cw, session, scale);
        cy += 150f * scale;

        float colGap = 8f * scale;
        float colW = (cw - colGap) / 2f;
        DrawMetric(cx, cy, colW, "连接", demoController.BackendConnected ? "Connected" : "Offline", demoController.BackendConnected ? _ok : _error, scale);
        DrawMetric(cx + colW + colGap, cy, colW, "状态", demoController.CurrentState.ToString(), StateStyle(demoController.CurrentState), scale);
        cy += 52f * scale;

        DrawMetric(cx, cy, colW, "最近事件", demoController.LastEvent, _value, scale);
        DrawMetric(cx + colW + colGap, cy, colW, "延迟", demoController.LastLatencyMs + " ms", demoController.LastLatencyMs <= 300 ? _ok : _warn, scale);
        cy += 52f * scale;

        DrawMetric(cx, cy, colW, "事件数", demoController.EventCount.ToString(), _value, scale);
        DrawMetric(cx + colW + colGap, cy, colW, "FPS", Mathf.RoundToInt(demoController.Fps).ToString(), demoController.Fps >= 30f ? _ok : _warn, scale);
        cy += 52f * scale;

        DrawMetric(cx, cy, colW, "能量", demoController.Energy.ToString(), _ok, scale);
        DrawMetric(cx + colW + colGap, cy, colW, "亲密度", demoController.Affinity.ToString(), _ok, scale);
        cy += 52f * scale;

        DrawMetric(cx, cy, colW, "分数", demoController.Score.ToString(), _value, scale);
        DrawMetric(cx + colW + colGap, cy, colW, "Backend", demoController.BackendState, _smallValue, scale);
        cy += 54f * scale;

        string detail = demoController.LastEvent == "tilt"
            ? $"Tilt beta={demoController.LastTiltBeta:0.0} gamma={demoController.LastTiltGamma:0.0}"
            : "Backend: " + demoController.BackendState + " " + demoController.BackendDetail;
        GUI.Label(new Rect(cx, cy, cw, 20f * scale), Shorten(detail, 48), _small);
        cy += 24f * scale;

        GUI.Label(new Rect(cx, cy, cw, 22f * scale), "Recent Events", _label);
        cy += 22f * scale;

        var events = demoController.RecentEvents;
        int count = Mathf.Min(events.Count, 3);
        if (count == 0)
        {
            GUI.Label(new Rect(cx, cy, cw, 22f * scale), "waiting for sensor input...", _small);
        }
        else
        {
            for (int i = 0; i < count; i++)
            {
                GUI.Label(new Rect(cx, cy + i * 19f * scale, cw, 19f * scale), events[i], _small);
            }
        }
    }

    private void DrawSessionBlock(float x, float y, float w, string session, float scale)
    {
        DrawRect(new Rect(x, y, w, 140f * scale), _panel);

        string value = string.IsNullOrEmpty(session) ? "-" : session;
        GUI.Label(new Rect(x + 8f * scale, y + 5f * scale, w - 16f * scale, 16f * scale), "Session ID", _label);
        GUI.Label(new Rect(x + 8f * scale, y + 23f * scale, w - 16f * scale, 24f * scale), value, _session);

        var sessions = demoController.RecentSessionIds;
        if (sessions.Count == 0)
        {
            GUI.Label(new Rect(x + 8f * scale, y + 55f * scale, w - 16f * scale, 18f * scale), "Recent sessions: waiting...", _small);
            return;
        }

        GUI.Label(new Rect(x + 8f * scale, y + 52f * scale, w - 16f * scale, 16f * scale), "Recent Sessions", _label);

        int count = Mathf.Min(sessions.Count, 5);
        for (int i = 0; i < count; i++)
        {
            GUI.Label(new Rect(x + 8f * scale, y + (70f + i * 13f) * scale, w - 16f * scale, 14f * scale),
                "Recent " + (i + 1) + ": " + sessions[i], _small);
        }
    }

    private void DrawMetric(float x, float y, float w, string name, string val, GUIStyle style, float scale)
    {
        DrawRect(new Rect(x, y, w, 45f * scale), _panel);
        GUI.Label(new Rect(x + 7f * scale, y + 3f * scale, w - 14f * scale, 16f * scale), name, _label);
        GUI.Label(new Rect(x + 7f * scale, y + 19f * scale, w - 14f * scale, 24f * scale), val, style);
    }

    private GUIStyle StateStyle(JdDemoInteractionController.DemoState state)
    {
        return state switch
        {
            JdDemoInteractionController.DemoState.Connected => _ok,
            JdDemoInteractionController.DemoState.Listening => _ok,
            JdDemoInteractionController.DemoState.UserSpeaking => _warn,
            JdDemoInteractionController.DemoState.Thinking => _warn,
            JdDemoInteractionController.DemoState.Reacting => _warn,
            JdDemoInteractionController.DemoState.Speaking => _warn,
            JdDemoInteractionController.DemoState.Interrupted => _warn,
            JdDemoInteractionController.DemoState.Error => _error,
            JdDemoInteractionController.DemoState.Reconnecting => _warn,
            _ => _value
        };
    }

    private void EnsureResources()
    {
        if (_bg != null)
            return;

        _bg = MakeTex(new Color(0.02f, 0.035f, 0.055f, 0.96f));
        _panel = MakeTex(new Color(0.07f, 0.095f, 0.13f, 0.98f));
        _accent = MakeTex(new Color(0.0f, 0.85f, 1f, 1f));

        _title = MakeStyle(20, FontStyle.Bold, new Color(0.9f, 0.98f, 1f));
        _session = MakeStyle(17, FontStyle.Bold, Color.white);
        _label = MakeStyle(12, FontStyle.Bold, new Color(0.68f, 0.78f, 0.88f));
        _value = MakeStyle(19, FontStyle.Bold, Color.white);
        _ok = MakeStyle(19, FontStyle.Bold, new Color(0.25f, 1f, 0.45f));
        _warn = MakeStyle(19, FontStyle.Bold, new Color(1f, 0.78f, 0.18f));
        _error = MakeStyle(19, FontStyle.Bold, new Color(1f, 0.28f, 0.28f));
        _small = MakeStyle(13, FontStyle.Bold, new Color(0.88f, 0.93f, 1f));
        _smallValue = MakeStyle(16, FontStyle.Bold, Color.white);
    }

    private static void DrawRect(Rect rect, Texture2D texture)
    {
        GUI.DrawTexture(rect, texture, ScaleMode.StretchToFill);
    }

    private static Texture2D MakeTex(Color color)
    {
        var tex = new Texture2D(1, 1, TextureFormat.RGBA32, false)
        {
            hideFlags = HideFlags.HideAndDontSave
        };
        tex.SetPixel(0, 0, color);
        tex.Apply();
        return tex;
    }

    private static GUIStyle MakeStyle(int size, FontStyle fontStyle, Color color)
    {
        return new GUIStyle(GUI.skin.label)
        {
            fontSize = size,
            fontStyle = fontStyle,
            normal = { textColor = color },
            clipping = TextClipping.Clip
        };
    }

    private static string Shorten(string value, int max)
    {
        if (string.IsNullOrEmpty(value) || value.Length <= max)
            return value ?? "";
        return value.Substring(0, max) + "...";
    }
}
