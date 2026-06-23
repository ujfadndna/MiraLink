using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

[Serializable]
public sealed class GestureEventData
{
    public string gesture_name;
    public float start_ms, apex_ms, duration_ms, intensity;
}

[DefaultExecutionOrder(20000)] // MUST run after UniVRM's [DefaultExecutionOrder(11000)]
public sealed class GestureAnimationController : MonoBehaviour
{
    [SerializeField] private Animator vrm10Animator;
    [SerializeField] private AvatarMask upperBodyMask; // kept for reference, unused
    [SerializeField] private AnimationClip[] gestureclips;
    [SerializeField] private float cooldownSec = 1.2f, blendInSec = 0.15f, blendOutSec = 0.2f;

    private static readonly HumanBodyBones[] UpperBodyBones =
    {
        HumanBodyBones.Hips, HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.UpperChest,
        HumanBodyBones.Neck, HumanBodyBones.Head,
        HumanBodyBones.LeftShoulder, HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftHand,
        HumanBodyBones.RightShoulder, HumanBodyBones.RightUpperArm, HumanBodyBones.RightLowerArm, HumanBodyBones.RightHand,
        HumanBodyBones.LeftThumbProximal, HumanBodyBones.LeftThumbIntermediate, HumanBodyBones.LeftThumbDistal,
        HumanBodyBones.LeftIndexProximal, HumanBodyBones.LeftIndexIntermediate, HumanBodyBones.LeftIndexDistal,
        HumanBodyBones.LeftMiddleProximal, HumanBodyBones.LeftMiddleIntermediate, HumanBodyBones.LeftMiddleDistal,
        HumanBodyBones.LeftRingProximal, HumanBodyBones.LeftRingIntermediate, HumanBodyBones.LeftRingDistal,
        HumanBodyBones.LeftLittleProximal, HumanBodyBones.LeftLittleIntermediate, HumanBodyBones.LeftLittleDistal,
        HumanBodyBones.RightThumbProximal, HumanBodyBones.RightThumbIntermediate, HumanBodyBones.RightThumbDistal,
        HumanBodyBones.RightIndexProximal, HumanBodyBones.RightIndexIntermediate, HumanBodyBones.RightIndexDistal,
        HumanBodyBones.RightMiddleProximal, HumanBodyBones.RightMiddleIntermediate, HumanBodyBones.RightMiddleDistal,
        HumanBodyBones.RightRingProximal, HumanBodyBones.RightRingIntermediate, HumanBodyBones.RightRingDistal,
        HumanBodyBones.RightLittleProximal, HumanBodyBones.RightLittleIntermediate, HumanBodyBones.RightLittleDistal,
    };

    // Cached bone transform pairs (avatar, sampleGO) - built once in Start.
    private (Transform avatar, Transform sample)[] _bonePairs;

    private AnimationClip _activeClip;
    private float _clipTime;
    private float _currentWeight;
    private float _lastGestureTime = -999f;
    private int _gestureToken;

    private GameObject _sampleGO;
    private Animator _sampleAnimator;

    private readonly Dictionary<string, int> _nameToIndex = new Dictionary<string, int>(StringComparer.Ordinal);
    private readonly HashSet<string> _warnedMissing = new HashSet<string>(StringComparer.Ordinal);

    private void Awake() => BuildNameMap();

    private void Start() => InitSampleRig();

    private void OnDestroy()
    {
        if (_sampleGO != null)
            Destroy(_sampleGO);
    }

    private void LateUpdate()
    {
        if (_activeClip == null || _currentWeight <= 0f || _bonePairs == null)
            return;

        _clipTime = (_clipTime + Time.deltaTime) % _activeClip.length;
        _activeClip.SampleAnimation(_sampleGO, _clipTime);

        foreach (var (avatarTransform, sampleTransform) in _bonePairs)
        {
            avatarTransform.localRotation = Quaternion.Slerp(
                avatarTransform.localRotation,
                sampleTransform.localRotation,
                _currentWeight);
        }
    }

    public void ScheduleGestures(List<GestureEventData> events, float audioOffsetMs = 0)
    {
        StopGestures();
        if (events == null || events.Count == 0)
            return;

        var sorted = new List<GestureEventData>(events);
        sorted.Sort((a, b) => a.start_ms.CompareTo(b.start_ms));

        foreach (var gestureEvent in sorted)
        {
            if (gestureEvent != null && !string.IsNullOrEmpty(gestureEvent.gesture_name))
                StartCoroutine(PlayGestureAtTime(gestureEvent, audioOffsetMs));
        }
    }

    public void StopGestures()
    {
        StopAllCoroutines();
        _gestureToken++;
        _activeClip = null;
        _clipTime = 0f;
        _currentWeight = 0f;
    }

