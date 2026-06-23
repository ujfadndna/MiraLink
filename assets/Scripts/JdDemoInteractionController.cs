using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// JD Demo interaction state and feedback layer.
/// Keeps sensor-driven reactions separate from the transport-only NetworkClient.
/// </summary>
public sealed class JdDemoInteractionController : MonoBehaviour
{
    public enum DemoState
    {
        Idle,
        Connected,
        Listening,
        UserSpeaking,
        Thinking,
        Reacting,
        Speaking,
        Interrupted,
        Reconnecting,
        Error
    }

    private sealed class AvatarInteractionCommand
    {
        public DemoState State = DemoState.Reacting;
        public string Emotion = "neutral";
        public string Gesture = "";
        public string GazeMode = "";
        public string PoseMode = "";
        public string SoundKey = "";
        public string VfxKey = "";
        public float DurationSec = 0.9f;
        public int Priority = 10;
        public string InterruptPolicy = "normal";
    }

    [Header("References")]
    [SerializeField] private NetworkClient networkClient;
    [SerializeField] private ExpressionController expressionController;
    [SerializeField] private GestureAnimationController gestureController;
    [SerializeField] private BodyTouchReactionController bodyTouchController;
    [SerializeField] private GazeController gazeController;
    [SerializeField] private AudioSource audioSource;
    [SerializeField] private ParticleSystem feedbackParticles;
    [SerializeField] private Animator avatarAnimator;

    [Header("Feedback")]
    [SerializeField] private bool enableSound = true;
    [SerializeField] private bool enableParticles = true;
    [SerializeField] private float defaultReactDurationSec = 0.9f;
    [SerializeField] private float tiltReactDurationSec = 0.35f;
    [SerializeField] private int maxEventLog = 10;

    public DemoState CurrentState { get; private set; } = DemoState.Idle;
    public string BackendState { get; private set; } = "disconnected";
    public string BackendDetail { get; private set; } = "";
    public string LastEvent { get; private set; } = "-";
    public string LastZone { get; private set; } = "";
    public int LastLatencyMs { get; private set; }
    public float LastTiltBeta { get; private set; }
    public float LastTiltGamma { get; private set; }
    public int Energy { get; private set; } = 30;
    public int Affinity { get; private set; } = 10;
    public int Score { get; private set; }
    public int EventCount { get; private set; }
    public float Fps { get; private set; }
    public string LastCommandEmotion { get; private set; } = "";
    public string LastCommandGesture { get; private set; } = "";
    public string LastCommandGazeMode { get; private set; } = "";
    public string LastCommandPoseMode { get; private set; } = "";
    public string LastCommandSoundKey { get; private set; } = "";
    public string LastCommandVfxKey { get; private set; } = "";
    public float LastCommandDurationSec { get; private set; }
    public int LastCommandPriority { get; private set; }
    public string LastCommandInterruptPolicy { get; private set; } = "";
    public IReadOnlyList<string> RecentEvents => _recentEvents;
    public IReadOnlyList<string> RecentSessionIds => _recentSessionIds;
    public string SessionId => networkClient != null ? networkClient.SessionId : "";
    public bool BackendConnected => networkClient != null && networkClient.State == NetworkClient.ConnectionState.Connected;

    private readonly List<string> _recentEvents = new List<string>();
    private readonly List<string> _recentSessionIds = new List<string>();
    private Coroutine _reactRoutine;
    private Transform _tiltTarget;
    private float _fpsTimer;
    private int _fpsFrames;
    private int _activeCommandPriority;

    private void Awake()
    {
        if (networkClient == null)
            networkClient = GetComponent<NetworkClient>();
        if (expressionController == null)
            expressionController = GetComponent<ExpressionController>();
        if (gestureController == null)
            gestureController = GetComponent<GestureAnimationController>();
        if (bodyTouchController == null)
            bodyTouchController = GetComponent<BodyTouchReactionController>();
        if (gazeController == null)
            gazeController = GetComponent<GazeController>();
        if (avatarAnimator == null)
            avatarAnimator = GetComponentInChildren<Animator>();
        if (audioSource == null)
            audioSource = GetComponent<AudioSource>();
        if (audioSource == null)
            audioSource = gameObject.AddComponent<AudioSource>();

        EnsureTiltTarget();
        EnsureParticleSystem();
    }

