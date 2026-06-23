using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Unity.RenderStreaming;
using Unity.WebRTC;
using UnityEngine;

[DefaultExecutionOrder(-10000)]
public sealed class RenderStreamingRuntimeConfig : MonoBehaviour
{
    private const string LogPrefix = "[RenderStreamingRuntimeConfig]";

    [SerializeField] private string defaultVideoCodec = "vp8";
    [SerializeField] private int defaultStreamWidth = 540;
    [SerializeField] private int defaultStreamHeight = 960;
    [SerializeField] private float defaultStreamFps = 24f;
    [SerializeField] private uint defaultStreamBitrateMin = 800;
    [SerializeField] private uint defaultStreamBitrateMax = 1800;
    [SerializeField] private bool limitApplicationFrameRate = true;
    [SerializeField] private bool startSignalingAfterConfigure = true;
    [SerializeField] private VideoStreamSender[] videoStreamSenders;
    [SerializeField] private SignalingManager[] signalingManagers;

    private RuntimeConfig _config;
    private bool _configured;

    private void Awake()
    {
        _config = RuntimeConfig.FromCommandLine(
            defaultVideoCodec,
            defaultStreamWidth,
            defaultStreamHeight,
            defaultStreamFps,
            defaultStreamBitrateMin,
            defaultStreamBitrateMax);

        ConfigureSignalingManagers();
        ConfigureApplicationFrameRate();
        ConfigureVideoStreamSenders();
        _configured = true;
    }

    private void Start()
    {
        if (!startSignalingAfterConfigure)
            return;

        if (!_configured)
            ConfigureVideoStreamSenders();

        foreach (var manager in ResolveSignalingManagers())
        {
            if (manager == null || manager.Running)
                continue;

            if (_config.HasIceConfigOverride)
                manager.Run(_config.CreateRtcConfiguration());
            else
                manager.Run();
            Debug.Log($"{LogPrefix} SignalingManager started");
        }
    }

    private void ConfigureSignalingManagers()
    {
        foreach (var manager in ResolveSignalingManagers())
        {
            if (manager == null)
                continue;

            manager.evaluateCommandlineArguments = true;
            if (startSignalingAfterConfigure)
                manager.runOnAwake = false;
        }
    }

    private void ConfigureApplicationFrameRate()
    {
        if (!limitApplicationFrameRate)
            return;

        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = Mathf.Max(1, Mathf.CeilToInt(_config.StreamFps));
        Debug.Log($"{LogPrefix} targetFrameRate={Application.targetFrameRate} vSyncCount={QualitySettings.vSyncCount}");
    }

    private void ConfigureVideoStreamSenders()
    {
        var senders = ResolveVideoStreamSenders();
        if (senders.Length == 0)
        {
            Debug.LogWarning($"{LogPrefix} no VideoStreamSender found");
            return;
        }

        var codec = ResolveCodec(_config.VideoCodec);
        foreach (var sender in senders)
        {
            if (sender == null)
                continue;

            if (_config.VideoCodecMode != VideoCodecMode.Default)
                sender.SetCodec(codec);
            sender.SetTextureSize(new Vector2Int(_config.StreamWidth, _config.StreamHeight));
            sender.SetFrameRate(_config.StreamFps);
            sender.SetBitrate(_config.StreamBitrateMin, _config.StreamBitrateMax);
        }

        Debug.Log($"{LogPrefix} videoCodec={_config.CodecLogName}");
        Debug.Log($"{LogPrefix} stream={_config.StreamWidth}x{_config.StreamHeight} fps={FormatFps(_config.StreamFps)} bitrate={_config.StreamBitrateMin}-{_config.StreamBitrateMax}");
        Debug.Log($"{LogPrefix} ice={_config.IceConfigLogName}");
    }

    private VideoCodecInfo ResolveCodec(string codecName)
    {
        if (_config.VideoCodecMode == VideoCodecMode.Default)
            return null;

        var codecs = VideoStreamSender.GetAvailableCodecs().ToArray();
        var expectedMimeType = _config.VideoCodecMode == VideoCodecMode.VP8 ? "video/VP8" : "video/H264";
        var codec = codecs.FirstOrDefault(candidate =>
            string.Equals(candidate.mimeType, expectedMimeType, StringComparison.OrdinalIgnoreCase));

        if (codec != null)
            return codec;

        var available = string.Join(", ", codecs.Select(candidate => candidate.mimeType));
        throw new InvalidOperationException($"{LogPrefix} requested videoCodec={codecName} but {expectedMimeType} is unavailable. Available codecs: {available}");
    }

    private VideoStreamSender[] ResolveVideoStreamSenders()
    {
        if (videoStreamSenders != null && videoStreamSenders.Length > 0)
            return videoStreamSenders.Where(sender => sender != null).ToArray();

        return FindObjectsOfType<VideoStreamSender>(true);
    }

