using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UniVRM10;

/// <summary>
/// Adds M3 ExpressionController to MainScene and wires it into NetworkClient.
/// Usage: -executeMethod SetupM3Scene.Run
/// </summary>
public static class SetupM3Scene
{
    public static void Run()
    {
        var scene = EditorSceneManager.OpenScene("Assets/Scenes/MainScene.unity", OpenSceneMode.Single);

        var controller = GameObject.Find("M0_Controller");
        if (controller == null)
        {
            Debug.LogError("[SetupM3Scene] M0_Controller not found — run SetupM1Scene first.");
            EditorApplication.Exit(1);
            return;
        }

        // Find Vrm10Instance in scene
        var vrmInstance = GameObject.FindAnyObjectByType<Vrm10Instance>();
        if (vrmInstance == null)
        {
            Debug.LogError("[SetupM3Scene] Vrm10Instance not found in scene.");
            EditorApplication.Exit(1);
            return;
        }

        // Add ExpressionController if not present
        var expr = controller.GetComponent<ExpressionController>();
        if (expr == null)
            expr = controller.AddComponent<ExpressionController>();

        // Wire VRM instance
        {
            var exprSO = new SerializedObject(expr);
            exprSO.FindProperty("vrmInstance").objectReferenceValue = vrmInstance;
            exprSO.ApplyModifiedPropertiesWithoutUndo();
        }

        // Wire ExpressionController into NetworkClient
        var netClient = controller.GetComponent<NetworkClient>();
        if (netClient != null)
        {
            var netSO = new SerializedObject(netClient);
            netSO.FindProperty("expressionController").objectReferenceValue = expr;
            netSO.ApplyModifiedPropertiesWithoutUndo();
        }

        EditorUtility.SetDirty(controller);
        EditorSceneManager.SaveScene(scene);
        Debug.Log($"[SetupM3Scene] Done. ExpressionController → Vrm10Instance ({vrmInstance.gameObject.name})");
        EditorApplication.Exit(0);
    }
}
