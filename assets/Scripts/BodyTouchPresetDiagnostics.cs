using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

[DefaultExecutionOrder(22000)]
public sealed class BodyTouchPresetDiagnostics : MonoBehaviour
{
    private const float LocalPositionRecoveryThreshold = 0.01f;
    private const float HeadViewportRecoveryThreshold = 0.05f;
    private const float HipsViewportRecoveryThreshold = 0.05f;
    private const float FootViewportRecoveryThreshold = 0.06f;
    private const float TargetRotationThresholdDeg = 2f;
    private const float TargetViewportThreshold = 0.01f;
    private const float ScreenshotMinAverageBrightness = 3f;
    private const float ScreenshotMinUsefulPixelRatio = 0.05f;
    private const float TPoseArmHorizontalThresholdDeg = 24f;

    private static readonly string[] BodyTouchZones =
    {
        "head",
        "face",
        "neck",
        "chest",
        "waist",
        "left_shoulder",
        "right_shoulder",
        "left_upper_arm",
        "right_upper_arm",
        "left_forearm",
        "right_forearm",
        "left_hand",
        "right_hand",
        "left_thigh",
        "right_thigh",
        "left_calf",
        "right_calf",
        "left_foot",
        "right_foot",
    };

    private static readonly HumanBodyBones[] SampleBones =
    {
        HumanBodyBones.Head,
        HumanBodyBones.Neck,
        HumanBodyBones.Chest,
        HumanBodyBones.Hips,
        HumanBodyBones.LeftShoulder,
        HumanBodyBones.RightShoulder,
        HumanBodyBones.LeftUpperArm,
        HumanBodyBones.RightUpperArm,
        HumanBodyBones.LeftLowerArm,
        HumanBodyBones.RightLowerArm,
        HumanBodyBones.LeftHand,
        HumanBodyBones.RightHand,
        HumanBodyBones.LeftUpperLeg,
        HumanBodyBones.RightUpperLeg,
        HumanBodyBones.LeftLowerLeg,
        HumanBodyBones.RightLowerLeg,
        HumanBodyBones.LeftFoot,
        HumanBodyBones.RightFoot,
    };

    [Header("References")]
    [SerializeField] private JdDemoInteractionController interactionController;
    [SerializeField] private Animator avatarAnimator;
    [SerializeField] private Camera sourceCamera;

    [Header("Backend")]
    [SerializeField] private string backendSensorUrl = "ws://127.0.0.1:8100/ws/sensor";
    [SerializeField] private bool preferBackendChain = true;

    [Header("Output")]
    [SerializeField] private string outputRoot = "diagnostics/body_touch";
    [SerializeField] private bool captureScreenshots = true;

    [Header("Timing")]
    [SerializeField] private float resetSettleSec = 0.7f;
    [SerializeField] private float stablePoseTimeoutSec = 3.0f;
    [SerializeField] private float stablePoseSampleIntervalSec = 0.12f;
    [SerializeField] private int stablePoseRequiredSamples = 3;
    [SerializeField] private float stablePoseViewportThreshold = 0.006f;
    [SerializeField] private float reactionStartSec = 0.15f;
    [SerializeField] private float reactionPeakSec = 0.35f;
    [SerializeField] private float recoveryPaddingSec = 0.3f;
    [SerializeField] private float backendAckTimeoutSec = 3f;

    public bool IsRunning { get; private set; }
    public string LatestRunId { get; private set; } = "";
    public string LatestReportDirectory { get; private set; } = "";
    public string LatestJsonReportPath { get; private set; } = "";
    public string LatestMarkdownReportPath { get; private set; } = "";
    public string LatestHtmlReportPath { get; private set; } = "";
    public string LatestSummary { get; private set; } = "";

    private readonly List<string> _consoleErrors = new List<string>();
    private Coroutine _runningRoutine;

    public static BodyTouchPresetDiagnostics EnsureInScene()
    {
        var existing = FindFirstObjectByType<BodyTouchPresetDiagnostics>();
        if (existing != null)
            return existing;

        var client = FindFirstObjectByType<NetworkClient>();
        var host = client != null ? client.gameObject : new GameObject("BodyTouchPresetDiagnostics");
        var diagnostics = host.AddComponent<BodyTouchPresetDiagnostics>();
        diagnostics.ResolveReferences();
        return diagnostics;
    }

    public static string RunFullMatrixFromMcp()
    {
        return EnsureInScene().StartFullMatrix(true);
    }

    public static string RunDirectFullMatrixFromMcp()
    {
        return EnsureInScene().StartFullMatrix(false);
    }

    public static string RunSmokeFromMcp()
    {
        return EnsureInScene().StartSmoke(true);
    }

    public static string GetLatestSummaryFromMcp()
    {
        var diagnostics = FindFirstObjectByType<BodyTouchPresetDiagnostics>();
        return diagnostics == null ? "BodyTouchPresetDiagnostics not found." : diagnostics.LatestSummary;
    }

    public string StartFullMatrix(bool preferBackend)
    {
        return StartRun(BuildFullMatrix(), preferBackend);
    }

    public string StartSmoke(bool preferBackend)
    {
        var specs = new List<EventSpec>
        {
            EventSpec.Touch("tap_head", "head", "tap"),
            EventSpec.Touch("tap_left_shoulder", "left_shoulder", "tap"),
            EventSpec.Touch("tap_right_shoulder", "right_shoulder", "tap"),
            EventSpec.Touch("hold_left_hand", "left_hand", "hold"),
            EventSpec.Touch("hold_right_hand", "right_hand", "hold"),
            EventSpec.Touch("tap_chest", "chest", "tap"),
            EventSpec.Touch("tap_waist", "waist", "tap"),
            EventSpec.Touch("tap_left_foot", "left_foot", "tap"),
            EventSpec.Touch("tap_right_foot", "right_foot", "tap"),
            EventSpec.Swipe("swipe_right_smoke", "swipe", "chest", "right"),
            EventSpec.Alias("tap_cheek", "tap_cheek", "face"),
            EventSpec.Alias("hold_hand", "hold_hand", "right_hand"),
        };
        return StartRun(specs, preferBackend);
    }

    private string StartRun(List<EventSpec> specs, bool preferBackend)
    {
        ResolveReferences();
        if (interactionController == null)
        {
            LatestSummary = "FAIL: JdDemoInteractionController not found.";
            return LatestSummary;
        }

        if (avatarAnimator == null)
        {
            LatestSummary = "FAIL: Animator not found.";
            return LatestSummary;
        }

        if (IsRunning)
            return "Body touch diagnostics already running: " + LatestRunId;

        preferBackendChain = preferBackend;
        LatestRunId = DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture);
        LatestReportDirectory = Path.Combine(ProjectRoot(), outputRoot, LatestRunId).Replace('\\', '/');
        Directory.CreateDirectory(LatestReportDirectory);

