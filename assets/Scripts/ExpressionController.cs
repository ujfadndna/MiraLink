using System.Collections;
using UnityEngine;
using UniVRM10;

/// <summary>
/// M3 expression layer using UniVRM 1.0 native Expression API.
/// Drives Vrm10Instance.Runtime.Expression with cross-fade and idle blink.
/// </summary>
public sealed class ExpressionController : MonoBehaviour
{
    [Header("VRM")]
    [SerializeField] private Vrm10Instance vrmInstance;

    [Header("Expression")]
    [SerializeField] private float fadeDurationSec = 0.3f;
    [SerializeField] private float expressionIntensity = 1.0f;

    [Header("Idle Blink")]
    [SerializeField] private bool enableIdleBlink = true;
    [SerializeField] private float blinkIntervalMin = 2.0f;
    [SerializeField] private float blinkIntervalMax = 5.0f;
    [SerializeField] private float blinkDurationSec = 0.12f;

    // Current emotion state
    private ExpressionPreset _currentPreset = ExpressionPreset.neutral;
    private ExpressionPreset _targetPreset  = ExpressionPreset.neutral;
    private float _currentWeight;
    private float _targetWeight;
    private float _fadeElapsed;
    private bool  _fading;

    public string CurrentEmotion => _currentPreset.ToString();

    private void Awake()
    {
        if (vrmInstance == null)
            vrmInstance = GetComponentInChildren<Vrm10Instance>();
        if (vrmInstance == null)
            vrmInstance = FindAnyObjectByType<Vrm10Instance>();
    }

    private void Start()
    {
        if (enableIdleBlink)
            StartCoroutine(BlinkRoutine());
    }

    // ── Public API ────────────────────────────────────────────

    public void SetEmotion(string emotion)
    {
        if (string.IsNullOrEmpty(emotion)) emotion = "neutral";
        emotion = emotion.Trim().ToLowerInvariant();

        // Map our emotion labels to VRM ExpressionPreset
        var preset = emotion switch
        {
            "happy"     => ExpressionPreset.happy,
            "sad"       => ExpressionPreset.sad,
            "angry"     => ExpressionPreset.angry,
            "surprised" => ExpressionPreset.surprised,
            "confident" => ExpressionPreset.relaxed,
            _           => ExpressionPreset.neutral,
        };

        if (preset == _targetPreset && !_fading) return;

        // Fade out current, then fade in new
        _currentPreset = _targetPreset;
        _currentWeight = _targetWeight;
        _targetPreset  = preset;
        _targetWeight  = preset == ExpressionPreset.neutral ? 0f : expressionIntensity;
        _fadeElapsed   = 0f;
        _fading        = true;
    }

    public void ResetToNeutral()
    {
        SetEmotion("neutral");
    }

    // ── Update ────────────────────────────────────────────────

    private void Update()
    {
        if (!_fading || vrmInstance?.Runtime?.Expression == null) return;

        _fadeElapsed += Time.deltaTime;
        float t = fadeDurationSec > 0f
            ? Mathf.SmoothStep(0f, 1f, _fadeElapsed / fadeDurationSec)
            : 1f;

        // Fade out old expression
        if (_currentPreset != ExpressionPreset.neutral)
        {
            float outWeight = Mathf.Lerp(_currentWeight, 0f, t);
            SetVrmWeight(_currentPreset, outWeight);
        }

        // Fade in new expression
        float inWeight = Mathf.Lerp(0f, _targetWeight, t);
        if (_targetPreset != ExpressionPreset.neutral)
            SetVrmWeight(_targetPreset, inWeight);
        else
            SetVrmWeight(_currentPreset, inWeight);  // fading to neutral means fading out

        if (t >= 1f)
        {
            // Clean up old
            if (_currentPreset != _targetPreset && _currentPreset != ExpressionPreset.neutral)
                SetVrmWeight(_currentPreset, 0f);

            _currentPreset = _targetPreset;
            _currentWeight = _targetWeight;
            _fading = false;
        }
    }

    // ── Idle Blink ────────────────────────────────────────────

    private IEnumerator BlinkRoutine()
    {
        while (true)
        {
            float wait = Random.Range(blinkIntervalMin, blinkIntervalMax);
            yield return new WaitForSeconds(wait);

            if (vrmInstance?.Runtime?.Expression == null) continue;

            // Close
            float elapsed = 0f;
            while (elapsed < blinkDurationSec * 0.5f)
            {
                elapsed += Time.deltaTime;
                float t = elapsed / (blinkDurationSec * 0.5f);
                SetVrmWeight(ExpressionPreset.blink, t);
                yield return null;
            }
            SetVrmWeight(ExpressionPreset.blink, 1f);

            // Open
            elapsed = 0f;
            while (elapsed < blinkDurationSec * 0.5f)
            {
                elapsed += Time.deltaTime;
                float t = elapsed / (blinkDurationSec * 0.5f);
                SetVrmWeight(ExpressionPreset.blink, 1f - t);
                yield return null;
            }
            SetVrmWeight(ExpressionPreset.blink, 0f);
        }
    }

    // ── Helper ────────────────────────────────────────────────

    private void SetVrmWeight(ExpressionPreset preset, float weight)
    {
        var key = ExpressionKey.CreateFromPreset(preset);
        vrmInstance.Runtime.Expression.SetWeight(key, Mathf.Clamp01(weight));
    }
}
