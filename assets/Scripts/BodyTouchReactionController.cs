using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

[DefaultExecutionOrder(21000)]
public sealed class BodyTouchReactionController : MonoBehaviour
{
    [Serializable]
    private sealed class PoseClip
    {
        public string poseMode = "";
        public AnimationClip clip;
    }

    private struct ProceduralBoneOffset
    {
        public readonly HumanBodyBones Bone;
        public readonly Vector3 EulerOffset;

        public ProceduralBoneOffset(HumanBodyBones bone, float x, float y, float z)
        {
            Bone = bone;
            EulerOffset = new Vector3(x, y, z);
        }
    }

    private struct ProceduralBoneState
    {
        public Transform Transform;
        public Quaternion StartRotation;
        public Quaternion TargetRotation;
    }

    private static readonly HumanBodyBones[] ReactionBones =
    {
        HumanBodyBones.Hips,
        HumanBodyBones.Spine,
        HumanBodyBones.Chest,
        HumanBodyBones.UpperChest,
        HumanBodyBones.Neck,
        HumanBodyBones.Head,
        HumanBodyBones.LeftShoulder,
        HumanBodyBones.LeftUpperArm,
        HumanBodyBones.LeftLowerArm,
        HumanBodyBones.LeftHand,
        HumanBodyBones.RightShoulder,
        HumanBodyBones.RightUpperArm,
        HumanBodyBones.RightLowerArm,
        HumanBodyBones.RightHand,
        HumanBodyBones.LeftUpperLeg,
        HumanBodyBones.LeftLowerLeg,
        HumanBodyBones.LeftFoot,
        HumanBodyBones.RightUpperLeg,
        HumanBodyBones.RightLowerLeg,
        HumanBodyBones.RightFoot,
    };

    [SerializeField] private Animator vrm10Animator;
    [SerializeField] private PoseClip[] poseClips;
    [SerializeField] private float blendInSec = 0.08f;
    [SerializeField] private float blendOutSec = 0.16f;
    [SerializeField] private bool autoLoadGeneratedClips = true;

    private readonly Dictionary<string, AnimationClip> _clips = new Dictionary<string, AnimationClip>(StringComparer.Ordinal);
    private readonly HashSet<string> _warnedMissing = new HashSet<string>(StringComparer.Ordinal);
    private (Transform avatar, Transform sample, Vector3 initialLocalPosition)[] _bonePairs;
    private GameObject _sampleGO;
    private Animator _sampleAnimator;
    private AnimationClip _activeClip;
    private ProceduralBoneState[] _activeProceduralStates;
    private float _clipTime;
    private float _weight;
    private int _token;

    private void Awake()
    {
        if (vrm10Animator == null)
            vrm10Animator = GetComponentInChildren<Animator>();

        BuildClipMap();
    }

    private void Start()
    {
        InitSampleRig();
    }

    private void OnDestroy()
    {
        RestoreInitialLocalPositions();

        if (_sampleGO != null)
            Destroy(_sampleGO);
    }

    private void OnDisable()
    {
        StopPose();
        RestoreInitialLocalPositions();
    }

    private void LateUpdate()
    {
        if (_activeProceduralStates != null)
        {
            for (int i = 0; i < _activeProceduralStates.Length; i++)
            {
                var state = _activeProceduralStates[i];
                if (state.Transform != null)
                    state.Transform.localRotation = Quaternion.Slerp(state.StartRotation, state.TargetRotation, _weight);
            }
            return;
        }

        if (_activeClip == null || _weight <= 0f || _sampleGO == null || _bonePairs == null)
            return;

        _clipTime = Mathf.Min(_clipTime + Time.deltaTime, Mathf.Max(0.01f, _activeClip.length));
        _activeClip.SampleAnimation(_sampleGO, _clipTime);

        foreach (var (avatarTransform, sampleTransform, _) in _bonePairs)
        {
            avatarTransform.localRotation = Quaternion.Slerp(
                avatarTransform.localRotation,
                sampleTransform.localRotation,
                _weight);
        }
    }

