using System;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class SetupM4GestureLayer
{
    private const string MenuPath = "MiraLink/Setup M4 Gesture Layer";
    private const string GestureFolderPath = "Assets/Animations/Gestures";
    private const string GestureIdleClipPath = GestureFolderPath + "/GestureIdle.anim";
    private const string GestureAnimatorControllerPath = GestureFolderPath + "/GestureAnimator.controller";
    private const string GestureLayerName = "Gesture";
    private const string IdleStateName = "Idle";
    private const float FrameRate = 60f;

    [MenuItem(MenuPath)]
    public static void Run()
    {
        EnsureFolder(GestureFolderPath);

        var idleClip = CreateOrUpdateGestureIdleClip();
        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(GestureAnimatorControllerPath);
        if (controller == null)
            throw new InvalidOperationException($"AnimatorController not found: {GestureAnimatorControllerPath}");

        var layers = controller.layers;
        var gestureLayerIndex = FindLayerIndex(layers, GestureLayerName);
        if (gestureLayerIndex < 0)
            throw new InvalidOperationException($"AnimatorController layer '{GestureLayerName}' not found in {GestureAnimatorControllerPath}");

        var gestureLayer = layers[gestureLayerIndex];
        gestureLayer.defaultWeight = 0f;

        var idleStateFound = ConfigureStates(gestureLayer.stateMachine, idleClip);
        if (!idleStateFound)
            throw new InvalidOperationException($"State '{IdleStateName}' not found on layer '{GestureLayerName}' in {GestureAnimatorControllerPath}");

        layers[gestureLayerIndex] = gestureLayer;
        controller.layers = layers;

        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log("[SetupM4GestureLayer] Gesture layer configured: idle clip assigned, Write Defaults disabled, layer weight set to 0.");
    }

    private static AnimationClip CreateOrUpdateGestureIdleClip()
    {
        var existing = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(GestureIdleClipPath);
        if (existing != null && existing is not AnimationClip)
            throw new InvalidOperationException($"Asset exists but is not an AnimationClip: {GestureIdleClipPath}");

        var clip = existing as AnimationClip;
        if (clip == null)
        {
            clip = new AnimationClip
            {
                legacy = false,
                frameRate = FrameRate
            };

            AssetDatabase.CreateAsset(clip, GestureIdleClipPath);
        }

        clip.legacy = false;
        clip.frameRate = FrameRate;
        ClearCurvesAndEvents(clip);

        var settings = AnimationUtility.GetAnimationClipSettings(clip);
        settings.startTime = 0f;
        settings.stopTime = 1f / FrameRate;
        settings.loopTime = false;
        settings.loopBlend = false;
        settings.loopBlendOrientation = false;
        settings.loopBlendPositionY = false;
        settings.loopBlendPositionXZ = false;
        AnimationUtility.SetAnimationClipSettings(clip, settings);

        EditorUtility.SetDirty(clip);
        AssetDatabase.ImportAsset(GestureIdleClipPath);

        return clip;
    }

    private static void ClearCurvesAndEvents(AnimationClip clip)
    {
        foreach (var binding in AnimationUtility.GetCurveBindings(clip))
            AnimationUtility.SetEditorCurve(clip, binding, null);

        foreach (var binding in AnimationUtility.GetObjectReferenceCurveBindings(clip))
            AnimationUtility.SetObjectReferenceCurve(clip, binding, null);

        AnimationUtility.SetAnimationEvents(clip, Array.Empty<AnimationEvent>());
    }

    private static bool ConfigureStates(AnimatorStateMachine stateMachine, AnimationClip idleClip)
    {
        var idleStateFound = false;

        foreach (var childState in stateMachine.states)
        {
            var state = childState.state;
            if (state == null)
                continue;

            state.writeDefaultValues = false;

            if (string.Equals(state.name, IdleStateName, StringComparison.Ordinal))
            {
                state.motion = idleClip;
                idleStateFound = true;
            }

            EditorUtility.SetDirty(state);
        }

        foreach (var childStateMachine in stateMachine.stateMachines)
        {
            if (childStateMachine.stateMachine == null)
                continue;

            idleStateFound |= ConfigureStates(childStateMachine.stateMachine, idleClip);
            EditorUtility.SetDirty(childStateMachine.stateMachine);
        }

        EditorUtility.SetDirty(stateMachine);
        return idleStateFound;
    }

    private static int FindLayerIndex(AnimatorControllerLayer[] layers, string layerName)
    {
        for (var i = 0; i < layers.Length; i++)
        {
            if (string.Equals(layers[i].name, layerName, StringComparison.Ordinal))
                return i;
        }

        return -1;
    }

    private static void EnsureFolder(string folderPath)
    {
        var parts = folderPath.Split('/');
        if (parts.Length == 0 || parts[0] != "Assets")
            throw new InvalidOperationException($"Folder must be under Assets: {folderPath}");

        var current = parts[0];
        for (var i = 1; i < parts.Length; i++)
        {
            var next = current + "/" + parts[i];
            if (!AssetDatabase.IsValidFolder(next))
                AssetDatabase.CreateFolder(current, parts[i]);

            current = next;
        }
    }
}
