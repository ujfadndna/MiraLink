using System.Globalization;
using System.Text;
using UnityEngine;

/// <summary>
/// Publishes normalized touch anchors for the mobile browser overlay.
/// </summary>
public sealed class AvatarAnchorPublisher : MonoBehaviour
{
    [SerializeField] private NetworkClient networkClient;
    [SerializeField] private Animator avatarAnimator;
    [SerializeField] private Camera sourceCamera;
    [SerializeField] private float publishIntervalSec = 0.1f;

    [Header("Anchor Radius")]
    [SerializeField] private float headRadius = 0.095f;
    [SerializeField] private float faceRadius = 0.095f;
    [SerializeField] private float neckRadius = 0.06f;
    [SerializeField] private float chestRadius = 0.12f;
    [SerializeField] private float waistRadius = 0.115f;
    [SerializeField] private float shoulderRadius = 0.065f;
    [SerializeField] private float armRadius = 0.07f;
    [SerializeField] private float handRadius = 0.095f;
    [SerializeField] private float legRadius = 0.08f;
    [SerializeField] private float footRadius = 0.07f;

    private float _nextPublishTime;

    private void Awake()
    {
        if (networkClient == null)
            networkClient = GetComponent<NetworkClient>();
        if (avatarAnimator == null)
            avatarAnimator = GetComponentInChildren<Animator>();
        if (sourceCamera == null)
            sourceCamera = Camera.main;
    }

    private void LateUpdate()
    {
        if (networkClient == null || !networkClient.BackendReady)
            return;

        if (Time.unscaledTime < _nextPublishTime)
            return;

        _nextPublishTime = Time.unscaledTime + Mathf.Max(0.03f, publishIntervalSec);

        if (sourceCamera == null)
            sourceCamera = Camera.main;
        if (sourceCamera == null)
            return;

        networkClient.SendAvatarAnchors(BuildAnchorsJson());
    }