    private void OnEnable()
    {
        if (networkClient == null)
            return;

        networkClient.OnConnected += OnConnected;
        networkClient.OnDisconnected += OnDisconnected;
        networkClient.OnSessionStarted += OnSessionStarted;
        networkClient.OnTurnStart += OnTurnStart;
        networkClient.OnTurnEnd += OnTurnEnd;
        networkClient.OnTurnCancel += OnTurnCancel;
        networkClient.OnStateChange += OnBackendStateChange;
        networkClient.OnError += OnError;
        networkClient.OnSensorFeedback += OnSensorFeedback;
        networkClient.OnAvatarAction += OnAvatarAction;
    }

    private void OnDisable()
    {
        if (networkClient == null)
            return;

        networkClient.OnConnected -= OnConnected;
        networkClient.OnDisconnected -= OnDisconnected;
        networkClient.OnSessionStarted -= OnSessionStarted;
        networkClient.OnTurnStart -= OnTurnStart;
        networkClient.OnTurnEnd -= OnTurnEnd;
        networkClient.OnTurnCancel -= OnTurnCancel;
        networkClient.OnStateChange -= OnBackendStateChange;
        networkClient.OnError -= OnError;
        networkClient.OnSensorFeedback -= OnSensorFeedback;
        networkClient.OnAvatarAction -= OnAvatarAction;
    }

    private void Update()
    {
        _fpsFrames++;
        _fpsTimer += Time.unscaledDeltaTime;
        if (_fpsTimer >= 0.5f)
        {
            Fps = _fpsFrames / Mathf.Max(0.001f, _fpsTimer);
            _fpsFrames = 0;
            _fpsTimer = 0f;
        }
    }

    private void OnConnected()
    {
        BackendState = "connected";
        SetState(DemoState.Connected);
        AddLog("backend connected");
    }

    private void OnDisconnected()
    {
        CancelReactTimer();
        BackendState = "disconnected";
        SetState(DemoState.Reconnecting);
        AddLog("backend disconnected");
    }

    private void OnSessionStarted(string sessionId)
    {
        BackendState = "idle";
        SetState(DemoState.Connected);
        AddSessionId(sessionId);
        AddLog("session " + sessionId);
    }

    private void OnTurnStart(string turnId, string emotion, string dialogueAct)
    {
        CancelReactTimer();
        SetState(DemoState.Speaking);
        BackendState = "speaking";
        _activeCommandPriority = 90;
        if (!string.IsNullOrEmpty(emotion))
            expressionController?.SetEmotion(emotion);
        AddLog("speaking " + Shorten(turnId, 8));
    }

    private void OnTurnEnd(string turnId)
    {
        _activeCommandPriority = 0;
        expressionController?.ResetToNeutral();
        gazeController?.SetState("idle");
        SetState(BackendConnected ? DemoState.Connected : DemoState.Idle);
        AddLog("turn end " + Shorten(turnId, 8));
    }

    private void OnTurnCancel(string turnId, string reason)
    {
        _activeCommandPriority = 0;
        CancelReactTimer();
        expressionController?.ResetToNeutral();
        gazeController?.SetState("idle");
        SetState(DemoState.Interrupted);
        AddLog("interrupted " + Shorten(reason, 16));
    }

    private void OnBackendStateChange(string state, string detail)
    {
        BackendState = string.IsNullOrEmpty(state) ? "unknown" : state;
        BackendDetail = detail ?? "";

        if (BackendState == "speaking")
        {
            SetState(DemoState.Speaking);
        }
        else if (BackendState == "listening")
        {
            SetState(DemoState.Listening);
        }
        else if (BackendState == "user_speaking")
        {
            SetState(DemoState.UserSpeaking);
        }
        else if (BackendState == "thinking" || BackendState == "asr")
        {
            SetState(DemoState.Thinking);
        }
        else if (BackendState == "interrupted")
        {
            SetState(DemoState.Interrupted);
        }
        else if (BackendState == "error")
        {
            SetState(DemoState.Error);
        }
        else if (CurrentState != DemoState.Reacting && CurrentState != DemoState.Speaking)
        {
            SetState(BackendConnected ? DemoState.Connected : DemoState.Idle);
        }
    }