    private SignalingManager[] ResolveSignalingManagers()
    {
        if (signalingManagers != null && signalingManagers.Length > 0)
            return signalingManagers.Where(manager => manager != null).ToArray();

        return FindObjectsOfType<SignalingManager>(true);
    }

    private static string FormatFps(float fps)
    {
        return Mathf.Approximately(fps, Mathf.Round(fps))
            ? Mathf.RoundToInt(fps).ToString(CultureInfo.InvariantCulture)
            : fps.ToString("0.###", CultureInfo.InvariantCulture);
    }

    private enum VideoCodecMode
    {
        Default,
        VP8,
        H264,
    }

    private readonly struct RuntimeConfig
    {
        public RuntimeConfig(
            VideoCodecMode videoCodecMode,
            string videoCodec,
            int streamWidth,
            int streamHeight,
            float streamFps,
            uint streamBitrateMin,
            uint streamBitrateMax,
            RTCIceTransportPolicy? iceTransportPolicy,
            string[] iceServerUrls,
            string iceServerUsername,
            string iceServerCredential,
            RTCIceCredentialType iceServerCredentialType)
        {
            VideoCodecMode = videoCodecMode;
            VideoCodec = videoCodec;
            StreamWidth = streamWidth;
            StreamHeight = streamHeight;
            StreamFps = streamFps;
            StreamBitrateMin = streamBitrateMin;
            StreamBitrateMax = streamBitrateMax;
            IceTransportPolicy = iceTransportPolicy;
            IceServerUrls = iceServerUrls ?? Array.Empty<string>();
            IceServerUsername = iceServerUsername;
            IceServerCredential = iceServerCredential;
            IceServerCredentialType = iceServerCredentialType;
        }

        public VideoCodecMode VideoCodecMode { get; }
        public string VideoCodec { get; }
        public int StreamWidth { get; }
        public int StreamHeight { get; }
        public float StreamFps { get; }
        public uint StreamBitrateMin { get; }
        public uint StreamBitrateMax { get; }
        public RTCIceTransportPolicy? IceTransportPolicy { get; }
        public string[] IceServerUrls { get; }
        public string IceServerUsername { get; }
        public string IceServerCredential { get; }
        public RTCIceCredentialType IceServerCredentialType { get; }
        public bool HasIceConfigOverride => IceTransportPolicy.HasValue || IceServerUrls.Length > 0;

        public string CodecLogName
        {
            get
            {
                switch (VideoCodecMode)
                {
                    case VideoCodecMode.VP8:
                        return "VP8";
                    case VideoCodecMode.H264:
                        return "H264";
                    default:
                        return "DEFAULT";
                }
            }
        }

        public string IceConfigLogName
        {
            get
            {
                if (!HasIceConfigOverride)
                    return "default";

                var policy = IceTransportPolicy.HasValue ? IceTransportPolicy.Value.ToString() : "default";
                var urls = IceServerUrls.Length == 0 ? "none" : string.Join(",", IceServerUrls);
                var username = string.IsNullOrEmpty(IceServerUsername) ? "empty" : "set";
                var credentialLength = string.IsNullOrEmpty(IceServerCredential) ? 0 : IceServerCredential.Length;
                return $"policy={policy}; urls=[{urls}]; user={username}; credType={IceServerCredentialType}; credLen={credentialLength}";
            }
        }

        public RTCConfiguration CreateRtcConfiguration()
        {
            var config = new RTCConfiguration();
            if (IceTransportPolicy.HasValue)
                config.iceTransportPolicy = IceTransportPolicy.Value;

            if (IceServerUrls.Length > 0)
            {
                config.iceServers = new[]
                {
                    new RTCIceServer
                    {
                        urls = IceServerUrls,
                        username = IceServerUsername,
                        credential = IceServerCredential,
                        credentialType = IceServerCredentialType,
                    }
                };
            }

            return config;
        }

        public static RuntimeConfig FromCommandLine(
            string defaultVideoCodec,
            int defaultStreamWidth,
            int defaultStreamHeight,
            float defaultStreamFps,
            uint defaultStreamBitrateMin,
            uint defaultStreamBitrateMax)
        {
            var args = Environment.GetCommandLineArgs();
            var codec = GetArgument(args, "-videoCodec") ?? defaultVideoCodec;
            var mode = ParseCodecMode(codec);
            var width = ParsePositiveInt(GetArgument(args, "-streamWidth"), "-streamWidth", defaultStreamWidth);
            var height = ParsePositiveInt(GetArgument(args, "-streamHeight"), "-streamHeight", defaultStreamHeight);
            var fps = ParsePositiveFloat(GetArgument(args, "-streamFps"), "-streamFps", defaultStreamFps);
            var bitrateMin = ParseUInt(GetArgument(args, "-streamBitrateMin"), "-streamBitrateMin", defaultStreamBitrateMin);
            var bitrateMax = ParseUInt(GetArgument(args, "-streamBitrateMax"), "-streamBitrateMax", defaultStreamBitrateMax);
            var iceTransportPolicy = ParseIceTransportPolicy(
                GetArgument(args, "-iceTransportPolicy") ?? GetEnvironmentValue("ICE_TRANSPORT_POLICY"));
            var iceServerUrls = GetIceServerUrls(args);
            var iceServerUsername = GetArgument(args, "-iceServerUsername") ?? GetEnvironmentValue("TURN_USERNAME");
            var iceServerCredential = GetArgument(args, "-iceServerCredential") ?? GetEnvironmentValue("TURN_CREDENTIAL");
            var iceServerCredentialType = ParseIceCredentialType(GetArgument(args, "-iceServerCredentialType"));

            if (bitrateMin > bitrateMax)
                throw new ArgumentException($"{LogPrefix} -streamBitrateMax must be greater than or equal to -streamBitrateMin.");

            return new RuntimeConfig(
                mode,
                codec,
                width,
                height,
                fps,
                bitrateMin,
                bitrateMax,
                iceTransportPolicy,
                iceServerUrls,
                iceServerUsername,
                iceServerCredential,
                iceServerCredentialType);
        }

        private static string GetArgument(string[] args, string key)
        {
            for (var index = 0; index < args.Length - 1; index++)
            {
                if (string.Equals(args[index], key, StringComparison.OrdinalIgnoreCase))
                    return args[index + 1];
            }

            return null;
        }

        private static string[] GetArguments(string[] args, string key)
        {
            var values = new List<string>();
            for (var index = 0; index < args.Length - 1; index++)
            {
                if (!string.Equals(args[index], key, StringComparison.OrdinalIgnoreCase))
                    continue;

                foreach (var part in SplitCsv(args[index + 1]))
                    values.Add(part);
            }

            return values.ToArray();
        }

        private static string[] GetIceServerUrls(string[] args)
        {
            var urls = GetArguments(args, "-iceServerUrl").ToList();
            if (urls.Count == 0)
                urls.AddRange(SplitCsv(GetEnvironmentValue("TURN_URLS")));

            return urls.Where(value => !string.IsNullOrWhiteSpace(value)).Distinct().ToArray();
        }

        private static IEnumerable<string> SplitCsv(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
                yield break;

            foreach (var item in raw.Split(','))
            {
                var value = item.Trim();
                if (!string.IsNullOrEmpty(value))
                    yield return value;
            }
        }

        private static string GetEnvironmentValue(string key)
        {
            var value = Environment.GetEnvironmentVariable(key);
            return string.IsNullOrWhiteSpace(value) ? null : value.Trim();
        }

        private static VideoCodecMode ParseCodecMode(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw) || string.Equals(raw, "default", StringComparison.OrdinalIgnoreCase))
                return VideoCodecMode.Default;
            if (string.Equals(raw, "vp8", StringComparison.OrdinalIgnoreCase))
                return VideoCodecMode.VP8;
            if (string.Equals(raw, "h264", StringComparison.OrdinalIgnoreCase))
                return VideoCodecMode.H264;

