using System.IO;
using UnityEditor;
using UnityEngine;

public static class ReliableScreenshot
{
    private static string _pendingPath;

    [MenuItem("HerUnity/Take Screenshot (Reliable)")]
    public static void TakeScreenshot() => Schedule("Assets/Screenshots/reliable_screenshot.png");

    public static void Schedule(string assetRelativePath)
    {
        if (!EditorApplication.isPlaying)
        {
            Debug.LogWarning("[ReliableScreenshot] Only works in Play mode.");
            return;
        }
        _pendingPath = assetRelativePath;
        EditorApplication.update += ExecutePending;
    }

    private static void ExecutePending()
    {
        EditorApplication.update -= ExecutePending;
        var capturer = Object.FindAnyObjectByType<ReliableScreenshotCapture>();
        if (capturer == null)
        {
            Debug.LogError("[ReliableScreenshot] ReliableScreenshotCapture not found in scene.");
            return;
        }
        capturer.TriggerCapture(_pendingPath);
        _pendingPath = null;
    }
}
