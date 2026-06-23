using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

public static class ClearBaseLayer
{
    private const string ControllerPath = "Assets/Animations/GestureAnimator.controller";

    [MenuItem("Tools/ClearBaseLayer/Run")]
    public static void Run()
    {
        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(ControllerPath);
        if (controller == null)
        {
            Debug.LogError($"ClearBaseLayer: AnimatorController not found at {ControllerPath}");
            return;
        }

        if (controller.layers == null || controller.layers.Length == 0)
        {
            Debug.LogError($"ClearBaseLayer: AnimatorController has no layers: {ControllerPath}");
            return;
        }

        var layers = controller.layers;
        var baseLayer = layers[0];
        var stateMachine = baseLayer.stateMachine;
        if (stateMachine == null)
        {
            Debug.LogError("ClearBaseLayer: Base Layer state machine is missing.");
            return;
        }

        var states = stateMachine.states;
        var removedCount = states.Length;
        foreach (var childState in states)
        {
            stateMachine.RemoveState(childState.state);
        }

        baseLayer.defaultWeight = 0f;
        layers[0] = baseLayer;
        controller.layers = layers;

        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log($"ClearBaseLayer: removed {removedCount} states from Base Layer and set defaultWeight=0 on {ControllerPath}");
    }
}