    private void OnError(string message)
    {
        BackendDetail = message ?? "";
        SetState(DemoState.Error);
        AddLog("error " + BackendDetail);
    }

    public void InjectSensorFeedbackForDiagnostics(SensorFeedbackData data)
    {
        OnSensorFeedback(data);
    }

    private void OnSensorFeedback(SensorFeedbackData data)
    {
        if (data == null)
            return;

        string evt = NormalizeEvent(data.event_name);
        if (evt == "reset")
        {
            ApplyReset();
            return;
        }

        LastEvent = evt;
        LastZone = DisplayZone(data);
        LastLatencyMs = data.latency_ms;
        LastTiltBeta = data.beta;
        LastTiltGamma = data.gamma;
        EventCount++;

        Energy = Mathf.Clamp(Energy + data.energy_delta, 0, 100);
        Affinity = Mathf.Clamp(Affinity + data.affinity_delta, 0, 100);
        Score = Mathf.Max(0, Score + data.score_delta);

        AddLog($"{LastEvent} {LastLatencyMs}ms");

        var command = BuildCommand(evt, data);
        RecordLastCommand(command);
        if (!CanApplyFeedback(evt, command))
        {
            AddLog("blocked " + evt + " during " + CurrentState);
            return;
        }

        ApplyFeedback(data, command);
    }

    private void OnAvatarAction(AvatarInteractionCommandData data)
    {
        if (data == null)
            return;

        var feedback = new SensorFeedbackData
        {
            event_name = "avatar_action",
            emotion = string.IsNullOrEmpty(data.emotion) ? "neutral" : data.emotion,
            command = data
        };
        var command = BuildCommand("avatar_action", feedback);
        RecordLastCommand(command);
        ApplyFeedback(feedback, command);
        AddLog("avatar action");
    }

    private void ApplyReset()
    {
        CancelReactTimer();
        gestureController?.StopGestures();
        bodyTouchController?.StopPose();
        expressionController?.ResetToNeutral();
        gazeController?.SetState("idle");

        LastEvent = "-";
        LastZone = "";
        LastLatencyMs = 0;
        LastTiltBeta = 0f;
        LastTiltGamma = 0f;
        Energy = 30;
        Affinity = 10;
        Score = 0;
        EventCount = 0;
        _activeCommandPriority = 0;
        _recentEvents.Clear();
        ClearLastCommand();

        SetState(BackendConnected ? DemoState.Connected : DemoState.Idle);
    }

    private void RecordLastCommand(AvatarInteractionCommand command)
    {
        if (command == null)
        {
            ClearLastCommand();
            return;
        }

        LastCommandEmotion = command.Emotion ?? "";
        LastCommandGesture = command.Gesture ?? "";
        LastCommandGazeMode = command.GazeMode ?? "";
        LastCommandPoseMode = command.PoseMode ?? "";
        LastCommandSoundKey = command.SoundKey ?? "";
        LastCommandVfxKey = command.VfxKey ?? "";
        LastCommandDurationSec = command.DurationSec;
        LastCommandPriority = command.Priority;
        LastCommandInterruptPolicy = command.InterruptPolicy ?? "";
    }

    private void ClearLastCommand()
    {
        LastCommandEmotion = "";
        LastCommandGesture = "";
        LastCommandGazeMode = "";
        LastCommandPoseMode = "";
        LastCommandSoundKey = "";
        LastCommandVfxKey = "";
        LastCommandDurationSec = 0f;
        LastCommandPriority = 0;
        LastCommandInterruptPolicy = "";
    }

