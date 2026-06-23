using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class GameViewCapture
{
    private const string ScreenshotFolder = "D:/HerUnity/Assets/Screenshots";

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

        Directory.CreateDirectory(ScreenshotFolder);
        string path = Path.Combine(ScreenshotFolder, filename).Replace('\\', '/');
        ScreenCapture.CaptureScreenshot(path);
        Debug.Log($"Game View screenshot capture requested: {path}");
    }
}
