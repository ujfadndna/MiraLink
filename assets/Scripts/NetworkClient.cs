using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

/// <summary>Structured low-latency feedback pushed by backend sensor events.</summary>
[Serializable]
public sealed class AvatarInteractionCommandData
{
    public string state = "Reacting";
    public string emotion = "neutral";
    public string gesture = "";
    public string gaze_mode = "";
    public string pose_mode = "";
    public string sound_key = "";
    public string vfx_key = "";
    public float duration_sec = 0.9f;
    public int priority = 10;
    public string interrupt_policy = "normal";
}

[Serializable]
public sealed class SensorFeedbackData
{
    public string session_id;
    public string event_name;
    public string zone;
    public string visual_zone;
    public string anatomical_zone;
    public string zone_basis;
    public long timestamp_ms;
    public long received_ms;
    public int latency_ms;
    public string emotion = "neutral";
    public string jd_state = "Reacting";
    public int energy_delta;
    public int affinity_delta;
    public int score_delta;
    public List<string> feedback_tags = new List<string>();
    public AvatarInteractionCommandData command = new AvatarInteractionCommandData();

    public float alpha;
    public float beta;
    public float gamma;
    public float accel_magnitude;
    public float net_magnitude;
    public float strength;
    public float confidence = 1f;
    public float touch_x;
    public float touch_y;
    public float dx;
    public float dy;
    public float duration_ms;
    public string direction;
    public bool anchors_live;
    public bool simulated;
}

/// <summary>
/// WebSocket client for connecting to MiraLink backend.
/// Handles session management, agent dialogue, audio/animation streaming.
/// </summary>
public sealed class NetworkClient : MonoBehaviour
{
    [Header("Connection")]
    [SerializeField] private string serverUrl = "ws://127.0.0.1:8100/ws/avatar";
    [SerializeField] private bool connectOnStart = true;
    [SerializeField] private float reconnectDelaySec = 5f;

    [Header("Session")]
    [SerializeField] private string avatarId = "vrm_female_001";
    [SerializeField] private string language = "zh";

    [Header("References")]
    [SerializeField] private StreamingAudioPlayer audioPlayer;
    [SerializeField] private FacialAnimationController facialController;
    [SerializeField] private ExpressionController expressionController;
    [SerializeField] private GestureAnimationController gestureController;

    public enum ConnectionState { Disconnected, Connecting, Connected, Reconnecting }
    public ConnectionState State { get; private set; } = ConnectionState.Disconnected;

    /// <summary>Current session identifier assigned by the backend.</summary>
    public string SessionId { get; private set; }

    /// <summary>Current turn identifier.</summary>
    public string CurrentTurnId { get; private set; }

    /// <summary>Emotion label for the current turn.</summary>
    public string CurrentEmotion { get; private set; }

    /// <summary>Dialogue act for the current turn.</summary>
    public string CurrentDialogueAct { get; private set; }

    /// <summary>Latest state reported by the backend.</summary>
    public string CurrentState { get; private set; } = "disconnected";

    public bool BackendReady => State == ConnectionState.Connected && !string.IsNullOrEmpty(SessionId);

    // ── Events ────────────────────────────────────────────

    public event Action OnConnected;
    public event Action OnDisconnected;
    public event Action<string> OnSessionStarted;
    public event Action<string, string, string> OnTurnStart; // turnId, emotion, dialogueAct
    public event Action<string> OnTurnEnd;
    public event Action<string, string> OnTurnCancel; // turnId, reason
    public event Action<string, string> OnStateChange; // state, detail
    public event Action<string> OnError;
    public event Action<string> OnAsrResult;
    public event Action<SensorFeedbackData> OnSensorFeedback;
    public event Action<AvatarInteractionCommandData> OnAvatarAction;