    private IEnumerator PlayGestureAtTime(GestureEventData gestureEvent, float audioOffsetMs)
    {
        var delay = Mathf.Max(0f, (gestureEvent.start_ms - audioOffsetMs) / 1000f);
        if (delay > 0f)
            yield return new WaitForSeconds(delay);

        var clip = GetClip(gestureEvent.gesture_name);
        if (clip == null || Time.time - _lastGestureTime < cooldownSec)
            yield break;

        _lastGestureTime = Time.time;
        yield return PlayGesture(clip, Mathf.Max(0f, gestureEvent.duration_ms / 1000f));
    }

    private IEnumerator PlayGesture(AnimationClip clip, float durationSec)
    {
        var token = ++_gestureToken;
        _activeClip = clip;
        _clipTime = 0f;
        _currentWeight = 0f;

        yield return LerpWeight(0f, 1f, blendInSec, token);
        if (token != _gestureToken)
            yield break;

        if (durationSec > 0f)
            yield return new WaitForSeconds(durationSec);
        if (token != _gestureToken)
            yield break;

        yield return LerpWeight(1f, 0f, blendOutSec, token);
        if (token == _gestureToken)
        {
            _activeClip = null;
            _clipTime = 0f;
            _currentWeight = 0f;
        }
    }

    private IEnumerator LerpWeight(float from, float to, float durationSec, int token)
    {
        if (durationSec <= 0f)
        {
            _currentWeight = to;
            yield break;
        }

        var elapsed = 0f;
        while (elapsed < durationSec && token == _gestureToken)
        {
            elapsed += Time.deltaTime;
            _currentWeight = Mathf.Lerp(from, to, Mathf.Clamp01(elapsed / durationSec));
            yield return null;
        }

        if (token == _gestureToken)
            _currentWeight = to;
    }

    private void InitSampleRig()
    {
        if (vrm10Animator == null)
        {
            Debug.LogWarning("[GestureAnimationController] vrm10Animator not assigned.", this);
            return;
        }

        _sampleGO = new GameObject("__GestureSample__")
        {
            hideFlags = HideFlags.HideAndDontSave
        };

        CopyTransformHierarchy(vrm10Animator.transform, _sampleGO.transform);

        _sampleAnimator = _sampleGO.AddComponent<Animator>();
        _sampleAnimator.avatar = vrm10Animator.avatar;
        _sampleAnimator.enabled = false;

        var pairs = new List<(Transform, Transform)>();
        foreach (var bone in UpperBodyBones)
        {
            var avatarTransform = vrm10Animator.GetBoneTransform(bone);
            var sampleTransform = _sampleAnimator.GetBoneTransform(bone);
            if (avatarTransform != null && sampleTransform != null)
                pairs.Add((avatarTransform, sampleTransform));
        }

        _bonePairs = pairs.ToArray();
        Debug.Log($"[GestureAnimationController] Ready. Cached {_bonePairs.Length} upper-body bone pairs.", this);
    }

    private static void CopyTransformHierarchy(Transform source, Transform target)
    {
        target.localPosition = source.localPosition;
        target.localRotation = source.localRotation;
        target.localScale = source.localScale;

        for (var i = 0; i < source.childCount; i++)
        {
            var sourceChild = source.GetChild(i);
            var targetChild = new GameObject(sourceChild.name)
            {
                hideFlags = HideFlags.HideAndDontSave
            };

            targetChild.transform.SetParent(target, false);
            CopyTransformHierarchy(sourceChild, targetChild.transform);
        }
    }

    private void BuildNameMap()
    {
        var names = new[]
        {
            "gesture_greet",
            "gesture_enumerate",
            "gesture_explain",
            "gesture_uncertain",
            "gesture_beat",
            "gesture_contrast",
            "gesture_emphasis"
        };

        _nameToIndex.Clear();
        for (var i = 0; i < names.Length; i++)
            _nameToIndex[names[i]] = i;
    }

    private AnimationClip GetClip(string gestureName)
    {
        if (_nameToIndex.TryGetValue(gestureName, out var index) &&
            gestureclips != null &&
            index < gestureclips.Length &&
            gestureclips[index] != null)
        {
            return gestureclips[index];
        }

        if (_warnedMissing.Add(gestureName))
            Debug.LogWarning($"[GestureAnimationController] Clip not found: {gestureName}", this);

        if (!string.Equals(gestureName, "gesture_beat", StringComparison.Ordinal) &&
            _nameToIndex.TryGetValue("gesture_beat", out var fallbackIndex) &&
            gestureclips != null &&
            fallbackIndex < gestureclips.Length &&
            gestureclips[fallbackIndex] != null)
        {
            return gestureclips[fallbackIndex];
        }

        return null;
    }
}
