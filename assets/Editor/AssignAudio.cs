using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Assigns the test AudioClip to AudioSyncPlayer in MainScene.
/// Usage: -executeMethod AssignAudio.Run
/// </summary>
public static class AssignAudio
{
    public static void Run()
    {
        var scene = EditorSceneManager.OpenScene("Assets/Scenes/MainScene.unity", OpenSceneMode.Single);

        // Find AudioSyncPlayer
        var syncPlayer = Object.FindFirstObjectByType<AudioSyncPlayer>();
        if (syncPlayer == null)
        {
            Debug.LogError("[AssignAudio] AudioSyncPlayer not found in scene.");
            EditorApplication.Exit(1);
            return;
        }

        // Load audio clip
        var clip = AssetDatabase.LoadAssetAtPath<AudioClip>("Assets/Audio/hello_digital_human.wav");
        if (clip == null)
        {
            Debug.LogError("[AssignAudio] AudioClip not found at Assets/Audio/hello_digital_human.wav");
            EditorApplication.Exit(1);
            return;
        }

        // Assign via SerializedObject
        var so = new SerializedObject(syncPlayer);
        so.FindProperty("audioClip").objectReferenceValue = clip;
        so.FindProperty("playOnStart").boolValue = true;
        so.ApplyModifiedPropertiesWithoutUndo();

        // Also set on AudioSource directly
        var audioSource = syncPlayer.GetComponent<AudioSource>();
        if (audioSource != null)
        {
            audioSource.clip = clip;
            EditorUtility.SetDirty(audioSource);
        }

        EditorUtility.SetDirty(syncPlayer);
        EditorSceneManager.SaveScene(scene);
        Debug.Log($"[AssignAudio] Assigned clip: {clip.name}, length={clip.length:F2}s, freq={clip.frequency}");
    }
}