    private bool CanApplyFeedback(string evt, AvatarInteractionCommand command)
    {
        if (command.InterruptPolicy == "force" || evt == "tilt")
            return true;

        if (CurrentState == DemoState.Speaking)
            return command.InterruptPolicy == "prefer_speaking" || command.InterruptPolicy == "hud_only";

        if (CurrentState == DemoState.Reacting &&
            command.InterruptPolicy != "nonblocking" &&
            command.InterruptPolicy != "hud_only" &&
            command.Priority < _activeCommandPriority)
        {
            return false;
        }

        return true;
    }

    private void ApplyFeedback(SensorFeedbackData data, AvatarInteractionCommand command)
    {
        string evt = NormalizeEvent(data.event_name);

        if (evt == "tilt")
        {
            ApplyTilt(data);
            return;
        }

        if (command.InterruptPolicy == "hud_only")
        {
            ApplyGazeMode(command.GazeMode, data);
            return;
        }

        bool staySpeaking = CurrentState == DemoState.Speaking;
        if (!string.IsNullOrEmpty(command.Emotion))
            expressionController?.SetEmotion(command.Emotion);

        ApplyGazeMode(command.GazeMode, data);

        if (!staySpeaking)
        {
            TriggerGesture(command.Gesture, command.DurationSec);
            bodyTouchController?.PlayPose(command.PoseMode, command.DurationSec, command.Priority, command.InterruptPolicy);
        }

        if (enableParticles && !string.IsNullOrEmpty(command.VfxKey))
            PlayParticles(command.VfxKey, data);

        if (enableSound && !string.IsNullOrEmpty(command.SoundKey))
            PlayToneForKey(command.SoundKey);

        if (staySpeaking)
            return;

        DemoState targetState = command.State == DemoState.Speaking ? DemoState.Reacting : command.State;
        SetState(targetState);
        _activeCommandPriority = command.Priority;

        if (targetState == DemoState.Reacting)
        {
            float duration = command.DurationSec > 0f ? command.DurationSec : defaultReactDurationSec;
            RestartReactTimer(duration);
        }
        else
        {
            _activeCommandPriority = 0;
        }
    }

    private void ApplyTilt(SensorFeedbackData data)
    {
        PositionGazeTarget(data.gamma / 45f, data.beta / 90f, 2.2f);
        gazeController?.SetState("speaking");
    }

    private void ApplyGazeMode(string gazeMode, SensorFeedbackData data)
    {
        switch ((gazeMode ?? "").Trim().ToLowerInvariant())
        {
            case "gaze_follow":
                ApplyTilt(data);
                break;
            case "gaze_sweep":
                ApplySwipeGaze(data);
                break;
            case "gaze_user":
                PositionGazeTarget(0f, 0.05f, 2.2f);
                gazeController?.SetState("speaking");
                break;
            case "gaze_left":
                PositionGazeTarget(-0.45f, 0f, 2.2f);
                gazeController?.SetState("speaking");
                break;
            case "gaze_right":
                PositionGazeTarget(0.45f, 0f, 2.2f);
                gazeController?.SetState("speaking");
                break;
            case "gaze_left_hand":
                PositionGazeTarget(-0.55f, -0.22f, 2.2f);
                gazeController?.SetState("speaking");
                break;
            case "gaze_right_hand":
                PositionGazeTarget(0.55f, -0.22f, 2.2f);
                gazeController?.SetState("speaking");
                break;
            case "gaze_left_low":
                PositionGazeTarget(-0.35f, -0.48f, 2.25f);
                gazeController?.SetState("speaking");
                break;
            case "gaze_right_low":
                PositionGazeTarget(0.35f, -0.48f, 2.25f);
                gazeController?.SetState("speaking");
                break;
            case "gaze_soft":
                PositionGazeTarget(0f, -0.05f, 2.4f);
                gazeController?.SetState("idle");
                break;
            case "gaze_idle":
                gazeController?.SetState("idle");
                break;
            default:
                gazeController?.SetState("thinking");
                break;
        }
    }

