using System;
using System.Collections.Generic;
using UnityEngine;
using UniVRM10;

/// <summary>
/// Loads and applies JSON blendshape animation curves to a SkinnedMeshRenderer.
/// </summary>
public sealed class FacialAnimationController : MonoBehaviour
{
    [Header("Targets")]
    [SerializeField] private SkinnedMeshRenderer faceRenderer;
    [SerializeField] private Vrm10Instance vrmInstance;
    [SerializeField] private TextAsset curveJson;

    [Header("Options")]
    [SerializeField] private bool loadOnAwake = true;
    [SerializeField] private bool applyOnUpdate;
    [SerializeField] private bool logMissingBlendshapes = true;
    [SerializeField] private bool preferVrmExpressions = true;
    [SerializeField] private bool logFirstVrmExpressionWrite = true;
    [SerializeField] private float globalWeightScale = 1.0f;
    [SerializeField] private float streamSmoothMs = 80.0f;
    [SerializeField] private float previewTimeMs;

    private BlendshapeCurveSet curveSet;
    private readonly Dictionary<string, BlendshapeCurve> curvesByName = new Dictionary<string, BlendshapeCurve>(StringComparer.Ordinal);
    private readonly Dictionary<string, int> blendshapeIndexByName = new Dictionary<string, int>(StringComparer.Ordinal);
    private readonly Dictionary<string, string> blendshapeNameByLower = new Dictionary<string, string>(StringComparer.Ordinal);
    private readonly Dictionary<string, string> retargetMap = new Dictionary<string, string>(StringComparer.Ordinal);
    private readonly HashSet<string> missingBlendshapes = new HashSet<string>(StringComparer.Ordinal);
    private readonly HashSet<string> streamLogicalChannels = new HashSet<string>(StringComparer.Ordinal);
    private readonly HashSet<int> writtenBlendshapeIndices = new HashSet<int>();
    private readonly Dictionary<int, float> currentWeights = new Dictionary<int, float>();
    private readonly Dictionary<int, float> targetWeights = new Dictionary<int, float>();
    private readonly Dictionary<ExpressionPreset, float> currentVrmMouthWeights = new Dictionary<ExpressionPreset, float>();
    private readonly Dictionary<ExpressionPreset, float> targetVrmMouthWeights = new Dictionary<ExpressionPreset, float>();
    private bool warnedMissingRenderer;
    private bool loggedFirstStreamWrite;
    private bool loggedFirstVrmStreamWrite;

    private static readonly ExpressionPreset[] VrmMouthPresets =
    {
        ExpressionPreset.aa,
        ExpressionPreset.ih,
        ExpressionPreset.ou,
        ExpressionPreset.ee,
        ExpressionPreset.oh,
    };

    private static readonly Dictionary<string, string[]> RuntimeAliases = new Dictionary<string, string[]>(StringComparer.Ordinal)
    {
        { "mouse_open", new[] { "mouth_open", "mouthOpen", "MouthOpen", "Mouth_Open", "jawOpen", "JawOpen", "A", "Aa", "aa", "vrc.v_aa", "Mouth_A", "Fcl_MTH_A" } },
        { "mouth_open", new[] { "mouth_open", "mouthOpen", "MouthOpen", "Mouth_Open", "jawOpen", "JawOpen", "A", "Aa", "aa", "vrc.v_aa", "Mouth_A", "Fcl_MTH_A" } },
        { "lip_a", new[] { "A", "Aa", "aa", "vrc.v_aa", "Mouth_A", "Fcl_MTH_A", "jawOpen", "JawOpen", "mouthOpen", "MouthOpen" } },
        { "lip_i", new[] { "I", "Ih", "ih", "vrc.v_ih", "Mouth_I", "Fcl_MTH_I", "mouthSmileLeft", "mouthSmileRight", "mouthOpen", "MouthOpen" } },
        { "lip_o", new[] { "O", "Oh", "oh", "vrc.v_oh", "Mouth_O", "Fcl_MTH_O", "mouthFunnel", "MouthFunnel", "mouthOpen", "MouthOpen" } },
        { "lip_u", new[] { "U", "Ou", "ou", "vrc.v_ou", "Mouth_U", "Fcl_MTH_U", "mouthPucker", "MouthPucker", "mouthOpen", "MouthOpen" } },
        { "lip_e", new[] { "E", "Ee", "ee", "vrc.v_e", "Mouth_E", "Fcl_MTH_E", "mouthStretchLeft", "mouthStretchRight", "mouthOpen", "MouthOpen" } },
        { "lip_w", new[] { "U", "Ou", "ou", "vrc.v_ou", "Mouth_U", "Fcl_MTH_U", "mouthPucker", "MouthPucker", "O", "mouthOpen", "MouthOpen" } },
    };