    private string BuildAnchorsJson()
    {
        var head = Bone(HumanBodyBones.Head);
        var neck = Bone(HumanBodyBones.Neck);
        var spine = Bone(HumanBodyBones.Spine);
        var chest = Bone(HumanBodyBones.Chest);
        var upperChest = Bone(HumanBodyBones.UpperChest);
        var hips = Bone(HumanBodyBones.Hips);
        var leftShoulder = Bone(HumanBodyBones.LeftShoulder);
        var rightShoulder = Bone(HumanBodyBones.RightShoulder);
        var leftUpperArm = Bone(HumanBodyBones.LeftUpperArm);
        var rightUpperArm = Bone(HumanBodyBones.RightUpperArm);
        var leftForearm = Bone(HumanBodyBones.LeftLowerArm);
        var rightForearm = Bone(HumanBodyBones.RightLowerArm);
        var leftHand = Bone(HumanBodyBones.LeftHand);
        var rightHand = Bone(HumanBodyBones.RightHand);
        var leftUpperLeg = Bone(HumanBodyBones.LeftUpperLeg);
        var rightUpperLeg = Bone(HumanBodyBones.RightUpperLeg);
        var leftLowerLeg = Bone(HumanBodyBones.LeftLowerLeg);
        var rightLowerLeg = Bone(HumanBodyBones.RightLowerLeg);
        var leftFoot = Bone(HumanBodyBones.LeftFoot);
        var rightFoot = Bone(HumanBodyBones.RightFoot);

        Vector3 headPos = head != null ? head.position : transform.position + Vector3.up * 1.55f;
        Vector3 neckPos = neck != null ? neck.position : headPos + Vector3.down * 0.18f;
        Vector3 chestPos = upperChest != null ? upperChest.position : chest != null ? chest.position : transform.position + Vector3.up * 1.15f;
        Vector3 spinePos = spine != null ? spine.position : Vector3.Lerp(chestPos, transform.position + Vector3.up * 0.8f, 0.5f);
        Vector3 hipsPos = hips != null ? hips.position : transform.position + Vector3.up * 0.85f;

        Vector3 facePos = Vector3.Lerp(headPos, neckPos, 0.38f);
        Vector3 waistPos = Vector3.Lerp(spinePos, hipsPos, 0.55f);
        Vector3 leftShoulderPos = PositionOrFallback(leftShoulder, Vector3.Lerp(neckPos, chestPos, 0.3f) + transform.TransformDirection(Vector3.left) * 0.18f);
        Vector3 rightShoulderPos = PositionOrFallback(rightShoulder, Vector3.Lerp(neckPos, chestPos, 0.3f) + transform.TransformDirection(Vector3.right) * 0.18f);
        Vector3 leftUpperArmPos = MidpointOrFallback(leftUpperArm, leftForearm, leftShoulderPos + transform.TransformDirection(Vector3.left + Vector3.down * 0.7f) * 0.18f);
        Vector3 rightUpperArmPos = MidpointOrFallback(rightUpperArm, rightForearm, rightShoulderPos + transform.TransformDirection(Vector3.right + Vector3.down * 0.7f) * 0.18f);
        Vector3 leftForearmPos = MidpointOrFallback(leftForearm, leftHand, leftUpperArmPos + transform.TransformDirection(Vector3.left + Vector3.down * 0.6f) * 0.18f);
        Vector3 rightForearmPos = MidpointOrFallback(rightForearm, rightHand, rightUpperArmPos + transform.TransformDirection(Vector3.right + Vector3.down * 0.6f) * 0.18f);
        Vector3 leftHandPos = PositionOrFallback(leftHand, leftForearmPos + transform.TransformDirection(Vector3.left + Vector3.down * 0.3f) * 0.16f);
        Vector3 rightHandPos = PositionOrFallback(rightHand, rightForearmPos + transform.TransformDirection(Vector3.right + Vector3.down * 0.3f) * 0.16f);
        Vector3 leftThighPos = MidpointOrFallback(leftUpperLeg, leftLowerLeg, hipsPos + transform.TransformDirection(Vector3.left + Vector3.down) * 0.14f);
        Vector3 rightThighPos = MidpointOrFallback(rightUpperLeg, rightLowerLeg, hipsPos + transform.TransformDirection(Vector3.right + Vector3.down) * 0.14f);
        Vector3 leftCalfPos = MidpointOrFallback(leftLowerLeg, leftFoot, leftThighPos + transform.TransformDirection(Vector3.down) * 0.28f);
        Vector3 rightCalfPos = MidpointOrFallback(rightLowerLeg, rightFoot, rightThighPos + transform.TransformDirection(Vector3.down) * 0.28f);
        Vector3 leftFootPos = PositionOrFallback(leftFoot, leftCalfPos + transform.TransformDirection(Vector3.down + Vector3.forward * 0.25f) * 0.16f);
        Vector3 rightFootPos = PositionOrFallback(rightFoot, rightCalfPos + transform.TransformDirection(Vector3.down + Vector3.forward * 0.25f) * 0.16f);

        var sb = new StringBuilder(1536);
        sb.Append('{');
        bool comma = false;
        AppendAnchor(sb, "head", headPos, headRadius, "center", "head", ref comma);
        AppendAnchor(sb, "face", facePos, faceRadius, "center", "face", ref comma);
        AppendAnchor(sb, "neck", neckPos, neckRadius, "center", "neck", ref comma);
        AppendAnchor(sb, "chest", chestPos, chestRadius, "center", "chest", ref comma);
        AppendAnchor(sb, "waist", waistPos, waistRadius, "center", "waist", ref comma);
        AppendAnchor(sb, "left_shoulder", leftShoulderPos, shoulderRadius, "left", "shoulder", ref comma);
        AppendAnchor(sb, "right_shoulder", rightShoulderPos, shoulderRadius, "right", "shoulder", ref comma);
        AppendAnchor(sb, "left_upper_arm", leftUpperArmPos, armRadius, "left", "upper_arm", ref comma);
        AppendAnchor(sb, "right_upper_arm", rightUpperArmPos, armRadius, "right", "upper_arm", ref comma);
        AppendAnchor(sb, "left_forearm", leftForearmPos, armRadius, "left", "forearm", ref comma);
        AppendAnchor(sb, "right_forearm", rightForearmPos, armRadius, "right", "forearm", ref comma);
        AppendAnchor(sb, "left_hand", leftHandPos, handRadius, "left", "hand", ref comma);
        AppendAnchor(sb, "right_hand", rightHandPos, handRadius, "right", "hand", ref comma);
        AppendAnchor(sb, "left_thigh", leftThighPos, legRadius, "left", "thigh", ref comma);
        AppendAnchor(sb, "right_thigh", rightThighPos, legRadius, "right", "thigh", ref comma);
        AppendAnchor(sb, "left_calf", leftCalfPos, legRadius, "left", "calf", ref comma);
        AppendAnchor(sb, "right_calf", rightCalfPos, legRadius, "right", "calf", ref comma);
        AppendAnchor(sb, "left_foot", leftFootPos, footRadius, "left", "foot", ref comma);
        AppendAnchor(sb, "right_foot", rightFootPos, footRadius, "right", "foot", ref comma);

        AppendAnchor(sb, "cheek", facePos, faceRadius, "center", "face", ref comma);
        sb.Append('}');
        return sb.ToString();
    }

    private Transform Bone(HumanBodyBones bone)
    {
        return avatarAnimator != null ? avatarAnimator.GetBoneTransform(bone) : null;
    }

    private static Vector3 PositionOrFallback(Transform bone, Vector3 fallback)
    {
        return bone != null ? bone.position : fallback;
    }

    private static Vector3 MidpointOrFallback(Transform start, Transform end, Vector3 fallback)
    {
        if (start != null && end != null)
            return Vector3.Lerp(start.position, end.position, 0.5f);
        if (start != null)
            return start.position;
        if (end != null)
            return end.position;
        return fallback;
    }

    private void AppendAnchor(StringBuilder sb, string name, Vector3 world, float radius, string side, string bodyGroup, ref bool hasPrevious)
    {
        if (hasPrevious)
            sb.Append(',');
        hasPrevious = true;

        Vector3 viewport = sourceCamera.WorldToViewportPoint(world);
        bool visible = viewport.z > 0f && viewport.x >= -0.15f && viewport.x <= 1.15f && viewport.y >= -0.15f && viewport.y <= 1.15f;

        sb.Append('"').Append(name).Append("\":{");
        sb.Append("\"x\":").Append(Format01(viewport.x)).Append(',');
        sb.Append("\"y\":").Append(Format01(1f - viewport.y)).Append(',');
        sb.Append("\"r\":").Append(radius.ToString("0.###", CultureInfo.InvariantCulture)).Append(',');
        sb.Append("\"visible\":").Append(visible ? "true" : "false").Append(',');
        sb.Append("\"side\":\"").Append(side).Append("\",");
        sb.Append("\"body_group\":\"").Append(bodyGroup).Append('"');
        sb.Append('}');
    }

    private static string Format01(float value)
    {
        return Mathf.Clamp01(value).ToString("0.###", CultureInfo.InvariantCulture);
    }
}