    private void ApplySwipeGaze(SensorFeedbackData data)
    {
        float horizontal = 0f;
        float vertical = 0f;

        string direction = (data.direction ?? "").Trim().ToLowerInvariant();
        if (direction == "left")
            horizontal = -0.75f;
        else if (direction == "right")
            horizontal = 0.75f;
        else if (direction == "up")
            vertical = 0.45f;
        else if (direction == "down")
            vertical = -0.45f;
        else if (Mathf.Abs(data.dx) > Mathf.Abs(data.dy))
            horizontal = Mathf.Clamp(data.dx / 120f, -0.75f, 0.75f);
        else
            vertical = Mathf.Clamp(-data.dy / 120f, -0.45f, 0.45f);

        PositionGazeTarget(horizontal, vertical, 2.2f);
        gazeController?.SetState("speaking");
    }

    private void PositionGazeTarget(float horizontal, float vertical, float distance)
    {
        EnsureTiltTarget();
        var cam = Camera.main;
        Vector3 origin = cam != null
            ? cam.transform.position + cam.transform.forward * distance
            : transform.position + transform.forward * distance;
        Vector3 right = cam != null ? cam.transform.right : transform.right;
        Vector3 up = cam != null ? cam.transform.up : transform.up;
        _tiltTarget.position = origin + right * Mathf.Clamp(horizontal, -1f, 1f) + up * Mathf.Clamp(vertical, -0.7f, 0.7f);
        gazeController?.SetUserTarget(_tiltTarget);
    }

    private void TriggerGesture(string gestureName, float durationSec)
    {
        if (gestureController == null || string.IsNullOrEmpty(gestureName))
            return;

        float durationMs = Mathf.Max(250f, durationSec * 1000f);
        gestureController.ScheduleGestures(new List<GestureEventData>
        {
            new GestureEventData
            {
                gesture_name = gestureName,
                start_ms = 0f,
                apex_ms = Mathf.Min(300f, durationMs * 0.45f),
                duration_ms = durationMs,
                intensity = 1f
            }
        });
    }

    private void RestartReactTimer(float durationSec)
    {
        CancelReactTimer();
        _reactRoutine = StartCoroutine(FinishReactingAfter(durationSec));
    }

    private void CancelReactTimer()
    {
        if (_reactRoutine != null)
        {
            StopCoroutine(_reactRoutine);
            _reactRoutine = null;
        }
    }

    private IEnumerator FinishReactingAfter(float durationSec)
    {
        yield return new WaitForSeconds(Mathf.Max(0f, durationSec));
        if (CurrentState == DemoState.Reacting)
        {
            expressionController?.ResetToNeutral();
            gazeController?.SetState("idle");
            SetState(BackendConnected ? DemoState.Connected : DemoState.Idle);
            _activeCommandPriority = 0;
        }
        _reactRoutine = null;
    }

    private void SetState(DemoState state)
    {
        CurrentState = state;
    }

    private AvatarInteractionCommand BuildCommand(string evt, SensorFeedbackData data)
    {
        var fallback = DefaultCommand(evt, data.emotion);
        var source = data.command;
        if (source == null || !HasExplicitCommand(source))
            return fallback;

        fallback.State = ParseState(source.state, fallback.State);
        fallback.Emotion = string.IsNullOrEmpty(source.emotion) ? fallback.Emotion : source.emotion;
        fallback.Gesture = source.gesture ?? fallback.Gesture;
        fallback.GazeMode = source.gaze_mode ?? fallback.GazeMode;
        fallback.PoseMode = source.pose_mode ?? fallback.PoseMode;
        fallback.SoundKey = source.sound_key ?? fallback.SoundKey;
        fallback.VfxKey = source.vfx_key ?? fallback.VfxKey;
        fallback.DurationSec = Mathf.Max(0f, source.duration_sec);
        fallback.Priority = source.priority > 0 ? source.priority : fallback.Priority;
        fallback.InterruptPolicy = string.IsNullOrEmpty(source.interrupt_policy) ? fallback.InterruptPolicy : source.interrupt_policy;
        return fallback;
    }