    public void PlayPose(string poseMode, float durationSec, int priority, string interruptPolicy)
    {
        poseMode = NormalizePoseMode(poseMode);
        if (string.IsNullOrEmpty(poseMode))
            return;

        if (poseMode == "reset")
        {
            StopPose();
            return;
        }

        var proceduralPose = GetProceduralPose(poseMode);
        if (proceduralPose != null && proceduralPose.Length > 0 && TryStartProceduralPose(proceduralPose))
        {
            StopAllCoroutines();
            StartCoroutine(PlayProceduralPoseRoutine(durationSec));
            return;
        }

        var clip = GetClip(poseMode);
        if (clip == null)
            return;

        StopAllCoroutines();
        RestoreActiveProceduralRotations();
        _activeProceduralStates = null;
        StartCoroutine(PlayPoseRoutine(clip, durationSec));
    }

    public void StopPose()
    {
        StopAllCoroutines();
        _token++;
        RestoreActiveProceduralRotations();
        _activeProceduralStates = null;
        _activeClip = null;
        _clipTime = 0f;
        _weight = 0f;
    }

    private IEnumerator PlayProceduralPoseRoutine(float durationSec)
    {
        int token = ++_token;
        _activeClip = null;
        _clipTime = 0f;
        _weight = 0f;

        yield return LerpWeight(0f, 1f, blendInSec, token);
        if (token != _token)
            yield break;

        float hold = Mathf.Max(0f, durationSec - blendInSec - blendOutSec);
        if (hold > 0f)
            yield return new WaitForSeconds(hold);
        if (token != _token)
            yield break;

        yield return LerpWeight(1f, 0f, blendOutSec, token);
        if (token == _token)
        {
            RestoreActiveProceduralRotations();
            _activeProceduralStates = null;
            _weight = 0f;
        }
    }

    private IEnumerator PlayPoseRoutine(AnimationClip clip, float durationSec)
    {
        int token = ++_token;
        _activeProceduralStates = null;
        _activeClip = clip;
        _clipTime = 0f;
        _weight = 0f;

        yield return LerpWeight(0f, 1f, blendInSec, token);
        if (token != _token)
            yield break;

        float hold = Mathf.Max(0f, durationSec - blendInSec - blendOutSec);
        if (hold > 0f)
            yield return new WaitForSeconds(hold);
        if (token != _token)
            yield break;

        yield return LerpWeight(1f, 0f, blendOutSec, token);
        if (token == _token)
        {
            _activeClip = null;
            _clipTime = 0f;
            _weight = 0f;
        }
    }

    private IEnumerator LerpWeight(float from, float to, float durationSec, int token)
    {
        if (durationSec <= 0f)
        {
            _weight = to;
            yield break;
        }

        float elapsed = 0f;
        while (elapsed < durationSec && token == _token)
        {
            elapsed += Time.deltaTime;
            _weight = Mathf.Lerp(from, to, Mathf.Clamp01(elapsed / durationSec));
            yield return null;
        }

        if (token == _token)
            _weight = to;
    }

    private bool TryStartProceduralPose(ProceduralBoneOffset[] pose)
    {
        if (vrm10Animator == null)
            return false;

        RestoreActiveProceduralRotations();

        var states = new List<ProceduralBoneState>();
        foreach (var offset in pose)
        {
            var bone = vrm10Animator.GetBoneTransform(offset.Bone);
            if (bone == null)
                continue;

            var start = bone.localRotation;
            states.Add(new ProceduralBoneState
            {
                Transform = bone,
                StartRotation = start,
                TargetRotation = start * Quaternion.Euler(offset.EulerOffset),
            });
        }

        if (states.Count == 0)
            return false;

        _activeClip = null;
        _clipTime = 0f;
        _weight = 0f;
        _activeProceduralStates = states.ToArray();
        return true;
    }

    private void RestoreActiveProceduralRotations()
    {
        if (_activeProceduralStates == null)
            return;

        for (int i = 0; i < _activeProceduralStates.Length; i++)
        {
            var state = _activeProceduralStates[i];
            if (state.Transform != null)
                state.Transform.localRotation = state.StartRotation;
        }
    }

