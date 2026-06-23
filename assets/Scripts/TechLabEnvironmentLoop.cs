using UnityEngine;

/// <summary>
/// Lightweight ambient motion for the MainScene tech lab environment.
/// This component is intentionally self-contained and does not read sensor or network events.
/// </summary>
public sealed class TechLabEnvironmentLoop : MonoBehaviour
{
    [System.Serializable]
    private struct DataStrip
    {
        public Transform strip;
        public Vector3 baseLocalPosition;
        public Vector3 baseLocalScale;
        public float phase;
        public float speed;
        public float travel;
        public float minScaleY;
        public float maxScaleY;
    }

    [System.Serializable]
    private struct BreathingLight
    {
        public Renderer renderer;
        public Light linkedLight;
        public Color color;
        public float baseIntensity;
        public float pulseIntensity;
        public float phase;
        public float speed;
    }

    [System.Serializable]
    private struct FloatingModule
    {
        public Transform module;
        public Vector3 baseLocalPosition;
        public Vector3 baseLocalEuler;
        public float verticalAmplitude;
        public float verticalSpeed;
        public float rotationSpeed;
        public float phase;
    }

    [SerializeField] private DataStrip[] dataStrips = new DataStrip[0];
    [SerializeField] private BreathingLight[] breathingLights = new BreathingLight[0];
    [SerializeField] private FloatingModule[] floatingModules = new FloatingModule[0];
    [SerializeField] private ParticleSystem[] ambientParticles = new ParticleSystem[0];

    private MaterialPropertyBlock _propertyBlock;
    private static readonly int EmissionColorId = Shader.PropertyToID("_EmissionColor");

    private void Awake()
    {
        _propertyBlock = new MaterialPropertyBlock();
        EnsureParticlesPlaying();
    }

    private void OnEnable()
    {
        EnsureParticlesPlaying();
    }

    private void Update()
    {
        float t = Time.time;
        AnimateDataStrips(t);
        AnimateBreathingLights(t);
        AnimateFloatingModules(t);
        EnsureParticlesPlaying();
    }

    private void AnimateDataStrips(float time)
    {
        for (int i = 0; i < dataStrips.Length; i++)
        {
            var item = dataStrips[i];
            if (item.strip == null)
                continue;

            float wave = Mathf.PingPong(time * Mathf.Max(0.01f, item.speed) + item.phase, 1f);
            var localPosition = item.baseLocalPosition;
            localPosition.y += Mathf.Lerp(-item.travel, item.travel, wave);
            item.strip.localPosition = localPosition;

            var localScale = item.baseLocalScale;
            localScale.y = Mathf.Lerp(item.minScaleY, item.maxScaleY, 0.35f + 0.65f * wave);
            item.strip.localScale = localScale;
        }
    }

    private void AnimateBreathingLights(float time)
    {
        for (int i = 0; i < breathingLights.Length; i++)
        {
            var item = breathingLights[i];
            float pulse = 0.5f + 0.5f * Mathf.Sin(time * Mathf.Max(0.01f, item.speed) + item.phase);
            float intensity = item.baseIntensity + item.pulseIntensity * pulse;

            if (item.renderer != null)
            {
                item.renderer.GetPropertyBlock(_propertyBlock);
                _propertyBlock.SetColor(EmissionColorId, item.color * intensity);
                item.renderer.SetPropertyBlock(_propertyBlock);
            }

            if (item.linkedLight != null)
            {
                item.linkedLight.color = item.color;
                item.linkedLight.intensity = intensity;
            }
        }
    }

    private void AnimateFloatingModules(float time)
    {
        for (int i = 0; i < floatingModules.Length; i++)
        {
            var item = floatingModules[i];
            if (item.module == null)
                continue;

            float bob = Mathf.Sin(time * Mathf.Max(0.01f, item.verticalSpeed) + item.phase);
            item.module.localPosition = item.baseLocalPosition + Vector3.up * (bob * item.verticalAmplitude);
            var euler = item.baseLocalEuler;
            euler.y += time * item.rotationSpeed;
            item.module.localRotation = Quaternion.Euler(euler);
        }
    }

    private void EnsureParticlesPlaying()
    {
        for (int i = 0; i < ambientParticles.Length; i++)
        {
            var particles = ambientParticles[i];
            if (particles != null && !particles.isPlaying)
                particles.Play();
        }
    }
}
