using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using UniVRM10;

public static class SetupGestureRig
{
    private const string ScenePath = "Assets/Scenes/MainScene.unity";
    private const string AvatarName = "Avatar";
    private const string ControllerName = "M0_Controller";
    private const string GestureRigName = "GestureRig";
    private const string GestureAnimatorFieldName = "gestureAnimator";
    private const string GestureAnimatorControllerPath = "Assets/Animations/Gestures/GestureAnimator.controller";
    private const string FallbackGestureAnimatorControllerPath = "Assets/Animations/GestureAnimator.controller";

    [MenuItem("Tools/Avatar/Setup Gesture Rig")]
    public static void Run()
    {
        if (EditorApplication.isPlayingOrWillChangePlaymode)
        {
            EditorApplication.isPlaying = false;
            EditorApplication.delayCall += RunWhenEditorIsReady;
            Debug.Log("[SetupGestureRig] Exiting Play Mode before editing the scene.");
            return;
        }

        SetupInEditMode();
    }

    private static void RunWhenEditorIsReady()
    {
        if (EditorApplication.isPlayingOrWillChangePlaymode)
        {
            EditorApplication.delayCall += RunWhenEditorIsReady;
            return;
        }

        SetupInEditMode();
    }

    private static void SetupInEditMode()
    {
        var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);

        var avatar = FindAvatar();
        if (avatar == null)
        {
            Debug.LogError("[SetupGestureRig] Avatar GameObject not found.");
            return;
        }

        var mainAnimator = avatar.GetComponent<Animator>();
        if (mainAnimator == null)
            mainAnimator = avatar.AddComponent<Animator>();

        if (mainAnimator.runtimeAnimatorController != null)
        {
            mainAnimator.runtimeAnimatorController = null;
            EditorUtility.SetDirty(mainAnimator);
        }

        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(GestureAnimatorControllerPath);
        if (controller == null)
            controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(FallbackGestureAnimatorControllerPath);

        if (controller == null)
        {
            Debug.LogError($"[SetupGestureRig] GestureAnimator.controller not found at {GestureAnimatorControllerPath} or {FallbackGestureAnimatorControllerPath}.");
            return;
        }

        FixGestureAnimatorUpperBodyMask.CreateOrUpdateUpperBodyMask();
        FixGestureAnimatorUpperBodyMask.ApplyUpperBodyMaskToGestureLayer(controller, AssetDatabase.LoadAssetAtPath<AvatarMask>(FixGestureAnimatorUpperBodyMask.MaskPath));

        var gestureRig = avatar.transform.Find(GestureRigName);
        if (gestureRig == null)
        {
            var gestureRigGameObject = new GameObject(GestureRigName);
            gestureRig = gestureRigGameObject.transform;
            Undo.RegisterCreatedObjectUndo(gestureRigGameObject, "Create GestureRig");
            gestureRig.SetParent(avatar.transform, false);
        }

        gestureRig.localPosition = Vector3.zero;
        gestureRig.localRotation = Quaternion.identity;
        gestureRig.localScale = Vector3.one;

        var gestureAnimator = gestureRig.GetComponent<Animator>();
        if (gestureAnimator == null)
            gestureAnimator = gestureRig.gameObject.AddComponent<Animator>();

        gestureAnimator.runtimeAnimatorController = controller;
        gestureAnimator.avatar = mainAnimator.avatar;
        gestureAnimator.applyRootMotion = false;
        gestureAnimator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
        gestureAnimator.updateMode = mainAnimator.updateMode;

        var controllerObject = GameObject.Find(ControllerName);
        if (controllerObject == null)
        {
            Debug.LogError($"[SetupGestureRig] {ControllerName} not found.");
            return;
        }

        var gestureController = controllerObject.GetComponent<GestureAnimationController>();
        if (gestureController == null)
            gestureController = controllerObject.AddComponent<GestureAnimationController>();

        var serializedGestureController = new SerializedObject(gestureController);
        var gestureAnimatorProperty = serializedGestureController.FindProperty(GestureAnimatorFieldName);
        if (gestureAnimatorProperty == null)
        {
            Debug.LogError($"[SetupGestureRig] Serialized field not found: GestureAnimationController.{GestureAnimatorFieldName}");
            return;
        }

        gestureAnimatorProperty.objectReferenceValue = gestureAnimator;
        serializedGestureController.ApplyModifiedPropertiesWithoutUndo();

        var networkClient = controllerObject.GetComponent<NetworkClient>();
        if (networkClient != null)
        {
            var serializedNetworkClient = new SerializedObject(networkClient);
            var gestureControllerProperty = serializedNetworkClient.FindProperty("gestureController");
            if (gestureControllerProperty != null)
            {
                gestureControllerProperty.objectReferenceValue = gestureController;
                serializedNetworkClient.ApplyModifiedPropertiesWithoutUndo();
                EditorUtility.SetDirty(networkClient);
            }
        }

        EditorUtility.SetDirty(avatar);
        EditorUtility.SetDirty(gestureRig.gameObject);
        EditorUtility.SetDirty(gestureAnimator);
        EditorUtility.SetDirty(gestureController);
        EditorUtility.SetDirty(controllerObject);
        AssetDatabase.SaveAssets();
        EditorSceneManager.SaveScene(scene);

        Debug.Log($"[SetupGestureRig] Done. {AvatarName}/{GestureRigName} uses {AssetDatabase.GetAssetPath(controller)}; Avatar Animator controller cleared.");
    }

    private static GameObject FindAvatar()
    {
        var avatar = GameObject.Find(AvatarName);
        if (avatar != null)
            return avatar;

        var vrmInstance = Object.FindFirstObjectByType<Vrm10Instance>();
        return vrmInstance != null ? vrmInstance.gameObject : null;
    }
}