            throw new ArgumentException($"{LogPrefix} unsupported -videoCodec value: {raw}. Use vp8, h264, or default.");
        }

        private static RTCIceTransportPolicy? ParseIceTransportPolicy(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
                return null;
            if (string.Equals(raw, "relay", StringComparison.OrdinalIgnoreCase))
                return RTCIceTransportPolicy.Relay;
            if (string.Equals(raw, "all", StringComparison.OrdinalIgnoreCase))
                return RTCIceTransportPolicy.All;

            throw new ArgumentException($"{LogPrefix} unsupported -iceTransportPolicy value: {raw}. Use relay or all.");
        }

        private static RTCIceCredentialType ParseIceCredentialType(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw) || string.Equals(raw, "password", StringComparison.OrdinalIgnoreCase))
                return RTCIceCredentialType.Password;
            if (string.Equals(raw, "oauth", StringComparison.OrdinalIgnoreCase))
                return RTCIceCredentialType.OAuth;

            throw new ArgumentException($"{LogPrefix} unsupported -iceServerCredentialType value: {raw}. Use password or oauth.");
        }

        private static int ParsePositiveInt(string raw, string name, int fallback)
        {
            if (string.IsNullOrWhiteSpace(raw))
                return fallback;
            if (int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) && value > 0)
                return value;

            throw new ArgumentException($"{LogPrefix} {name} must be a positive integer.");
        }

        private static float ParsePositiveFloat(string raw, string name, float fallback)
        {
            if (string.IsNullOrWhiteSpace(raw))
                return fallback;
            if (float.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) && value > 0f)
                return value;

            throw new ArgumentException($"{LogPrefix} {name} must be a positive number.");
        }

        private static uint ParseUInt(string raw, string name, uint fallback)
        {
            if (string.IsNullOrWhiteSpace(raw))
                return fallback;
            if (uint.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value))
                return value;

            throw new ArgumentException($"{LogPrefix} {name} must be an unsigned integer.");
        }
    }
}