    private AvatarInteractionCommand DefaultCommand(string evt, string emotion)
    {
        var command = new AvatarInteractionCommand
        {
            Emotion = string.IsNullOrEmpty(emotion) ? "neutral" : emotion,
            DurationSec = defaultReactDurationSec
        };

        switch (evt)
        {
            case "shake":
                command.Gesture = "gesture_emphasis";
                command.GazeMode = "gaze_user";
                command.SoundKey = "shake_tone";
                command.VfxKey = "shake_burst";
                command.DurationSec = 0.9f;
                command.Priority = 70;
                command.InterruptPolicy = "interrupt_reacting";
                break;
            case "tilt":
                command.GazeMode = "gaze_follow";
                command.DurationSec = tiltReactDurationSec;
                command.Priority = 10;
                command.InterruptPolicy = "nonblocking";
                break;
            case "tap_hand":
            case "hold_hand":
            case "wave":
                command.Gesture = "gesture_greet";
                command.GazeMode = "gaze_user";
                command.SoundKey = "soft_tone";
                command.VfxKey = "affinity_spark";
                command.DurationSec = 0.8f;
                command.Priority = 35;
                break;
            case "tap_cheek":
            case "hold_cheek":
                command.Gesture = "gesture_uncertain";
                command.GazeMode = "gaze_user";
                command.SoundKey = "tap_tone";
                command.VfxKey = "pink_spark";
                command.DurationSec = 0.7f;
                command.Priority = 30;
                break;
            case "swipe":
                command.Gesture = "gesture_contrast";
                command.GazeMode = "gaze_sweep";
                command.SoundKey = "swipe_tone";
                command.DurationSec = 0.65f;
                command.Priority = 40;
                break;
            case "pickup":
                command.Gesture = "gesture_greet";
                command.GazeMode = "gaze_user";
                command.SoundKey = "soft_tone";
                command.DurationSec = 0.8f;
                command.Priority = 45;
                break;
            case "near_ear":
                command.State = DemoState.Speaking;
                command.Gesture = "gesture_beat";
                command.GazeMode = "gaze_user";
                command.SoundKey = "whisper_cue";
                command.DurationSec = 1.2f;
                command.Priority = 60;
                command.InterruptPolicy = "prefer_speaking";
                break;
            case "walking":
            case "dark":
                command.State = DemoState.Connected;
                command.GazeMode = "gaze_soft";
                command.DurationSec = evt == "dark" ? 1.0f : 0.4f;
                command.Priority = 5;
                command.InterruptPolicy = "hud_only";
                break;
            default:
                command.Gesture = "gesture_beat";
                command.GazeMode = "gaze_user";
                command.SoundKey = "tap_tone";
                command.VfxKey = "pink_spark";
                command.DurationSec = 0.7f;
                command.Priority = 30;
                break;
        }

        return command;
    }

    private void EnsureTiltTarget()
    {
        if (_tiltTarget != null)
            return;

        var target = new GameObject("JD_TiltTarget")
        {
            hideFlags = HideFlags.HideInHierarchy
        };
        target.transform.SetParent(transform, false);
        target.transform.localPosition = new Vector3(0f, 1.5f, 2f);
        _tiltTarget = target.transform;
    }

    private void EnsureParticleSystem()
    {
        if (feedbackParticles != null)
            return;

        var go = new GameObject("JD_FeedbackParticles");
        go.transform.SetParent(transform, false);
        go.transform.localPosition = new Vector3(0f, 1.4f, 1.2f);
        feedbackParticles = go.AddComponent<ParticleSystem>();

        var main = feedbackParticles.main;
        main.startLifetime = 0.55f;
        main.startSpeed = 2.4f;
        main.startSize = 0.08f;
        main.maxParticles = 80;
        main.simulationSpace = ParticleSystemSimulationSpace.World;

        var emission = feedbackParticles.emission;
        emission.enabled = false;

        var shape = feedbackParticles.shape;
        shape.shapeType = ParticleSystemShapeType.Sphere;
        shape.radius = 0.18f;

        var renderer = feedbackParticles.GetComponent<ParticleSystemRenderer>();
        if (renderer != null)
        {
            renderer.renderMode = ParticleSystemRenderMode.Billboard;
            var shader = Shader.Find("Particles/Standard Unlit") ?? Shader.Find("Sprites/Default");
            if (shader != null)
            {
                renderer.sharedMaterial = new Material(shader)
                {
                    name = "JD_FeedbackParticles_Material",
                    hideFlags = HideFlags.HideAndDontSave
                };
            }
            else
            {
                renderer.enabled = false;
            }
        }
    }

