using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class FixMixamoImport
{
    private const string GestureDir = "Assets/Animations/Gestures";
    private const string LogPrefix = "[FixMixamo]";

    [MenuItem("Tools/Avatar/Fix Mixamo Import Root Motion")]
    public static void Run()
    {
        var exitCode = 0;

        try
        {
            File.WriteAllText(GetLogPath(), string.Empty);

            var guids = AssetDatabase.FindAssets("t:Model", new[] { GestureDir });
            var processed = 0;
            var changedClips = 0;

            foreach (var guid in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (!path.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase))
                    continue;

                var importer = AssetImporter.GetAtPath(path) as ModelImporter;
                if (importer == null)
                {
                    LogError($"ModelImporter not found for {path}");
                    exitCode = 1;
                    continue;
                }

                var clips = importer.clipAnimations;
                if (clips == null || clips.Length == 0)
                    clips = importer.defaultClipAnimations;

                if (clips == null || clips.Length == 0)
                {
                    LogError($"No animation clips found in {path}");
                    exitCode = 1;
                    continue;
                }

                for (var i = 0; i < clips.Length; i++)
                {
                    clips[i].lockRootRotation = true;
                    clips[i].lockRootHeightY = true;
                    clips[i].lockRootPositionXZ = true;
                    changedClips++;
                }

                importer.clipAnimations = clips;
                importer.SaveAndReimport();

                processed++;
                Log($"Fixed {Path.GetFileName(path)} clips={clips.Length}");
            }

            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            if (processed != 7)
            {
                LogError($"Expected 7 FBX files in {GestureDir}, processed {processed}.");
                exitCode = 1;
            }
            else
            {
                Log($"Done. Processed {processed} FBX files, updated {changedClips} clip(s).");
            }
        }
        catch (Exception ex)
        {
            LogError($"Failed: {ex}");
            exitCode = 1;
        }
        finally
        {
            if (Application.isBatchMode)
                EditorApplication.Exit(exitCode);
        }
    }

    private static void Log(string message)
    {
        var formatted = $"{LogPrefix} {message}";
        Debug.Log(formatted);
        File.AppendAllText(GetLogPath(), formatted + Environment.NewLine);
    }

    private static void LogError(string message)
    {
        var formatted = $"{LogPrefix} {message}";
        Debug.LogError(formatted);
        File.AppendAllText(GetLogPath(), formatted + Environment.NewLine);
    }

    private static string GetLogPath()
    {
        var projectRoot = Directory.GetParent(Application.dataPath)?.FullName;
        return Path.Combine(projectRoot ?? Directory.GetCurrentDirectory(), "fix_mixamo.log");
    }
}
