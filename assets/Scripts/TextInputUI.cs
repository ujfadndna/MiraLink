using UnityEngine;

/// <summary>
/// IMGUI-based text input with dialogue state machine visualization.
/// Shows Idle / Listening / Thinking / Speaking / Interrupted / Error states.
/// </summary>
public sealed class TextInputUI : MonoBehaviour
{
    [Header("Network")]
    [SerializeField] private NetworkClient networkClient;

    private string _inputText = "";
    private string _statusText = "连接中...";
    private string _stateLabel = "disconnected";
    private string _sessionId = "";
    private string _turnId = "";
    private string _emotion = "";
    private string _dialogueAct = "";
    private int _turnCount;
    private bool _showUI = false;

    private void Start()
    {
        if (networkClient != null)
        {
            networkClient.OnConnected += OnConnected;
            networkClient.OnDisconnected += () => SetState("disconnected", "已断开 - 等待重连...");
            networkClient.OnSessionStarted += OnSessionStarted;
            networkClient.OnTurnStart += OnTurnStart;
            networkClient.OnTurnEnd += _ => { _turnCount++; };
            networkClient.OnStateChange += OnStateChange;
            networkClient.OnError += msg => SetState("error", $"错误: {msg}");
            networkClient.OnAsrResult += OnAsrResult;
        }
    }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.F1))
            _showUI = !_showUI;
    }

    private void OnConnected()
    {
        SetState("idle", "已连接 - 等待会话创建...");
    }

    private void OnSessionStarted(string sid)
    {
        _sessionId = sid;
        _turnCount = 0;
        SetState("idle", "就绪 - 输入文本按 Enter 发送");
    }

    private void OnTurnStart(string turnId, string emotion, string dialogueAct)
    {
        _turnId = turnId;
        _emotion = emotion;
        _dialogueAct = dialogueAct;
    }

    private void OnStateChange(string state, string detail)
    {
        SetState(state, detail);
    }

    private void OnAsrResult(string text)
    {
        _inputText = text;
    }

    private void SetState(string state, string detail)
    {
        _stateLabel = state;
        _statusText = detail;
    }

    private void OnGUI()
    {
        if (!_showUI) return;

        // ── Top bar ───────────────────────────────────────
        float barH = 60f;
        GUI.Box(new Rect(0, 0, Screen.width, barH), "");
        GUI.Label(new Rect(10, 5, Screen.width - 20, 20),
            $"<color={StateColor(_stateLabel)}><b>[{_stateLabel.ToUpper()}]</b></color> {_statusText}");

        // Session info line
        string infoLine = $"Session: {Truncate(_sessionId, 16)}";
        if (!string.IsNullOrEmpty(_emotion))
            infoLine += $" | 情绪: {_emotion}";
        if (!string.IsNullOrEmpty(_dialogueAct))
            infoLine += $" | 行为: {_dialogueAct}";
        if (_turnCount > 0)
            infoLine += $" | 轮次: {_turnCount}";
        GUI.Label(new Rect(10, 22, Screen.width - 20, 20), $"<color=#aaa>{infoLine}</color>");

        // Input row
        float inputW = Mathf.Min(300, Screen.width - 100);
        GUI.SetNextControlName("TextInput");
        _inputText = GUI.TextField(new Rect(10, 40, inputW, 18), _inputText);

        bool blocked = _stateLabel is "thinking" or "speaking" or "connecting";
        GUI.enabled = !blocked;
        if (GUI.Button(new Rect(inputW + 15, 40, 60, 18), "发送") || IsEnterPressed())
        {
            Submit();
        }
        GUI.enabled = true;

        if (blocked)
            GUI.Label(new Rect(inputW + 80, 40, 200, 18), "<color=#888>处理中，请等待...</color>");
    }

    private void Submit()
    {
        var text = _inputText.Trim();
        if (string.IsNullOrEmpty(text) || networkClient == null) return;

        networkClient.SendText(text);
        _inputText = "";
        _emotion = "";
        _dialogueAct = "";
        GUI.FocusControl("TextInput");
        Debug.Log($"[TextInputUI] Sent: {text}");
    }

    private bool IsEnterPressed()
    {
        return Event.current.type == EventType.KeyDown &&
               (Event.current.keyCode == KeyCode.Return || Event.current.keyCode == KeyCode.KeypadEnter) &&
               GUI.GetNameOfFocusedControl() == "TextInput";
    }

    private static string StateColor(string state) => state switch
    {
        "idle" => "#4f4",
        "listening" => "#4ff",
        "thinking" => "#ff4",
        "speaking" => "#48f",
        "interrupted" => "#f84",
        "error" => "#f44",
        _ => "#888",
    };

    private static string Truncate(string s, int max) =>
        string.IsNullOrEmpty(s) || s.Length <= max ? s ?? "" : s[..max] + "...";
}
