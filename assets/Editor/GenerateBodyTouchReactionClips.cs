using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class GenerateBodyTouchReactionClips
{
    private const string OutputDir = "assets/Animations/BodyTouch";
    private static readonly Dictionary<string, string> BonePaths = new Dictionary<string, string>();

    private static readonly string[] ClipNames =
    {
        "touch_head_recoil",
        "touch_face_flinch",
        "touch_neck_shy",
        "touch_chest_guard",
        "touch_waist_guard",
        "touch_left_shoulder_ack",
        "touch_right_shoulder_ack",
        "touch_left_arm_ack",
        "touch_right_arm_ack",
        "touch_left_hand_hold",
        "touch_right_hand_hold",
        "touch_left_hand_ack",
        "touch_right_hand_ack",
        "touch_left_leg_step",
        "touch_right_leg_step",
        "touch_left_foot_step",
        "touch_right_foot_step",
    };

    [MenuItem("MiraLink/Generate Body Touch Reaction Clips")]
    public static void Generate()
    {
        EnsureFolder(OutputDir);
        BuildBonePathMap(Object.FindFirstObjectByType<Animator>());

        foreach (var clipName in ClipNames)
        {
            var clip = CreateClip(clipName);
            var path = $"{OutputDir}/{clipName}.anim";
            var existing = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            if (existing == null)
            {
                AssetDatabase.CreateAsset(clip, path);
            }
            else
            {
                EditorUtility.CopySerialized(clip, existing);
                EditorUtility.SetDirty(existing);
            }
        }

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log($"[GenerateBodyTouchReactionClips] Generated {ClipNames.Length} clips in {OutputDir}");
    }

    [MenuItem("MiraLink/Setup Body Touch Reaction Controller")]
    public static void SetupController()
    {
        Generate();

        var networkClient = Object.FindFirstObjectByType<NetworkClient>();
        if (networkClient == null)
        {
            Debug.LogError("[GenerateBodyTouchReactionClips] NetworkClient not found in open scene.");
            return;
        }

        var root = networkClient.gameObject;
        var animator = root.GetComponentInChildren<Animator>();

        var bodyTouch = root.GetComponent<BodyTouchReactionController>();
        if (bodyTouch == null)
            bodyTouch = root.AddComponent<BodyTouchReactionController>();

        var serialized = new SerializedObject(bodyTouch);
        serialized.FindProperty("vrm10Animator").objectReferenceValue = animator;
        var poseClips = serialized.FindProperty("poseClips");
        poseClips.arraySize = ClipNames.Length;
        for (int i = 0; i < ClipNames.Length; i++)
        {
            var element = poseClips.GetArrayElementAtIndex(i);
            element.FindPropertyRelative("poseMode").stringValue = ClipNames[i];
            element.FindPropertyRelative("clip").objectReferenceValue =
                AssetDatabase.LoadAssetAtPath<AnimationClip>($"{OutputDir}/{ClipNames[i]}.anim");
        }
        serialized.ApplyModifiedPropertiesWithoutUndo();
        EditorUtility.SetDirty(bodyTouch);

        var demo = root.GetComponent<JdDemoInteractionController>();
        if (demo != null)
        {
            var serializedDemo = new SerializedObject(demo);
            serializedDemo.FindProperty("bodyTouchController").objectReferenceValue = bodyTouch;
            if (animator != null)
                serializedDemo.FindProperty("avatarAnimator").objectReferenceValue = animator;
            serializedDemo.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(demo);
        }

        var anchorPublisher = root.GetComponent<AvatarAnchorPublisher>();
        if (anchorPublisher == null)
            anchorPublisher = root.AddComponent<AvatarAnchorPublisher>();

        var serializedAnchor = new SerializedObject(anchorPublisher);
        serializedAnchor.FindProperty("networkClient").objectReferenceValue = networkClient;
        if (animator != null)
            serializedAnchor.FindProperty("avatarAnimator").objectReferenceValue = animator;
        serializedAnchor.ApplyModifiedPropertiesWithoutUndo();
        EditorUtility.SetDirty(anchorPublisher);

        UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(root.scene);
        Debug.Log("[GenerateBodyTouchReactionClips] Body touch runtime components configured.");
    }

    private static AnimationClip CreateClip(string clipName)
    {
        var clip = new AnimationClip
        {
            name = clipName,
            frameRate = 60f,
            legacy = false,
        };

        var curves = new List<(string path, string property, AnimationCurve curve)>();
        AddCurvesForPose(clipName, curves);
        foreach (var item in curves)
            clip.SetCurve(item.path, typeof(Transform), item.property, item.curve);

        var settings = AnimationUtility.GetAnimationClipSettings(clip);
        settings.loopTime = false;
        AnimationUtility.SetAnimationClipSettings(clip, settings);
        EditorUtility.SetDirty(clip);
        return clip;
    }

    private static void AddCurvesForPose(string clipName, List<(string path, string property, AnimationCurve curve)> curves)
    {
        float side = clipName.Contains("_left_") ? -1f : clipName.Contains("_right_") ? 1f : 0f;

        if (clipName == "touch_head_recoil")
        {
            AddEuler(curves, "J_Bip_C_Head", -10f, 0f, 0f);
            AddEuler(curves, "J_Bip_C_Neck", -5f, 0f, 0f);
            return;
        }

        if (clipName == "touch_face_flinch")
        {
            AddEuler(curves, "J_Bip_C_Head", -4f, sideOrDefault(side, -8f), 3f);
            AddEuler(curves, "J_Bip_C_Neck", -3f, sideOrDefault(side, -5f), 0f);
            return;
        }

        if (clipName == "touch_neck_shy")
        {
            AddEuler(curves, "J_Bip_C_Neck", 7f, -7f, 0f);
            AddEuler(curves, "J_Bip_C_Head", 5f, -10f, 0f);
            AddEuler(curves, "J_Bip_C_Chest", 0f, -4f, 0f);
            return;
        }

        if (clipName == "touch_chest_guard")
        {
            AddEuler(curves, "J_Bip_C_Chest", -3f, 0f, 0f);
            AddEuler(curves, "J_Bip_L_UpperArm", 12f, 0f, 42f);
            AddEuler(curves, "J_Bip_R_UpperArm", 12f, 0f, -42f);
            AddEuler(curves, "J_Bip_L_LowerArm", 18f, 0f, 22f);
            AddEuler(curves, "J_Bip_R_LowerArm", 18f, 0f, -22f);
            return;
        }

        if (clipName == "touch_waist_guard")
        {
            AddEuler(curves, "J_Bip_C_Hips", 0f, 0f, 5f);
            AddEuler(curves, "J_Bip_C_Spine", 0f, 0f, 7f);
            AddEuler(curves, "J_Bip_L_UpperArm", 5f, 0f, 30f);
            AddEuler(curves, "J_Bip_R_UpperArm", 5f, 0f, -30f);
            return;
        }

        if (clipName.Contains("_shoulder_ack"))
        {
            string arm = side < 0f ? "L" : "R";
            AddEuler(curves, $"J_Bip_{arm}_Shoulder", 0f, 0f, side * -10f);
            AddEuler(curves, $"J_Bip_{arm}_UpperArm", 10f, side * 5f, side * -18f);
            AddEuler(curves, "J_Bip_C_Head", 0f, side * 10f, 0f);
            return;
        }

        if (clipName.Contains("_arm_ack"))
        {
            string arm = side < 0f ? "L" : "R";
            AddEuler(curves, $"J_Bip_{arm}_UpperArm", 10f, side * 8f, side * -20f);
            AddEuler(curves, $"J_Bip_{arm}_LowerArm", 8f, side * 4f, side * -16f);
            AddEuler(curves, "J_Bip_C_Head", 0f, side * 8f, 0f);
            return;
        }

        if (clipName.Contains("_hand_"))
        {
            string arm = side < 0f ? "L" : "R";
            AddEuler(curves, $"J_Bip_{arm}_UpperArm", 14f, side * 8f, side * -26f);
            AddEuler(curves, $"J_Bip_{arm}_LowerArm", 20f, side * 4f, side * -22f);
            AddEuler(curves, $"J_Bip_{arm}_Hand", 0f, side * 6f, side * -10f);
            AddEuler(curves, "J_Bip_C_Head", 4f, side * 8f, 0f);
            return;
        }

        if (clipName.Contains("_leg_step"))
        {
            string leg = side < 0f ? "L" : "R";
            AddEuler(curves, "J_Bip_C_Hips", 0f, 0f, side * -4f);
            AddEuler(curves, $"J_Bip_{leg}_UpperLeg", -7f, 0f, side * 4f);
            AddEuler(curves, $"J_Bip_{leg}_LowerLeg", 10f, 0f, 0f);
            AddEuler(curves, "J_Bip_C_Head", 9f, side * 6f, 0f);
            return;
        }

        if (clipName.Contains("_foot_step"))
        {
            string leg = side < 0f ? "L" : "R";
            AddEuler(curves, "J_Bip_C_Hips", 0f, 0f, side * -5f);
            AddEuler(curves, $"J_Bip_{leg}_UpperLeg", -5f, 0f, side * 5f);
            AddEuler(curves, $"J_Bip_{leg}_LowerLeg", 12f, 0f, 0f);
            AddEuler(curves, $"J_Bip_{leg}_Foot", -12f, 0f, side * 4f);
            AddEuler(curves, "J_Bip_C_Head", 11f, side * 6f, 0f);
        }
    }

    private static float sideOrDefault(float side, float fallback)
    {
        return Mathf.Approximately(side, 0f) ? fallback : side * 8f;
    }

    private static void AddEuler(List<(string path, string property, AnimationCurve curve)> curves, string boneName, float x, float y, float z)
    {
        const float start = 0f;
        const float peak = 0.18f;
        const float end = 0.55f;
        AddCurve(curves, boneName, "localEulerAnglesRaw.x", start, peak, end, x);
        AddCurve(curves, boneName, "localEulerAnglesRaw.y", start, peak, end, y);
        AddCurve(curves, boneName, "localEulerAnglesRaw.z", start, peak, end, z);
    }

    private static void AddCurve(List<(string path, string property, AnimationCurve curve)> curves, string boneName, string property, float start, float peak, float end, float value)
    {
        var curve = new AnimationCurve(
            new Keyframe(start, 0f),
            new Keyframe(peak, value),
            new Keyframe(end, 0f));
        for (int i = 0; i < curve.length; i++)
            curve.SmoothTangents(i, 0f);
        curves.Add((ResolveBonePath(boneName), property, curve));
    }

    private static string ResolveBonePath(string boneName)
    {
        return BonePaths.TryGetValue(boneName, out var path) ? path : boneName;
    }

    private static void BuildBonePathMap(Animator animator)
    {
        BonePaths.Clear();
        if (animator == null)
            return;

        foreach (var alias in BoneAliases())
        {
            var bone = animator.GetBoneTransform(alias.Value);
            if (bone == null)
                continue;

            var path = AnimationUtility.CalculateTransformPath(bone, animator.transform);
            BonePaths[alias.Key] = path;
            BonePaths[bone.name] = path;
        }
    }

    private static Dictionary<string, HumanBodyBones> BoneAliases()
    {
        return new Dictionary<string, HumanBodyBones>
        {
            { "J_Bip_C_Hips", HumanBodyBones.Hips },
            { "J_Bip_C_Spine", HumanBodyBones.Spine },
            { "J_Bip_C_Chest", HumanBodyBones.Chest },
            { "J_Bip_C_UpperChest", HumanBodyBones.UpperChest },
            { "J_Bip_C_Neck", HumanBodyBones.Neck },
            { "J_Bip_C_Head", HumanBodyBones.Head },
            { "J_Bip_L_Shoulder", HumanBodyBones.LeftShoulder },
            { "J_Bip_L_UpperArm", HumanBodyBones.LeftUpperArm },
            { "J_Bip_L_LowerArm", HumanBodyBones.LeftLowerArm },
            { "J_Bip_L_Hand", HumanBodyBones.LeftHand },
            { "J_Bip_R_Shoulder", HumanBodyBones.RightShoulder },
            { "J_Bip_R_UpperArm", HumanBodyBones.RightUpperArm },
            { "J_Bip_R_LowerArm", HumanBodyBones.RightLowerArm },
            { "J_Bip_R_Hand", HumanBodyBones.RightHand },
            { "J_Bip_L_UpperLeg", HumanBodyBones.LeftUpperLeg },
            { "J_Bip_L_LowerLeg", HumanBodyBones.LeftLowerLeg },
            { "J_Bip_L_Foot", HumanBodyBones.LeftFoot },
            { "J_Bip_R_UpperLeg", HumanBodyBones.RightUpperLeg },
            { "J_Bip_R_LowerLeg", HumanBodyBones.RightLowerLeg },
            { "J_Bip_R_Foot", HumanBodyBones.RightFoot },
        };
    }

    private static void EnsureFolder(string folder)
    {
        var parts = folder.Split('/');
        string current = parts[0];
        for (int i = 1; i < parts.Length; i++)
        {
            string next = $"{current}/{parts[i]}";
            if (!AssetDatabase.IsValidFolder(next))
                AssetDatabase.CreateFolder(current, parts[i]);
            current = next;
        }
    }
}
