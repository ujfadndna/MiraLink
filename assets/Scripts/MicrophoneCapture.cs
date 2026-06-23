using System;
using System.Text;
using UnityEngine;

/// <summary>
/// Captures microphone input, detects silence, and sends PCM audio to NetworkClient.
/// Hold the configured key to record; release to stop and send.
/// Silence-based auto-stop is also supported: if amplitude stays below threshold
/// for silenceDurationSec seconds the recording stops automatically.
/// </summary>
public sealed class MicrophoneCapture : MonoBehaviour
{
    [Header("References")]
    [SerializeField] private NetworkClient networkClient;

    [Header("Recording")]
    [SerializeField] private KeyCode recordKey = KeyCode.Space;
    [SerializeField] private int sampleRate = 16000;
    [SerializeField] private float silenceDurationSec = 1.0f;
    [SerializeField] private float minRecordSec = 0.5f;
    [SerializeField] private float silenceAmplitudeThreshold = 0.01f;

    private enum CaptureState { Idle, Recording, Processing }
    private CaptureState _state = CaptureState.Idle;

    private AudioClip _clip;
    private float _recordStartTime;
    private float _silenceStartTime;
    private bool _silenceDetected;

    private const int MaxRecordSec = 30;

    private void Update()
    {
        switch (_state)
        {
            case CaptureState.Idle:
                if (Input.GetKeyDown(recordKey))
                    StartRecording();
                break;

            case CaptureState.Recording:
                if (Input.GetKeyUp(recordKey))
                {
                    StopAndSend();
                    break;
                }
                CheckSilence();
                break;

            case CaptureState.Processing:
                // Wait for asr.result callback before returning to Idle.
                break;
        }
    }

    private void StartRecording()
    {
        if (Microphone.devices.Length == 0)
        {
            Debug.LogWarning("[MicrophoneCapture] No microphone found.");
            return;
        }

        _clip = Microphone.Start(null, false, MaxRecordSec, sampleRate);
        _recordStartTime = Time.time;
        _silenceStartTime = Time.time;
        _silenceDetected = false;
        _state = CaptureState.Recording;
        Debug.Log("[MicrophoneCapture] Recording started.");
    }

    private void CheckSilence()
    {
        int pos = Microphone.GetPosition(null);
        if (pos <= 0) return;

        float[] samples = new float[pos];
        _clip.GetData(samples, 0);

        float peak = 0f;
        int checkStart = Mathf.Max(0, samples.Length - sampleRate / 10); // last 100ms
        for (int i = checkStart; i < samples.Length; i++)
        {
            float abs = Mathf.Abs(samples[i]);
            if (abs > peak) peak = abs;
        }

        if (peak < silenceAmplitudeThreshold)
        {
            if (!_silenceDetected)
            {
                _silenceDetected = true;
                _silenceStartTime = Time.time;
            }
            else if (Time.time - _silenceStartTime >= silenceDurationSec)
            {
                float elapsed = Time.time - _recordStartTime;
                if (elapsed >= minRecordSec)
                {
                    Debug.Log("[MicrophoneCapture] Silence detected — auto stopping.");
                    StopAndSend();
                }
            }
        }
        else
        {
            _silenceDetected = false;
        }
    }

    private void StopAndSend()
    {
        float elapsed = Time.time - _recordStartTime;
        int recordedSamples = Mathf.Min(Microphone.GetPosition(null), (int)(elapsed * sampleRate));
        Microphone.End(null);

        if (recordedSamples <= 0 || elapsed < minRecordSec)
        {
            Debug.Log("[MicrophoneCapture] Recording too short, discarded.");
            _state = CaptureState.Idle;
            return;
        }

        float[] floatSamples = new float[recordedSamples];
        _clip.GetData(floatSamples, 0);

        byte[] pcmBytes = FloatToPcmInt16(floatSamples);
        _state = CaptureState.Processing;
        Debug.Log($"[MicrophoneCapture] Sending {recordedSamples} samples ({elapsed:F2}s).");

        if (networkClient != null)
            networkClient.SendAudio(pcmBytes, sampleRate);
        else
            Debug.LogWarning("[MicrophoneCapture] NetworkClient reference is null.");
    }

    /// <summary>Called by NetworkClient when asr.result arrives, returning to Idle.</summary>
    public void OnAsrResultReceived()
    {
        if (_state == CaptureState.Processing)
            _state = CaptureState.Idle;
    }

    private static byte[] FloatToPcmInt16(float[] samples)
    {
        byte[] bytes = new byte[samples.Length * 2];
        for (int i = 0; i < samples.Length; i++)
        {
            float clamped = Mathf.Clamp(samples[i], -1f, 1f);
            short s16 = (short)(clamped * 32767);
            bytes[i * 2] = (byte)(s16 & 0xFF);
            bytes[i * 2 + 1] = (byte)((s16 >> 8) & 0xFF);
        }
        return bytes;
    }

    private void OnGUI()
    {
        if (_state == CaptureState.Idle) return;

        string label = _state == CaptureState.Recording ? "[RECORDING]" : "[PROCESSING]";
        string color = _state == CaptureState.Recording ? "#f44" : "#ff4";
        GUI.Label(new Rect(10, Screen.height - 30, 200, 25),
            $"<color={color}><b>{label}</b></color>");
    }
}
