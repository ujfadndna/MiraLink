using UnityEngine;

/// <summary>
/// Keeps the Editor Game View visible while Render Streaming captures Main Camera to a RenderTexture.
/// </summary>
public sealed class GameViewDisplayCamera : MonoBehaviour
{
    [SerializeField] private Camera sourceCamera;
    [SerializeField] private bool onlyWhenSourceUsesTargetTexture = true;
    [SerializeField] private float depthOffset = 0.01f;

    private Camera _displayCamera;

    private void LateUpdate()
    {
        if (!Application.isPlaying)
        {
            return;
        }

        if (sourceCamera == null)
        {
            sourceCamera = Camera.main;
        }

        if (sourceCamera == null)
        {
            SetDisplayCameraEnabled(false);
            return;
        }

        EnsureDisplayCamera();
        SyncDisplayCamera();
    }

    private void OnDisable()
    {
        DestroyDisplayCamera();
    }

    private void OnDestroy()
    {
        DestroyDisplayCamera();
    }

    private void EnsureDisplayCamera()
    {
        if (_displayCamera != null)
        {
            return;
        }

        var go = new GameObject("GameView_DisplayCamera");
        go.transform.SetParent(transform, false);
        _displayCamera = go.AddComponent<Camera>();
        _displayCamera.enabled = false;
    }

    private void SyncDisplayCamera()
    {
        var shouldRender = sourceCamera.isActiveAndEnabled &&
                           (!onlyWhenSourceUsesTargetTexture || sourceCamera.targetTexture != null);

        _displayCamera.CopyFrom(sourceCamera);
        _displayCamera.targetTexture = null;
        _displayCamera.depth = sourceCamera.depth + depthOffset;
        _displayCamera.enabled = shouldRender;

        var sourceTransform = sourceCamera.transform;
        var displayTransform = _displayCamera.transform;
        displayTransform.SetPositionAndRotation(sourceTransform.position, sourceTransform.rotation);
        displayTransform.localScale = sourceTransform.lossyScale;
    }

    private void SetDisplayCameraEnabled(bool enabled)
    {
        if (_displayCamera != null)
        {
            _displayCamera.enabled = enabled;
        }
    }

    private void DestroyDisplayCamera()
    {
        if (_displayCamera == null)
        {
            return;
        }

        var go = _displayCamera.gameObject;
        _displayCamera = null;

        if (Application.isPlaying)
        {
            Destroy(go);
        }
        else
        {
            DestroyImmediate(go);
        }
    }
}
