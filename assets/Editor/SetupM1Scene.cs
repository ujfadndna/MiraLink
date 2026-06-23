using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Adds M1 networking components to MainScene.
/// Usage: -executeMethod SetupM1Scene.Run
/// </summary>
public static class SetupM1Scene
{
    public static void Run()
    {
        var scene = EditorSceneManager.OpenScene("Assets/Scenes/MainScene.unity", OpenSceneMode.Single);

        // Find existing M0_Controller
        var controller = GameObject.Find("M0_Controller");
        if (controller == null)
        {
            controller = new GameObject("M0_Controller");
            Debug.LogWarning("[SetupM1Scene] M0_Controller not found, created new one.");
        }

        // Add StreamingAudioPlayer if not present
        var streamPlayer = controller.GetComponent<StreamingAudioPlayer>();
        if (streamPlayer == null)
            streamPlayer = controller.AddComponent<StreamingAudioPlayer>();
        // Always refresh references
        {
            var streamSO = new SerializedObject(streamPlayer);
            streamSO.FindProperty("audioSource").objectReferenceValue = controller.GetComponent<AudioSource>();
            streamSO.FindProperty("facialController").objectReferenceValue = controller.GetComponent<FacialAnimationController>();
            streamSO.ApplyModifiedPropertiesWithoutUndo();
        }

        // Add NetworkClient if not present
        var netClient = controller.GetComponent<NetworkClient>();
        if (netClient == null)
            netClient = controller.AddComponent<NetworkClient>();
        // Always overwrite port + references
        {
            var netSO = new SerializedObject(netClient);
            netSO.FindProperty("serverUrl").stringValue = "ws://127.0.0.1:8100/ws/avatar";
            netSO.FindProperty("connectOnStart").boolValue = true;
            netSO.FindProperty("audioPlayer").objectReferenceValue = streamPlayer;
            netSO.FindProperty("facialController").objectReferenceValue = controller.GetComponent<FacialAnimationController>();
            netSO.ApplyModifiedPropertiesWithoutUndo();
        }

        // Add TextInputUI if not present
        var inputUI = controller.GetComponent<TextInputUI>();
        if (inputUI == null)
            inputUI = controller.AddComponent<TextInputUI>();
        {
            var uiSO = new SerializedObject(inputUI);
            uiSO.FindProperty("networkClient").objectReferenceValue = netClient;
            uiSO.ApplyModifiedPropertiesWithoutUndo();
        }

        // Disable M0's AudioSyncPlayer (playOnStart) to avoid conflict
        var oldSync = controller.GetComponent<AudioSyncPlayer>();
        if (oldSync != null)
        {
            var oldSO = new SerializedObject(oldSync);
            oldSO.FindProperty("playOnStart").boolValue = false;
            oldSO.ApplyModifiedPropertiesWithoutUndo();
        }

        EditorUtility.SetDirty(controller);
        EditorSceneManager.SaveScene(scene);
        Debug.Log("[SetupM1Scene] M1 components added: NetworkClient + StreamingAudioPlayer + TextInputUI");
    }
}
