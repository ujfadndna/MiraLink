using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Streams PCM audio chunks received from the backend via a ring buffer
/// and plays them through an AudioSource in real-time.
/// </summary>
public sealed class StreamingAudioPlayer : MonoBehaviour
{
    [Header("Playback")]
    [SerializeField] private AudioSource audioSource;
    [SerializeField] private int bufferLengthSec = 60;
    [SerializeField] private int maxBufferLengthSec = 120;
    [SerializeField] private float startThresholdSec = 0.2f;

    [Header("Sync")]
    [SerializeField] private FacialAnimationController facialController;
    [SerializeField] private float audioClockStallGraceMs = 120.0f;
    [SerializeField] private float turnEndHoldMs = 180.0f;

    private AudioClip _streamClip;
    private int _sampleRate = 24000;
    private int _writePos;
    private int _samplesWritten;
    private float _expectedDurationMs;
    private bool _isPlaying;
    private bool _turnActive;
    private bool _allChunksReceived;
    private readonly Queue<AnimPacket> _animQueue = new Queue<AnimPacket>();
    private Dictionary<string, float> _lastAppliedBlendshapes;
    private float _turnClockStartRealtime;
    private float _playbackClockStartRealtime;
    private int _lastAudioClockSamples;
    private float _lastAudioClockAdvanceRealtime;
    private float _logicalTimeMs;
    private int _turnPacketCount;
    private int _turnNonEmptyPacketCount;
    private bool _loggedFirstPacketKeys;
    private bool _loggedFirstAppliedPacket;
    private bool _loggedFallbackClock;

    private struct AnimPacket
    {
        public float startMs, endMs;
        public Dictionary<string, float> blendshapes;
    }

    /// <summary>Gets whether audio is currently playing.</summary>
    public bool IsPlaying => _isPlaying;

    public event Action PlaybackStarted;

    /// <summary>Gets the current playback position in milliseconds.</summary>
    public float CurrentTimeMs
    {
        get
        {
            return _logicalTimeMs;
        }
    }

    private void Awake()
    {
        if (audioSource == null)
            audioSource = GetComponent<AudioSource>();
    }

    /// <summary>Called when a new turn begins. Resets the buffer.</summary>
    public void BeginTurn()
    {
        BeginTurn(0f, 0, 0);
    }

    /// <summary>Called when a new turn begins. Resets the buffer and preallocates if duration metadata is available.</summary>
    public void BeginTurn(float expectedDurationMs, int sampleRate, int totalSamples)
    {
        StopPlayback();
        if (sampleRate > 0)
            _sampleRate = sampleRate;

        _writePos = 0;
        _samplesWritten = 0;
        _expectedDurationMs = Mathf.Max(0.0f, expectedDurationMs);
        _turnActive = true;
        _allChunksReceived = false;
        _animQueue.Clear();
        _lastAppliedBlendshapes = null;
        _turnClockStartRealtime = Time.realtimeSinceStartup;
        _playbackClockStartRealtime = 0.0f;
        _lastAudioClockSamples = 0;
        _lastAudioClockAdvanceRealtime = _turnClockStartRealtime;
        _logicalTimeMs = 0.0f;
        _turnPacketCount = 0;
        _turnNonEmptyPacketCount = 0;
        _loggedFirstPacketKeys = false;
        _loggedFirstAppliedPacket = false;
        _loggedFallbackClock = false;
        facialController?.ResetStreamWeights();

        if (_sampleRate > 0)
            InitializeClip(expectedDurationMs, totalSamples);

        Debug.Log($"[StreamingAudioPlayer] Turn begin expectedDurationMs={_expectedDurationMs:0.0} sampleRate={_sampleRate} totalSamples={totalSamples}");
    }

    /// <summary>Enqueues a PCM audio chunk (16-bit signed LE) into the ring buffer.</summary>
    public void EnqueueAudioChunk(byte[] pcmData, int sampleRate)
    {
        if (pcmData == null || pcmData.Length == 0) return;

        // Initialize clip on first chunk if sample rate changed
        if (_streamClip == null || _sampleRate != sampleRate)
        {
            _sampleRate = sampleRate;
            InitializeClip(0f, 0);
        }

        // Convert PCM s16le to float
        int sampleCount = pcmData.Length / 2;
        var samples = new float[sampleCount];
        for (int i = 0; i < sampleCount; i++)
        {
            short s = (short)(pcmData[i * 2] | (pcmData[i * 2 + 1] << 8));
            samples[i] = s / 32768f;
        }

        // Write to clip — clamp to buffer size to avoid SetData out-of-bounds
        int clipLength = _streamClip.samples;
        if (_writePos >= clipLength) return;

        int writeCount = Mathf.Min(sampleCount, clipLength - _writePos);
        if (writeCount < sampleCount)
        {
            var trimmed = new float[writeCount];
            Array.Copy(samples, trimmed, writeCount);
            samples = trimmed;
        }

        _streamClip.SetData(samples, _writePos);
        _writePos += writeCount;
        _samplesWritten += writeCount;

        // Start playback once we have enough buffered
        if (!_isPlaying && _samplesWritten >= _sampleRate * startThresholdSec)
        {
            StartPlayback();
        }
    }