    private void InitSampleRig()
    {
        if (vrm10Animator == null)
        {
            Debug.LogWarning("[BodyTouchReactionController] vrm10Animator not assigned.", this);
            return;
        }

        _sampleGO = new GameObject("__BodyTouchSample__")
        {
            hideFlags = HideFlags.HideAndDontSave
        };

        CopyTransformHierarchy(vrm10Animator.transform, _sampleGO.transform);
        _sampleAnimator = _sampleGO.AddComponent<Animator>();
        _sampleAnimator.avatar = vrm10Animator.avatar;
        _sampleAnimator.enabled = false;

        var pairs = new List<(Transform, Transform, Vector3)>();
        foreach (var bone in ReactionBones)
        {
            var avatarTransform = vrm10Animator.GetBoneTransform(bone);
            var sampleTransform = _sampleAnimator.GetBoneTransform(bone);
            if (avatarTransform != null && sampleTransform != null)
                pairs.Add((avatarTransform, sampleTransform, avatarTransform.localPosition));
        }

        _bonePairs = pairs.ToArray();
        Debug.Log($"[BodyTouchReactionController] Ready. Cached {_bonePairs.Length} reaction bone pairs.", this);
    }

    private void BuildClipMap()
    {
        _clips.Clear();

        if (poseClips != null)
        {
            foreach (var entry in poseClips)
            {
                if (entry == null || string.IsNullOrEmpty(entry.poseMode) || entry.clip == null)
                    continue;
                _clips[NormalizePoseMode(entry.poseMode)] = entry.clip;
            }
        }

#if UNITY_EDITOR
        if (autoLoadGeneratedClips)
        {
            var generated = UnityEditor.AssetDatabase.FindAssets("t:AnimationClip", new[] { "assets/Animations/BodyTouch" });
            foreach (var guid in generated)
            {
                var path = UnityEditor.AssetDatabase.GUIDToAssetPath(guid);
                var clip = UnityEditor.AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
                if (clip != null)
                    _clips[NormalizePoseMode(clip.name)] = clip;
            }
        }
#endif
    }

    private AnimationClip GetClip(string poseMode)
    {
        BuildClipMap();
        if (_clips.TryGetValue(poseMode, out var clip) && clip != null)
            return clip;

        if (_warnedMissing.Add(poseMode))
            Debug.LogWarning($"[BodyTouchReactionController] Clip not found for pose_mode: {poseMode}", this);

        return null;
    }

    private static ProceduralBoneOffset[] GetProceduralPose(string poseMode)
    {
        switch (poseMode)
        {
            case "touch_head_recoil":
                return Pose(
                    Bone(HumanBodyBones.Head, -10f, 0f, 0f),
                    Bone(HumanBodyBones.Neck, -5f, 0f, 0f));
            case "touch_face_flinch":
                return Pose(
                    Bone(HumanBodyBones.Head, -4f, -8f, 3f),
                    Bone(HumanBodyBones.Neck, -3f, -5f, 0f));
            case "touch_neck_shy":
                return Pose(
                    Bone(HumanBodyBones.Neck, 7f, -7f, 0f),
                    Bone(HumanBodyBones.Head, 5f, -10f, 0f),
                    Bone(HumanBodyBones.Chest, 0f, -4f, 0f));
            case "touch_chest_guard":
                return Pose(
                    Bone(HumanBodyBones.Chest, -3f, 0f, 0f),
                    Bone(HumanBodyBones.LeftUpperArm, 12f, 0f, 42f),
                    Bone(HumanBodyBones.RightUpperArm, 12f, 0f, -42f),
                    Bone(HumanBodyBones.LeftLowerArm, 18f, 0f, 22f),
                    Bone(HumanBodyBones.RightLowerArm, 18f, 0f, -22f));
            case "touch_waist_guard":
                return Pose(
                    Bone(HumanBodyBones.Hips, 0f, 0f, 5f),
                    Bone(HumanBodyBones.Spine, 0f, 0f, 7f),
                    Bone(HumanBodyBones.LeftUpperArm, 5f, 0f, 30f),
                    Bone(HumanBodyBones.RightUpperArm, 5f, 0f, -30f));
            case "touch_left_shoulder_ack":
                return SideShoulderPose(-1f);
            case "touch_right_shoulder_ack":
                return SideShoulderPose(1f);
            case "touch_left_arm_ack":
                return SideArmPose(-1f);
            case "touch_right_arm_ack":
                return SideArmPose(1f);
            case "touch_left_hand_ack":
                return SideHandPose(-1f, false);
            case "touch_right_hand_ack":
                return SideHandPose(1f, false);
            case "touch_left_hand_hold":
                return SideHandPose(-1f, true);
            case "touch_right_hand_hold":
                return SideHandPose(1f, true);
            case "touch_left_leg_step":
                return SideLegPose(-1f);
            case "touch_right_leg_step":
                return SideLegPose(1f);
            case "touch_left_foot_step":
                return SideFootPose(-1f);
            case "touch_right_foot_step":
                return SideFootPose(1f);
            default:
                return null;
        }
    }

