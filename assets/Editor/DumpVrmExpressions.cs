using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using System.Text;
using UniVRM10;

/// <summary>
/// Dumps available VRM ExpressionPresets and custom expressions on the Avatar.
/// Usage: -executeMethod DumpVrmExpressions.Run
/// </summary>
public static class DumpVrmExpressions
{
    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/Scenes/MainScene.unity", OpenSceneMode.Single);

        var vrm = GameObject.FindFirstObjectByType<Vrm10Instance>();
        if (vrm == null)
        {
            Debug.LogError("[DumpVrmExpressions] Vrm10Instance not found in scene.");
            EditorApplication.Exit(1);
            return;
        }

        var sb = new StringBuilder();
        sb.AppendLine($"[DumpVrmExpressions] Found: {vrm.gameObject.name}");

        // List all ExpressionPreset values
        sb.AppendLine("Standard ExpressionPresets:");
        foreach (ExpressionPreset preset in System.Enum.GetValues(typeof(ExpressionPreset)))
        {
            sb.AppendLine($"  {preset}");
        }

        // List expressions defined on this VRM
        if (vrm.Vrm != null && vrm.Vrm.Expression != null)
        {
            sb.AppendLine("Expressions defined on this VRM:");
            foreach (var clip in vrm.Vrm.Expression.Clips)
            {
                sb.AppendLine($"  Preset={clip.Preset} Clip={clip.Clip}");
            }
        }
        else
        {
            sb.AppendLine("vrm.Vrm.Expression is null — VRM may not be fully loaded in batch mode.");
        }

        Debug.Log(sb.ToString());
        EditorApplication.Exit(0);
    }
}