    private void PlayParticles(string vfxKey, SensorFeedbackData data)
    {
        if (feedbackParticles == null)
            return;

        feedbackParticles.transform.position = ResolveFeedbackWorldPosition(data);

        var main = feedbackParticles.main;
        main.startColor = vfxKey switch
        {
            "shake_burst" => new ParticleSystem.MinMaxGradient(new Color(1f, 0.85f, 0.25f)),
            "pink_spark" => new ParticleSystem.MinMaxGradient(new Color(1f, 0.35f, 0.75f)),
            "affinity_spark" => new ParticleSystem.MinMaxGradient(new Color(0.35f, 1f, 0.7f)),
            "subtle_spark" => new ParticleSystem.MinMaxGradient(new Color(0.75f, 0.9f, 1f, 0.7f)),
            _ => new ParticleSystem.MinMaxGradient(new Color(0.5f, 1f, 0.65f))
        };

        feedbackParticles.Emit(vfxKey == "shake_burst" ? 36 : vfxKey == "subtle_spark" ? 10 : 18);
    }

    private void PlayToneForKey(string soundKey)
    {
        float frequency = soundKey switch
        {
            "shake_tone" => 740f,
            "tap_tone" => 520f,
            "soft_tone" => 660f,
            "swipe_tone" => 610f,
            "boundary_tone" => 290f,
            "step_tone" => 420f,
            "whisper_cue" => 360f,
            _ => 440f
        };
        float duration = soundKey == "shake_tone" ? 0.12f : soundKey == "boundary_tone" ? 0.1f : 0.08f;
        float volume = soundKey == "whisper_cue" ? 0.1f : 0.18f;
        PlayTone(frequency, duration, volume);
    }

    private Vector3 ResolveFeedbackWorldPosition(SensorFeedbackData data)
    {
        string zone = FeedbackAnatomicalZone(data);
        if (avatarAnimator == null)
            avatarAnimator = GetComponentInChildren<Animator>();

        Transform bone = avatarAnimator != null ? BoneForZone(zone) : null;
        if (bone != null)
            return bone.position;

        Vector3 fallback = transform.position + Vector3.up * 1.3f;
        if (zone.Contains("foot"))
            fallback = transform.position + Vector3.up * 0.08f;
        else if (zone.Contains("calf"))
            fallback = transform.position + Vector3.up * 0.45f;
        else if (zone.Contains("thigh") || zone == "waist")
            fallback = transform.position + Vector3.up * 0.85f;
        else if (zone.Contains("hand") || zone.Contains("forearm"))
            fallback = transform.position + Vector3.up * 0.95f;
        else if (zone == "head" || zone == "face")
            fallback = transform.position + Vector3.up * 1.55f;

        if (zone.StartsWith("left_", StringComparison.Ordinal))
            fallback += transform.TransformDirection(Vector3.left) * 0.22f;
        else if (zone.StartsWith("right_", StringComparison.Ordinal))
            fallback += transform.TransformDirection(Vector3.right) * 0.22f;

        return fallback;
    }

    private static string FeedbackAnatomicalZone(SensorFeedbackData data)
    {
        string anatomical = (data?.anatomical_zone ?? "").Trim().ToLowerInvariant();
        if (!string.IsNullOrEmpty(anatomical))
            return anatomical;

        return (data?.zone ?? "").Trim().ToLowerInvariant();
    }

    private static string DisplayZone(SensorFeedbackData data)
    {
        string visual = (data?.visual_zone ?? "").Trim().ToLowerInvariant();
        string anatomical = (data?.anatomical_zone ?? "").Trim().ToLowerInvariant();
        string zone = (data?.zone ?? "").Trim().ToLowerInvariant();

        if (!string.IsNullOrEmpty(visual) && !string.IsNullOrEmpty(anatomical) && visual != anatomical)
            return visual + " -> " + anatomical;

        if (!string.IsNullOrEmpty(visual))
            return visual;

        return zone;
    }

