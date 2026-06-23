using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Automated M0 scene assembly: loads VRM model, attaches scripts, wires references.
/// Usage: -executeMethod SetupM0Scene.Run
/// </summary>
public static class SetupM0Scene
{
    private const string ScenePath = "Assets/Scenes/MainScene.unity";
    private const string VrmPath = "Assets/Models/Seed-san.vrm";
    private const string CurveJsonPath = "Assets/Data/hello_digital_human_curve.json";

    public static void Run()
    {
        // Open or create scene
        var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);

        // Clear existing non-essential objects (keep Camera and Light)
        foreach (var go in scene.GetRootGameObjects())
        {
            if (go.GetComponent<Camera>() == null && go.GetComponent<Light>() == null)
            {
                Object.DestroyImmediate(go);
            }
        }

        // Load VRM prefab
        var vrmPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(VrmPath);
        if (vrmPrefab == null)
        {
            Debug.LogError($"[SetupM0Scene] VRM model not found at: {VrmPath}");
            EditorApplication.Exit(1);
            return;
        }

        // Instantiate VRM
        var avatar = (GameObject)PrefabUtility.InstantiatePrefab(vrmPrefab);
        avatar.name = "Avatar";
        avatar.transform.position = Vector3.zero;
        avatar.transform.rotation = Quaternion.identity;
        Debug.Log($"[SetupM0Scene] Instantiated avatar: {avatar.name}");

        // Find face SkinnedMeshRenderer (usually named "Face" or the one with most blendshapes)
        SkinnedMeshRenderer faceRenderer = null;
        int maxBlendshapes = 0;
        foreach (var smr in avatar.GetComponentsInChildren<SkinnedMeshRenderer>())
        {
            if (smr.sharedMesh != null && smr.sharedMesh.blendShapeCount > maxBlendshapes)
            {
                maxBlendshapes = smr.sharedMesh.blendShapeCount;
                faceRenderer = smr;
            }
        }

        if (faceRenderer == null)
        {
            Debug.LogError("[SetupM0Scene] No SkinnedMeshRenderer with blendshapes found on avatar.");
            EditorApplication.Exit(1);
            return;
        }

        Debug.Log($"[SetupM0Scene] Face renderer: {faceRenderer.name} ({maxBlendshapes} blendshapes)");

        // Log available blendshape names for debugging
        var mesh = faceRenderer.sharedMesh;
        System.Text.StringBuilder sb = new System.Text.StringBuilder();
        sb.AppendLine("[SetupM0Scene] Available blendshapes:");
        for (int i = 0; i < mesh.blendShapeCount; i++)
        {
            sb.AppendLine($"  [{i}] {mesh.GetBlendShapeName(i)}");
        }
        Debug.Log(sb.ToString());

        // Create controller GameObject
        var controllerGo = new GameObject("M0_Controller");

        // Add AudioSource
        var audioSource = controllerGo.AddComponent<AudioSource>();
        audioSource.playOnAwake = false;

        // Add FacialAnimationController
        var facial = controllerGo.AddComponent<FacialAnimationController>();

        // Load curve JSON as TextAsset
        var curveAsset = AssetDatabase.LoadAssetAtPath<TextAsset>(CurveJsonPath);
        if (curveAsset == null)
        {
            Debug.LogWarning($"[SetupM0Scene] Curve JSON not found at: {CurveJsonPath}. Will need manual assignment.");
        }

        // Use SerializedObject to set private [SerializeField] fields
        var facialSO = new SerializedObject(facial);
        facialSO.FindProperty("faceRenderer").objectReferenceValue = faceRenderer;
        facialSO.FindProperty("curveJson").objectReferenceValue = curveAsset;
        facialSO.FindProperty("loadOnAwake").boolValue = true;
        facialSO.FindProperty("logMissingBlendshapes").boolValue = true;
        facialSO.FindProperty("globalWeightScale").floatValue = 1.0f;
        facialSO.ApplyModifiedPropertiesWithoutUndo();

        // Add AudioSyncPlayer
        var syncPlayer = controllerGo.AddComponent<AudioSyncPlayer>();
        var syncSO = new SerializedObject(syncPlayer);
        syncSO.FindProperty("audioSource").objectReferenceValue = audioSource;
        syncSO.FindProperty("facialController").objectReferenceValue = facial;
        syncSO.FindProperty("playOnStart").boolValue = false;
        syncSO.FindProperty("playKey").intValue = (int)KeyCode.Space;
        syncSO.ApplyModifiedPropertiesWithoutUndo();

        // Setup camera to frame avatar head/chest
        var cam = Camera.main;
        if (cam != null)
        {
            cam.transform.position = new Vector3(0f, 1.3f, 1.5f);
            cam.transform.rotation = Quaternion.Euler(5f, 180f, 0f);
            cam.nearClipPlane = 0.1f;
        }

        // Add ground plane
        var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
        ground.name = "Ground";
        ground.transform.position = Vector3.zero;
        ground.transform.localScale = new Vector3(2f, 1f, 2f);

        // Save scene
        EditorSceneManager.SaveScene(scene, ScenePath);
        Debug.Log("[SetupM0Scene] M0 scene setup complete. Press Space in Play mode to test.");
        Debug.Log("[SetupM0Scene] Note: Assign an AudioClip to AudioSyncPlayer to hear audio.");
    }
}
