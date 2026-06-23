using UnityEditor;
using UnityEngine;

/// <summary>
/// Editor utility for automated project setup via -executeMethod.
/// </summary>
public static class SetupProject
{
    /// <summary>
    /// Imports the UniVRM unitypackage silently in batch mode.
    /// Usage: -executeMethod SetupProject.ImportUniVRM
    /// </summary>
    public static void ImportUniVRM()
    {
        string packagePath = "Assets/Plugins/UniVRM-0.131.0.unitypackage";
        string fullPath = System.IO.Path.GetFullPath(packagePath);

        if (!System.IO.File.Exists(fullPath))
        {
            Debug.LogError($"[SetupProject] UniVRM package not found at: {fullPath}");
            EditorApplication.Exit(1);
            return;
        }

        Debug.Log($"[SetupProject] Importing UniVRM from: {fullPath}");
        AssetDatabase.ImportPackage(fullPath, false);
        AssetDatabase.Refresh();
        Debug.Log("[SetupProject] UniVRM import completed.");
    }

    /// <summary>
    /// Creates the MainScene with basic URP setup.
    /// Usage: -executeMethod SetupProject.CreateMainScene
    /// </summary>
    public static void CreateMainScene()
    {
        var scene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
            UnityEditor.SceneManagement.NewSceneSetup.DefaultGameObjects,
            UnityEditor.SceneManagement.NewSceneMode.Single);

        // Add ground plane
        var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
        ground.name = "Ground";
        ground.transform.position = Vector3.zero;
        ground.transform.localScale = new Vector3(2f, 1f, 2f);

        // Position camera for half-body shot
        var cam = Camera.main;
        if (cam != null)
        {
            cam.transform.position = new Vector3(0f, 1.4f, 1.8f);
            cam.transform.rotation = Quaternion.Euler(5f, 180f, 0f);
        }

        // Save scene
        string scenePath = "Assets/Scenes/MainScene.unity";
        System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(
            System.IO.Path.GetFullPath(scenePath)));
        UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, scenePath);
        Debug.Log($"[SetupProject] MainScene created at: {scenePath}");
    }
}
