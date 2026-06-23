using UnityEngine;

// Attach this to M0_Controller (or any persistent GameObject in the scene).
// Call TriggerCapture(path) from Editor scripts to take a screenshot on the next frame.
public class ReliableScreenshotCapture : MonoBehaviour
{
    private string _pendingPath;
    private string _pendingAssetPath;

    // Called from the EditorApplication.update callback on Unity's main thread.
    public void TriggerCapture(string assetRelativePath)
    {
        _pendingAssetPath = assetRelativePath.Replace('\\', '/');
        string projectRoot = System.IO.Directory.GetParent(Application.dataPath).FullName;
        _pendingPath = System.IO.Path.GetFullPath(
            System.IO.Path.Combine(projectRoot, assetRelativePath));
        StartCoroutine(CaptureNextFrame());
    }

    private System.Collections.IEnumerator CaptureNextFrame()
    {
        yield return new WaitForEndOfFrame();
        var tex = ScreenCapture.CaptureScreenshotAsTexture();
        var dir = System.IO.Path.GetDirectoryName(_pendingPath);
        if (!System.IO.Directory.Exists(dir)) System.IO.Directory.CreateDirectory(dir);
        System.IO.File.WriteAllBytes(_pendingPath, tex.EncodeToPNG());
        Destroy(tex);
#if UNITY_EDITOR
        UnityEditor.AssetDatabase.ImportAsset(_pendingAssetPath);
#endif
        Debug.Log($"[ReliableScreenshot] Saved {_pendingPath}");
    }
}