    private static ProceduralBoneOffset[] SideShoulderPose(float side)
    {
        bool left = side < 0f;
        return Pose(
            Bone(left ? HumanBodyBones.LeftShoulder : HumanBodyBones.RightShoulder, 0f, 0f, side * -10f),
            Bone(left ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm, 10f, side * 5f, side * -18f),
            Bone(HumanBodyBones.Head, 0f, side * 10f, 0f));
    }

    private static ProceduralBoneOffset[] SideArmPose(float side)
    {
        bool left = side < 0f;
        return Pose(
            Bone(left ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm, 10f, side * 8f, side * -20f),
            Bone(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm, 8f, side * 4f, side * -16f),
            Bone(HumanBodyBones.Head, 0f, side * 8f, 0f));
    }

    private static ProceduralBoneOffset[] SideHandPose(float side, bool hold)
    {
        bool left = side < 0f;
        float scale = hold ? 0.82f : 0.68f;
        return Pose(
            Bone(left ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm, 8f * scale, side * 4f * scale, side * -12f * scale),
            Bone(left ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm, 10f * scale, side * 3f * scale, side * -10f * scale),
            Bone(left ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand, 0f, side * 3f * scale, side * -5f * scale),
            Bone(HumanBodyBones.Head, 3f, side * 5f, 0f));
    }

    private static ProceduralBoneOffset[] SideLegPose(float side)
    {
        bool left = side < 0f;
        return Pose(
            Bone(HumanBodyBones.Hips, 0f, 0f, side * -4f),
            Bone(left ? HumanBodyBones.LeftUpperLeg : HumanBodyBones.RightUpperLeg, -9f, 0f, side * 5f),
            Bone(left ? HumanBodyBones.LeftLowerLeg : HumanBodyBones.RightLowerLeg, 13f, 0f, 0f),
            Bone(left ? HumanBodyBones.LeftFoot : HumanBodyBones.RightFoot, -4f, 0f, side * 3f),
            Bone(HumanBodyBones.Head, 9f, side * 6f, 0f));
    }

    private static ProceduralBoneOffset[] SideFootPose(float side)
    {
        bool left = side < 0f;
        return Pose(
            Bone(HumanBodyBones.Hips, 0f, 0f, side * -5f),
            Bone(left ? HumanBodyBones.LeftUpperLeg : HumanBodyBones.RightUpperLeg, -6f, 0f, side * 5f),
            Bone(left ? HumanBodyBones.LeftLowerLeg : HumanBodyBones.RightLowerLeg, 13f, 0f, 0f),
            Bone(left ? HumanBodyBones.LeftFoot : HumanBodyBones.RightFoot, -14f, 0f, side * 5f),
            Bone(HumanBodyBones.Head, 11f, side * 6f, 0f));
    }

    private static ProceduralBoneOffset[] Pose(params ProceduralBoneOffset[] offsets)
    {
        return offsets;
    }

    private static ProceduralBoneOffset Bone(HumanBodyBones bone, float x, float y, float z)
    {
        return new ProceduralBoneOffset(bone, x, y, z);
    }

    private void RestoreInitialLocalPositions()
    {
        if (_bonePairs == null)
            return;

        foreach (var pair in _bonePairs)
        {
            if (pair.avatar != null)
                pair.avatar.localPosition = pair.initialLocalPosition;
        }
    }

    private static string NormalizePoseMode(string poseMode)
    {
        return string.IsNullOrEmpty(poseMode) ? "" : poseMode.Trim().ToLowerInvariant();
    }

    private static void CopyTransformHierarchy(Transform source, Transform target)
    {
        target.localPosition = source.localPosition;
        target.localRotation = source.localRotation;
        target.localScale = source.localScale;

        for (int i = 0; i < source.childCount; i++)
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
}