    /// <summary>
    /// Gets whether a valid curve set has been loaded.
    /// </summary>
    public bool HasCurveSet => curveSet != null;

    /// <summary>
    /// Gets the loaded curve duration in milliseconds, or zero when no curve is loaded.
    /// </summary>
    public float DurationMs => curveSet != null ? Mathf.Max(0.0f, curveSet.duration_ms) : 0.0f;

    private void Awake()
    {
        if (vrmInstance == null)
        {
            vrmInstance = GetComponentInChildren<Vrm10Instance>();
        }

        if (vrmInstance == null)
        {
            vrmInstance = FindAnyObjectByType<Vrm10Instance>();
        }

        CacheBlendshapeIndices();

        if (loadOnAwake && curveJson != null)
        {
            LoadCurve(curveJson);
        }
    }

    private void OnValidate()
    {
        globalWeightScale = Mathf.Max(0.0f, globalWeightScale);
        streamSmoothMs = Mathf.Max(0.0f, streamSmoothMs);
        previewTimeMs = Mathf.Max(0.0f, previewTimeMs);
    }

    private void Update()
    {
        if (applyOnUpdate)
        {
            Apply(previewTimeMs);
        }

        SmoothTargetWeights();
    }

    /// <summary>
    /// Loads a curve set from a Unity TextAsset and prepares it for playback.
    /// </summary>
    /// <param name="json">The JSON TextAsset containing a BlendshapeCurveSet.</param>
    /// <returns>True when a usable curve set was loaded; otherwise false.</returns>
    public bool LoadCurve(TextAsset json)
    {
        if (json == null)
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Curve JSON is not assigned.", this);
            ClearCurveState();
            return false;
        }

