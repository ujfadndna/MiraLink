using System.Collections;
using UnityEngine;

/// <summary>
/// Head and eye gaze controller for UniVRM 1.0 avatars.
/// Runs at [DefaultExecutionOrder(20000)] to apply after UniVRM's LateUpdate (11000).
/// Directly writes localRotation on head and eye bones without Animation Rigging or FinalIK.
/// Attach to M0_Controller. Assign vrm10Animator in Inspector.
/// </summary>
[DefaultExecutionOrder(20000)]
public sealed class GazeController : MonoBehaviour
{
    [Header("VRM")]
    [SerializeField] private Animator vrm10Animator;

    [Header("Gaze Targets")]
    [SerializeField] private Transform userTarget;
    [SerializeField] private Transform thinkTarget;
    [SerializeField] private Transform idleTarget;

    [Header("Head Settings")]
    [SerializeField] private float headSpeedIdle = 2f;
    [SerializeField] private float headSpeedThinking = 3f;
    [SerializeField] private float headSpeedSpeaking = 5f;
    [SerializeField] private float headYawLimit = 40f;
    [SerializeField] private float headPitchLimit = 25f;

    [Header("Eye Settings")]
    [SerializeField] private float eyeWeight = 0.5f;

    // Bone transforms
    private Transform _headBone;
    private Transform _leftEyeBone;
    private Transform _rightEyeBone;

    // State
    private string _currentState = "idle";
    private float _headSpeed;

    // Idle drift
    private Vector3 _idleDriftOffset;
    private float _idleDriftTimer;
    private float _idleDriftInterval;

    // Speaking random offset
    private Vector3 _speakingOffset;
    private float _speakingOffsetTimer;

    // Saccade
    private Quaternion _saccadeOffsetLeft = Quaternion.identity;
    private Quaternion _saccadeOffsetRight = Quaternion.identity;
    private float _saccadeTimer;
    private float _saccadeInterval;

    // Smoothed head rotation (world space)
    private Quaternion _headTargetRot;

    private void Start()
    {
        if (vrm10Animator == null)
            vrm10Animator = GetComponentInChildren<Animator>();

        if (vrm10Animator != null)
        {
            _headBone = vrm10Animator.GetBoneTransform(HumanBodyBones.Head);
            _leftEyeBone = vrm10Animator.GetBoneTransform(HumanBodyBones.LeftEye);
            _rightEyeBone = vrm10Animator.GetBoneTransform(HumanBodyBones.RightEye);
        }

        if (_headBone == null)
            Debug.LogWarning("[GazeController] Head bone not found. Assign vrm10Animator.", this);

        _headTargetRot = _headBone != null ? _headBone.rotation : Quaternion.identity;
        _headSpeed = headSpeedIdle;

        _idleDriftInterval = Random.Range(3f, 8f);
        _saccadeInterval = Random.Range(1.5f, 4f);

        var nc = FindFirstObjectByType<NetworkClient>();
        if (nc != null)
        {
            nc.OnTurnStart += (turnId, emotion, act) => SetState("speaking");
            nc.OnTurnEnd += (turnId) => SetState("idle");
            nc.OnStateChange += (state, detail) => SetState(state);
        }
        else
        {
            Debug.LogWarning("[GazeController] NetworkClient not found. State driven manually.", this);
        }
    }

    private void LateUpdate()
    {
        if (_headBone == null) return;

        UpdateIdleDrift();
        UpdateSpeakingOffset();

        Quaternion desiredWorldRot = ComputeDesiredHeadRotation();
        desiredWorldRot = ClampHeadRotation(desiredWorldRot);

        _headTargetRot = Quaternion.Slerp(_headTargetRot, desiredWorldRot, Time.deltaTime * _headSpeed);
        _headBone.rotation = _headTargetRot;

        UpdateEyes();
        UpdateSaccade();
    }

    // ── State ─────────────────────────────────────────────────

    public void SetState(string state)
    {
        if (string.IsNullOrEmpty(state)) return;
        _currentState = state.ToLowerInvariant();

        switch (_currentState)
        {
            case "speaking":
                _headSpeed = headSpeedSpeaking;
                break;
            case "thinking":
                _headSpeed = headSpeedThinking;
                break;
            default:
                _headSpeed = headSpeedIdle;
                break;
        }
    }

    public void SetUserTarget(Transform t)
    {
        userTarget = t;
    }

    // ── Head rotation ─────────────────────────────────────────

    private Quaternion ComputeDesiredHeadRotation()
    {
        Vector3 targetPos = GetCurrentTargetPosition();

        if (_headBone == null)
            return Quaternion.identity;

        Vector3 dir = (targetPos - _headBone.position).normalized;
        if (dir == Vector3.zero)
            dir = _headBone.forward;

        return Quaternion.LookRotation(dir, Vector3.up);
    }

    private Vector3 GetCurrentTargetPosition()
    {
        switch (_currentState)
        {
            case "speaking":
            {
                Vector3 base_pos = userTarget != null
                    ? userTarget.position
                    : GetCameraForwardPoint();
                return base_pos + _speakingOffset;
            }
            case "thinking":
            {
                return thinkTarget != null
                    ? thinkTarget.position
                    : GetThinkDefaultPoint();
            }
            case "disconnected":
            {
                return GetCameraForwardPoint();
            }
            default: // idle
            {
                Vector3 base_pos = idleTarget != null
                    ? idleTarget.position
                    : GetCameraForwardPoint();
                return base_pos + _idleDriftOffset;
            }
        }
    }