    public void EnqueueAnimationPacket(float startMs, float endMs, Dictionary<string, float> blendshapes)
    {
        if (blendshapes == null) return;
        _turnPacketCount++;
        if (blendshapes.Count > 0)
        {
            _turnNonEmptyPacketCount++;
            if (!_loggedFirstPacketKeys)
            {
                _loggedFirstPacketKeys = true;
                Debug.Log($"[StreamingAudioPlayer] First non-empty animation.packet keys={FirstKeys(blendshapes, 6)}");
            }
        }

        if (!_loggedFirstAppliedPacket && facialController != null && HasPositiveWeight(blendshapes))
        {
            _lastAppliedBlendshapes = blendshapes;
            facialController.ApplyStreamWeights(blendshapes);
            _loggedFirstAppliedPacket = true;
            Debug.Log($"[StreamingAudioPlayer] Applied first positive animation.packet on receive start={startMs:0.0}ms keys={FirstKeys(blendshapes, 6)}");
        }

        _animQueue.Enqueue(new AnimPacket { startMs = startMs, endMs = endMs, blendshapes = blendshapes });
    }

    /// <summary>Called when all audio chunks for the turn have been received.</summary>
    public void EndTurn()
    {
        _allChunksReceived = true;
        _turnActive = false;
        Debug.Log($"[StreamingAudioPlayer] Turn end packets={_turnPacketCount} nonEmpty={_turnNonEmptyPacketCount} samplesWritten={_samplesWritten} durationMs={TurnDurationLimitMs():0.0}");
    }

    private void Update()
    {
        if (!_isPlaying && !_turnActive && _animQueue.Count == 0 && _lastAppliedBlendshapes == null)
            return;

        _logicalTimeMs = ComputeLogicalTimeMs();

        // Check if playback has caught up with written data
        if (_allChunksReceived && HasReachedTurnEnd(_logicalTimeMs))
        {
            StopPlayback();
            facialController?.ResetStreamWeights();
            _animQueue.Clear();
            _lastAppliedBlendshapes = null;
            return;
        }

        // Drive blendshapes in sync with audio playback time
        float nowMs = _logicalTimeMs;
        AnimPacket? currentPacket = null;
        while (_animQueue.Count > 0)
        {
            var front = _animQueue.Peek();
            if (nowMs < front.startMs)
                break;

            _animQueue.Dequeue();
            if (nowMs <= front.endMs + 20.0f)
            {
                currentPacket = front;
            }
        }

        if (currentPacket.HasValue && facialController != null)
        {
            _lastAppliedBlendshapes = currentPacket.Value.blendshapes;
            facialController.ApplyStreamWeights(currentPacket.Value.blendshapes);
            if (!_loggedFirstAppliedPacket && HasPositiveWeight(currentPacket.Value.blendshapes))
            {
                _loggedFirstAppliedPacket = true;
                Debug.Log($"[StreamingAudioPlayer] Applied first animation.packet at {nowMs:0.0}ms keys={FirstKeys(currentPacket.Value.blendshapes, 6)}");
            }
        }
        else if (_lastAppliedBlendshapes != null && _animQueue.Count == 0 && _allChunksReceived && HasReachedTurnEnd(nowMs))
        {
            facialController?.ResetStreamWeights();
            _lastAppliedBlendshapes = null;
        }
    }

    private void InitializeClip(float expectedDurationMs, int expectedTotalSamples)
    {
        StopPlayback();
        int clipSamples = CalculateClipSamples(expectedDurationMs, expectedTotalSamples);
        _streamClip = AudioClip.Create("StreamClip", clipSamples, 1, _sampleRate, false);
        audioSource.clip = _streamClip;
        audioSource.loop = false;
        _writePos = 0;
        _samplesWritten = 0;
    }