        _runningRoutine = StartCoroutine(RunRoutine(specs));
        LatestSummary = "STARTED: " + LatestRunId + " -> " + LatestReportDirectory;
        Debug.Log("[BodyTouchPresetDiagnostics] " + LatestSummary, this);
        return LatestSummary;
    }

    private IEnumerator RunRoutine(List<EventSpec> specs)
    {
        IsRunning = true;
        _consoleErrors.Clear();
        Application.logMessageReceived += OnLogMessageReceived;

        var results = new List<EventResult>();
        string runStartedAt = DateTime.Now.ToString("O", CultureInfo.InvariantCulture);

        try
        {
            yield return ResetAndSettle();

            for (int i = 0; i < specs.Count; i++)
            {
                var spec = specs[i];
                var result = new EventResult(spec);
                results.Add(result);

                string eventDir = Path.Combine(LatestReportDirectory, SafeFileName($"{i + 1:000}_{spec.Id}")).Replace('\\', '/');
                Directory.CreateDirectory(eventDir);
                result.EventDirectory = eventDir;

                int errorStart = _consoleErrors.Count;
                yield return ResetAndSettle();
                yield return WaitForDemoIdlePoseWarning(value => result.StartupPoseWarning = value);

                result.Baseline = SampleBonesNow();
                yield return CaptureStage(result, "baseline");

                yield return DispatchEvent(spec, result);
                yield return WaitSecondsUnscaled(reactionStartSec);
                result.Start = SampleBonesNow();
                yield return CaptureStage(result, "start");

                yield return WaitSecondsUnscaled(Mathf.Max(0f, reactionPeakSec - reactionStartSec));
                result.Peak = SampleBonesNow();
                yield return CaptureStage(result, "peak");

                float duration = Mathf.Max(result.CommandDurationSec, DirectDurationFor(spec));
                float remaining = Mathf.Max(0f, duration + recoveryPaddingSec - reactionPeakSec);
                yield return WaitSecondsUnscaled(remaining);
                result.Recovery = SampleBonesNow();
                yield return CaptureStage(result, "recovery");

                for (int e = errorStart; e < _consoleErrors.Count; e++)
                    result.ConsoleErrors.Add(_consoleErrors[e]);

                EvaluateResult(result);
                Debug.Log($"[BodyTouchPresetDiagnostics] {i + 1}/{specs.Count} {spec.Id}: {result.Status} {string.Join("; ", result.Reasons)}", this);
            }
        }
        finally
        {
            Application.logMessageReceived -= OnLogMessageReceived;
            IsRunning = false;
            _runningRoutine = null;
        }

        var report = new DiagnosticsReport
        {
            RunId = LatestRunId,
            StartedAt = runStartedAt,
            FinishedAt = DateTime.Now.ToString("O", CultureInfo.InvariantCulture),
            PreferBackend = preferBackendChain,
            SensorUrl = backendSensorUrl,
            ReportDirectory = LatestReportDirectory,
            Results = results,
        };

        WriteReports(report);
        LatestSummary = BuildSummary(report);
        Debug.Log("[BodyTouchPresetDiagnostics] " + LatestSummary, this);
    }

    private IEnumerator DispatchEvent(EventSpec spec, EventResult result)
    {
        bool sentByBackend = false;
        if (preferBackendChain && !string.IsNullOrEmpty(backendSensorUrl) && !string.IsNullOrEmpty(interactionController.SessionId))
        {
            var task = SendSensorEventViaBackendAsync(spec, interactionController.SessionId);
            float deadline = Time.realtimeSinceStartup + Mathf.Max(0.5f, backendAckTimeoutSec + 0.5f);
            while (!task.IsCompleted && Time.realtimeSinceStartup < deadline)
                yield return null;

            if (task.IsCompletedSuccessfully)
            {
                var dispatch = task.Result;
                result.BackendAttempted = true;
                result.BackendAccepted = dispatch.Accepted;
                result.BackendAckEvent = dispatch.AckEvent;
                result.BackendMessage = dispatch.Message;
                if (dispatch.Accepted)
                    sentByBackend = true;
            }
            else
            {
                result.BackendAttempted = true;
                result.BackendAccepted = false;
                result.BackendMessage = task.IsFaulted && task.Exception != null
                    ? task.Exception.GetBaseException().Message
                    : "backend ack timeout";
            }
        }
        else if (preferBackendChain)
        {
            result.BackendAttempted = true;
            result.BackendAccepted = false;
            result.BackendMessage = string.IsNullOrEmpty(interactionController.SessionId)
                ? "no Unity session id; using direct fallback"
                : "backendSensorUrl is empty; using direct fallback";
        }

        if (sentByBackend)
        {
            result.DispatchMode = "backend";
            string expected = NormalizeEvent(spec.EventName);
            float deadline = Time.realtimeSinceStartup + 1.5f;
            while (Time.realtimeSinceStartup < deadline)
            {
                if (interactionController.LastEvent == expected || expected == "reset")
                    break;
                yield return null;
            }

            CaptureLastCommand(result);
            if (expected == "reset" && string.IsNullOrEmpty(result.CommandPoseMode))
                CaptureCommand(result, DirectCommandFor("reset", "", ""));
            yield break;
        }

        result.DispatchMode = "direct_fallback";
        var feedback = BuildDirectFeedback(spec);
        interactionController.InjectSensorFeedbackForDiagnostics(feedback);
        CaptureLastCommand(result);
        if (string.IsNullOrEmpty(result.CommandPoseMode))
            CaptureCommand(result, feedback.command);
        yield return null;
    }

    private IEnumerator ResetAndSettle()
    {
        var reset = BuildDirectFeedback(EventSpec.Alias("reset", "reset", ""));
        interactionController.InjectSensorFeedbackForDiagnostics(reset);
        yield return WaitSecondsUnscaled(resetSettleSec);
        yield return WaitForStablePose();
    }

    private IEnumerator WaitForStablePose()
    {
        float deadline = Time.realtimeSinceStartup + Mathf.Max(0.2f, stablePoseTimeoutSec);
        int stableCount = 0;
        BoneSampleSet previous = SampleBonesNow();

        while (Time.realtimeSinceStartup < deadline)
        {
            yield return WaitSecondsUnscaled(Mathf.Max(0.03f, stablePoseSampleIntervalSec));
            var current = SampleBonesNow();
            float delta = MaxTrackedViewportDelta(previous, current);
            if (delta <= stablePoseViewportThreshold)
            {
                stableCount++;
                if (stableCount >= Mathf.Max(1, stablePoseRequiredSamples))
                    yield break;
            }
            else
            {
                stableCount = 0;
            }

            previous = current;
        }
    }

    private IEnumerator WaitForDemoIdlePoseWarning(Action<string> setWarning)
    {
        float deadline = Time.realtimeSinceStartup + Mathf.Max(0.2f, stablePoseTimeoutSec);
        int stableCount = 0;
        BoneSampleSet previous = SampleBonesNow();
        string lastReason = "";

        while (Time.realtimeSinceStartup < deadline)
        {
            yield return WaitSecondsUnscaled(Mathf.Max(0.03f, stablePoseSampleIntervalSec));
            var current = SampleBonesNow();
            float delta = MaxTrackedViewportDelta(previous, current);
            bool stable = delta <= stablePoseViewportThreshold;
            bool tPose = IsLikelyTPose(current);

            if (stable && !tPose)
            {
                stableCount++;
                if (stableCount >= Mathf.Max(1, stablePoseRequiredSamples))
                {
                    setWarning?.Invoke("");
                    yield break;
                }
            }
            else
            {
                stableCount = 0;
                lastReason = tPose ? "startup pose not settled" : "startup viewport not stable";
            }

            previous = current;
        }

        setWarning?.Invoke(string.IsNullOrEmpty(lastReason) ? "startup pose not settled" : lastReason);
    }

    private void CaptureLastCommand(EventResult result)
    {
        result.UnityLastEvent = interactionController.LastEvent;
        result.UnityLastZone = interactionController.LastZone;
        result.UnityState = interactionController.CurrentState.ToString();
        result.CommandEmotion = interactionController.LastCommandEmotion;
        result.CommandGesture = interactionController.LastCommandGesture;
        result.CommandGazeMode = interactionController.LastCommandGazeMode;
        result.CommandPoseMode = interactionController.LastCommandPoseMode;
        result.CommandSoundKey = interactionController.LastCommandSoundKey;
        result.CommandVfxKey = interactionController.LastCommandVfxKey;
        result.CommandDurationSec = interactionController.LastCommandDurationSec;
        result.CommandPriority = interactionController.LastCommandPriority;
        result.CommandInterruptPolicy = interactionController.LastCommandInterruptPolicy;
    }

    private static void CaptureCommand(EventResult result, AvatarInteractionCommandData command)
    {
        if (command == null)
            return;

        result.CommandEmotion = command.emotion ?? "";
        result.CommandGesture = command.gesture ?? "";
        result.CommandGazeMode = command.gaze_mode ?? "";
        result.CommandPoseMode = command.pose_mode ?? "";
        result.CommandSoundKey = command.sound_key ?? "";
        result.CommandVfxKey = command.vfx_key ?? "";
        result.CommandDurationSec = command.duration_sec;
        result.CommandPriority = command.priority;
        result.CommandInterruptPolicy = command.interrupt_policy ?? "";
    }

    private IEnumerator CaptureStage(EventResult result, string stage)
    {
        if (!captureScreenshots)
            yield break;

        yield return new WaitForEndOfFrame();

        string path = Path.Combine(result.EventDirectory, stage + ".png").Replace('\\', '/');
        var stats = CaptureScreenshot(path);
        result.Screenshots[stage] = path;
        result.ScreenshotStats[stage] = stats;
    }

    private ScreenshotStats CaptureScreenshot(string path)
    {
        int width = Mathf.Max(1, Screen.width);
        int height = Mathf.Max(1, Screen.height);
        var texture = new Texture2D(width, height, TextureFormat.RGB24, false);
        texture.ReadPixels(new Rect(0, 0, width, height), 0, 0);
        texture.Apply(false);

        Color32[] pixels = texture.GetPixels32();
        long brightnessTotal = 0;
        int usefulPixels = 0;
        for (int i = 0; i < pixels.Length; i++)
        {
            int brightness = (pixels[i].r + pixels[i].g + pixels[i].b) / 3;
            brightnessTotal += brightness;
            if (brightness > 8)
                usefulPixels++;
        }

        File.WriteAllBytes(path, texture.EncodeToPNG());
        Destroy(texture);

        return new ScreenshotStats
        {
            Width = width,
            Height = height,
            AverageBrightness = pixels.Length > 0 ? brightnessTotal / (float)pixels.Length : 0f,
            UsefulPixelRatio = pixels.Length > 0 ? usefulPixels / (float)pixels.Length : 0f,
        };
    }

    private BoneSampleSet SampleBonesNow()
    {
        if (sourceCamera == null)
            sourceCamera = Camera.main;

        var set = new BoneSampleSet();
        foreach (var bone in SampleBones)
        {
            var sample = new BoneSample
            {
                Bone = bone.ToString(),
            };

            var transformForBone = avatarAnimator != null ? avatarAnimator.GetBoneTransform(bone) : null;
            if (transformForBone == null)
            {
                sample.Exists = false;
                set.Bones[sample.Bone] = sample;
                continue;
            }

            sample.Exists = true;
            sample.World = transformForBone.position;
            sample.LocalPosition = transformForBone.localPosition;
            sample.LocalRotation = transformForBone.localRotation;
            sample.LocalRotationEuler = transformForBone.localRotation.eulerAngles;

            if (sourceCamera != null)
            {
                sample.Viewport = sourceCamera.WorldToViewportPoint(transformForBone.position);
                sample.Visible = sample.Viewport.z > 0f &&
                                 sample.Viewport.x >= -0.15f && sample.Viewport.x <= 1.15f &&
                                 sample.Viewport.y >= -0.15f && sample.Viewport.y <= 1.15f;
            }

            set.Bones[sample.Bone] = sample;
        }

        return set;
    }

    private void EvaluateResult(EventResult result)
    {
        result.Status = "PASS";
        result.Reasons.Clear();

        if (result.DispatchMode == "backend" && !result.BackendAccepted)
            Fail(result, "backend rejected event");

        if (result.DispatchMode == "direct_fallback" && result.BackendAttempted)
            Warn(result, "backend unavailable; used direct fallback: " + result.BackendMessage);

        if (string.IsNullOrEmpty(result.CommandEmotion))
            Fail(result, "missing command emotion");
        if (string.IsNullOrEmpty(result.CommandPoseMode))
            Fail(result, "missing command pose_mode");
        if (string.IsNullOrEmpty(result.CommandInterruptPolicy))
            Fail(result, "missing interrupt_policy");
        if (result.CommandDurationSec < 0f)
            Fail(result, "invalid duration_sec");

        if (result.ConsoleErrors.Count > 0)
            Fail(result, "Unity console errors: " + result.ConsoleErrors.Count);

        if (!string.IsNullOrEmpty(result.StartupPoseWarning))
            Warn(result, result.StartupPoseWarning);

        CheckScreenshots(result);
        CheckComposition(result);
        CheckMotion(result);
        CheckSensitiveVoicePolicy(result);
    }

    private void CheckScreenshots(EventResult result)
    {
        foreach (var item in result.ScreenshotStats)
        {
            if (item.Value.AverageBrightness <= ScreenshotMinAverageBrightness)
                Fail(result, item.Key + " screenshot is too dark/blank");
            if (item.Value.UsefulPixelRatio <= ScreenshotMinUsefulPixelRatio)
                Fail(result, item.Key + " screenshot useful pixel ratio too low");
        }
    }

    private void CheckComposition(EventResult result)
    {
        var recovery = result.Recovery;
        if (recovery == null)
            return;

        CheckViewportRange(result, recovery, "Head", 0.45f, 0.95f, -0.15f, 1.15f);
        CheckViewportRange(result, recovery, "Hips", 0.15f, 0.75f, -0.15f, 1.15f);
        CheckViewportRange(result, recovery, "LeftFoot", -0.05f, 0.35f, -0.15f, 1.15f);
        CheckViewportRange(result, recovery, "RightFoot", -0.05f, 0.35f, -0.15f, 1.15f);
    }

    private void CheckViewportRange(EventResult result, BoneSampleSet set, string bone, float minY, float maxY, float minX, float maxX)
    {
        if (!set.TryGet(bone, out var sample) || !sample.Exists)
        {
            Warn(result, bone + " missing");
            return;
        }

        if (sample.Viewport.z <= 0f ||
            sample.Viewport.x < minX || sample.Viewport.x > maxX ||
            sample.Viewport.y < minY || sample.Viewport.y > maxY)
        {
            Fail(result, $"{bone} viewport out of range: {FormatVector(sample.Viewport)}");
        }
    }

    private void CheckMotion(EventResult result)
    {
        if (result.Baseline == null || result.Peak == null || result.Recovery == null)
            return;

        result.LocalPositionMaxDelta = MaxLocalPositionDelta(result.Baseline, result.Recovery);
        if (result.LocalPositionMaxDelta > LocalPositionRecoveryThreshold)
            Fail(result, "localPosition drift after recovery: " + FormatFloat(result.LocalPositionMaxDelta));

        result.HeadViewportRecoveryDelta = ViewportDelta(result.Baseline, result.Recovery, "Head");
        result.HipsViewportRecoveryDelta = ViewportDelta(result.Baseline, result.Recovery, "Hips");
        result.FeetViewportRecoveryDelta = Mathf.Max(
            ViewportDelta(result.Baseline, result.Recovery, "LeftFoot"),
            ViewportDelta(result.Baseline, result.Recovery, "RightFoot"));

        if (result.HeadViewportRecoveryDelta > HeadViewportRecoveryThreshold)
            Fail(result, "Head viewport did not recover: " + FormatFloat(result.HeadViewportRecoveryDelta));
        if (result.HipsViewportRecoveryDelta > HipsViewportRecoveryThreshold)
            Fail(result, "Hips viewport did not recover: " + FormatFloat(result.HipsViewportRecoveryDelta));
        if (result.FeetViewportRecoveryDelta > FootViewportRecoveryThreshold)
            Fail(result, "Feet viewport did not recover: " + FormatFloat(result.FeetViewportRecoveryDelta));

        var targetBones = TargetBonesForZone(result.Spec.Zone);
        result.TargetRotationDeltaDeg = MaxRotationDelta(result.Baseline, result.Peak, targetBones);
        result.TargetViewportDelta = MaxViewportDelta(result.Baseline, result.Peak, targetBones);
        if (result.Spec.EventName != "reset" &&
            result.TargetRotationDeltaDeg < TargetRotationThresholdDeg &&
            result.TargetViewportDelta < TargetViewportThreshold)
        {
            Warn(result, "target bones barely changed");
        }

        CheckSideDominance(result);
    }

    private void CheckSideDominance(EventResult result)
    {
        string zone = result.Spec.Zone;
        if (string.IsNullOrEmpty(zone))
            return;

        bool left = zone.StartsWith("left_", StringComparison.Ordinal);
        bool right = zone.StartsWith("right_", StringComparison.Ordinal);
        if (!left && !right)
            return;

        string oppositeZone = left ? "right_" + zone.Substring("left_".Length) : "left_" + zone.Substring("right_".Length);
        var own = TargetBonesForZone(zone);
        var opposite = TargetBonesForZone(oppositeZone);
        float ownDelta = MaxRotationDelta(result.Baseline, result.Peak, own);
        float oppositeDelta = MaxRotationDelta(result.Baseline, result.Peak, opposite);
        result.OwnSideRotationDeltaDeg = ownDelta;
        result.OppositeSideRotationDeltaDeg = oppositeDelta;

        if (ownDelta + 0.25f < oppositeDelta * 0.8f)
            Warn(result, "opposite side moved more than touched side");
    }

    private void CheckSensitiveVoicePolicy(EventResult result)
    {
        string zone = result.Spec.Zone;
        if (string.IsNullOrEmpty(zone))
            return;

        bool sensitive = zone == "chest" ||
                         zone == "waist" ||
                         zone.EndsWith("_thigh", StringComparison.Ordinal) ||
                         zone.EndsWith("_calf", StringComparison.Ordinal) ||
                         zone.EndsWith("_foot", StringComparison.Ordinal);

        if (!sensitive)
            return;

        string expectedSound = zone == "chest" || zone == "waist" ? "boundary_tone" : "step_tone";
        if (result.CommandSoundKey != expectedSound || result.CommandVfxKey != "subtle_spark")
        {
            Warn(result, "sensitive zone did not use expected boundary/step feedback keys");
        }
    }

    private async Task<SensorDispatchResult> SendSensorEventViaBackendAsync(EventSpec spec, string sessionId)
    {
        var result = new SensorDispatchResult();
        using var ws = new System.Net.WebSockets.ClientWebSocket();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(Mathf.Max(1f, backendAckTimeoutSec)));

        await ws.ConnectAsync(new Uri(backendSensorUrl), cts.Token);
        await SendTextAsync(ws, "{\"type\":\"sensor.bind\",\"session_id\":\"" + EscapeJson(sessionId) + "\"}", cts.Token);
        await ReceiveTextAsync(ws, cts.Token);

        await SendTextAsync(ws, BuildSensorEventJson(spec, sessionId), cts.Token);
        while (!cts.IsCancellationRequested)
        {
            string message = await ReceiveTextAsync(ws, cts.Token);
            if (message.IndexOf("\"type\":\"sensor.ack\"", StringComparison.Ordinal) < 0)
                continue;

            result.Accepted = ExtractJsonBool(message, "accepted");
            result.AckEvent = ExtractJsonString(message, "event") ?? "";
            result.Message = ExtractJsonString(message, "reason") ?? "";
            return result;
        }

        result.Accepted = false;
        result.Message = "ack timeout";
        return result;
    }

    private static async Task SendTextAsync(System.Net.WebSockets.ClientWebSocket ws, string text, CancellationToken ct)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(text);
        await ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, ct);
    }

    private static async Task<string> ReceiveTextAsync(System.Net.WebSockets.ClientWebSocket ws, CancellationToken ct)
    {
        var buffer = new byte[65536];
        using var ms = new MemoryStream();
        WebSocketReceiveResult result;
        do
        {
            result = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), ct);
            if (result.MessageType == WebSocketMessageType.Close)
                return "";
            ms.Write(buffer, 0, result.Count);
        }
        while (!result.EndOfMessage);

        return Encoding.UTF8.GetString(ms.ToArray());
    }

    private static string BuildSensorEventJson(EventSpec spec, string sessionId)
    {
        long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        string zone = spec.Zone ?? "";
        string direction = spec.Direction ?? "";
        string side = SideForZone(zone);
        string group = BodyGroupForZone(zone);
        float dx = direction == "left" ? -90f : direction == "right" ? 90f : 0f;
        float dy = direction == "up" ? -90f : direction == "down" ? 90f : 0f;

        var sb = new StringBuilder(512);
        sb.Append('{');
        sb.Append("\"type\":\"sensor.event\",");
        sb.Append("\"session_id\":\"").Append(EscapeJson(sessionId)).Append("\",");
        sb.Append("\"event\":\"").Append(EscapeJson(spec.EventName)).Append("\",");
        if (!string.IsNullOrEmpty(zone))
            sb.Append("\"zone\":\"").Append(EscapeJson(zone)).Append("\",");
        sb.Append("\"diagnostic\":true,");
        sb.Append("\"timestamp_ms\":").Append(now).Append(',');
        sb.Append("\"value\":{");
        sb.Append("\"diagnostic\":true,");
        sb.Append("\"simulated\":true,");
        sb.Append("\"confidence\":1.0,");
        sb.Append("\"touch_x\":0.5,");
        sb.Append("\"touch_y\":0.5,");
        sb.Append("\"duration_ms\":300,");
        sb.Append("\"dx\":").Append(FormatFloat(dx)).Append(',');
        sb.Append("\"dy\":").Append(FormatFloat(dy));
        if (!string.IsNullOrEmpty(zone))
        {
            sb.Append(",\"zone\":\"").Append(EscapeJson(zone)).Append('"');
            sb.Append(",\"side\":\"").Append(EscapeJson(side)).Append('"');
            sb.Append(",\"body_group\":\"").Append(EscapeJson(group)).Append('"');
            sb.Append(",\"anchors_live\":true");
        }
        if (!string.IsNullOrEmpty(direction))
            sb.Append(",\"direction\":\"").Append(EscapeJson(direction)).Append('"');
        sb.Append("}}");
        return sb.ToString();
    }

    private SensorFeedbackData BuildDirectFeedback(EventSpec spec)
    {
        string normalized = NormalizeEvent(spec.EventName);
        string zone = string.IsNullOrEmpty(spec.Zone) ? ZoneFromEvent(normalized) : spec.Zone;
        var command = DirectCommandFor(normalized, zone, spec.Direction);

        return new SensorFeedbackData
        {
            session_id = interactionController != null ? interactionController.SessionId : "",
            event_name = normalized,
            zone = zone,
            visual_zone = zone,
            anatomical_zone = zone,
            zone_basis = "diagnostic_direct",
            timestamp_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            received_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            latency_ms = 0,
            emotion = command.emotion,
            jd_state = command.state,
            energy_delta = 0,
            affinity_delta = 0,
            score_delta = 0,
            feedback_tags = new List<string> { "diagnostic", "pose", "gaze", "sound", "vfx" },
            command = command,
            confidence = 1f,
            touch_x = 0.5f,
            touch_y = 0.5f,
            dx = spec.Direction == "left" ? -90f : spec.Direction == "right" ? 90f : 0f,
            dy = spec.Direction == "up" ? -90f : spec.Direction == "down" ? 90f : 0f,
            duration_ms = 300f,
            direction = spec.Direction ?? "",
            anchors_live = true,
            simulated = true,
        };
    }

    private static AvatarInteractionCommandData DirectCommandFor(string normalizedEvent, string zone, string direction)
    {
        if (normalizedEvent == "reset")
        {
            return new AvatarInteractionCommandData
            {
                state = "Connected",
                emotion = "neutral",
                pose_mode = "reset",
                gaze_mode = "gaze_idle",
                duration_sec = 0f,
                priority = 100,
                interrupt_policy = "force",
            };
        }

        if (normalizedEvent == "swipe")
        {
            if (!string.IsNullOrEmpty(zone))
            {
                var swipeCommand = DirectTouchCommandForZone(zone, false);
                swipeCommand.gaze_mode = "gaze_sweep";
                swipeCommand.duration_sec = DirectSwipeDurationForZone(zone);
                return swipeCommand;
            }

            return new AvatarInteractionCommandData
            {
                state = "Reacting",
                emotion = "happy",
                gesture = "gesture_contrast",
                gaze_mode = "gaze_sweep",
                pose_mode = "swipe_shift",
                sound_key = "swipe_tone",
                duration_sec = 0.65f,
                priority = 40,
                interrupt_policy = "normal",
            };
        }

        bool hold = normalizedEvent.StartsWith("hold_", StringComparison.Ordinal);
        return DirectTouchCommandForZone(zone, hold);
    }

    private static AvatarInteractionCommandData DirectTouchCommandForZone(string zone, bool hold)
    {
        string group = BodyGroupForZone(zone);
        string side = SideForZone(zone);
        var command = new AvatarInteractionCommandData
        {
            state = "Reacting",
            emotion = DirectEmotionFor(zone, hold),
            pose_mode = PoseForZone(zone, hold),
            duration_sec = hold ? 1.0f : 0.75f,
            priority = 30,
            interrupt_policy = "normal",
        };

        if (group == "head" || group == "face" || group == "neck")
        {
            command.gesture = group == "head" ? "gesture_beat" : "gesture_uncertain";
            command.gaze_mode = "gaze_user";
            command.sound_key = hold ? "soft_tone" : "tap_tone";
            command.vfx_key = "pink_spark";
            command.duration_sec = hold ? 1.0f : 0.75f;
            command.priority = hold ? 28 : 32;
        }
        else if (group == "shoulder" || group == "upper_arm" || group == "forearm")
        {
            command.gesture = "";
            command.gaze_mode = "gaze_" + side;
            command.sound_key = "soft_tone";
            command.vfx_key = "affinity_spark";
            command.duration_sec = hold ? 1.0f : 0.8f;
            command.priority = group == "shoulder" ? 35 : 32;
        }
        else if (group == "hand")
        {
            command.gesture = "";
            command.gaze_mode = "gaze_" + side + "_hand";
            command.sound_key = "soft_tone";
            command.vfx_key = "affinity_spark";
            command.duration_sec = hold ? 1.1f : 0.85f;
            command.priority = hold ? 36 : 35;
        }
        else if (group == "chest" || group == "waist")
        {
            command.gesture = "gesture_uncertain";
            command.gaze_mode = "gaze_user";
            command.sound_key = "boundary_tone";
            command.vfx_key = "subtle_spark";
            command.duration_sec = hold ? 1.15f : 1.0f;
            command.priority = group == "chest" ? 68 : 62;
            command.interrupt_policy = "interrupt_reacting";
        }
        else
        {
            command.gesture = "";
            command.gaze_mode = "gaze_" + side + "_low";
            command.sound_key = "step_tone";
            command.vfx_key = "subtle_spark";
            command.duration_sec = hold ? 1.1f : 0.95f;
            command.priority = 58;
            command.interrupt_policy = "interrupt_reacting";
        }

        return command;
    }

    private static float DirectSwipeDurationForZone(string zone)
    {
        string group = BodyGroupForZone(zone);
        if (group == "hand")
            return 0.85f;
        if (group == "chest" || group == "waist")
            return 1.0f;
        if (group == "thigh" || group == "calf" || group == "foot")
            return 0.95f;
        return 0.75f;
    }

    private static string DirectEmotionFor(string zone, bool hold)
    {
        string group = BodyGroupForZone(zone);
        if (group == "head" || group == "face" || group == "neck")
            return hold ? "happy" : "surprised";
        if (group == "shoulder" || group == "upper_arm" || group == "forearm")
            return hold ? "happy" : "neutral";
        if (group == "hand")
            return "happy";
        if (group == "chest" || group == "waist")
            return hold ? "neutral" : "surprised";
        return hold ? "neutral" : "surprised";
    }

    private static string PoseForZone(string zone, bool hold)
    {
        if (zone == "head") return "touch_head_recoil";
        if (zone == "face") return "touch_face_flinch";
        if (zone == "neck") return "touch_neck_shy";
        if (zone == "chest") return "touch_chest_guard";
        if (zone == "waist") return "touch_waist_guard";
        if (zone == "left_shoulder" || zone == "right_shoulder") return "touch_" + zone + "_ack";
        if (zone == "left_upper_arm" || zone == "left_forearm") return "touch_left_arm_ack";
        if (zone == "right_upper_arm" || zone == "right_forearm") return "touch_right_arm_ack";
        if (zone == "left_hand" || zone == "right_hand") return hold ? "touch_" + zone + "_hold" : "touch_" + zone + "_ack";
        if (zone == "left_foot" || zone == "right_foot") return "touch_" + zone + "_step";
        if (zone == "left_thigh" || zone == "left_calf") return "touch_left_leg_step";
        if (zone == "right_thigh" || zone == "right_calf") return "touch_right_leg_step";
        return "touch_ack";
    }

    private static float DirectDurationFor(EventSpec spec)
    {
        string normalized = NormalizeEvent(spec.EventName);
        string zone = string.IsNullOrEmpty(spec.Zone) ? ZoneFromEvent(normalized) : spec.Zone;
        return DirectCommandFor(normalized, zone, spec.Direction).duration_sec;
    }

    private static List<EventSpec> BuildFullMatrix()
    {
        var specs = new List<EventSpec>();
        foreach (string zone in BodyTouchZones)
        {
            specs.Add(EventSpec.Touch("tap_" + zone, zone, "tap"));
            specs.Add(EventSpec.Touch("hold_" + zone, zone, "hold"));
        }

        foreach (string zone in BodyTouchZones)
            specs.Add(EventSpec.Swipe("swipe_" + zone + "_right", "swipe", zone, "right"));

        specs.Add(EventSpec.Swipe("alias_swipe_left", "swipe_left", "chest", "left"));
        specs.Add(EventSpec.Swipe("alias_swipe_right", "swipe_right", "chest", "right"));
        specs.Add(EventSpec.Swipe("alias_swipe_up", "swipe_up", "chest", "up"));
        specs.Add(EventSpec.Swipe("alias_swipe_down", "swipe_down", "chest", "down"));

        specs.Add(EventSpec.Alias("alias_tap_cheek", "tap_cheek", "face"));
        specs.Add(EventSpec.Alias("alias_tap_left_cheek", "tap_left_cheek", "face"));
        specs.Add(EventSpec.Alias("alias_tap_right_cheek", "tap_right_cheek", "face"));
        specs.Add(EventSpec.Alias("alias_tap_hand", "tap_hand", "right_hand"));
        specs.Add(EventSpec.Alias("alias_hold", "hold", "right_hand"));
        specs.Add(EventSpec.Alias("alias_hold_cheek", "hold_cheek", "face"));
        specs.Add(EventSpec.Alias("alias_hold_left_cheek", "hold_left_cheek", "face"));
        specs.Add(EventSpec.Alias("alias_hold_right_cheek", "hold_right_cheek", "face"));
        specs.Add(EventSpec.Alias("alias_hold_hand", "hold_hand", "right_hand"));
        specs.Add(EventSpec.Alias("reset", "reset", ""));
        return specs;
    }

    private static string[] TargetBonesForZone(string zone)
    {
        switch (zone)
        {
            case "head":
            case "face":
                return new[] { "Head", "Neck" };
            case "neck":
                return new[] { "Neck", "Head", "Chest" };
            case "chest":
                return new[] { "Chest", "LeftUpperArm", "RightUpperArm", "LeftLowerArm", "RightLowerArm" };
            case "waist":
                return new[] { "Hips", "Chest", "LeftUpperArm", "RightUpperArm" };
            case "left_shoulder":
                return new[] { "LeftShoulder", "LeftUpperArm" };
            case "right_shoulder":
                return new[] { "RightShoulder", "RightUpperArm" };
            case "left_upper_arm":
                return new[] { "LeftUpperArm", "LeftLowerArm" };
            case "right_upper_arm":
                return new[] { "RightUpperArm", "RightLowerArm" };
            case "left_forearm":
                return new[] { "LeftLowerArm", "LeftHand" };
            case "right_forearm":
                return new[] { "RightLowerArm", "RightHand" };
            case "left_hand":
                return new[] { "LeftHand", "LeftLowerArm" };
            case "right_hand":
                return new[] { "RightHand", "RightLowerArm" };
            case "left_thigh":
                return new[] { "LeftUpperLeg", "LeftLowerLeg", "Hips" };
            case "right_thigh":
                return new[] { "RightUpperLeg", "RightLowerLeg", "Hips" };
            case "left_calf":
                return new[] { "LeftLowerLeg", "LeftFoot" };
            case "right_calf":
                return new[] { "RightLowerLeg", "RightFoot" };
            case "left_foot":
                return new[] { "LeftFoot", "LeftLowerLeg" };
            case "right_foot":
                return new[] { "RightFoot", "RightLowerLeg" };
            default:
                return new[] { "Head", "Chest", "Hips" };
        }
    }

    private static float MaxLocalPositionDelta(BoneSampleSet baseline, BoneSampleSet recovery)
    {
        float max = 0f;
        foreach (var item in baseline.Bones)
        {
            if (!item.Value.Exists || !recovery.TryGet(item.Key, out var other) || !other.Exists)
                continue;
            max = Mathf.Max(max, Vector3.Distance(item.Value.LocalPosition, other.LocalPosition));
        }
        return max;
    }

    private static float MaxRotationDelta(BoneSampleSet baseline, BoneSampleSet peak, string[] bones)
    {
        float max = 0f;
        foreach (string bone in bones)
        {
            if (!baseline.TryGet(bone, out var a) || !peak.TryGet(bone, out var b) || !a.Exists || !b.Exists)
                continue;
            max = Mathf.Max(max, Quaternion.Angle(a.LocalRotation, b.LocalRotation));
        }
        return max;
    }

    private static float MaxViewportDelta(BoneSampleSet baseline, BoneSampleSet peak, string[] bones)
    {
        float max = 0f;
        foreach (string bone in bones)
        {
            if (!baseline.TryGet(bone, out var a) || !peak.TryGet(bone, out var b) || !a.Exists || !b.Exists)
                continue;
            max = Mathf.Max(max, Vector2.Distance(new Vector2(a.Viewport.x, a.Viewport.y), new Vector2(b.Viewport.x, b.Viewport.y)));
        }
        return max;
    }

    private static float MaxTrackedViewportDelta(BoneSampleSet first, BoneSampleSet second)
    {
        return Mathf.Max(
            ViewportDelta(first, second, "Head"),
            ViewportDelta(first, second, "Hips"),
            ViewportDelta(first, second, "LeftFoot"),
            ViewportDelta(first, second, "RightFoot"));
    }

    private static bool IsLikelyTPose(BoneSampleSet set)
    {
        return IsForearmHorizontalT(set, "LeftUpperArm", "LeftLowerArm") &&
               IsForearmHorizontalT(set, "RightUpperArm", "RightLowerArm");
    }

    private static bool IsForearmHorizontalT(BoneSampleSet set, string upperArm, string lowerArm)
    {
        if (!set.TryGet(upperArm, out var upper) || !set.TryGet(lowerArm, out var lower) || !upper.Exists || !lower.Exists)
            return false;

        Vector3 dir = lower.World - upper.World;
        if (dir.sqrMagnitude <= 0.0001f)
            return false;

        float verticalAngle = Vector3.Angle(dir.normalized, Vector3.up);
        return Mathf.Abs(verticalAngle - 90f) <= TPoseArmHorizontalThresholdDeg;
    }

    private static float ViewportDelta(BoneSampleSet baseline, BoneSampleSet recovery, string bone)
    {
        if (!baseline.TryGet(bone, out var a) || !recovery.TryGet(bone, out var b) || !a.Exists || !b.Exists)
            return 0f;
        return Vector2.Distance(new Vector2(a.Viewport.x, a.Viewport.y), new Vector2(b.Viewport.x, b.Viewport.y));
    }

    private void ResolveReferences()
    {
        if (interactionController == null)
            interactionController = FindFirstObjectByType<JdDemoInteractionController>();
        if (avatarAnimator == null)
        {
            if (interactionController != null)
                avatarAnimator = interactionController.GetComponentInChildren<Animator>();
            if (avatarAnimator == null)
                avatarAnimator = FindUsableAnimator();
        }
        if (sourceCamera == null)
            sourceCamera = Camera.main != null ? Camera.main : FindFirstObjectByType<Camera>();
    }

    private static Animator FindUsableAnimator()
    {
        var animators = FindObjectsByType<Animator>(FindObjectsInactive.Include, FindObjectsSortMode.None);
        foreach (var animator in animators)
        {
            if (animator != null && animator.isHuman)
                return animator;
        }

        return animators.Length > 0 ? animators[0] : null;
    }

    private void OnLogMessageReceived(string condition, string stackTrace, LogType type)
    {
        if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert)
            _consoleErrors.Add(condition);
    }

    private void WriteReports(DiagnosticsReport report)
    {
        LatestJsonReportPath = Path.Combine(LatestReportDirectory, "report.json").Replace('\\', '/');
        LatestMarkdownReportPath = Path.Combine(LatestReportDirectory, "report.md").Replace('\\', '/');
        LatestHtmlReportPath = Path.Combine(LatestReportDirectory, "index.html").Replace('\\', '/');

        File.WriteAllText(LatestJsonReportPath, BuildJson(report), Encoding.UTF8);
        File.WriteAllText(LatestMarkdownReportPath, BuildMarkdown(report), Encoding.UTF8);
        File.WriteAllText(LatestHtmlReportPath, BuildHtml(report), Encoding.UTF8);
    }

    private string BuildSummary(DiagnosticsReport report)
    {
        CountStatuses(report.Results, out int pass, out int warn, out int fail);
        return $"DONE: {report.RunId} total={report.Results.Count} PASS={pass} WARN={warn} FAIL={fail} json={LatestJsonReportPath}";
    }

    private static string BuildJson(DiagnosticsReport report)
    {
        var sb = new StringBuilder(16384);
        sb.Append("{\n");
        AppendJsonProp(sb, "run_id", report.RunId, 1, true);
        AppendJsonProp(sb, "started_at", report.StartedAt, 1, true);
        AppendJsonProp(sb, "finished_at", report.FinishedAt, 1, true);
        AppendJsonProp(sb, "prefer_backend", report.PreferBackend, 1, true);
        AppendJsonProp(sb, "sensor_url", report.SensorUrl, 1, true);
        AppendJsonProp(sb, "report_directory", report.ReportDirectory, 1, true);
        sb.Append("  \"results\": [\n");
        for (int i = 0; i < report.Results.Count; i++)
        {
            AppendResultJson(sb, report.Results[i], 2);
            sb.Append(i + 1 < report.Results.Count ? ",\n" : "\n");
        }
        sb.Append("  ]\n");
        sb.Append("}\n");
        return sb.ToString();
    }

    private static void AppendResultJson(StringBuilder sb, EventResult result, int indent)
    {
        Indent(sb, indent).Append("{\n");
        AppendJsonProp(sb, "id", result.Spec.Id, indent + 1, true);
        AppendJsonProp(sb, "event", result.Spec.EventName, indent + 1, true);
        AppendJsonProp(sb, "normalized_event", NormalizeEvent(result.Spec.EventName), indent + 1, true);
        AppendJsonProp(sb, "zone", result.Spec.Zone, indent + 1, true);
        AppendJsonProp(sb, "direction", result.Spec.Direction, indent + 1, true);
        AppendJsonProp(sb, "dispatch_mode", result.DispatchMode, indent + 1, true);
        AppendJsonProp(sb, "status", result.Status, indent + 1, true);
        AppendJsonStringArray(sb, "reasons", result.Reasons, indent + 1, true);
        Indent(sb, indent + 1).Append("\"backend\": {");
        sb.Append("\"attempted\":").Append(result.BackendAttempted ? "true" : "false").Append(',');
        sb.Append("\"accepted\":").Append(result.BackendAccepted ? "true" : "false").Append(',');
        sb.Append("\"ack_event\":\"").Append(EscapeJson(result.BackendAckEvent)).Append("\",");
        sb.Append("\"message\":\"").Append(EscapeJson(result.BackendMessage)).Append("\"},\n");
        Indent(sb, indent + 1).Append("\"unity\": {");
        sb.Append("\"last_event\":\"").Append(EscapeJson(result.UnityLastEvent)).Append("\",");
        sb.Append("\"last_zone\":\"").Append(EscapeJson(result.UnityLastZone)).Append("\",");
        sb.Append("\"state\":\"").Append(EscapeJson(result.UnityState)).Append("\"},\n");
        Indent(sb, indent + 1).Append("\"command\": {");
        sb.Append("\"emotion\":\"").Append(EscapeJson(result.CommandEmotion)).Append("\",");
        sb.Append("\"gesture\":\"").Append(EscapeJson(result.CommandGesture)).Append("\",");
        sb.Append("\"gaze_mode\":\"").Append(EscapeJson(result.CommandGazeMode)).Append("\",");
        sb.Append("\"pose_mode\":\"").Append(EscapeJson(result.CommandPoseMode)).Append("\",");
        sb.Append("\"sound_key\":\"").Append(EscapeJson(result.CommandSoundKey)).Append("\",");
        sb.Append("\"vfx_key\":\"").Append(EscapeJson(result.CommandVfxKey)).Append("\",");
        sb.Append("\"duration_sec\":").Append(FormatFloat(result.CommandDurationSec)).Append(',');
        sb.Append("\"priority\":").Append(result.CommandPriority).Append(',');
        sb.Append("\"interrupt_policy\":\"").Append(EscapeJson(result.CommandInterruptPolicy)).Append("\"},\n");
        Indent(sb, indent + 1).Append("\"bone_checks\": {");
        sb.Append("\"target_rotation_delta_deg\":").Append(FormatFloat(result.TargetRotationDeltaDeg)).Append(',');
        sb.Append("\"target_viewport_delta\":").Append(FormatFloat(result.TargetViewportDelta)).Append(',');
        sb.Append("\"local_position_max_delta\":").Append(FormatFloat(result.LocalPositionMaxDelta)).Append(',');
        sb.Append("\"head_viewport_recovery_delta\":").Append(FormatFloat(result.HeadViewportRecoveryDelta)).Append(',');
        sb.Append("\"hips_viewport_recovery_delta\":").Append(FormatFloat(result.HipsViewportRecoveryDelta)).Append(',');
        sb.Append("\"feet_viewport_recovery_delta\":").Append(FormatFloat(result.FeetViewportRecoveryDelta)).Append(',');
        sb.Append("\"own_side_rotation_delta_deg\":").Append(FormatFloat(result.OwnSideRotationDeltaDeg)).Append(',');
        sb.Append("\"opposite_side_rotation_delta_deg\":").Append(FormatFloat(result.OppositeSideRotationDeltaDeg)).Append("},\n");
        AppendJsonProp(sb, "startup_pose_warning", result.StartupPoseWarning, indent + 1, true);
        AppendScreenshotsJson(sb, result, indent + 1, true);
        AppendBoneSetJson(sb, "baseline_bones", result.Baseline, indent + 1, true);
        AppendBoneSetJson(sb, "peak_bones", result.Peak, indent + 1, true);
        AppendBoneSetJson(sb, "recovery_bones", result.Recovery, indent + 1, false);
        sb.Append('\n');
        Indent(sb, indent).Append('}');
    }

    private static void AppendScreenshotsJson(StringBuilder sb, EventResult result, int indent, bool comma)
    {
        Indent(sb, indent).Append("\"screenshots\": {");
        int index = 0;
        foreach (var item in result.Screenshots)
        {
            if (index++ > 0)
                sb.Append(',');
            sb.Append('"').Append(EscapeJson(item.Key)).Append("\":\"").Append(EscapeJson(item.Value)).Append('"');
        }
        sb.Append(comma ? "},\n" : "}\n");
    }

    private static void AppendBoneSetJson(StringBuilder sb, string name, BoneSampleSet set, int indent, bool comma)
    {
        Indent(sb, indent).Append('"').Append(name).Append("\": {");
        if (set != null)
        {
            int index = 0;
            foreach (var item in set.Bones)
            {
                if (index++ > 0)
                    sb.Append(',');
                var b = item.Value;
                sb.Append('"').Append(EscapeJson(item.Key)).Append("\":{");
                sb.Append("\"exists\":").Append(b.Exists ? "true" : "false").Append(',');
                sb.Append("\"visible\":").Append(b.Visible ? "true" : "false").Append(',');
                sb.Append("\"world\":").Append(VectorJson(b.World)).Append(',');
                sb.Append("\"localPosition\":").Append(VectorJson(b.LocalPosition)).Append(',');
                sb.Append("\"localRotationEuler\":").Append(VectorJson(b.LocalRotationEuler)).Append(',');
                sb.Append("\"viewport\":").Append(VectorJson(b.Viewport));
                sb.Append('}');
            }
        }
        sb.Append(comma ? "},\n" : "}");
    }

    private static string BuildMarkdown(DiagnosticsReport report)
    {
        CountStatuses(report.Results, out int pass, out int warn, out int fail);
        var sb = new StringBuilder(8192);
        sb.AppendLine("# Body Touch Preset Diagnostics");
        sb.AppendLine();
        sb.AppendLine("- Run: `" + report.RunId + "`");
        sb.AppendLine("- Started: `" + report.StartedAt + "`");
        sb.AppendLine("- Finished: `" + report.FinishedAt + "`");
        sb.AppendLine("- Backend preferred: `" + report.PreferBackend + "`");
        sb.AppendLine("- Sensor URL: `" + report.SensorUrl + "`");
        sb.AppendLine("- Total: `" + report.Results.Count + "` PASS=`" + pass + "` WARN=`" + warn + "` FAIL=`" + fail + "`");
        sb.AppendLine();
        sb.AppendLine("| Status | Event | Zone | Mode | Pose | Reasons |");
        sb.AppendLine("|---|---|---|---|---|---|");
        foreach (var result in report.Results)
        {
            sb.Append("| ")
                .Append(result.Status).Append(" | `")
                .Append(result.Spec.EventName).Append("` | `")
                .Append(result.Spec.Zone).Append("` | `")
                .Append(result.DispatchMode).Append("` | `")
                .Append(result.CommandPoseMode).Append("` | ")
                .Append(EscapeMarkdown(string.Join("; ", result.Reasons))).AppendLine(" |");
        }
        sb.AppendLine();
        sb.AppendLine("## Failures And Warnings");
        foreach (var result in report.Results)
        {
            if (result.Status == "PASS")
                continue;
            sb.AppendLine();
            sb.AppendLine("### " + result.Status + " `" + result.Spec.Id + "`");
            sb.AppendLine("- Event: `" + result.Spec.EventName + "` normalized `" + NormalizeEvent(result.Spec.EventName) + "`");
            sb.AppendLine("- Zone: `" + result.Spec.Zone + "` direction `" + result.Spec.Direction + "`");
            sb.AppendLine("- Dispatch: `" + result.DispatchMode + "` backend `" + result.BackendMessage + "`");
            sb.AppendLine("- Pose: `" + result.CommandPoseMode + "` duration `" + FormatFloat(result.CommandDurationSec) + "` interrupt `" + result.CommandInterruptPolicy + "`");
            sb.AppendLine("- Bone delta: rotation `" + FormatFloat(result.TargetRotationDeltaDeg) + "deg`, viewport `" + FormatFloat(result.TargetViewportDelta) + "`, local drift `" + FormatFloat(result.LocalPositionMaxDelta) + "`");
            sb.AppendLine("- Reasons: " + EscapeMarkdown(string.Join("; ", result.Reasons)));
            if (result.Screenshots.TryGetValue("peak", out var peak))
                sb.AppendLine("- Peak screenshot: `" + peak + "`");
        }
        return sb.ToString();
    }

    private static string BuildHtml(DiagnosticsReport report)
    {
        CountStatuses(report.Results, out int pass, out int warn, out int fail);
        var sb = new StringBuilder(8192);
        sb.AppendLine("<!doctype html><html><head><meta charset=\"utf-8\"><title>Body Touch Diagnostics</title>");
        sb.AppendLine("<style>body{font-family:Arial,sans-serif;margin:24px;background:#101418;color:#e8eef4}table{border-collapse:collapse;width:100%}td,th{border:1px solid #34404c;padding:6px}th{background:#1d2730}.PASS{color:#6ee7a8}.WARN{color:#ffd166}.FAIL{color:#ff6b6b}img{max-width:180px}</style>");
        sb.AppendLine("</head><body>");
        sb.AppendLine("<h1>Body Touch Preset Diagnostics</h1>");
        sb.AppendLine("<p>Run <code>" + Html(report.RunId) + "</code> Total " + report.Results.Count + " PASS " + pass + " WARN " + warn + " FAIL " + fail + "</p>");
        sb.AppendLine("<table><thead><tr><th>Status</th><th>Event</th><th>Zone</th><th>Mode</th><th>Pose</th><th>Reasons</th><th>Peak</th></tr></thead><tbody>");
        foreach (var result in report.Results)
        {
            string peak = result.Screenshots.TryGetValue("peak", out var path) ? path : "";
            string rel = string.IsNullOrEmpty(peak) ? "" : RelativePath(report.ReportDirectory, peak);
            sb.Append("<tr><td class=\"").Append(result.Status).Append("\">").Append(result.Status).Append("</td><td><code>")
                .Append(Html(result.Spec.EventName)).Append("</code></td><td><code>")
                .Append(Html(result.Spec.Zone)).Append("</code></td><td><code>")
                .Append(Html(result.DispatchMode)).Append("</code></td><td><code>")
                .Append(Html(result.CommandPoseMode)).Append("</code></td><td>")
                .Append(Html(string.Join("; ", result.Reasons))).Append("</td><td>");
            if (!string.IsNullOrEmpty(peak))
                sb.Append("<img src=\"").Append(Html(rel)).Append("\" alt=\"peak\">");
            sb.AppendLine("</td></tr>");
        }
        sb.AppendLine("</tbody></table></body></html>");
        return sb.ToString();
    }

    private static void CountStatuses(List<EventResult> results, out int pass, out int warn, out int fail)
    {
        pass = warn = fail = 0;
        foreach (var result in results)
        {
            if (result.Status == "FAIL") fail++;
            else if (result.Status == "WARN") warn++;
            else pass++;
        }
    }

    private static void Fail(EventResult result, string reason)
    {
        result.Status = "FAIL";
        AddReason(result, reason);
    }

    private static void Warn(EventResult result, string reason)
    {
        if (result.Status != "FAIL")
            result.Status = "WARN";
        AddReason(result, reason);
    }

    private static void AddReason(EventResult result, string reason)
    {
        if (!string.IsNullOrEmpty(reason) && !result.Reasons.Contains(reason))
            result.Reasons.Add(reason);
    }

    private static IEnumerator WaitSecondsUnscaled(float seconds)
    {
        float until = Time.realtimeSinceStartup + Mathf.Max(0f, seconds);
        while (Time.realtimeSinceStartup < until)
            yield return null;
    }

    private static string NormalizeEvent(string eventName)
    {
        string evt = (eventName ?? "").Trim().ToLowerInvariant();
        switch (evt)
        {
            case "click": return "tap";
            case "tap_cheek":
            case "tap_left_cheek":
            case "tap_right_cheek": return "tap_face";
            case "tap_hand": return "tap_right_hand";
            case "hold": return "hold_right_hand";
            case "hold_cheek":
            case "hold_left_cheek":
            case "hold_right_cheek": return "hold_face";
            case "hold_hand": return "hold_right_hand";
            case "swipe_left":
            case "swipe_right":
            case "swipe_up":
            case "swipe_down": return "swipe";
            default: return evt;
        }
    }

    private static string ZoneFromEvent(string normalizedEvent)
    {
        if (normalizedEvent.StartsWith("tap_", StringComparison.Ordinal))
            return normalizedEvent.Substring(4);
        if (normalizedEvent.StartsWith("hold_", StringComparison.Ordinal))
            return normalizedEvent.Substring(5);
        return "";
    }

    private static string SideForZone(string zone)
    {
        if (zone.StartsWith("left_", StringComparison.Ordinal))
            return "left";
        if (zone.StartsWith("right_", StringComparison.Ordinal))
            return "right";
        return "center";
    }

    private static string BodyGroupForZone(string zone)
    {
        if (zone.StartsWith("left_", StringComparison.Ordinal))
            zone = zone.Substring("left_".Length);
        else if (zone.StartsWith("right_", StringComparison.Ordinal))
            zone = zone.Substring("right_".Length);
        return string.IsNullOrEmpty(zone) ? "unknown" : zone;
    }

    private static string ProjectRoot()
    {
        var assets = Application.dataPath;
        return Directory.GetParent(assets)?.FullName ?? Directory.GetCurrentDirectory();
    }

    private static string RelativePath(string root, string path)
    {
        if (string.IsNullOrEmpty(root) || string.IsNullOrEmpty(path))
            return path ?? "";

        root = root.Replace('\\', '/').TrimEnd('/');
        path = path.Replace('\\', '/');
        if (path.StartsWith(root + "/", StringComparison.OrdinalIgnoreCase))
            return path.Substring(root.Length + 1);
        return path;
    }

    private static string SafeFileName(string value)
    {
        foreach (char c in Path.GetInvalidFileNameChars())
            value = value.Replace(c, '_');
        return value;
    }

    private static string FormatVector(Vector3 value)
    {
        return "(" + FormatFloat(value.x) + "," + FormatFloat(value.y) + "," + FormatFloat(value.z) + ")";
    }

    private static string FormatFloat(float value)
    {
        return value.ToString("0.####", CultureInfo.InvariantCulture);
    }

    private static string VectorJson(Vector3 value)
    {
        return "{\"x\":" + FormatFloat(value.x) + ",\"y\":" + FormatFloat(value.y) + ",\"z\":" + FormatFloat(value.z) + "}";
    }

    private static string EscapeJson(string value)
    {
        if (string.IsNullOrEmpty(value))
            return "";
        return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r");
    }

    private static string EscapeMarkdown(string value)
    {
        return string.IsNullOrEmpty(value) ? "" : value.Replace("|", "\\|");
    }

    private static string Html(string value)
    {
        return string.IsNullOrEmpty(value)
            ? ""
            : value.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;").Replace("\"", "&quot;");
    }

    private static StringBuilder Indent(StringBuilder sb, int indent)
    {
        for (int i = 0; i < indent; i++)
            sb.Append("  ");
        return sb;
    }

    private static void AppendJsonProp(StringBuilder sb, string name, string value, int indent, bool comma)
    {
        Indent(sb, indent).Append('"').Append(name).Append("\": \"").Append(EscapeJson(value)).Append('"');
        sb.Append(comma ? ",\n" : "\n");
    }

    private static void AppendJsonProp(StringBuilder sb, string name, bool value, int indent, bool comma)
    {
        Indent(sb, indent).Append('"').Append(name).Append("\": ").Append(value ? "true" : "false");
        sb.Append(comma ? ",\n" : "\n");
    }

    private static void AppendJsonStringArray(StringBuilder sb, string name, List<string> values, int indent, bool comma)
    {
        Indent(sb, indent).Append('"').Append(name).Append("\": [");
        for (int i = 0; i < values.Count; i++)
        {
            if (i > 0)
                sb.Append(", ");
            sb.Append('"').Append(EscapeJson(values[i])).Append('"');
        }
        sb.Append(comma ? "],\n" : "]\n");
    }

    private static string ExtractJsonString(string json, string key)
    {
        string pattern = "\"" + key + "\":\"";
        int start = json.IndexOf(pattern, StringComparison.Ordinal);
        if (start < 0) return null;
        start += pattern.Length;
        int end = json.IndexOf('"', start);
        return end > start ? json.Substring(start, end - start) : null;
    }

    private static bool ExtractJsonBool(string json, string key)
    {
        string pattern = "\"" + key + "\":";
        int start = json.IndexOf(pattern, StringComparison.Ordinal);
        if (start < 0) return false;
        start += pattern.Length;
        while (start < json.Length && char.IsWhiteSpace(json[start]))
            start++;
        return json.IndexOf("true", start, StringComparison.OrdinalIgnoreCase) == start;
    }

    private sealed class EventSpec
    {
        public string Id;
        public string EventName;
        public string Zone;
        public string Kind;
        public string Direction;

        public static EventSpec Touch(string eventName, string zone, string kind)
        {
            return new EventSpec { Id = eventName, EventName = eventName, Zone = zone, Kind = kind, Direction = "" };
        }

        public static EventSpec Swipe(string id, string eventName, string zone, string direction)
        {
            return new EventSpec { Id = id, EventName = eventName, Zone = zone, Kind = "swipe", Direction = direction };
        }

        public static EventSpec Alias(string id, string eventName, string zone)
        {
            return new EventSpec { Id = id, EventName = eventName, Zone = zone, Kind = "alias", Direction = "" };
        }
    }

    private sealed class EventResult
    {
        public readonly EventSpec Spec;
        public string Status = "PASS";
        public string DispatchMode = "";
        public string EventDirectory = "";
        public bool BackendAttempted;
        public bool BackendAccepted;
        public string BackendAckEvent = "";
        public string BackendMessage = "";
        public string UnityLastEvent = "";
        public string UnityLastZone = "";
        public string UnityState = "";
        public string CommandEmotion = "";
        public string CommandGesture = "";
        public string CommandGazeMode = "";
        public string CommandPoseMode = "";
        public string CommandSoundKey = "";
        public string CommandVfxKey = "";
        public float CommandDurationSec;
        public int CommandPriority;
        public string CommandInterruptPolicy = "";
        public BoneSampleSet Baseline;
        public BoneSampleSet Start;
        public BoneSampleSet Peak;
        public BoneSampleSet Recovery;
        public float TargetRotationDeltaDeg;
        public float TargetViewportDelta;
        public float LocalPositionMaxDelta;
        public float HeadViewportRecoveryDelta;
        public float HipsViewportRecoveryDelta;
        public float FeetViewportRecoveryDelta;
        public float OwnSideRotationDeltaDeg;
        public float OppositeSideRotationDeltaDeg;
        public string StartupPoseWarning = "";
        public readonly List<string> Reasons = new List<string>();
        public readonly List<string> ConsoleErrors = new List<string>();
        public readonly Dictionary<string, string> Screenshots = new Dictionary<string, string>(StringComparer.Ordinal);
        public readonly Dictionary<string, ScreenshotStats> ScreenshotStats = new Dictionary<string, ScreenshotStats>(StringComparer.Ordinal);

        public EventResult(EventSpec spec)
        {
            Spec = spec;
        }
    }

    private sealed class BoneSampleSet
    {
        public readonly Dictionary<string, BoneSample> Bones = new Dictionary<string, BoneSample>(StringComparer.Ordinal);

        public bool TryGet(string bone, out BoneSample sample)
        {
            return Bones.TryGetValue(bone, out sample);
        }
    }

    private sealed class BoneSample
    {
        public string Bone = "";
        public bool Exists;
        public bool Visible;
        public Vector3 World;
        public Vector3 LocalPosition;
        public Quaternion LocalRotation;
        public Vector3 LocalRotationEuler;
        public Vector3 Viewport;
    }

    private sealed class ScreenshotStats
    {
        public int Width;
        public int Height;
        public float AverageBrightness;
        public float UsefulPixelRatio;
    }

    private sealed class SensorDispatchResult
    {
        public bool Accepted;
        public string AckEvent = "";
        public string Message = "";
    }

    private sealed class DiagnosticsReport
    {
        public string RunId = "";
        public string StartedAt = "";
        public string FinishedAt = "";
        public bool PreferBackend;
        public string SensorUrl = "";
        public string ReportDirectory = "";
        public List<EventResult> Results = new List<EventResult>();
    }
}
