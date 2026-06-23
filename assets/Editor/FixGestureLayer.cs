using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class FixGestureLayer
{
    private const string ControllerPath = "Assets/Animations/GestureAnimator.controller";
    private const string MaskPath = "Assets/Animations/UpperBodyMask.mask";
    private const string BaseLayerName = "Base Layer";
    private const string GestureLayerName = "Gesture";

    [MenuItem("Tools/Avatar/Fix Gesture Layer")]
    [MenuItem("Tools/FixGestureLayer/Run")]
    public static void RunFromMenu()
    {
        Run(false);
    }

    public static void Run()
    {
        Run(true);
    }

    private static void Run(bool exitWhenDone)
    {
        var ac = AssetDatabase.LoadAssetAtPath<AnimatorController>(ControllerPath);
        if (ac == null)
        {
            Debug.LogError("[Fix] Controller not found: " + ControllerPath);
            if (exitWhenDone)
                EditorApplication.Exit(1);
            return;
        }

        var mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(MaskPath);
        if (mask == null)
        {
            Debug.LogError("[Fix] Upper body mask not found: " + MaskPath);
            if (exitWhenDone)
                EditorApplication.Exit(1);
            return;
        }

        var layers = ac.layers;
        if (layers.Length < 2)
        {
            Debug.LogError("[Fix] Expected at least two layers in " + ControllerPath);
            if (exitWhenDone)
                EditorApplication.Exit(1);
            return;
        }

        layers[0].defaultWeight = 0f;
        layers[0].avatarMask = mask;
        Debug.Log("[Fix] " + BaseLayerName + " configured: mask=" + MaskPath + ", weight=0");

        var foundGestureLayer = false;
        for (var i = 0; i < layers.Length; i++)
        {
            if (layers[i].name != GestureLayerName)
                continue;

            layers[i].avatarMask = mask;
            layers[i].blendingMode = AnimatorLayerBlendingMode.Override;
            layers[i].defaultWeight = 1f;
            foundGestureLayer = true;
            Debug.Log("[Fix] Gesture layer mask assigned: " + MaskPath + ", blending=Override, weight=1");
            break;
        }

        if (!foundGestureLayer)
        {
            Debug.LogError("[Fix] Gesture layer not found in " + ControllerPath);
            if (exitWhenDone)
                EditorApplication.Exit(1);
            return;
        }

        ac.layers = layers;
        EditorUtility.SetDirty(ac);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log("[Fix] Done");
        if (exitWhenDone)
            EditorApplication.Exit(0);
    }
}
