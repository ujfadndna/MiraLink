using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;

public static class SetupGestureController
{
    [MenuItem("MiraLink/Setup Gesture Controller")]
    public static void Run()
    {
        // 1. Delete GestureRig child under Avatar
        var avatar = GameObject.Find("Avatar");
        if (avatar != null)
        {
            var gestureRigT = avatar.transform.Find("GestureRig");
            if (gestureRigT != null)
            {
                Undo.DestroyObjectImmediate(gestureRigT.gameObject);
                Debug.Log("[SetupGesture] Deleted GestureRig child.");
            }
            else
                Debug.Log("[SetupGesture] GestureRig not found (already removed).");
        }
        else
            Debug.LogError("[SetupGesture] 'Avatar' GameObject not found!");

        // 2. Find GestureAnimationController
        var ctrl = Object.FindAnyObjectByType<GestureAnimationController>();
        if (ctrl == null) { Debug.LogError("[SetupGesture] GestureAnimationController not found!"); return; }
        var so = new SerializedObject(ctrl);

        // 3. Assign vrm10Animator (Animator on Avatar)
        if (avatar != null)
        {
            var anim = avatar.GetComponent<Animator>();
            if (anim != null)
            {
                so.FindProperty("vrm10Animator").objectReferenceValue = anim;
                Debug.Log("[SetupGesture] Assigned vrm10Animator.");
            }
            else
                Debug.LogError("[SetupGesture] No Animator on Avatar!");
        }

        // 4. Assign UpperBodyMask
        var mask = AssetDatabase.LoadAssetAtPath<AvatarMask>("Assets/Animations/UpperBodyMask.mask");
        if (mask != null)
        {
            so.FindProperty("upperBodyMask").objectReferenceValue = mask;
            Debug.Log("[SetupGesture] Assigned UpperBodyMask.");
        }
        else
            Debug.LogError("[SetupGesture] UpperBodyMask.mask not found!");

        // 5. Assign 7 gesture clips — order matches BuildGestureMap indices:
        //    0=greet(Waving), 1=enumerate(Counting), 2=explain(Pointing), 3=uncertain(Shrugging),
        //    4=beat(Talking), 5=contrast(Thinking), 6=emphasis(Acknowledging)
        string[] fbxPaths = {
            "Assets/Animations/Gestures/X Bot@Waving.fbx",
            "Assets/Animations/Gestures/X Bot@Counting.fbx",
            "Assets/Animations/Gestures/X Bot@Pointing Forward.fbx",
            "Assets/Animations/Gestures/X Bot@Shrugging.fbx",
            "Assets/Animations/Gestures/X Bot@Talking.fbx",
            "Assets/Animations/Gestures/X Bot@Thinking.fbx",
            "Assets/Animations/Gestures/X Bot@Acknowledging.fbx"
        };

        var clipsProp = so.FindProperty("gestureclips");
        clipsProp.arraySize = fbxPaths.Length;
        int assigned = 0;
        for (int i = 0; i < fbxPaths.Length; i++)
        {
            var allAssets = AssetDatabase.LoadAllAssetsAtPath(fbxPaths[i]);
            AnimationClip clip = null;
            foreach (var a in allAssets)
            {
                if (a is AnimationClip c && !c.name.StartsWith("__"))
                {
                    clip = c;
                    break;
                }
            }
            if (clip != null)
            {
                clipsProp.GetArrayElementAtIndex(i).objectReferenceValue = clip;
                assigned++;
                Debug.Log($"[SetupGesture] Assigned clip[{i}] = {clip.name}");
            }
            else
                Debug.LogError($"[SetupGesture] No AnimationClip found in {fbxPaths[i]}");
        }

        so.ApplyModifiedProperties();
        EditorUtility.SetDirty(ctrl);
        EditorSceneManager.MarkSceneDirty(ctrl.gameObject.scene);
        AssetDatabase.SaveAssets();
        Debug.Log($"[SetupGesture] Done. Assigned {assigned}/7 clips.");

        // Add ReliableScreenshotCapture to M0_Controller for AI-triggered screenshots
        var m0 = GameObject.Find("M0_Controller");
        if (m0 != null && m0.GetComponent<ReliableScreenshotCapture>() == null)
        {
            m0.AddComponent<ReliableScreenshotCapture>();
            EditorUtility.SetDirty(m0);
            Debug.Log("[SetupGesture] Added ReliableScreenshotCapture to M0_Controller.");
        }
    }
}
