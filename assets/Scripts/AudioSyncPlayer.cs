using UnityEngine;

/// <summary>
/// Plays an AudioSource and drives a FacialAnimationController from the audio clock.
/// </summary>
public sealed class AudioSyncPlayer : MonoBehaviour
{
    [Header("Playback")]
    [SerializeField] private AudioSource audioSource;
    [SerializeField] private AudioClip audioClip;
    [SerializeField] private KeyCode playKey = KeyCode.Space;
    [SerializeField] private bool playOnStart;

    [Header("Sync")]
    [SerializeField] private FacialAnimationController facialController;
    [SerializeField] private float startDelayMs;

    private bool isPlaying;
    private bool endNotified;
    private double playbackStartDspTime;
    private bool warnedMissingAudioSource;
    private bool warnedMissingController;

    /// <summary>
    /// Gets whether this sync player currently considers playback active.
    /// </summary>
    public bool IsPlaying => isPlaying;

    private void Reset()
    {
        audioSource = GetComponent<AudioSource>();
        facialController = GetComponent<FacialAnimationController>();
    }

    private void Awake()
    {
        if (audioSource == null)
        {
            audioSource = GetComponent<AudioSource>();
        }

        if (facialController == null)
        {
            facialController = GetComponent<FacialAnimationController>();
        }

        if (audioSource != null && audioClip != null)
        {
            audioSource.clip = audioClip;
        }
    }

    private void Start()
    {
        if (playOnStart)
        {
            Play();
        }
    }

    private void OnValidate()
    {
        startDelayMs = Mathf.Max(0.0f, startDelayMs);
    }

    private void Update()
    {
        if (Input.GetKeyDown(playKey))
        {
            Restart();
        }

        if (!isPlaying)
        {
            return;
        }

        if (!HasPlayableAudio())
        {
            Stop();
            return;
        }

        if (IsAudioEnded())
        {
            OnAudioEnd();
            return;
        }

        if (facialController == null)
        {
            WarnMissingControllerOnce();
            return;
        }

        float currentTimeMs = Mathf.Max(0.0f, GetCurrentTimeMs() - startDelayMs);
        facialController.Apply(currentTimeMs);
    }

    /// <summary>
    /// Starts audio playback from the beginning and resets the facial pose.
    /// </summary>
    public void Play()
    {
        if (!HasPlayableAudio())
        {
            return;
        }

        if (facialController == null)
        {
            WarnMissingControllerOnce();
        }
        else
        {
            facialController.ApplyRestPose();
        }

        if (audioSource.clip != audioClip && audioClip != null)
        {
            audioSource.clip = audioClip;
        }

        audioSource.Stop();
        audioSource.timeSamples = 0;
        audioSource.Play();

        isPlaying = true;
        endNotified = false;
        playbackStartDspTime = AudioSettings.dspTime;
    }

    /// <summary>
    /// Stops audio playback, resets the audio time, and returns the face to rest pose.
    /// </summary>
    public void Stop()
    {
        if (audioSource != null)
        {
            audioSource.Stop();

            if (audioSource.clip != null)
            {
                audioSource.timeSamples = 0;
            }
        }

        isPlaying = false;
        endNotified = true;
        playbackStartDspTime = 0.0d;

        if (facialController != null)
        {
            facialController.ApplyRestPose();
        }
    }

    /// <summary>
    /// Stops any current playback and immediately starts again from the beginning.
    /// </summary>
    public void Restart()
    {
        Stop();
        Play();
    }

    /// <summary>
    /// Gets the current audio playback time in milliseconds using timeSamples.
    /// </summary>
    /// <returns>The current audio time in milliseconds, or zero when no clip is available.</returns>
    public float GetCurrentTimeMs()
    {
        if (audioSource == null || audioSource.clip == null || audioSource.clip.frequency <= 0)
        {
            return 0.0f;
        }

        return audioSource.timeSamples / (float)audioSource.clip.frequency * 1000.0f;
    }

    /// <summary>
    /// Checks whether the current audio clip has reached its end.
    /// </summary>
    /// <returns>True when playback has ended; otherwise false.</returns>
    public bool IsAudioEnded()
    {
        if (audioSource == null || audioSource.clip == null)
        {
            return true;
        }

        if (audioSource.isPlaying)
        {
            return false;
        }

        if (endNotified)
        {
            return true;
        }

        if (!isPlaying)
        {
            return audioSource.timeSamples >= audioSource.clip.samples - 1;
        }

        double elapsedSeconds = AudioSettings.dspTime - playbackStartDspTime;
        return audioSource.timeSamples >= audioSource.clip.samples - 1 ||
               elapsedSeconds >= audioSource.clip.length;
    }

    private void OnAudioEnd()
    {
        if (endNotified)
        {
            return;
        }

        isPlaying = false;
        endNotified = true;

        if (facialController != null)
        {
            facialController.ApplyRestPose();
        }
    }

    private bool HasPlayableAudio()
    {
        if (audioSource == null)
        {
            if (!warnedMissingAudioSource)
            {
                Debug.LogWarning($"{nameof(AudioSyncPlayer)}: AudioSource is not assigned.", this);
                warnedMissingAudioSource = true;
            }

            return false;
        }

        if (audioSource.clip == null && audioClip != null)
        {
            audioSource.clip = audioClip;
        }

        if (audioSource.clip == null)
        {
            Debug.LogWarning($"{nameof(AudioSyncPlayer)}: No AudioClip is assigned.", this);
            return false;
        }

        return true;
    }

    private void WarnMissingControllerOnce()
    {
        if (warnedMissingController)
        {
            return;
        }

        Debug.LogWarning($"{nameof(AudioSyncPlayer)}: FacialAnimationController is not assigned. Audio can play, but facial animation will not update.", this);
        warnedMissingController = true;
    }
}