    private Quaternion ClampHeadRotation(Quaternion worldRot)
    {
        if (_headBone == null || _headBone.parent == null)
            return worldRot;

        // Convert to local space relative to parent
        Quaternion parentInv = Quaternion.Inverse(_headBone.parent.rotation);
        Quaternion localRot = parentInv * worldRot;

        Vector3 euler = localRot.eulerAngles;

        // Normalize angles to [-180, 180]
        float yaw = NormalizeAngle(euler.y);
        float pitch = NormalizeAngle(euler.x);

        yaw = Mathf.Clamp(yaw, -headYawLimit, headYawLimit);
        pitch = Mathf.Clamp(pitch, -headPitchLimit, headPitchLimit);

        Quaternion clampedLocal = Quaternion.Euler(pitch, yaw, 0f);
        return _headBone.parent.rotation * clampedLocal;
    }

    // ── Eyes ──────────────────────────────────────────────────

    private void UpdateEyes()
    {
        if (_leftEyeBone == null && _rightEyeBone == null) return;

        Vector3 targetPos = GetCurrentTargetPosition();

        if (_leftEyeBone != null)
        {
            Vector3 dirL = (targetPos - _leftEyeBone.position).normalized;
            if (dirL != Vector3.zero)
            {
                Quaternion eyeWorld = Quaternion.LookRotation(dirL, Vector3.up);
                Quaternion blended = Quaternion.Slerp(_headBone.rotation, eyeWorld, eyeWeight);
                Quaternion withSaccade = blended * _saccadeOffsetLeft;

                if (_leftEyeBone.parent != null)
                    _leftEyeBone.localRotation = Quaternion.Inverse(_leftEyeBone.parent.rotation) * withSaccade;
                else
                    _leftEyeBone.rotation = withSaccade;
            }
        }

        if (_rightEyeBone != null)
        {
            Vector3 dirR = (targetPos - _rightEyeBone.position).normalized;
            if (dirR != Vector3.zero)
            {
                Quaternion eyeWorld = Quaternion.LookRotation(dirR, Vector3.up);
                Quaternion blended = Quaternion.Slerp(_headBone.rotation, eyeWorld, eyeWeight);
                Quaternion withSaccade = blended * _saccadeOffsetRight;

                if (_rightEyeBone.parent != null)
                    _rightEyeBone.localRotation = Quaternion.Inverse(_rightEyeBone.parent.rotation) * withSaccade;
                else
                    _rightEyeBone.rotation = withSaccade;
            }
        }
    }

    private void UpdateSaccade()
    {
        _saccadeTimer += Time.deltaTime;
        if (_saccadeTimer < _saccadeInterval) return;

        _saccadeTimer = 0f;
        _saccadeInterval = Random.Range(1.5f, 4f);

        float angleL_y = Random.Range(-5f, 5f);
        float angleL_x = Random.Range(-3f, 3f);
        float angleR_y = Random.Range(-5f, 5f);
        float angleR_x = Random.Range(-3f, 3f);

        _saccadeOffsetLeft = Quaternion.Euler(angleL_x, angleL_y, 0f);
        _saccadeOffsetRight = Quaternion.Euler(angleR_x, angleR_y, 0f);

        StartCoroutine(ClearSaccadeAfterDelay(0.1f));
    }

    private IEnumerator ClearSaccadeAfterDelay(float delay)
    {
        yield return new WaitForSeconds(delay);
        _saccadeOffsetLeft = Quaternion.identity;
        _saccadeOffsetRight = Quaternion.identity;
    }

    // ── Idle drift ────────────────────────────────────────────

    private void UpdateIdleDrift()
    {
        if (_currentState != "idle") return;

        _idleDriftTimer += Time.deltaTime;
        if (_idleDriftTimer < _idleDriftInterval) return;

        _idleDriftTimer = 0f;
        _idleDriftInterval = Random.Range(3f, 8f);

        float xOff = Random.Range(-15f, 15f);
        float yOff = Random.Range(-10f, 10f);
        float zOff = Random.Range(-15f, 15f);

        bool doNod = Random.value < 0.3f;
        if (doNod)
            yOff -= 10f; // brief downward tilt

        _idleDriftOffset = new Vector3(xOff, yOff, zOff) * 0.05f;
    }

    // ── Speaking offset ───────────────────────────────────────

    private void UpdateSpeakingOffset()
    {
        if (_currentState != "speaking") return;

        _speakingOffsetTimer += Time.deltaTime;
        if (_speakingOffsetTimer < 2f) return;

        _speakingOffsetTimer = 0f;
        _speakingOffset = new Vector3(
            Random.Range(-0.03f, 0.03f),
            Random.Range(-0.02f, 0.02f),
            0f);
    }

    // ── Helpers ───────────────────────────────────────────────

    private static Vector3 GetCameraForwardPoint()
    {
        var cam = Camera.main;
        if (cam == null) return Vector3.forward * 2f;
        return cam.transform.position + cam.transform.forward * 2f;
    }

    private static Vector3 GetThinkDefaultPoint()
    {
        var cam = Camera.main;
        Vector3 origin = cam != null ? cam.transform.position : Vector3.zero;
        return origin + new Vector3(0.5f, 0.5f, 1f);
    }

    private static float NormalizeAngle(float angle)
    {
        while (angle > 180f) angle -= 360f;
        while (angle < -180f) angle += 360f;
        return angle;
    }
}
