using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using System.Text;

/// <summary>
/// Dumps all component types on all GameObjects in MainScene to identify VRM runtime components.
/// Usage: -executeMethod DumpVrmComponents.Run
/// </summary>
public static class DumpVrmComponents
{
    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/Scenes/MainScene.unity", OpenSceneMode.Single);

        var sb = new StringBuilder();
        sb.AppendLine("[DumpVrmComponents] All components in scene:");

        foreach (var go in GameObject.FindObjectsByType<GameObject>(
            FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            foreach (var comp in go.GetComponents<Component>())
            {
                if (comp == null) continue;
                string typeName = comp.GetType().FullName;
                if (typeName.Contains("Vrm") || typeName.Contains("VRM") || typeName.Contains("UniGLTF"))
                    sb.AppendLine($"  [{go.name}] {typeName}");
            }
        }

        Debug.Log(sb.ToString());
        EditorApplication.Exit(0);
    }
}
