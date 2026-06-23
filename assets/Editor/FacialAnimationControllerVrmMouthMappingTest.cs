using System;
using UniVRM10;
using UnityEngine;

public static class FacialAnimationControllerVrmMouthMappingTest
{
    public static void Run()
    {
        AssertPreset("lip_a", true, true, ExpressionPreset.aa);
        AssertPreset("lip_i", true, true, ExpressionPreset.ih);
        AssertPreset("lip_u", true, true, ExpressionPreset.ou);
        AssertPreset("lip_w", true, true, ExpressionPreset.ou);
        AssertPreset("lip_e", true, true, ExpressionPreset.ee);
        AssertPreset("lip_o", true, true, ExpressionPreset.oh);
        AssertPreset("mouse_open", false, true, ExpressionPreset.aa);
        AssertPreset("mouse_open", true, false, ExpressionPreset.neutral);

        Debug.Log("[FacialAnimationControllerVrmMouthMappingTest] PASS");
    }

    private static void AssertPreset(string logicalName, bool hasAnyLipWeight, bool expectedResult, ExpressionPreset expectedPreset)
    {
        bool result = FacialAnimationController.TryResolveVrmMouthPreset(logicalName, hasAnyLipWeight, out ExpressionPreset preset);
        if (result != expectedResult || preset != expectedPreset)
        {
            throw new Exception(
                $"Expected {logicalName} hasLip={hasAnyLipWeight} -> result={expectedResult} preset={expectedPreset}, got result={result} preset={preset}");
        }
    }
}