    private Transform BoneForZone(string zone)
    {
        if (avatarAnimator == null)
            return null;

        HumanBodyBones bone = zone switch
        {
            "head" => HumanBodyBones.Head,
            "face" => HumanBodyBones.Head,
            "neck" => HumanBodyBones.Neck,
            "chest" => HumanBodyBones.Chest,
            "waist" => HumanBodyBones.Hips,
            "left_shoulder" => HumanBodyBones.LeftShoulder,
            "right_shoulder" => HumanBodyBones.RightShoulder,
            "left_upper_arm" => HumanBodyBones.LeftUpperArm,
            "right_upper_arm" => HumanBodyBones.RightUpperArm,
            "left_forearm" => HumanBodyBones.LeftLowerArm,
            "right_forearm" => HumanBodyBones.RightLowerArm,
            "left_hand" => HumanBodyBones.LeftHand,
            "right_hand" => HumanBodyBones.RightHand,
            "left_thigh" => HumanBodyBones.LeftUpperLeg,
            "right_thigh" => HumanBodyBones.RightUpperLeg,
            "left_calf" => HumanBodyBones.LeftLowerLeg,
            "right_calf" => HumanBodyBones.RightLowerLeg,
            "left_foot" => HumanBodyBones.LeftFoot,
            "right_foot" => HumanBodyBones.RightFoot,
            _ => HumanBodyBones.LastBone
        };

        return bone == HumanBodyBones.LastBone ? null : avatarAnimator.GetBoneTransform(bone);
    }

    private void PlayTone(float frequency, float durationSec, float volume)
    {
        if (audioSource == null)
            return;

        const int sampleRate = 24000;
        int samples = Mathf.Max(1, Mathf.RoundToInt(sampleRate * durationSec));
        var data = new float[samples];
        for (int i = 0; i < samples; i++)
        {
            float t = i / (float)sampleRate;
            float envelope = 1f - i / (float)samples;
            data[i] = Mathf.Sin(2f * Mathf.PI * frequency * t) * envelope * volume;
        }

        var clip = AudioClip.Create("JD_Tone_" + frequency, samples, 1, sampleRate, false);
        clip.SetData(data, 0);
        audioSource.PlayOneShot(clip);
    }

    private void AddLog(string line)
    {
        string stamped = DateTime.Now.ToString("HH:mm:ss") + " " + line;
        _recentEvents.Insert(0, stamped);
        while (_recentEvents.Count > maxEventLog)
            _recentEvents.RemoveAt(_recentEvents.Count - 1);
    }

    private void AddSessionId(string sessionId)
    {
        if (string.IsNullOrEmpty(sessionId))
            return;

        _recentSessionIds.Insert(0, DateTime.Now.ToString("HH:mm:ss") + "  " + sessionId);
        while (_recentSessionIds.Count > 5)
            _recentSessionIds.RemoveAt(_recentSessionIds.Count - 1);
    }

    private static bool HasExplicitCommand(AvatarInteractionCommandData command)
    {
        return command.state != "Reacting" ||
               !string.IsNullOrEmpty(command.gesture) ||
               !string.IsNullOrEmpty(command.gaze_mode) ||
               !string.IsNullOrEmpty(command.pose_mode) ||
               !string.IsNullOrEmpty(command.sound_key) ||
               !string.IsNullOrEmpty(command.vfx_key) ||
               !Mathf.Approximately(command.duration_sec, 0.9f) ||
               command.priority != 10 ||
               command.interrupt_policy != "normal";
    }

    private static DemoState ParseState(string state, DemoState fallback)
    {
        if (Enum.TryParse(state, true, out DemoState parsed))
            return parsed;
        return fallback;
    }

    private static string NormalizeEvent(string value)
    {
        return string.IsNullOrEmpty(value) ? "unknown" : value.Trim().ToLowerInvariant();
    }

    private static string Shorten(string value, int max)
    {
        if (string.IsNullOrEmpty(value) || value.Length <= max)
            return value ?? "";
        return value.Substring(0, max) + "...";
    }
}
