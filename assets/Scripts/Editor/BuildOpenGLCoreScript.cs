using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

public static class BuildOpenGLCoreScript
{
    public static void Build()
    {
        EditorBuildSettings.scenes = new[] {
            new EditorBuildSettingsScene("Assets/Scenes/MainScene.unity", true)
        };

        PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneLinux64, false);
        PlayerSettings.SetGraphicsAPIs(
            BuildTarget.StandaloneLinux64,
            new[] { GraphicsDeviceType.OpenGLCore }
        );

        var outputPath = GetCommandLineValue("-buildOutputPath")
            ?? System.IO.Path.Combine(
                System.IO.Directory.GetParent(Application.dataPath).Parent.FullName,
                "MiraLink-Build-GL",
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
            Debug.Log($"BUILD GL OK: {outputPath} ({mb} MB)");
        }
        else
        {
            Debug.LogError($"BUILD GL FAILED: {report.summary.result} errors={report.summary.totalErrors}");
            EditorApplication.Exit(1);
        }
    }

    private static string GetCommandLineValue(string key)
    {
        var args = System.Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length; i++)
        {
            if (string.Equals(args[i], key, System.StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                return args[i + 1];
        }
        return null;
    }
}
