using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using System.IO;

/// <summary>
/// Creates GestureAnimator.controller and wires M4 components into MainScene.
/// Usage: -executeMethod SetupM4Scene.Run
/// </summary>
public static class SetupM4Scene
{
    private const string ScenePath       = "Assets/Scenes/MainScene.unity";
    private const string GestureDir      = "Assets/Animations/Gestures";
    private const string ControllerPath  = "Assets/Animations/GestureAnimator.controller";

    // clip name → state name in Animator (must match GestureAnimationController)
    private static readonly string[] GestureClipNames =
    {
        "gesture_emphasis",
        "gesture_enumerate",
        "gesture_explain",
        "gesture_contrast",
        "gesture_beat",
        "gesture_uncertain",
        "gesture_greet",
    };

    public static void Run()
    {
        // 1. Create AnimatorController asset
        var animController = CreateGestureAnimatorController();

        // 2. Open scene and wire components
        var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);

        var controller = GameObject.Find("M0_Controller");
        if (controller == null)
        {
            Debug.LogError("[SetupM4Scene] M0_Controller not found. Run SetupM1Scene first.");
            EditorApplication.Exit(1); return;
        }

        var avatar = GameObject.Find("Avatar");
        if (avatar == null)
        {
            Debug.LogError("[SetupM4Scene] Avatar not found in MainScene.");
            EditorApplication.Exit(1); return;
        }

        // Assign AnimatorController to Avatar's Animator
        var avatarAnimator = avatar.GetComponent<Animator>();
        if (avatarAnimator == null) avatarAnimator = avatar.AddComponent<Animator>();
        avatarAnimator.runtimeAnimatorController = animController;
        EditorUtility.SetDirty(avatarAnimator);
        EditorUtility.SetDirty(avatar);

        // Add/configure GestureAnimationController
        var gestureComp = controller.GetComponent<GestureAnimationController>();
        if (gestureComp == null) gestureComp = controller.AddComponent<GestureAnimationController>();
        {
            var so = new SerializedObject(gestureComp);
            SetObjectReference(so, "animator", avatarAnimator);
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        // Wire into NetworkClient
        var netClient = controller.GetComponent<NetworkClient>();
        if (netClient != null)
        {
            var so = new SerializedObject(netClient);
            SetObjectReference(so, "gestureController", gestureComp);
            so.ApplyModifiedPropertiesWithoutUndo();
        }
        else
        {
            Debug.LogError("[SetupM4Scene] NetworkClient not found on M0_Controller. Run SetupM1Scene first.");
            EditorApplication.Exit(1); return;
        }

        EditorUtility.SetDirty(gestureComp);
        EditorUtility.SetDirty(netClient);
        EditorUtility.SetDirty(controller);
        EditorSceneManager.SaveScene(scene);
        Debug.Log($"[SetupM4Scene] Done. GestureAnimator created with {GestureClipNames.Length} states.");
        EditorApplication.Exit(0);
    }

    private static AnimatorController CreateGestureAnimatorController()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(ControllerPath)));

        if (AssetDatabase.LoadAssetAtPath<AnimatorController>(ControllerPath) != null)
        {
            AssetDatabase.DeleteAsset(ControllerPath);
        }

        var ac = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
        if (ac == null)
        {
            Debug.LogError($"[SetupM4Scene] Failed to create AnimatorController at {ControllerPath}");
            EditorApplication.Exit(1);
            return null;
        }

        // Add Gesture layer if not present
        int gestureLayerIdx = -1;
        for (int i = 0; i < ac.layers.Length; i++)
        {
            if (ac.layers[i].name == "Gesture") { gestureLayerIdx = i; break; }
        }

        if (gestureLayerIdx < 0)
        {
            ac.AddLayer("Gesture");
            gestureLayerIdx = ac.layers.Length - 1;
        }

        // Set layer weight = 1, restricted to upper body so gestures do not replace the VRM base pose.
        var upperBodyMask = FixGestureAnimatorUpperBodyMask.CreateOrUpdateUpperBodyMask();
        var layers = ac.layers;
        layers[gestureLayerIdx].defaultWeight = 1f;
        layers[gestureLayerIdx].blendingMode = AnimatorLayerBlendingMode.Override;
        layers[gestureLayerIdx].avatarMask = upperBodyMask;
        ac.layers = layers;

        var sm = ac.layers[gestureLayerIdx].stateMachine;

        // Clear existing states (except Entry/Exit/Any)
        foreach (var existing in sm.states)
            sm.RemoveState(existing.state);

        // Add Idle default state
        var idleState = sm.AddState("Idle");
        sm.defaultState = idleState;

        // Add one state per gesture clip
        foreach (var clipName in GestureClipNames)
        {
            var clip = FindClip(clipName);
            if (clip == null)
            {
                Debug.LogError($"[SetupM4Scene] Required AnimationClip not found: {clipName}");
                EditorApplication.Exit(1);
                return ac;
            }

            var state = sm.AddState(clipName);
            state.motion = clip;
        }

        EditorUtility.SetDirty(ac);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log($"[SetupM4Scene] AnimatorController saved: {ControllerPath}");
        return ac;
    }

    private static AnimationClip FindClip(string clipName)
    {
        var guids = AssetDatabase.FindAssets("t:Model", new[] { GestureDir });
        foreach (var guid in guids)
        {
            var path = AssetDatabase.GUIDToAssetPath(guid);
            foreach (var asset in AssetDatabase.LoadAllAssetsAtPath(path))
            {
                if (asset is AnimationClip clip && clip.name == clipName)
                    return clip;
            }
        }
        Debug.LogWarning($"[SetupM4Scene] AnimationClip not found: {clipName}");
        return null;
    }

    private static void SetObjectReference(SerializedObject serializedObject, string propertyName, Object value)
    {
        var property = serializedObject.FindProperty(propertyName);
        if (property == null)
        {
            Debug.LogError($"[SetupM4Scene] Serialized field not found: {serializedObject.targetObject.GetType().Name}.{propertyName}");
            EditorApplication.Exit(1);
            return;
        }

        property.objectReferenceValue = value;
    }
}
