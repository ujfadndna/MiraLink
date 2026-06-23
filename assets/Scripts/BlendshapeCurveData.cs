using System;
using UnityEngine;

/// <summary>
/// JsonUtility-compatible root object for an M0 blendshape curve clip.
/// </summary>
[Serializable]
public sealed class BlendshapeCurveSet
{
    public string version;
    public string clip_id;
    public string audio_file;
    public string text;
    public string language;
    public string timebase;
    public float duration_ms;
    public string weight_unit;
    public string interpolation;
    public int fps_hint;
    public BlendshapeMappingEntry[] blendshape_mapping;
    public BlendshapeCurve[] curves;
}

/// <summary>
/// Maps a logical curve channel to the actual blendshape name on the model.
/// </summary>
[Serializable]
public sealed class BlendshapeMappingEntry
{
    public string logical;
    public string actual;
}

/// <summary>
/// A named series of normalized blendshape keyframes.
/// </summary>
[Serializable]
public sealed class BlendshapeCurve
{
    public string name;
    public CurveKeyframe[] keyframes;
}

/// <summary>
/// A single blendshape keyframe on the audio timebase.
/// </summary>
[Serializable]
public sealed class CurveKeyframe
{
    public float t;
    public float v;
}

