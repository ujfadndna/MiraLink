using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using UnityEditor;
using UnityEngine;

public static class StreamingAudioPlayerFallbackClockTest
{
    public static void Run()
    {
        GameObject root = null;
        Mesh mesh = null;

        try
        {
            root = new GameObject("StreamingAudioPlayerFallbackClockTest");
            var renderer = root.AddComponent<SkinnedMeshRenderer>();
            mesh = CreateFaceMesh();
            renderer.sharedMesh = mesh;

            var facial = root.AddComponent<FacialAnimationController>();
            SetPrivateField(facial, "faceRenderer", renderer);
            SetPrivateField(facial, "streamSmoothMs", 0.0f);
            InvokePrivate(facial, "Awake");

            root.AddComponent<AudioSource>();
            var player = root.AddComponent<StreamingAudioPlayer>();
            SetPrivateField(player, "facialController", facial);
            SetPrivateField(player, "audioClockStallGraceMs", 20.0f);
            InvokePrivate(player, "Awake");

            player.BeginTurn(360.0f, 24000, 0);
            player.EnqueueAnimationPacket(40.0f, 260.0f, new Dictionary<string, float>
            {
                { "mouse_open", 0.82f },
                { "lip_a", 0.65f },
            });

            Thread.Sleep(90);
            InvokePrivate(player, "Update");

            float weight = renderer.GetBlendShapeWeight(0);
            if (weight <= 1.0f)
            {
                throw new Exception($"Expected realtime fallback clock to apply mouthOpen > 1, got {weight:0.###}");
            }

            if (player.CurrentTimeMs < 40.0f)
            {
                throw new Exception($"Expected logical time to advance past packet start, got {player.CurrentTimeMs:0.###}ms");
            }

            Debug.Log($"[StreamingAudioPlayerFallbackClockTest] PASS weight={weight:0.###} currentTimeMs={player.CurrentTimeMs:0.###}");
        }
        finally
        {
            if (root != null)
            {
                UnityEngine.Object.DestroyImmediate(root);
            }

            if (mesh != null)
            {
                UnityEngine.Object.DestroyImmediate(mesh);
            }
        }
    }

    private static Mesh CreateFaceMesh()
    {
        var mesh = new Mesh
        {
            name = "StreamingAudioPlayerFallbackClockTestMesh",
            vertices = new[]
            {
                new Vector3(-0.5f, -0.5f, 0.0f),
                new Vector3(0.5f, -0.5f, 0.0f),
                new Vector3(0.0f, 0.5f, 0.0f),
            },
            triangles = new[] { 0, 1, 2 },
        };
        mesh.RecalculateBounds();

        var deltaVertices = new[]
        {
            Vector3.zero,
            Vector3.zero,
            new Vector3(0.0f, 0.08f, 0.0f),
        };
        var deltaNormals = new Vector3[deltaVertices.Length];
        var deltaTangents = new Vector3[deltaVertices.Length];
        mesh.AddBlendShapeFrame("mouthOpen", 100.0f, deltaVertices, deltaNormals, deltaTangents);
        return mesh;
    }

    private static void SetPrivateField(object target, string fieldName, object value)
    {
        FieldInfo field = target.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
        if (field == null)
        {
            throw new MissingFieldException(target.GetType().Name, fieldName);
        }

        field.SetValue(target, value);
    }

    private static void InvokePrivate(object target, string methodName)
    {
        MethodInfo method = target.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.NonPublic);
        if (method == null)
        {
            throw new MissingMethodException(target.GetType().Name, methodName);
        }

        method.Invoke(target, Array.Empty<object>());
    }
}
