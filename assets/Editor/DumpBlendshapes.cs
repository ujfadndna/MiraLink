using UnityEngine;
using UnityEditor;
using System.Text;

/// <summary>
/// Prints all blendshape names from every SkinnedMeshRenderer in the scene.
/// Run via: -executeMethod DumpBlendshapes.Run
/// </summary>
public static class DumpBlendshapes
{
    public static void Run()
    {
        // Open MainScene
        var scene = UnityEditor.SceneManagement.EditorSceneManager.OpenScene(
            "Assets/Scenes/MainScene.unity",
            UnityEditor.SceneManagement.OpenSceneMode.Single);

        var renderers = GameObject.FindObjectsByType<SkinnedMeshRenderer>(FindObjectsSortMode.None);
        if (renderers.Length == 0)
        {
            Debug.Log("[DumpBlendshapes] No SkinnedMeshRenderer found in scene.");
            return;
        }

        foreach (var smr in renderers)
        {
            var mesh = smr.sharedMesh;
            if (mesh == null) continue;

            var sb = new StringBuilder();
            sb.AppendLine($"[DumpBlendshapes] Renderer: {smr.name} | Blendshapes: {mesh.blendShapeCount}");
            for (int i = 0; i < mesh.blendShapeCount; i++)
                sb.AppendLine($"  [{i}] {mesh.GetBlendShapeName(i)}");

            Debug.Log(sb.ToString());
        }

        Debug.Log("[DumpBlendshapes] Done.");
        EditorApplication.Exit(0);
    }
}
