using UnityEditor;
using UnityEngine;

public static class BuildScript
{
    public static void Build()
    {
        // Ensure MainScene is in build settings
        EditorBuildSettings.scenes = new[] {
            new EditorBuildSettingsScene("Assets/Scenes/MainScene.unity", true)
        };

        var outputPath = System.IO.Path.Combine(
            System.IO.Directory.GetParent(Application.dataPath).Parent.FullName,
            "MiraLink-Build",
            "MiraLink.x86_64"
        );
        System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(outputPath));

        var report = BuildPipeline.BuildPlayer(
            EditorBuildSettings.scenes,
            outputPath,
            BuildTarget.StandaloneLinux64,
            BuildOptions.None
        );

        if (report.summary.result == UnityEditor.Build.Reporting.BuildResult.Succeeded)
        {
            long mb = (long)(report.summary.totalSize / 1048576);
            Debug.Log($"BUILD OK: {outputPath} ({mb} MB)");
        }
        else
        {
            Debug.LogError($"BUILD FAILED: {report.summary.result} errors={report.summary.totalErrors}");
            EditorApplication.Exit(1);
        }
    }
}