        return LoadCurveFromJson(json.text, json.name);
    }

    /// <summary>
    /// Loads a curve set from a raw JSON string and prepares it for playback.
    /// </summary>
    /// <param name="json">The raw JSON content.</param>
    /// <returns>True when a usable curve set was loaded; otherwise false.</returns>
    public bool LoadCurveFromJson(string json)
    {
        return LoadCurveFromJson(json, "raw JSON");
    }

    /// <summary>
    /// Evaluates one logical blendshape channel at a given audio time.
    /// </summary>
    /// <param name="logicalName">The logical channel name from the curve file.</param>
    /// <param name="timeMs">The audio time in milliseconds.</param>
    /// <returns>The interpolated normalized value clamped to [0, 1].</returns>
    public float Evaluate(string logicalName, float timeMs)
    {
        if (string.IsNullOrWhiteSpace(logicalName) || !curvesByName.TryGetValue(logicalName, out BlendshapeCurve curve))
        {
            return 0.0f;
        }

        return EvaluateCurve(curve, timeMs);
    }

    /// <summary>
    /// Evaluates all loaded logical blendshape channels at a given audio time.
    /// </summary>
    /// <param name="timeMs">The audio time in milliseconds.</param>
    /// <returns>A new dictionary of logical channel names to normalized weights.</returns>
    public Dictionary<string, float> EvaluateAll(float timeMs)
    {
        var weights = new Dictionary<string, float>(curvesByName.Count, StringComparer.Ordinal);

        foreach (KeyValuePair<string, BlendshapeCurve> entry in curvesByName)
        {
            weights[entry.Key] = EvaluateCurve(entry.Value, timeMs);
        }

        return weights;
    }

    /// <summary>
    /// Evaluates all loaded curves at a given audio time and writes the result to the renderer.
    /// </summary>
    /// <param name="timeMs">The audio time in milliseconds.</param>
    public void Apply(float timeMs)
    {
        if (curveSet == null)
        {
            return;
        }

        if (DurationMs > 0.0f && timeMs > DurationMs)
        {
            ApplyRestPose();
            return;
        }

        ApplyWeights(EvaluateAll(timeMs));
    }

    /// <summary>
    /// Writes normalized logical blendshape weights to the renderer.
    /// </summary>
    /// <param name="weights">Logical channel names mapped to normalized [0, 1] weights.</param>
    public void ApplyWeights(Dictionary<string, float> weights)
    {
        if (weights == null || weights.Count == 0)
        {
            return;
        }

        if (!EnsureRendererReady())
        {
            return;
        }

        ApplyWeightsInternal(weights, trackStream: false);
    }

    /// <summary>
    /// Writes one streaming viseme packet and fades previously streamed channels to zero when omitted.
    /// </summary>
    public void ApplyStreamWeights(Dictionary<string, float> weights)
    {
        if (weights == null)
        {
            return;
        }

        if (TryApplyVrmStreamWeights(weights))
        {
            return;
        }

        if (!EnsureRendererReady())
        {
            return;
        }

        var expanded = new Dictionary<string, float>(weights, StringComparer.Ordinal);
        foreach (string logicalName in streamLogicalChannels)
        {
            if (!expanded.ContainsKey(logicalName))
            {
                expanded[logicalName] = 0.0f;
            }
        }

        foreach (string logicalName in weights.Keys)
        {
            if (!string.IsNullOrWhiteSpace(logicalName))
            {
                streamLogicalChannels.Add(logicalName);
            }
        }

        ApplyWeightsInternal(expanded, trackStream: true);
    }

    /// <summary>
    /// Immediately zeros all blendshapes touched by streaming viseme packets.
    /// </summary>
    public void ResetStreamWeights()
    {
        ResetVrmMouthWeights();

        if (!EnsureRendererReady())
        {
            streamLogicalChannels.Clear();
            loggedFirstStreamWrite = false;
            loggedFirstVrmStreamWrite = false;
            return;
        }

        foreach (int index in writtenBlendshapeIndices)
        {
            faceRenderer.SetBlendShapeWeight(index, 0.0f);
            currentWeights[index] = 0.0f;
            targetWeights[index] = 0.0f;
        }

        streamLogicalChannels.Clear();
        writtenBlendshapeIndices.Clear();
        targetWeights.Clear();
        currentWeights.Clear();
        loggedFirstStreamWrite = false;
        loggedFirstVrmStreamWrite = false;
    }

    public static bool TryResolveVrmMouthPreset(string logicalName, bool hasAnyLipWeight, out ExpressionPreset preset)
    {
        preset = ExpressionPreset.neutral;
        if (string.IsNullOrWhiteSpace(logicalName))
        {
            return false;
        }

        switch (logicalName)
        {
            case "lip_a":
                preset = ExpressionPreset.aa;
                return true;
            case "lip_i":
                preset = ExpressionPreset.ih;
                return true;
            case "lip_u":
            case "lip_w":
                preset = ExpressionPreset.ou;
                return true;
            case "lip_e":
                preset = ExpressionPreset.ee;
                return true;
            case "lip_o":
                preset = ExpressionPreset.oh;
                return true;
            case "mouse_open":
            case "mouth_open":
                if (!hasAnyLipWeight)
                {
                    preset = ExpressionPreset.aa;
                    return true;
                }

                return false;
            default:
                return false;
        }
    }

    private void ApplyWeightsInternal(Dictionary<string, float> weights, bool trackStream)
    {
        var resolvedTargets = new Dictionary<int, float>();
        var resolvedNames = new Dictionary<int, string>();

        foreach (KeyValuePair<string, float> entry in weights)
        {
            if (!TryResolveBlendshapeTarget(entry.Key, out int index, out string actualName))
            {
                continue;
            }

            float normalizedWeight = Mathf.Clamp01(entry.Value * globalWeightScale);
            if (resolvedTargets.TryGetValue(index, out float existingWeight))
            {
                resolvedTargets[index] = Mathf.Max(existingWeight, normalizedWeight);
            }
            else
            {
                resolvedTargets[index] = normalizedWeight;
                resolvedNames[index] = actualName;
            }
        }

        foreach (KeyValuePair<int, float> entry in resolvedTargets)
        {
            int index = entry.Key;
            float normalizedWeight = entry.Value;
            if (!currentWeights.ContainsKey(index))
            {
                currentWeights[index] = Mathf.Clamp01(faceRenderer.GetBlendShapeWeight(index) / 100.0f);
            }

            targetWeights[index] = normalizedWeight;
            if (trackStream)
            {
                writtenBlendshapeIndices.Add(index);
            }

            if (trackStream && !loggedFirstStreamWrite && normalizedWeight > 0.001f)
            {
                loggedFirstStreamWrite = true;
                string actualName = resolvedNames.TryGetValue(index, out string name) ? name : index.ToString();
                Debug.Log($"{nameof(FacialAnimationController)}: First stream blendshape write target='{actualName}' weight={normalizedWeight:0.###}.", this);
            }

            if (streamSmoothMs <= 0.0f)
            {
                currentWeights[index] = normalizedWeight;
                faceRenderer.SetBlendShapeWeight(index, normalizedWeight * 100.0f);
            }
        }
    }

    /// <summary>
    /// Zeros every blendshape channel managed by the loaded curve set.
    /// </summary>
    public void ApplyRestPose()
    {
        if (curvesByName.Count == 0 && writtenBlendshapeIndices.Count == 0)
        {
            return;
        }

        if (!EnsureRendererReady())
        {
            return;
        }

        foreach (string logicalName in curvesByName.Keys)
        {
            if (TryResolveBlendshapeIndex(logicalName, out int index))
            {
                faceRenderer.SetBlendShapeWeight(index, 0.0f);
                currentWeights[index] = 0.0f;
                targetWeights[index] = 0.0f;
            }
        }

        ResetStreamWeights();
    }

    /// <summary>
    /// Resolves a logical curve channel to the corresponding SkinnedMeshRenderer blendshape index.
    /// </summary>
    /// <param name="logicalName">The logical channel name from the curve file.</param>
    /// <param name="index">The resolved blendshape index when found.</param>
    /// <returns>True when the target blendshape exists on the renderer; otherwise false.</returns>
    public bool TryResolveBlendshapeIndex(string logicalName, out int index)
    {
        return TryResolveBlendshapeTarget(logicalName, out index, out _);
    }

    private bool TryResolveBlendshapeTarget(string logicalName, out int index, out string actualName)
    {
        index = -1;
        actualName = "";

        if (string.IsNullOrWhiteSpace(logicalName))
        {
            return false;
        }

        actualName = ResolveActualBlendshapeName(logicalName);
        if (blendshapeIndexByName.TryGetValue(actualName, out index))
        {
            return true;
        }

        if (logMissingBlendshapes && missingBlendshapes.Add(actualName))
        {
            string rendererName = faceRenderer != null ? faceRenderer.name : "unassigned renderer";
            Debug.LogWarning(
                $"{nameof(FacialAnimationController)}: Blendshape '{actualName}' for logical channel '{logicalName}' was not found on '{rendererName}'.",
                this);
        }

        return false;
    }

    private bool LoadCurveFromJson(string json, string sourceName)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Curve JSON '{sourceName}' is empty.", this);
            ClearCurveState();
            return false;
        }

        BlendshapeCurveSet parsed;
        try
        {
            parsed = JsonUtility.FromJson<BlendshapeCurveSet>(json);
        }
        catch (ArgumentException exception)
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Failed to parse curve JSON '{sourceName}'. {exception.Message}", this);
            ClearCurveState();
            return false;
        }

        if (!ValidateCurveSet(parsed, sourceName))
        {
            ClearCurveState();
            return false;
        }

        curveSet = parsed;
        curvesByName.Clear();
        retargetMap.Clear();
        missingBlendshapes.Clear();

        BuildRetargetMap(parsed);
        BuildCurveCache(parsed);
        CacheBlendshapeIndices();

        return curvesByName.Count > 0;
    }

    private bool ValidateCurveSet(BlendshapeCurveSet candidate, string sourceName)
    {
        if (candidate == null)
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Curve JSON '{sourceName}' did not deserialize to a curve set.", this);
            return false;
        }

        if (string.IsNullOrWhiteSpace(candidate.version))
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Curve JSON '{sourceName}' is missing version.", this);
            return false;
        }

        if (!string.Equals(candidate.timebase, "audio_ms", StringComparison.Ordinal))
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Curve JSON '{sourceName}' has unsupported timebase '{candidate.timebase}'. Expected 'audio_ms'.", this);
            return false;
        }

        if (!string.IsNullOrWhiteSpace(candidate.weight_unit) &&
            !string.Equals(candidate.weight_unit, "normalized_0_1", StringComparison.Ordinal))
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Curve JSON '{sourceName}' has unsupported weight_unit '{candidate.weight_unit}'. Expected 'normalized_0_1'.", this);
            return false;
        }

        if (candidate.duration_ms < 0.0f)
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Curve JSON '{sourceName}' has a negative duration_ms.", this);
            return false;
        }

        if (candidate.curves == null || candidate.curves.Length == 0)
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Curve JSON '{sourceName}' does not contain any curves.", this);
            return false;
        }

        return true;
    }

    private void BuildRetargetMap(BlendshapeCurveSet parsed)
    {
        if (parsed.blendshape_mapping == null)
        {
            return;
        }

        foreach (BlendshapeMappingEntry mapping in parsed.blendshape_mapping)
        {
            if (mapping == null || string.IsNullOrWhiteSpace(mapping.logical) || string.IsNullOrWhiteSpace(mapping.actual))
            {
                Debug.LogWarning($"{nameof(FacialAnimationController)}: Ignoring an invalid blendshape_mapping entry.", this);
                continue;
            }

            retargetMap[mapping.logical] = mapping.actual;
        }
    }

    private void BuildCurveCache(BlendshapeCurveSet parsed)
    {
        foreach (BlendshapeCurve curve in parsed.curves)
        {
            if (curve == null || string.IsNullOrWhiteSpace(curve.name))
            {
                Debug.LogWarning($"{nameof(FacialAnimationController)}: Ignoring a curve with no name.", this);
                continue;
            }

            if (curve.keyframes == null || curve.keyframes.Length == 0)
            {
                Debug.LogWarning($"{nameof(FacialAnimationController)}: Ignoring curve '{curve.name}' because it has no keyframes.", this);
                continue;
            }

            Array.Sort(curve.keyframes, (left, right) => left.t.CompareTo(right.t));
            curvesByName[curve.name] = curve;
        }
    }

    private void CacheBlendshapeIndices()
    {
        blendshapeIndexByName.Clear();
        blendshapeNameByLower.Clear();

        if (faceRenderer == null || faceRenderer.sharedMesh == null)
        {
            return;
        }

        Mesh mesh = faceRenderer.sharedMesh;
        for (int i = 0; i < mesh.blendShapeCount; i++)
        {
            string blendshapeName = mesh.GetBlendShapeName(i);
            if (!string.IsNullOrEmpty(blendshapeName) && !blendshapeIndexByName.ContainsKey(blendshapeName))
            {
                blendshapeIndexByName.Add(blendshapeName, i);
                string lower = blendshapeName.ToLowerInvariant();
                if (!blendshapeNameByLower.ContainsKey(lower))
                {
                    blendshapeNameByLower.Add(lower, blendshapeName);
                }
            }
        }
    }

    private bool EnsureRendererReady()
    {
        if (faceRenderer == null)
        {
            if (!warnedMissingRenderer)
            {
                Debug.LogWarning($"{nameof(FacialAnimationController)}: Face renderer is not assigned.", this);
                warnedMissingRenderer = true;
            }

            return false;
        }

        if (faceRenderer.sharedMesh == null)
        {
            Debug.LogWarning($"{nameof(FacialAnimationController)}: Face renderer '{faceRenderer.name}' has no shared mesh.", this);
            return false;
        }

        if (blendshapeIndexByName.Count != faceRenderer.sharedMesh.blendShapeCount)
        {
            CacheBlendshapeIndices();
        }

        return true;
    }

    private string ResolveActualBlendshapeName(string logicalName)
    {
        if (retargetMap.TryGetValue(logicalName, out string actualName) && !string.IsNullOrWhiteSpace(actualName))
        {
            return actualName;
        }

        if (TryFindExistingBlendshapeName(logicalName, out actualName))
        {
            return actualName;
        }

        if (RuntimeAliases.TryGetValue(logicalName, out string[] aliases))
        {
            foreach (string alias in aliases)
            {
                if (TryFindExistingBlendshapeName(alias, out actualName))
                {
                    retargetMap[logicalName] = actualName;
                    return actualName;
                }
            }
        }

        return logicalName;
    }

    private bool TryFindExistingBlendshapeName(string candidate, out string actualName)
    {
        actualName = null;
        if (string.IsNullOrWhiteSpace(candidate))
        {
            return false;
        }

        if (blendshapeIndexByName.ContainsKey(candidate))
        {
            actualName = candidate;
            return true;
        }

        if (blendshapeNameByLower.TryGetValue(candidate.ToLowerInvariant(), out actualName))
        {
            return true;
        }

        return false;
    }

    private void SmoothTargetWeights()
    {
        SmoothVrmMouthWeights();

        if (faceRenderer == null || targetWeights.Count == 0)
        {
            return;
        }

        float durationSec = Mathf.Max(0.001f, streamSmoothMs / 1000.0f);
        float ratio = streamSmoothMs <= 0.0f ? 1.0f : Mathf.Clamp01(Time.deltaTime / durationSec);
        var indices = new List<int>(targetWeights.Keys);
        foreach (int index in indices)
        {
            float current = currentWeights.TryGetValue(index, out float value)
                ? value
                : Mathf.Clamp01(faceRenderer.GetBlendShapeWeight(index) / 100.0f);
            float target = targetWeights[index];
            float next = Mathf.Lerp(current, target, ratio);
            if (Mathf.Abs(next - target) < 0.002f)
            {
                next = target;
            }

            currentWeights[index] = next;
            faceRenderer.SetBlendShapeWeight(index, next * 100.0f);
        }
    }

    private bool TryApplyVrmStreamWeights(Dictionary<string, float> weights)
    {
        if (!preferVrmExpressions || !EnsureVrmExpressionReady())
        {
            return false;
        }

        bool hasAnyLipWeight = HasAnyLipWeight(weights);
        var resolvedTargets = new Dictionary<ExpressionPreset, float>();
        foreach (ExpressionPreset preset in VrmMouthPresets)
        {
            resolvedTargets[preset] = 0.0f;
        }

        foreach (KeyValuePair<string, float> entry in weights)
        {
            if (!TryResolveVrmMouthPreset(entry.Key, hasAnyLipWeight, out ExpressionPreset preset))
            {
                continue;
            }

            float normalizedWeight = Mathf.Clamp01(entry.Value * globalWeightScale);
            resolvedTargets[preset] = Mathf.Max(resolvedTargets[preset], normalizedWeight);
        }

        foreach (KeyValuePair<ExpressionPreset, float> entry in resolvedTargets)
        {
            ExpressionPreset preset = entry.Key;
            float normalizedWeight = entry.Value;
            if (!currentVrmMouthWeights.ContainsKey(preset))
            {
                currentVrmMouthWeights[preset] = 0.0f;
            }

            targetVrmMouthWeights[preset] = normalizedWeight;

            if (logFirstVrmExpressionWrite && !loggedFirstVrmStreamWrite && normalizedWeight > 0.001f)
            {
                loggedFirstVrmStreamWrite = true;
                Debug.Log($"{nameof(FacialAnimationController)}: First stream expression write target='vrm:{preset}' weight={normalizedWeight:0.###}.", this);
            }

            if (streamSmoothMs <= 0.0f)
            {
                currentVrmMouthWeights[preset] = normalizedWeight;
                SetVrmExpressionWeight(preset, normalizedWeight);
            }
        }

        foreach (string logicalName in weights.Keys)
        {
            if (!string.IsNullOrWhiteSpace(logicalName))
            {
                streamLogicalChannels.Add(logicalName);
            }
        }

        return true;
    }

    private bool EnsureVrmExpressionReady()
    {
        if (vrmInstance == null)
        {
            vrmInstance = GetComponentInChildren<Vrm10Instance>();
        }

        if (vrmInstance == null)
        {
            vrmInstance = FindAnyObjectByType<Vrm10Instance>();
        }

        return vrmInstance?.Runtime?.Expression != null;
    }

    private static bool HasAnyLipWeight(Dictionary<string, float> weights)
    {
        foreach (KeyValuePair<string, float> entry in weights)
        {
            if (entry.Value <= 0.001f)
            {
                continue;
            }

            switch (entry.Key)
            {
                case "lip_a":
                case "lip_i":
                case "lip_u":
                case "lip_w":
                case "lip_e":
                case "lip_o":
                    return true;
            }
        }

        return false;
    }

    private void SmoothVrmMouthWeights()
    {
        if (targetVrmMouthWeights.Count == 0 || !EnsureVrmExpressionReady())
        {
            return;
        }

        float durationSec = Mathf.Max(0.001f, streamSmoothMs / 1000.0f);
        float ratio = streamSmoothMs <= 0.0f ? 1.0f : Mathf.Clamp01(Time.deltaTime / durationSec);
        var presets = new List<ExpressionPreset>(targetVrmMouthWeights.Keys);
        foreach (ExpressionPreset preset in presets)
        {
            float current = currentVrmMouthWeights.TryGetValue(preset, out float value) ? value : 0.0f;
            float target = targetVrmMouthWeights[preset];
            float next = Mathf.Lerp(current, target, ratio);
            if (Mathf.Abs(next - target) < 0.002f)
            {
                next = target;
            }

            currentVrmMouthWeights[preset] = next;
            SetVrmExpressionWeight(preset, next);
        }
    }

    private void ResetVrmMouthWeights()
    {
        if (EnsureVrmExpressionReady())
        {
            foreach (ExpressionPreset preset in VrmMouthPresets)
            {
                SetVrmExpressionWeight(preset, 0.0f);
            }
        }

        currentVrmMouthWeights.Clear();
        targetVrmMouthWeights.Clear();
    }

    private void SetVrmExpressionWeight(ExpressionPreset preset, float weight)
    {
        if (vrmInstance?.Runtime?.Expression == null)
        {
            return;
        }

        var key = ExpressionKey.CreateFromPreset(preset);
        vrmInstance.Runtime.Expression.SetWeight(key, Mathf.Clamp01(weight));
    }

    private static float EvaluateCurve(BlendshapeCurve curve, float timeMs)
    {
        if (curve == null || curve.keyframes == null || curve.keyframes.Length == 0)
        {
            return 0.0f;
        }

        CurveKeyframe[] keyframes = curve.keyframes;
        float clampedTime = Mathf.Max(0.0f, timeMs);

        if (clampedTime <= keyframes[0].t)
        {
            return Mathf.Clamp01(keyframes[0].v);
        }

        int lastIndex = keyframes.Length - 1;
        if (clampedTime >= keyframes[lastIndex].t)
        {
            return Mathf.Clamp01(keyframes[lastIndex].v);
        }

        for (int i = 0; i < lastIndex; i++)
        {
            CurveKeyframe from = keyframes[i];
            CurveKeyframe to = keyframes[i + 1];

            if (clampedTime < from.t || clampedTime > to.t)
            {
                continue;
            }

            float segmentDuration = to.t - from.t;
            if (segmentDuration <= Mathf.Epsilon)
            {
                return Mathf.Clamp01(to.v);
            }

            float ratio = (clampedTime - from.t) / segmentDuration;
            return Mathf.Clamp01(Mathf.Lerp(from.v, to.v, ratio));
        }

        return 0.0f;
    }

    private void ClearCurveState()
    {
        curveSet = null;
        curvesByName.Clear();
        retargetMap.Clear();
        missingBlendshapes.Clear();
    }
}
