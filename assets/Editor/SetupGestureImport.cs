using UnityEditor;
using UnityEngine;
using System.IO;

/// <summary>
/// Configures all Mixamo FBX files in Assets/Animations/Gestures/ for Unity Humanoid rig.
/// Sets rig type to Humanoid, disables mesh import, names animation clips correctly.
/// Usage: -executeMethod SetupGestureImport.Run
/// </summary>
public static class SetupGestureImport
{
    private static readonly string GestureDir = "Assets/Animations/Gestures";

    // Map filename keyword → clip name used by GestureAnimationController
    private static readonly (string keyword, string clipName)[] ClipNames =
    {
        ("Acknowledging", "gesture_emphasis"),
        ("Counting",      "gesture_enumerate"),
        ("Pointing",      "gesture_explain"),
        ("Shrugging",     "gesture_contrast"),
        ("Talking",       "gesture_beat"),
        ("Thinking",      "gesture_uncertain"),
        ("Waving",        "gesture_greet"),
        ("Disagreement",  "gesture_deny"),
    };

    public static void Run()
    {
        var guids = AssetDatabase.FindAssets("t:Model", new[] { GestureDir });
        if (guids.Length == 0)
        {
            Debug.LogError($"[SetupGestureImport] No FBX found in {GestureDir}");
            EditorApplication.Exit(1);
            return;
        }

        int configured = 0;
        foreach (var guid in guids)
        {
            var path = AssetDatabase.GUIDToAssetPath(guid);
            if (!path.EndsWith(".fbx", System.StringComparison.OrdinalIgnoreCase)) continue;

            var importer = AssetImporter.GetAtPath(path) as ModelImporter;
            if (importer == null) continue;

            // Set Humanoid rig
            importer.animationType = ModelImporterAnimationType.Human;
            importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;

            // Strip mesh — we only need the animation
            importer.importVisibility = false;
            importer.importBlendShapes = false;
            importer.importCameras = false;
            importer.importLights = false;
            importer.materialImportMode = ModelImporterMaterialImportMode.None;

            // Rename the animation clip
            string fileName = Path.GetFileNameWithoutExtension(path);
            string clipName = ResolveClipName(fileName);

            var clips = importer.clipAnimations;
            if (clips == null || clips.Length == 0)
            {
                // Use default clips
                clips = importer.defaultClipAnimations;
            }

            if (clips != null && clips.Length > 0)
            {
                clips[0].name = clipName;
                clips[0].loopTime = false;
                importer.clipAnimations = clips;
            }

            importer.SaveAndReimport();
            Debug.Log($"[SetupGestureImport] Configured: {Path.GetFileName(path)} → clip='{clipName}'");
            configured++;
        }

        AssetDatabase.Refresh();
        Debug.Log($"[SetupGestureImport] Done. Configured {configured} FBX files.");
        EditorApplication.Exit(0);
    }

    private static string ResolveClipName(string fileName)
    {
        foreach (var (keyword, clipName) in ClipNames)
        {
            if (fileName.IndexOf(keyword, System.StringComparison.OrdinalIgnoreCase) >= 0)
                return clipName;
        }
        return "gesture_beat"; // fallback
    }
}
