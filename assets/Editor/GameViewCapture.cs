using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class GameViewCapture
{
    [MenuItem("Tools/Capture Game View")]
    public static void CaptureFromMenu()
    {
        Capture($"game-view-{DateTime.Now:yyyyMMdd-HHmmss}.png");
    }

    public static void Capture(string filename)
    {
        if (string.IsNullOrWhiteSpace(filename))
        {
            filename = $"game-view-{DateTime.Now:yyyyMMdd-HHmmss}.png";
        }

        string screenshotFolder = Path.Combine(Application.dataPath, "Screenshots");
        Directory.CreateDirectory(screenshotFolder);
        string path = Path.Combine(screenshotFolder, filename).Replace('\\', '/');
        ScreenCapture.CaptureScreenshot(path);
        Debug.Log($"Game View screenshot capture requested: {path}");
    }
}
