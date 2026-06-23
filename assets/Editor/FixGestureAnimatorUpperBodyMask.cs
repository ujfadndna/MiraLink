using System;
using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class FixGestureAnimatorUpperBodyMask
{
    public const string MaskPath = "Assets/Animations/UpperBodyMask.mask";
    private const string GestureLayerName = "Gesture";

    private static readonly string[] ControllerPaths =
    {
        "Assets/Animations/GestureAnimator.controller",
        "Assets/Animations/Gestures/GestureAnimator.controller",
    };

    private static readonly string[] EnabledHumanoidParts =
    {
        "Body",
        "LeftArm",
        "RightArm",
        "LeftFingers",
        "RightFingers",
        "LeftHandIK",
        "RightHandIK",
    };

    [MenuItem("Tools/Avatar/Fix Gesture Animator Upper Body Mask")]
    public static void Run()
    {
        var mask = CreateOrUpdateUpperBodyMask();
        var updatedControllers = 0;

        foreach (var controllerPath in ControllerPaths)
        {
            var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(controllerPath);
            if (controller == null)
            {
                Debug.LogWarning($"[FixGestureAnimatorUpperBodyMask] Controller not found: {controllerPath}");
                continue;
            }

            if (ApplyUpperBodyMaskToGestureLayer(controller, mask))
                updatedControllers++;
        }

        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log($"[FixGestureAnimatorUpperBodyMask] Applied {MaskPath} to {updatedControllers} controller(s).");
    }

    public static AvatarMask CreateOrUpdateUpperBodyMask()
    {
        var maskDirectory = Path.GetDirectoryName(MaskPath);
        if (!string.IsNullOrEmpty(maskDirectory))
            Directory.CreateDirectory(maskDirectory);

        var mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(MaskPath);
        if (mask == null)
        {
            mask = new AvatarMask();
            AssetDatabase.CreateAsset(mask, MaskPath);
        }

        for (var i = 0; i < (int)AvatarMaskBodyPart.LastBodyPart; i++)
            mask.SetHumanoidBodyPartActive((AvatarMaskBodyPart)i, false);

        foreach (var bodyPartName in EnabledHumanoidParts)
        {
            if (Enum.TryParse(bodyPartName, out AvatarMaskBodyPart bodyPart))
                mask.SetHumanoidBodyPartActive(bodyPart, true);
        }

        mask.transformCount = 0;
        EditorUtility.SetDirty(mask);
        return mask;
    }

    public static bool ApplyUpperBodyMaskToGestureLayer(AnimatorController controller, AvatarMask mask)
    {
        if (controller == null || mask == null)
            return false;

        var layers = controller.layers;
        var changed = false;

        for (var i = 0; i < layers.Length; i++)
        {
            if (layers[i].name != GestureLayerName)
                continue;

            if (layers[i].avatarMask != mask)
            {
                layers[i].avatarMask = mask;
                changed = true;
            }

            if (!Mathf.Approximately(layers[i].defaultWeight, 1f))
            {
                layers[i].defaultWeight = 1f;
                changed = true;
            }

            break;
        }

        if (changed)
        {
            controller.layers = layers;
            EditorUtility.SetDirty(controller);
        }

        return changed;
    }
}