    private int CalculateClipSamples(float expectedDurationMs, int expectedTotalSamples)
    {
        int fallbackSeconds = Mathf.Max(1, bufferLengthSec);
        int capSeconds = Mathf.Max(fallbackSeconds, maxBufferLengthSec);

        if (expectedTotalSamples > 0)
        {
            float expectedSeconds = expectedTotalSamples / (float)Mathf.Max(1, _sampleRate);
            int seconds = Mathf.Clamp(Mathf.CeilToInt(expectedSeconds + 2f), 1, capSeconds);
            return Mathf.Max(1, seconds * _sampleRate);
        }

        if (expectedDurationMs > 0f)
        {
            float expectedSeconds = expectedDurationMs / 1000f;
            int seconds = Mathf.Clamp(Mathf.CeilToInt(expectedSeconds + 2f), 1, capSeconds);
            return Mathf.Max(1, seconds * _sampleRate);
        }

        return Mathf.Max(1, fallbackSeconds * _sampleRate);
    }

    private void StartPlayback()
    {
        if (_streamClip == null) return;
        audioSource.timeSamples = 0;
        audioSource.Play();
        _isPlaying = true;
        _playbackClockStartRealtime = Time.realtimeSinceStartup;
        _lastAudioClockSamples = 0;
        _lastAudioClockAdvanceRealtime = _playbackClockStartRealtime;
        PlaybackStarted?.Invoke();
    }

    public void StopPlayback()
    {
        if (audioSource != null && audioSource.isPlaying)
            audioSource.Stop();
        _isPlaying = false;
    }

    public void StopAndClear()
    {
        StopPlayback();
        _animQueue.Clear();
        _writePos = 0;
        _samplesWritten = 0;
        _expectedDurationMs = 0.0f;
        _turnActive = false;
        _allChunksReceived = false;
        _lastAppliedBlendshapes = null;
        _logicalTimeMs = 0.0f;
        facialController?.ResetStreamWeights();
    }

    private float ComputeLogicalTimeMs()
    {
        float realtimeNow = Time.realtimeSinceStartup;
        float turnRealtimeMs = Mathf.Max(0.0f, (realtimeNow - _turnClockStartRealtime) * 1000.0f);

        if (audioSource == null || !_isPlaying || _sampleRate <= 0)
        {
            return ClampLogicalTime(turnRealtimeMs);
        }

        int samples = Mathf.Max(0, audioSource.timeSamples);
        if (samples > _lastAudioClockSamples)
        {
            _lastAudioClockSamples = samples;
            _lastAudioClockAdvanceRealtime = realtimeNow;
        }

        float audioMs = samples / (float)_sampleRate * 1000.0f;
        float stalledMs = (realtimeNow - _lastAudioClockAdvanceRealtime) * 1000.0f;
        if (samples <= 0 || stalledMs > audioClockStallGraceMs)
        {
            float baseRealtime = _playbackClockStartRealtime > 0.0f ? _playbackClockStartRealtime : _turnClockStartRealtime;
            float fallbackMs = Mathf.Max(audioMs, (realtimeNow - baseRealtime) * 1000.0f);
            if (!_loggedFallbackClock && fallbackMs > audioClockStallGraceMs)
            {
                _loggedFallbackClock = true;
                Debug.LogWarning($"[StreamingAudioPlayer] AudioSource clock stalled at samples={samples}; using realtime fallback.");
            }
            return ClampLogicalTime(fallbackMs);
        }

        return ClampLogicalTime(audioMs);
    }

    private float ClampLogicalTime(float valueMs)
    {
        float limit = TurnDurationLimitMs() + turnEndHoldMs;
        return limit > 0.0f ? Mathf.Min(valueMs, limit) : Mathf.Max(0.0f, valueMs);
    }

    private float TurnDurationLimitMs()
    {
        float samplesMs = _sampleRate > 0 && _samplesWritten > 0 ? _samplesWritten / (float)_sampleRate * 1000.0f : 0.0f;
        return Mathf.Max(_expectedDurationMs, samplesMs);
    }

    private bool HasReachedTurnEnd(float nowMs)
    {
        if (!_allChunksReceived)
            return false;

        float limitMs = TurnDurationLimitMs();
        if (limitMs <= 0.0f)
            return _animQueue.Count == 0;

        return nowMs >= limitMs + turnEndHoldMs;
    }

    private static string FirstKeys(Dictionary<string, float> blendshapes, int maxCount)
    {
        if (blendshapes == null || blendshapes.Count == 0)
            return "<empty>";

        var keys = new List<string>(Mathf.Max(1, maxCount));
        foreach (string key in blendshapes.Keys)
        {
            keys.Add(key);
            if (keys.Count >= maxCount)
                break;
        }

        return string.Join(",", keys);
    }

    private static bool HasPositiveWeight(Dictionary<string, float> blendshapes)
    {
        if (blendshapes == null)
            return false;

        foreach (float value in blendshapes.Values)
        {
            if (value > 0.001f)
                return true;
        }

        return false;
    }
}