    private ClientWebSocket _ws;
    private CancellationTokenSource _cts;
    private readonly ConcurrentQueue<Action> _mainThreadActions = new ConcurrentQueue<Action>();
    private readonly SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);
    private bool _shouldReconnect = true;
    private List<GestureEventData> _pendingGestureEvents;
    private string _pendingGestureTurnId;

    private void Awake()
    {
        var cliServerUrl = GetCommandLineValue("-backendWsUrl");
        if (!string.IsNullOrWhiteSpace(cliServerUrl))
        {
            serverUrl = cliServerUrl.Trim();
            Debug.Log($"[NetworkClient] backendWsUrl override: {serverUrl}");
        }
    }

    private void Start()
    {
        if (audioPlayer != null)
            audioPlayer.PlaybackStarted += OnAudioPlaybackStarted;

        if (connectOnStart)
            Connect();
    }

    private void OnDestroy()
    {
        if (audioPlayer != null)
            audioPlayer.PlaybackStarted -= OnAudioPlaybackStarted;

        _shouldReconnect = false;
        Disconnect();
    }

    private void Update()
    {
        while (_mainThreadActions.TryDequeue(out var action))
            action?.Invoke();
    }

    /// <summary>Connects to the backend WebSocket.</summary>
    public async void Connect()
    {
        if (State == ConnectionState.Connected || State == ConnectionState.Connecting)
            return;

        State = ConnectionState.Connecting;
        _cts = new CancellationTokenSource();

        try
        {
            _ws = new ClientWebSocket();
            await _ws.ConnectAsync(new Uri(serverUrl), _cts.Token);
            State = ConnectionState.Connected;
            _mainThreadActions.Enqueue(() =>
            {
                CurrentState = "connected";
                OnConnected?.Invoke();
            });
            Debug.Log($"[NetworkClient] Connected to {serverUrl}");

            // Auto-start session on connect
            SendSessionStart();

            _ = ReceiveLoop(_cts.Token);
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[NetworkClient] Connection failed: {ex.Message}");
            State = ConnectionState.Disconnected;
            CurrentState = "disconnected";
            if (_shouldReconnect)
                ScheduleReconnect();
        }
    }

    /// <summary>Disconnects from the backend.</summary>
    public void Disconnect()
    {
        _cts?.Cancel();
        try { _ws?.Abort(); } catch { }
        _ws?.Dispose();
        _ws = null;
        State = ConnectionState.Disconnected;
        CurrentState = "disconnected";
        _mainThreadActions.Enqueue(() => OnDisconnected?.Invoke());
    }

    /// <summary>Sends a session.start message to create a new dialogue session.</summary>
    public async void SendSessionStart()
    {
        if (State != ConnectionState.Connected || _ws == null) return;

        var json = $"{{\"type\":\"session.start\",\"avatar_id\":\"{EscapeJson(avatarId)}\",\"language\":\"{EscapeJson(language)}\"}}";
        if (await SendTextMessageAsync(json, "session.start"))
            Debug.Log("[NetworkClient] Sent session.start");
    }

    /// <summary>Sends a text input to the backend for Agent processing.</summary>
    public async void SendText(string text)
    {
        if (State != ConnectionState.Connected || _ws == null)
        {
            Debug.LogWarning("[NetworkClient] Not connected, cannot send text.");
            return;
        }

        if (string.IsNullOrEmpty(SessionId))
        {
            Debug.LogWarning("[NetworkClient] No session — send session.start first.");
            return;
        }

        var json = $"{{\"type\":\"turn.submit_text\",\"session_id\":\"{EscapeJson(SessionId)}\",\"text\":\"{EscapeJson(text)}\"}}";
        await SendTextMessageAsync(json, "turn.submit_text");
    }

    /// <summary>Sends raw PCM int16 audio to the backend for ASR processing.</summary>
    public async void SendAudio(byte[] pcmInt16, int sampleRate)
    {
        if (State != ConnectionState.Connected || _ws == null)
        {
            Debug.LogWarning("[NetworkClient] Not connected, cannot send audio.");
            return;
        }

        if (string.IsNullOrEmpty(SessionId))
        {
            Debug.LogWarning("[NetworkClient] No session — send session.start first.");
            return;
        }

        var b64 = Convert.ToBase64String(pcmInt16);
        var json = $"{{\"type\":\"turn.submit_audio\",\"session_id\":\"{EscapeJson(SessionId)}\",\"base64\":\"{b64}\",\"sample_rate\":{sampleRate}}}";
        if (await SendTextMessageAsync(json, "turn.submit_audio"))
            Debug.Log($"[NetworkClient] Sent audio: {pcmInt16.Length} bytes, {sampleRate}Hz");
    }

    /// <summary>Sends normalized avatar touch anchors through the avatar WebSocket.</summary>
    public async void SendAvatarAnchors(string anchorsJson)
    {
        if (State != ConnectionState.Connected || _ws == null)
            return;

        if (string.IsNullOrEmpty(SessionId))
            return;

        var json = $"{{\"type\":\"avatar.anchors\",\"session_id\":\"{EscapeJson(SessionId)}\",\"anchors\":{anchorsJson},\"timestamp_ms\":{UnixEpochMs()}}}";
        await SendTextMessageAsync(json, "avatar.anchors");
    }

    private async Task<bool> SendTextMessageAsync(string json, string label)
    {
        if (State != ConnectionState.Connected || _ws == null || _cts == null)
            return false;

        try
        {
            await _sendLock.WaitAsync(_cts.Token);
        }
        catch (OperationCanceledException)
        {
            return false;
        }

        try
        {
            if (State != ConnectionState.Connected || _ws == null || _cts == null)
                return false;

            var bytes = Encoding.UTF8.GetBytes(json);
            await _ws.SendAsync(new ArraySegment<byte>(bytes),
                System.Net.WebSockets.WebSocketMessageType.Text, true, _cts.Token);
            return true;
        }
        catch (OperationCanceledException)
        {
            return false;
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[NetworkClient] {label} failed: {ex.Message}");
            return false;
        }
        finally
        {
            _sendLock.Release();
        }
    }

    private static long UnixEpochMs()
    {
        return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    }

    private async Task ReceiveLoop(CancellationToken ct)
    {
        var buffer = new byte[65536];

        try
        {
            while (!ct.IsCancellationRequested && _ws.State == System.Net.WebSockets.WebSocketState.Open)
            {
                var result = await _ws.ReceiveAsync(new ArraySegment<byte>(buffer), ct);
                if (result.MessageType == System.Net.WebSockets.WebSocketMessageType.Close)
                    break;

                var json = Encoding.UTF8.GetString(buffer, 0, result.Count);
                ProcessMessage(json);
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            Debug.LogWarning($"[NetworkClient] Receive error: {ex.Message}");
        }

        if (_shouldReconnect && !ct.IsCancellationRequested)
        {
            State = ConnectionState.Disconnected;
            CurrentState = "disconnected";
            _mainThreadActions.Enqueue(() => OnDisconnected?.Invoke());
            ScheduleReconnect();
        }
    }

    private void ProcessMessage(string json)
    {
        var type = ExtractJsonString(json, "type");

        switch (type)
        {
            case "session.started":
            {
                var sid = ExtractJsonString(json, "session_id");
                _mainThreadActions.Enqueue(() =>
                {
                    SessionId = sid;
                    OnSessionStarted?.Invoke(sid);
                });
                Debug.Log($"[NetworkClient] Session started: {sid}");
                break;
            }

            case "state.change":
            {
                var state = ExtractJsonString(json, "state");
                var detail = ExtractJsonString(json, "detail") ?? "";
                _mainThreadActions.Enqueue(() =>
                {
                    CurrentState = state;
                    OnStateChange?.Invoke(state, detail);
                });
                break;
            }

            case "call.state":
            {
                var state = ExtractJsonString(json, "state");
                var detail = ExtractJsonString(json, "detail") ?? "";
                _mainThreadActions.Enqueue(() =>
                {
                    CurrentState = state;
                    OnStateChange?.Invoke(state, detail);
                });
                break;
            }

            case "turn.start":
            {
                CurrentTurnId = ExtractJsonString(json, "turn_id");
                CurrentEmotion = ExtractJsonString(json, "emotion") ?? "neutral";
                CurrentDialogueAct = ExtractJsonString(json, "dialogue_act") ?? "unknown";
                var durationMs = ExtractJsonFloat(json, "duration_ms");
                var sampleRate = ExtractJsonInt(json, "sample_rate");
                var totalSamples = ExtractJsonInt(json, "total_samples");
                var gestureEvents = ExtractGestureEvents(json);
                var avatarActionJson = ExtractJsonObject(json, "avatar_action");
                var avatarAction = string.IsNullOrEmpty(avatarActionJson)
                    ? null
                    : ExtractAvatarInteractionCommand(avatarActionJson, CurrentEmotion);
                _mainThreadActions.Enqueue(() =>
                {
                    audioPlayer?.BeginTurn(durationMs, sampleRate, totalSamples);
                    expressionController?.SetEmotion(CurrentEmotion);
                    QueueGesturesForAudioStart(CurrentTurnId, gestureEvents);
                    OnTurnStart?.Invoke(CurrentTurnId, CurrentEmotion, CurrentDialogueAct);
                    if (avatarAction != null)
                        OnAvatarAction?.Invoke(avatarAction);
                });
                Debug.Log($"[NetworkClient] Turn start: {CurrentTurnId} emotion={CurrentEmotion} act={CurrentDialogueAct} durationMs={durationMs} sampleRate={sampleRate} totalSamples={totalSamples}");
                break;
            }

            case "audio.chunk":
            {
                var b64 = ExtractJsonString(json, "base64");
                var sampleRate = ExtractJsonInt(json, "sample_rate");
                if (!string.IsNullOrEmpty(b64))
                {
                    var pcm = Convert.FromBase64String(b64);
                    _mainThreadActions.Enqueue(() => audioPlayer?.EnqueueAudioChunk(pcm, sampleRate));
                }
                break;
            }

            case "animation.packet":
            {
                var blendshapes = ExtractBlendshapes(json);
                var startMs = ExtractJsonFloat(json, "start_ms");
                var endMs   = ExtractJsonFloat(json, "end_ms");
                _mainThreadActions.Enqueue(() =>
                    audioPlayer?.EnqueueAnimationPacket(startMs, endMs, blendshapes));
                break;
            }

            case "turn.end":
            {
                _mainThreadActions.Enqueue(() =>
                {
                    audioPlayer?.EndTurn();
                    expressionController?.ResetToNeutral();
                    _pendingGestureEvents = null;
                    _pendingGestureTurnId = null;
                    OnTurnEnd?.Invoke(CurrentTurnId);
                });
                break;
            }

            case "turn.cancel":
            {
                var turnId = ExtractJsonString(json, "turn_id") ?? CurrentTurnId;
                var reason = ExtractJsonString(json, "reason") ?? "";
                _mainThreadActions.Enqueue(() =>
                {
                    audioPlayer?.StopAndClear();
                    expressionController?.ResetToNeutral();
                    gestureController?.StopGestures();
                    _pendingGestureEvents = null;
                    _pendingGestureTurnId = null;
                    OnTurnCancel?.Invoke(turnId, reason);
                });
                Debug.Log($"[NetworkClient] Turn cancel: {turnId} reason={reason}");
                break;
            }

            case "error":
            case "call.error":
            {
                var msg = ExtractJsonString(json, "message");
                _mainThreadActions.Enqueue(() => OnError?.Invoke(msg));
                Debug.LogWarning($"[NetworkClient] Server error: {msg}");
                break;
            }

            case "asr.result":
            case "asr.final":
            {
                var text = ExtractJsonString(json, "text");
                _mainThreadActions.Enqueue(() =>
                {
                    OnAsrResult?.Invoke(text ?? "");
                });
                Debug.Log($"[NetworkClient] ASR result: {text}");
                break;
            }

            case "sensor.feedback":
            {
                var feedback = ExtractSensorFeedback(json);
                _mainThreadActions.Enqueue(() => OnSensorFeedback?.Invoke(feedback));
                Debug.Log(
                    $"[NetworkClient] Sensor feedback: {feedback.event_name} zone={feedback.zone} " +
                    $"visual={feedback.visual_zone} anatomical={feedback.anatomical_zone} " +
                    $"pose={feedback.command?.pose_mode} gaze={feedback.command?.gaze_mode} " +
                    $"latency={feedback.latency_ms}ms emotion={feedback.emotion}");
                break;
            }
        }
    }

    private async void ScheduleReconnect()
    {
        State = ConnectionState.Reconnecting;
        Debug.Log($"[NetworkClient] Reconnecting in {reconnectDelaySec}s...");
        await Task.Delay((int)(reconnectDelaySec * 1000));
        if (_shouldReconnect)
            Connect();
    }

    private void QueueGesturesForAudioStart(string turnId, List<GestureEventData> gestureEvents)
    {
        gestureController?.StopGestures();
        _pendingGestureEvents = gestureEvents != null && gestureEvents.Count > 0
            ? new List<GestureEventData>(gestureEvents)
            : null;
        _pendingGestureTurnId = turnId;

        if (_pendingGestureEvents == null || _pendingGestureEvents.Count == 0)
            return;

        if (audioPlayer == null)
        {
            gestureController?.ScheduleGestures(_pendingGestureEvents, 0f);
            _pendingGestureEvents = null;
            _pendingGestureTurnId = null;
        }
    }

    private void OnAudioPlaybackStarted()
    {
        if (_pendingGestureEvents == null || _pendingGestureEvents.Count == 0)
            return;

        if (!string.IsNullOrEmpty(_pendingGestureTurnId) &&
            !string.IsNullOrEmpty(CurrentTurnId) &&
            _pendingGestureTurnId != CurrentTurnId)
        {
            return;
        }

        gestureController?.ScheduleGestures(_pendingGestureEvents, 0f);
        Debug.Log($"[NetworkClient] Scheduled {_pendingGestureEvents.Count} gesture_events at audio start");
        _pendingGestureEvents = null;
        _pendingGestureTurnId = null;
    }

    // ── Simple JSON helpers (no external dependency) ──────────

    private static string GetCommandLineValue(string key)
    {
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length; i++)
        {
            if (!string.Equals(args[i], key, StringComparison.OrdinalIgnoreCase))
                continue;

            if (i + 1 >= args.Length)
                return null;

            var value = args[i + 1];
            return string.IsNullOrWhiteSpace(value) || value.StartsWith("-") ? null : value;
        }

        return null;
    }

    private static string ExtractJsonString(string json, string key)
    {
        var pattern = $"\"{key}\":\"";
        int start = json.IndexOf(pattern, StringComparison.Ordinal);
        if (start < 0) return null;
        start += pattern.Length;
        int end = json.IndexOf('"', start);
        return end > start ? json.Substring(start, end - start) : null;
    }

    private static int ExtractJsonInt(string json, string key)
    {
        var pattern = $"\"{key}\":";
        int start = json.IndexOf(pattern, StringComparison.Ordinal);
        if (start < 0) return 0;
        start += pattern.Length;
        int end = start;
        while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '-')) end++;
        if (int.TryParse(json.Substring(start, end - start), out int val)) return val;
        return 0;
    }

    private static long ExtractJsonLong(string json, string key)
    {
        var pattern = $"\"{key}\":";
        int start = json.IndexOf(pattern, StringComparison.Ordinal);
        if (start < 0) return 0;
        start += pattern.Length;
        int end = start;
        while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '-')) end++;
        if (long.TryParse(json.Substring(start, end - start), out long val)) return val;
        return 0;
    }

    private static float ExtractJsonFloat(string json, string key)
    {
        var pattern = $"\"{key}\":";
        int start = json.IndexOf(pattern, StringComparison.Ordinal);
        if (start < 0) return 0f;
        start += pattern.Length;
        int end = start;
        while (end < json.Length && (char.IsDigit(json[end]) || json[end] == '-' ||
                                     json[end] == '+' || json[end] == '.' ||
                                     json[end] == 'e' || json[end] == 'E'))
        {
            end++;
        }

        if (float.TryParse(json.Substring(start, end - start), System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out float val))
        {
            return val;
        }

        return 0f;
    }

    private static bool ExtractJsonBool(string json, string key)
    {
        var pattern = $"\"{key}\":";
        int start = json.IndexOf(pattern, StringComparison.Ordinal);
        if (start < 0) return false;
        start += pattern.Length;
        return json.IndexOf("true", start, StringComparison.OrdinalIgnoreCase) == start;
    }

    private static SensorFeedbackData ExtractSensorFeedback(string json)
    {
        var valueJson = ExtractJsonObject(json, "value") ?? "{}";
        var commandJson = ExtractJsonObject(json, "command") ?? "{}";
        return new SensorFeedbackData
        {
            session_id = ExtractJsonString(json, "session_id") ?? "",
            event_name = ExtractJsonString(json, "event") ?? "unknown",
            zone = ExtractJsonString(json, "zone") ?? "",
            visual_zone = ExtractJsonString(valueJson, "visual_zone") ?? "",
            anatomical_zone = ExtractJsonString(valueJson, "anatomical_zone") ?? "",
            zone_basis = ExtractJsonString(valueJson, "zone_basis") ?? "",
            timestamp_ms = ExtractJsonLong(json, "timestamp_ms"),
            received_ms = ExtractJsonLong(json, "received_ms"),
            latency_ms = ExtractJsonInt(json, "latency_ms"),
            emotion = ExtractJsonString(json, "emotion") ?? "neutral",
            jd_state = ExtractJsonString(json, "jd_state") ?? "Reacting",
            energy_delta = ExtractJsonInt(json, "energy_delta"),
            affinity_delta = ExtractJsonInt(json, "affinity_delta"),
            score_delta = ExtractJsonInt(json, "score_delta"),
            feedback_tags = ExtractJsonStringArray(json, "feedback_tags"),
            command = ExtractAvatarInteractionCommand(commandJson, ExtractJsonString(json, "emotion") ?? "neutral"),
            alpha = ExtractJsonFloat(valueJson, "alpha"),
            beta = ExtractJsonFloat(valueJson, "beta"),
            gamma = ExtractJsonFloat(valueJson, "gamma"),
            accel_magnitude = ExtractJsonFloat(valueJson, "accel_magnitude"),
            net_magnitude = ExtractJsonFloat(valueJson, "net_magnitude"),
            strength = ExtractJsonFloat(valueJson, "strength"),
            confidence = Mathf.Max(ExtractJsonFloat(valueJson, "confidence"), 0f),
            touch_x = ExtractJsonFloat(valueJson, "touch_x"),
            touch_y = ExtractJsonFloat(valueJson, "touch_y"),
            dx = ExtractJsonFloat(valueJson, "dx"),
            dy = ExtractJsonFloat(valueJson, "dy"),
            duration_ms = ExtractJsonFloat(valueJson, "duration_ms"),
            direction = ExtractJsonString(valueJson, "direction") ?? "",
            anchors_live = ExtractJsonBool(valueJson, "anchors_live"),
            simulated = ExtractJsonBool(valueJson, "simulated")
        };
    }

    private static AvatarInteractionCommandData ExtractAvatarInteractionCommand(string json, string fallbackEmotion)
    {
        var duration = ExtractJsonFloat(json, "duration_sec");
        var priority = ExtractJsonInt(json, "priority");
        return new AvatarInteractionCommandData
        {
            state = ExtractJsonString(json, "state") ?? "Reacting",
            emotion = ExtractJsonString(json, "emotion") ?? fallbackEmotion ?? "neutral",
            gesture = ExtractJsonString(json, "gesture") ?? "",
            gaze_mode = ExtractJsonString(json, "gaze_mode") ?? "",
            pose_mode = ExtractJsonString(json, "pose_mode") ?? "",
            sound_key = ExtractJsonString(json, "sound_key") ?? "",
            vfx_key = ExtractJsonString(json, "vfx_key") ?? "",
            duration_sec = json == "{}" ? 0.9f : Mathf.Max(0f, duration),
            priority = priority > 0 ? priority : 10,
            interrupt_policy = ExtractJsonString(json, "interrupt_policy") ?? "normal"
        };
    }

    private static string ExtractJsonObject(string json, string key)
    {
        var keyPattern = $"\"{key}\"";
        int keyStart = json.IndexOf(keyPattern, StringComparison.Ordinal);
        if (keyStart < 0) return null;

        int colon = json.IndexOf(':', keyStart + keyPattern.Length);
        if (colon < 0) return null;

        int index = colon + 1;
        while (index < json.Length && char.IsWhiteSpace(json[index]))
            index++;

        if (index >= json.Length || json[index] != '{')
            return null;

        int end = FindMatchingObjectEnd(json, index, json.Length);
        return end > index ? json.Substring(index, end - index + 1) : null;
    }

    private static List<string> ExtractJsonStringArray(string json, string key)
    {
        var result = new List<string>();
        var keyPattern = $"\"{key}\"";
        int keyStart = json.IndexOf(keyPattern, StringComparison.Ordinal);
        if (keyStart < 0) return result;

        int colon = json.IndexOf(':', keyStart + keyPattern.Length);
        if (colon < 0) return result;

        int index = colon + 1;
        while (index < json.Length && char.IsWhiteSpace(json[index]))
            index++;

        if (index >= json.Length || json[index] != '[')
            return result;

        int end = FindMatchingArrayEnd(json, index);
        if (end <= index) return result;

        var inner = json.Substring(index + 1, end - index - 1);
        var parts = inner.Split(',');
        foreach (var part in parts)
        {
            var item = part.Trim().Trim('"');
            if (!string.IsNullOrEmpty(item))
                result.Add(item);
        }

        return result;
    }

    private static List<GestureEventData> ExtractGestureEvents(string json)
    {
        var result = new List<GestureEventData>();
        var arrayStart = FindGestureEventsArrayStart(json);
        if (arrayStart < 0) return result;

        var arrayEnd = FindMatchingArrayEnd(json, arrayStart);
        if (arrayEnd <= arrayStart) return result;

        int index = arrayStart + 1;
        while (index < arrayEnd)
        {
            int objectStart = json.IndexOf('{', index);
            if (objectStart < 0 || objectStart >= arrayEnd)
                break;

            int objectEnd = FindMatchingObjectEnd(json, objectStart, arrayEnd);
            if (objectEnd <= objectStart)
                break;

            var objectJson = json.Substring(objectStart, objectEnd - objectStart + 1);
            var gestureName = ExtractJsonString(objectJson, "gesture_name");
            if (!string.IsNullOrEmpty(gestureName))
            {
                result.Add(new GestureEventData
                {
                    gesture_name = gestureName,
                    start_ms = ExtractJsonFloat(objectJson, "start_ms"),
                    apex_ms = ExtractJsonFloat(objectJson, "apex_ms"),
                    duration_ms = ExtractJsonFloat(objectJson, "duration_ms"),
                    intensity = ExtractJsonFloat(objectJson, "intensity")
                });
            }

            index = objectEnd + 1;
        }

        return result;
    }

    private static int FindGestureEventsArrayStart(string json)
    {
        var exactPattern = "\"gesture_events\":[";
        int exactStart = json.IndexOf(exactPattern, StringComparison.Ordinal);
        if (exactStart >= 0)
            return exactStart + exactPattern.Length - 1;

        var keyPattern = "\"gesture_events\"";
        int keyStart = json.IndexOf(keyPattern, StringComparison.Ordinal);
        if (keyStart < 0) return -1;

        int colon = json.IndexOf(':', keyStart + keyPattern.Length);
        if (colon < 0) return -1;

        int index = colon + 1;
        while (index < json.Length && char.IsWhiteSpace(json[index]))
            index++;

        return index < json.Length && json[index] == '[' ? index : -1;
    }

    private static int FindMatchingArrayEnd(string json, int arrayStart)
    {
        int depth = 0;
        bool inString = false;
        bool escaped = false;

        for (int i = arrayStart; i < json.Length; i++)
        {
            char ch = json[i];
            if (inString)
            {
                if (escaped)
                {
                    escaped = false;
                }
                else if (ch == '\\')
                {
                    escaped = true;
                }
                else if (ch == '"')
                {
                    inString = false;
                }
                continue;
            }

            if (ch == '"')
            {
                inString = true;
            }
            else if (ch == '[')
            {
                depth++;
            }
            else if (ch == ']')
            {
                depth--;
                if (depth == 0)
                    return i;
            }
        }

        return -1;
    }

    private static int FindMatchingObjectEnd(string json, int objectStart, int limit)
    {
        int depth = 0;
        bool inString = false;
        bool escaped = false;

        for (int i = objectStart; i < limit; i++)
        {
            char ch = json[i];
            if (inString)
            {
                if (escaped)
                {
                    escaped = false;
                }
                else if (ch == '\\')
                {
                    escaped = true;
                }
                else if (ch == '"')
                {
                    inString = false;
                }
                continue;
            }

            if (ch == '"')
            {
                inString = true;
            }
            else if (ch == '{')
            {
                depth++;
            }
            else if (ch == '}')
            {
                depth--;
                if (depth == 0)
                    return i;
            }
        }

        return -1;
    }

    private static System.Collections.Generic.Dictionary<string, float> ExtractBlendshapes(string json)
    {
        var result = new System.Collections.Generic.Dictionary<string, float>(StringComparer.Ordinal);
        var objectJson = ExtractJsonObject(json, "blendshapes");
        if (string.IsNullOrEmpty(objectJson) || objectJson.Length < 2)
            return result;

        var inner = objectJson.Substring(1, objectJson.Length - 2);
        var pairs = inner.Split(',');
        foreach (var pair in pairs)
        {
            var kv = pair.Split(new[] { ':' }, 2);
            if (kv.Length == 2)
            {
                var k = UnescapeJsonString(kv[0].Trim().Trim('"'));
                if (float.TryParse(kv[1].Trim(), System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out float v))
                    result[k] = v;
            }
        }
        return result;
    }

    private static string UnescapeJsonString(string value)
    {
        if (string.IsNullOrEmpty(value) || value.IndexOf('\\') < 0)
            return value ?? "";

        return value
            .Replace("\\\"", "\"")
            .Replace("\\\\", "\\")
            .Replace("\\n", "\n")
            .Replace("\\r", "\r")
            .Replace("\\t", "\t");
    }

    private static string EscapeJson(string s) =>
        s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n");
}

/// <summary>Minimal wrapper around System.Net.WebSockets.ClientWebSocket for Unity.</summary>
internal sealed class ClientWebSocket : IDisposable
{
    private readonly System.Net.WebSockets.ClientWebSocket _inner = new System.Net.WebSockets.ClientWebSocket();

    public System.Net.WebSockets.WebSocketState State => _inner.State;

    public Task ConnectAsync(Uri uri, CancellationToken ct) => _inner.ConnectAsync(uri, ct);

    public Task SendAsync(ArraySegment<byte> buffer, System.Net.WebSockets.WebSocketMessageType type,
        bool endOfMessage, CancellationToken ct) => _inner.SendAsync(buffer, type, endOfMessage, ct);

    public Task<System.Net.WebSockets.WebSocketReceiveResult> ReceiveAsync(ArraySegment<byte> buffer,
        CancellationToken ct) => _inner.ReceiveAsync(buffer, ct);

    public void Abort() => _inner.Abort();
    public void Dispose() => _inner.Dispose();
}
