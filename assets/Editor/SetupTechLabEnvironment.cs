using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// Builds a lightweight high-tech laboratory environment in MainScene.
/// Usage: -executeMethod SetupTechLabEnvironment.Run
/// </summary>
public static class SetupTechLabEnvironment
{
    private const string ScenePath = "Assets/Scenes/MainScene.unity";
    private const string MaterialDir = "Assets/Materials/TechLab";

    private static readonly Color DarkMetal = new Color(0.075f, 0.085f, 0.1f, 1f);
    private static readonly Color FloorMetal = new Color(0.11f, 0.125f, 0.14f, 1f);
    private static readonly Color WallMetal = new Color(0.065f, 0.075f, 0.09f, 1f);
    private static readonly Color ScreenBlack = new Color(0.005f, 0.02f, 0.035f, 1f);
    private static readonly Color SeatFabric = new Color(0.055f, 0.06f, 0.072f, 1f);
    private static readonly Color Cyan = new Color(0.0f, 0.88f, 1f, 1f);
    private static readonly Color Blue = new Color(0.15f, 0.38f, 1f, 1f);
    private static readonly Color Purple = new Color(0.72f, 0.24f, 1f, 1f);
    private static readonly Color Lime = new Color(0.55f, 1f, 0.28f, 1f);
    private static readonly Color Amber = new Color(1f, 0.75f, 0.24f, 1f);

    public static void Run()
    {
        if (EditorApplication.isPlaying)
        {
            Debug.LogError("[SetupTechLabEnvironment] Exit Play Mode before modifying MainScene.");
            EditorApplication.Exit(1);
            return;
        }

        AssetDatabase.Refresh();
        var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        var materials = CreateMaterials();

        RemoveExistingEnvironment();

        var root = new GameObject("TechLabEnvironment");
        var roomShell = CreateGroup(root, "RoomShell");
        var consoles = CreateGroup(root, "Consoles");
        var wallScreens = CreateGroup(root, "WallScreens");
        var ceilingLights = CreateGroup(root, "CeilingLights");
        var loopingMotion = CreateGroup(root, "LoopingMotion");
        var environmentParticles = CreateGroup(root, "EnvironmentParticles");

        BuildRoomShell(roomShell, materials);
        BuildConsoles(consoles, materials);
        BuildWallScreens(wallScreens, loopingMotion, materials, out var dataStrips, out var breathingLights, out var floatingModules);
        BuildCeilingAndLights(ceilingLights, materials, breathingLights);
        BuildSeatsAndSideProps(consoles, materials);
        BuildAmbientParticles(environmentParticles, materials, out var particleSystems);

        var loop = loopingMotion.gameObject.AddComponent<TechLabEnvironmentLoop>();
        ConfigureLoop(loop, dataStrips, breathingLights, floatingModules, particleSystems);

        ConfigureLightingAndCamera();

        EditorUtility.SetDirty(root);
        EditorSceneManager.MarkSceneDirty(scene);
        EditorSceneManager.SaveScene(scene, ScenePath);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();

        Debug.Log("[SetupTechLabEnvironment] Tech lab environment added to MainScene.");
        Debug.Log("[SetupTechLabEnvironment] Existing Avatar, M0_Controller, RenderStreamingManager, EventSystem and Main Camera sender were preserved.");
    }

    private sealed class LabMaterials
    {
        public Material DarkMetal;
        public Material FloorMetal;
        public Material WallMetal;
        public Material Screen;
        public Material ScreenGlass;
        public Material CyanEmission;
        public Material BlueEmission;
        public Material PurpleEmission;
        public Material LimeEmission;
        public Material AmberEmission;
        public Material Seat;
        public Material Particle;
    }

    private struct DataStripInfo
    {
        public Transform Transform;
        public Vector3 BaseLocalPosition;
        public Vector3 BaseLocalScale;
        public float Phase;
        public float Speed;
        public float Travel;
        public float MinScaleY;
        public float MaxScaleY;
    }

    private struct BreathingLightInfo
    {
        public Renderer Renderer;
        public Light LinkedLight;
        public Color Color;
        public float BaseIntensity;
        public float PulseIntensity;
        public float Phase;
        public float Speed;
    }

    private struct FloatingModuleInfo
    {
        public Transform Transform;
        public Vector3 BaseLocalPosition;
        public Vector3 BaseLocalEuler;
        public float VerticalAmplitude;
        public float VerticalSpeed;
        public float RotationSpeed;
        public float Phase;
    }

    private static LabMaterials CreateMaterials()
    {
        Directory.CreateDirectory(Path.GetFullPath(MaterialDir));

        return new LabMaterials
        {
            DarkMetal = CreateOrUpdateMaterial("TechLab_DarkMetal", DarkMetal, 0.65f, 0.46f),
            FloorMetal = CreateOrUpdateMaterial("TechLab_FloorMetal", FloorMetal, 0.7f, 0.34f),
            WallMetal = CreateOrUpdateMaterial("TechLab_WallMetal", WallMetal, 0.55f, 0.3f),
            Screen = CreateOrUpdateMaterial("TechLab_ScreenBlack", ScreenBlack, 0f, 0.2f, new Color(0f, 0.08f, 0.12f), 0.8f),
            ScreenGlass = CreateOrUpdateMaterial("TechLab_ScreenGlass", new Color(0.02f, 0.09f, 0.13f, 1f), 0.1f, 0.72f, new Color(0f, 0.18f, 0.28f), 0.55f),
            CyanEmission = CreateOrUpdateMaterial("TechLab_Emission_Cyan", Cyan, 0f, 0.25f, Cyan, 2.2f),
            BlueEmission = CreateOrUpdateMaterial("TechLab_Emission_Blue", Blue, 0f, 0.2f, Blue, 1.7f),
            PurpleEmission = CreateOrUpdateMaterial("TechLab_Emission_Purple", Purple, 0f, 0.2f, Purple, 1.9f),
            LimeEmission = CreateOrUpdateMaterial("TechLab_Emission_Lime", Lime, 0f, 0.18f, Lime, 1.55f),
            AmberEmission = CreateOrUpdateMaterial("TechLab_Emission_Amber", Amber, 0f, 0.18f, Amber, 1.45f),
            Seat = CreateOrUpdateMaterial("TechLab_Seat", SeatFabric, 0.15f, 0.42f),
            Particle = CreateOrUpdateMaterial("TechLab_Particle_Cyan", new Color(0.55f, 0.95f, 1f, 0.8f), 0f, 0f, Cyan, 1.6f)
        };
    }

    private static Material CreateOrUpdateMaterial(string name, Color color, float metallic, float smoothness)
    {
        return CreateOrUpdateMaterial(name, color, metallic, smoothness, Color.black, 0f);
    }

    private static Material CreateOrUpdateMaterial(string name, Color color, float metallic, float smoothness, Color emissionColor, float emissionIntensity)
    {
        string path = $"{MaterialDir}/{name}.mat";
        var material = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (material == null)
        {
            material = new Material(Shader.Find("Standard") ?? Shader.Find("Legacy Shaders/Diffuse"));
            AssetDatabase.CreateAsset(material, path);
        }

        material.name = name;
        material.shader = Shader.Find("Standard") ?? material.shader;
        material.color = color;
        if (material.HasProperty("_Metallic"))
            material.SetFloat("_Metallic", metallic);
        if (material.HasProperty("_Glossiness"))
            material.SetFloat("_Glossiness", smoothness);

        if (emissionIntensity > 0f && material.HasProperty("_EmissionColor"))
        {
            material.EnableKeyword("_EMISSION");
            material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            material.SetColor("_EmissionColor", emissionColor * emissionIntensity);
        }
        else
        {
            material.DisableKeyword("_EMISSION");
            material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.EmissiveIsBlack;
            if (material.HasProperty("_EmissionColor"))
                material.SetColor("_EmissionColor", Color.black);
        }

        EditorUtility.SetDirty(material);
        return material;
    }

    private static Transform CreateGroup(GameObject root, string name)
    {
        var group = new GameObject(name);
        group.transform.SetParent(root.transform, false);
        return group.transform;
    }

    private static void RemoveExistingEnvironment()
    {
        DestroyIfFound("TechLabEnvironment");
        DestroyIfFound("Ground");
    }

    private static void DestroyIfFound(string name)
    {
        var found = GameObject.Find(name);
        if (found != null)
            Object.DestroyImmediate(found);
    }

    private static void BuildRoomShell(Transform parent, LabMaterials materials)
    {
        CreateCube("Floor", parent, new Vector3(0f, -0.035f, -1.05f), Vector3.zero, new Vector3(8.5f, 0.07f, 6.9f), materials.FloorMetal);
        CreateCube("BackWall", parent, new Vector3(0f, 1.7f, -4.05f), Vector3.zero, new Vector3(8.5f, 3.45f, 0.12f), materials.WallMetal);
        CreateCube("LeftWall", parent, new Vector3(-4.25f, 1.55f, -1.05f), Vector3.zero, new Vector3(0.12f, 3.1f, 6.15f), materials.WallMetal);
        CreateCube("RightWall", parent, new Vector3(4.25f, 1.55f, -1.05f), Vector3.zero, new Vector3(0.12f, 3.1f, 6.15f), materials.WallMetal);
        CreateCube("CeilingPanel", parent, new Vector3(0f, 3.08f, -1.05f), Vector3.zero, new Vector3(8.5f, 0.1f, 6.15f), materials.DarkMetal);

        for (int i = -4; i <= 4; i++)
        {
            CreateCube($"FloorPanel_Z_{i + 4:00}", parent, new Vector3(0f, 0.006f, -3.8f + i * 0.68f), Vector3.zero, new Vector3(8.2f, 0.018f, 0.016f), materials.DarkMetal);
        }

        for (int i = -4; i <= 4; i++)
        {
            CreateCube($"FloorPanel_X_{i + 4:00}", parent, new Vector3(i * 0.95f, 0.009f, -1.05f), Vector3.zero, new Vector3(0.016f, 0.018f, 6.25f), materials.DarkMetal);
        }

        CreateCube("RearBaseTrim", parent, new Vector3(0f, 0.27f, -3.96f), Vector3.zero, new Vector3(8.2f, 0.18f, 0.16f), materials.DarkMetal);
        CreateCube("LeftBaseTrim", parent, new Vector3(-4.13f, 0.24f, -1.05f), Vector3.zero, new Vector3(0.15f, 0.16f, 5.95f), materials.DarkMetal);
        CreateCube("RightBaseTrim", parent, new Vector3(4.13f, 0.24f, -1.05f), Vector3.zero, new Vector3(0.15f, 0.16f, 5.95f), materials.DarkMetal);

        for (int i = 0; i < 5; i++)
        {
            float x = -3.2f + i * 1.6f;
            CreateCube($"BackWallVerticalRib_{i:00}", parent, new Vector3(x, 1.7f, -3.9f), Vector3.zero, new Vector3(0.045f, 2.75f, 0.1f), materials.DarkMetal);
        }
    }

    private static void BuildConsoles(Transform parent, LabMaterials materials)
    {
        var main = new GameObject("ForegroundAngledConsole");
        main.transform.SetParent(parent, false);
        main.transform.localPosition = new Vector3(0f, 0.42f, 0.72f);
        main.transform.localRotation = Quaternion.Euler(-12f, 0f, 0f);

        CreateCube("ConsoleBody", main.transform, Vector3.zero, Vector3.zero, new Vector3(3.6f, 0.34f, 0.7f), materials.DarkMetal);
        CreateCube("ConsoleTopGlass", main.transform, new Vector3(0f, 0.2f, -0.02f), Vector3.zero, new Vector3(3.35f, 0.035f, 0.56f), materials.ScreenGlass);
        CreateCube("ConsoleCyanEdge", main.transform, new Vector3(0f, 0.235f, -0.31f), Vector3.zero, new Vector3(3.38f, 0.03f, 0.035f), materials.CyanEmission);
        CreateCube("ConsolePurpleEdge", main.transform, new Vector3(0f, 0.235f, 0.31f), Vector3.zero, new Vector3(3.38f, 0.03f, 0.035f), materials.PurpleEmission);

        for (int i = 0; i < 8; i++)
        {
            float x = -1.45f + i * 0.42f;
            var mat = i % 3 == 0 ? materials.LimeEmission : materials.CyanEmission;
            CreateCube($"ConsoleStatusKey_{i:00}", main.transform, new Vector3(x, 0.265f, -0.09f), Vector3.zero, new Vector3(0.16f, 0.016f, 0.08f), mat);
        }

        CreateCube("LeftSideConsole", parent, new Vector3(-2.85f, 0.52f, -0.7f), new Vector3(-6f, 26f, 0f), new Vector3(1.15f, 0.42f, 1.7f), materials.DarkMetal);
        CreateCube("LeftSideConsoleScreen", parent, new Vector3(-2.72f, 0.78f, -0.8f), new Vector3(-12f, 26f, 0f), new Vector3(0.92f, 0.035f, 1.15f), materials.ScreenGlass);
        CreateCube("RightSideConsole", parent, new Vector3(2.85f, 0.52f, -0.7f), new Vector3(-6f, -26f, 0f), new Vector3(1.15f, 0.42f, 1.7f), materials.DarkMetal);
        CreateCube("RightSideConsoleScreen", parent, new Vector3(2.72f, 0.78f, -0.8f), new Vector3(-12f, -26f, 0f), new Vector3(0.92f, 0.035f, 1.15f), materials.ScreenGlass);
    }

    private static void BuildWallScreens(
        Transform parent,
        Transform loopingParent,
        LabMaterials materials,
        out List<DataStripInfo> dataStrips,
        out List<BreathingLightInfo> breathingLights,
        out List<FloatingModuleInfo> floatingModules)
    {
        dataStrips = new List<DataStripInfo>();
        breathingLights = new List<BreathingLightInfo>();
        floatingModules = new List<FloatingModuleInfo>();

        CreateCube("CentralScreenFrame", parent, new Vector3(0f, 1.72f, -3.92f), Vector3.zero, new Vector3(3.35f, 1.72f, 0.08f), materials.DarkMetal);
        CreateCube("CentralScreenPanel", parent, new Vector3(0f, 1.72f, -3.86f), Vector3.zero, new Vector3(3.06f, 1.45f, 0.035f), materials.Screen);

        for (int i = 0; i < 12; i++)
        {
            float x = -1.25f + i * 0.23f;
            float y = 1.18f + (i % 5) * 0.21f;
            var strip = CreateCube($"CentralDataStrip_{i:00}", parent, new Vector3(x, y, -3.82f), Vector3.zero, new Vector3(0.055f, 0.17f + 0.035f * (i % 3), 0.02f), i % 4 == 0 ? materials.LimeEmission : materials.CyanEmission);
            dataStrips.Add(new DataStripInfo
            {
                Transform = strip.transform,
                BaseLocalPosition = strip.transform.localPosition,
                BaseLocalScale = strip.transform.localScale,
                Phase = i * 0.17f,
                Speed = 0.18f + i * 0.018f,
                Travel = 0.42f,
                MinScaleY = 0.08f,
                MaxScaleY = 0.36f
            });
        }

        for (int i = 0; i < 5; i++)
        {
            float y = 1.05f + i * 0.28f;
            var line = CreateCube($"CentralTelemetryLine_{i:00}", parent, new Vector3(0.58f, y, -3.81f), Vector3.zero, new Vector3(1.25f - i * 0.08f, 0.022f, 0.02f), i % 2 == 0 ? materials.BlueEmission : materials.CyanEmission);
            dataStrips.Add(new DataStripInfo
            {
                Transform = line.transform,
                BaseLocalPosition = line.transform.localPosition,
                BaseLocalScale = line.transform.localScale,
                Phase = 0.45f + i * 0.23f,
                Speed = 0.22f + i * 0.04f,
                Travel = 0.12f,
                MinScaleY = 0.018f,
                MaxScaleY = 0.04f
            });
        }

        BuildSideScreenCluster(parent, materials, dataStrips, "Left", -2.75f, 14f);
        BuildSideScreenCluster(parent, materials, dataStrips, "Right", 2.75f, -14f);

        var haloA = CreateCube("CentralScreenCyanHalo", parent, new Vector3(0f, 2.56f, -3.8f), Vector3.zero, new Vector3(3.25f, 0.035f, 0.035f), materials.CyanEmission);
        breathingLights.Add(new BreathingLightInfo
        {
            Renderer = haloA.GetComponent<Renderer>(),
            Color = Cyan,
            BaseIntensity = 1.4f,
            PulseIntensity = 1.4f,
            Phase = 0f,
            Speed = 1.3f
        });

        var haloB = CreateCube("CentralScreenPurpleHalo", parent, new Vector3(0f, 0.88f, -3.8f), Vector3.zero, new Vector3(3.25f, 0.035f, 0.035f), materials.PurpleEmission);
        breathingLights.Add(new BreathingLightInfo
        {
            Renderer = haloB.GetComponent<Renderer>(),
            Color = Purple,
            BaseIntensity = 1.1f,
            PulseIntensity = 1.0f,
            Phase = 1.8f,
            Speed = 1.1f
        });

        for (int i = 0; i < 3; i++)
        {
            var module = new GameObject($"FloatingAnalysisModule_{i:00}");
            module.transform.SetParent(loopingParent, false);
            module.transform.localPosition = new Vector3(-1.8f + i * 1.8f, 2.35f + 0.12f * (i % 2), -2.45f);
            module.transform.localRotation = Quaternion.Euler(0f, i * 36f, 0f);

            CreateCube("Core", module.transform, Vector3.zero, Vector3.zero, new Vector3(0.34f, 0.08f, 0.34f), materials.DarkMetal);
            CreateCube("LightRing_X", module.transform, Vector3.zero, Vector3.zero, new Vector3(0.56f, 0.018f, 0.035f), i == 1 ? materials.PurpleEmission : materials.CyanEmission);
            CreateCube("LightRing_Z", module.transform, Vector3.zero, Vector3.zero, new Vector3(0.035f, 0.018f, 0.56f), i == 1 ? materials.PurpleEmission : materials.CyanEmission);

            floatingModules.Add(new FloatingModuleInfo
            {
                Transform = module.transform,
                BaseLocalPosition = module.transform.localPosition,
                BaseLocalEuler = module.transform.localEulerAngles,
                VerticalAmplitude = 0.08f + i * 0.018f,
                VerticalSpeed = 0.85f + i * 0.18f,
                RotationSpeed = i == 1 ? -18f : 24f,
                Phase = i * 1.35f
            });
        }
    }

    private static void BuildSideScreenCluster(Transform parent, LabMaterials materials, List<DataStripInfo> dataStrips, string sideName, float x, float yaw)
    {
        CreateCube($"{sideName}ScreenFrame", parent, new Vector3(x, 1.62f, -3.63f), new Vector3(0f, yaw, 0f), new Vector3(1.38f, 1.15f, 0.08f), materials.DarkMetal);
        CreateCube($"{sideName}ScreenPanel", parent, new Vector3(x, 1.62f, -3.56f), new Vector3(0f, yaw, 0f), new Vector3(1.16f, 0.93f, 0.035f), materials.Screen);

        for (int i = 0; i < 6; i++)
        {
            var strip = CreateCube($"{sideName}DataStrip_{i:00}", parent, new Vector3(x - 0.38f + i * 0.15f, 1.28f + i * 0.08f, -3.49f), new Vector3(0f, yaw, 0f), new Vector3(0.045f, 0.14f, 0.02f), i % 2 == 0 ? materials.CyanEmission : materials.PurpleEmission);
            dataStrips.Add(new DataStripInfo
            {
                Transform = strip.transform,
                BaseLocalPosition = strip.transform.localPosition,
                BaseLocalScale = strip.transform.localScale,
                Phase = 0.3f + i * 0.27f + (x > 0f ? 0.7f : 0f),
                Speed = 0.2f + i * 0.025f,
                Travel = 0.22f,
                MinScaleY = 0.06f,
                MaxScaleY = 0.23f
            });
        }
    }

    private static void BuildCeilingAndLights(Transform parent, LabMaterials materials, List<BreathingLightInfo> breathingLights)
    {
        for (int i = 0; i < 6; i++)
        {
            float x = -3.3f + i * 1.32f;
            CreateCube($"CeilingRib_X_{i:00}", parent, new Vector3(x, 2.98f, -1.05f), Vector3.zero, new Vector3(0.06f, 0.12f, 5.7f), materials.DarkMetal);
        }

        for (int i = 0; i < 5; i++)
        {
            float z = -3.4f + i * 1.1f;
            CreateCube($"CeilingRib_Z_{i:00}", parent, new Vector3(0f, 2.99f, z), Vector3.zero, new Vector3(7.4f, 0.12f, 0.055f), materials.DarkMetal);
        }

        for (int i = 0; i < 4; i++)
        {
            float x = -2.7f + i * 1.8f;
            var strip = CreateCube($"CeilingCyanLightStrip_{i:00}", parent, new Vector3(x, 2.9f, -1.15f), Vector3.zero, new Vector3(1.05f, 0.035f, 0.08f), materials.CyanEmission);
            var light = CreateLight($"CeilingCyanPoint_{i:00}", parent, LightType.Point, new Vector3(x, 2.62f, -1.05f), Cyan, 1.2f, 3.1f);
            breathingLights.Add(new BreathingLightInfo
            {
                Renderer = strip.GetComponent<Renderer>(),
                LinkedLight = light,
                Color = Cyan,
                BaseIntensity = 1.1f,
                PulseIntensity = 0.9f,
                Phase = i * 0.8f,
                Speed = 1.25f
            });
        }

        var purpleStrip = CreateCube("RearCeilingPurpleLightStrip", parent, new Vector3(0f, 2.9f, -3.22f), Vector3.zero, new Vector3(4.6f, 0.035f, 0.08f), materials.PurpleEmission);
        var purpleLight = CreateLight("RearPurpleWash", parent, LightType.Point, new Vector3(0f, 2.25f, -2.75f), Purple, 1.1f, 4f);
        breathingLights.Add(new BreathingLightInfo
        {
            Renderer = purpleStrip.GetComponent<Renderer>(),
            LinkedLight = purpleLight,
            Color = Purple,
            BaseIntensity = 1f,
            PulseIntensity = 0.75f,
            Phase = 1.2f,
            Speed = 0.9f
        });
    }

    private static void BuildSeatsAndSideProps(Transform parent, LabMaterials materials)
    {
        BuildSeat(parent, materials, "LeftOperatorSeat", new Vector3(-1.95f, 0.34f, -1.15f), 18f);
        BuildSeat(parent, materials, "RightOperatorSeat", new Vector3(1.95f, 0.34f, -1.15f), -18f);

        for (int i = 0; i < 4; i++)
        {
            float x = -3.25f + i * 2.15f;
            CreateCube($"FloorStatusBeacon_{i:00}", parent, new Vector3(x, 0.045f, -2.75f), Vector3.zero, new Vector3(0.12f, 0.035f, 0.12f), i % 2 == 0 ? materials.LimeEmission : materials.AmberEmission);
        }
    }

    private static void BuildSeat(Transform parent, LabMaterials materials, string name, Vector3 position, float yaw)
    {
        var seat = new GameObject(name);
        seat.transform.SetParent(parent, false);
        seat.transform.localPosition = position;
        seat.transform.localRotation = Quaternion.Euler(0f, yaw, 0f);

        CreateCube("SeatBase", seat.transform, new Vector3(0f, 0f, 0f), Vector3.zero, new Vector3(0.58f, 0.12f, 0.58f), materials.Seat);
        CreateCube("SeatBack", seat.transform, new Vector3(0f, 0.42f, 0.27f), new Vector3(-10f, 0f, 0f), new Vector3(0.6f, 0.78f, 0.12f), materials.Seat);
        CreateCube("SeatStem", seat.transform, new Vector3(0f, -0.2f, 0f), Vector3.zero, new Vector3(0.1f, 0.42f, 0.1f), materials.DarkMetal);
        CreateCube("SeatCyanTrim", seat.transform, new Vector3(0f, 0.08f, -0.31f), Vector3.zero, new Vector3(0.52f, 0.035f, 0.035f), materials.CyanEmission);
    }

    private static void BuildAmbientParticles(Transform parent, LabMaterials materials, out List<ParticleSystem> particleSystems)
    {
        particleSystems = new List<ParticleSystem>();

        var mist = new GameObject("AmbientCyanDust");
        mist.transform.SetParent(parent, false);
        mist.transform.localPosition = new Vector3(0f, 1.25f, -1.75f);

        var ps = mist.AddComponent<ParticleSystem>();
        var main = ps.main;
        main.loop = true;
        main.playOnAwake = true;
        main.startLifetime = new ParticleSystem.MinMaxCurve(4.2f, 6.8f);
        main.startSpeed = new ParticleSystem.MinMaxCurve(0.04f, 0.14f);
        main.startSize = new ParticleSystem.MinMaxCurve(0.015f, 0.045f);
        main.startColor = new ParticleSystem.MinMaxGradient(new Color(0.35f, 0.92f, 1f, 0.38f), new Color(0.8f, 0.55f, 1f, 0.28f));
        main.maxParticles = 90;
        main.simulationSpace = ParticleSystemSimulationSpace.World;

        var emission = ps.emission;
        emission.rateOverTime = 13f;

        var shape = ps.shape;
        shape.shapeType = ParticleSystemShapeType.Box;
        shape.scale = new Vector3(6.2f, 1.55f, 3.0f);

        var renderer = mist.GetComponent<ParticleSystemRenderer>();
        renderer.renderMode = ParticleSystemRenderMode.Billboard;
        renderer.sharedMaterial = materials.Particle;
        renderer.sortingFudge = -0.4f;

        particleSystems.Add(ps);
    }

    private static void ConfigureLoop(
        TechLabEnvironmentLoop loop,
        List<DataStripInfo> dataStrips,
        List<BreathingLightInfo> breathingLights,
        List<FloatingModuleInfo> floatingModules,
        List<ParticleSystem> particleSystems)
    {
        var so = new SerializedObject(loop);
        WriteDataStrips(so.FindProperty("dataStrips"), dataStrips);
        WriteBreathingLights(so.FindProperty("breathingLights"), breathingLights);
        WriteFloatingModules(so.FindProperty("floatingModules"), floatingModules);
        WriteParticles(so.FindProperty("ambientParticles"), particleSystems);
        so.ApplyModifiedPropertiesWithoutUndo();
        EditorUtility.SetDirty(loop);
    }

    private static void WriteDataStrips(SerializedProperty property, List<DataStripInfo> items)
    {
        property.arraySize = items.Count;
        for (int i = 0; i < items.Count; i++)
        {
            var entry = property.GetArrayElementAtIndex(i);
            entry.FindPropertyRelative("strip").objectReferenceValue = items[i].Transform;
            entry.FindPropertyRelative("baseLocalPosition").vector3Value = items[i].BaseLocalPosition;
            entry.FindPropertyRelative("baseLocalScale").vector3Value = items[i].BaseLocalScale;
            entry.FindPropertyRelative("phase").floatValue = items[i].Phase;
            entry.FindPropertyRelative("speed").floatValue = items[i].Speed;
            entry.FindPropertyRelative("travel").floatValue = items[i].Travel;
            entry.FindPropertyRelative("minScaleY").floatValue = items[i].MinScaleY;
            entry.FindPropertyRelative("maxScaleY").floatValue = items[i].MaxScaleY;
        }
    }

    private static void WriteBreathingLights(SerializedProperty property, List<BreathingLightInfo> items)
    {
        property.arraySize = items.Count;
        for (int i = 0; i < items.Count; i++)
        {
            var entry = property.GetArrayElementAtIndex(i);
            entry.FindPropertyRelative("renderer").objectReferenceValue = items[i].Renderer;
            entry.FindPropertyRelative("linkedLight").objectReferenceValue = items[i].LinkedLight;
            entry.FindPropertyRelative("color").colorValue = items[i].Color;
            entry.FindPropertyRelative("baseIntensity").floatValue = items[i].BaseIntensity;
            entry.FindPropertyRelative("pulseIntensity").floatValue = items[i].PulseIntensity;
            entry.FindPropertyRelative("phase").floatValue = items[i].Phase;
            entry.FindPropertyRelative("speed").floatValue = items[i].Speed;
        }
    }

    private static void WriteFloatingModules(SerializedProperty property, List<FloatingModuleInfo> items)
    {
        property.arraySize = items.Count;
        for (int i = 0; i < items.Count; i++)
        {
            var entry = property.GetArrayElementAtIndex(i);
            entry.FindPropertyRelative("module").objectReferenceValue = items[i].Transform;
            entry.FindPropertyRelative("baseLocalPosition").vector3Value = items[i].BaseLocalPosition;
            entry.FindPropertyRelative("baseLocalEuler").vector3Value = items[i].BaseLocalEuler;
            entry.FindPropertyRelative("verticalAmplitude").floatValue = items[i].VerticalAmplitude;
            entry.FindPropertyRelative("verticalSpeed").floatValue = items[i].VerticalSpeed;
            entry.FindPropertyRelative("rotationSpeed").floatValue = items[i].RotationSpeed;
            entry.FindPropertyRelative("phase").floatValue = items[i].Phase;
        }
    }

    private static void WriteParticles(SerializedProperty property, List<ParticleSystem> items)
    {
        property.arraySize = items.Count;
        for (int i = 0; i < items.Count; i++)
        {
            property.GetArrayElementAtIndex(i).objectReferenceValue = items[i];
        }
    }

    private static void ConfigureLightingAndCamera()
    {
        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
        RenderSettings.ambientLight = new Color(0.19f, 0.24f, 0.31f, 1f);
        RenderSettings.fog = true;
        RenderSettings.fogColor = new Color(0.025f, 0.045f, 0.065f, 1f);
        RenderSettings.fogDensity = 0.012f;

        var directional = GameObject.Find("Directional Light");
        if (directional != null)
        {
            var light = directional.GetComponent<Light>();
            if (light != null)
            {
                light.intensity = 0.42f;
                light.color = new Color(0.78f, 0.88f, 1f, 1f);
                directional.transform.rotation = Quaternion.Euler(42f, -28f, 18f);
                EditorUtility.SetDirty(light);
            }
        }

        DestroyIfFound("TechLab_KeyFaceLight");
        DestroyIfFound("TechLab_RimLight");
        DestroyIfFound("TechLab_ScreenWash");

        CreateRootLight("TechLab_KeyFaceLight", LightType.Point, new Vector3(0f, 1.65f, 0.9f), new Color(0.72f, 0.92f, 1f, 1f), 2.2f, 3.0f);
        CreateRootLight("TechLab_RimLight", LightType.Point, new Vector3(-1.35f, 1.55f, 2.1f), Cyan, 1.45f, 3.2f);
        CreateRootLight("TechLab_ScreenWash", LightType.Point, new Vector3(0f, 1.55f, -2.85f), new Color(0.24f, 0.66f, 1f, 1f), 1.35f, 3.8f);

        var camera = Camera.main;
        if (camera != null)
        {
            camera.transform.position = new Vector3(0f, 1.43f, 1.72f);
            camera.transform.rotation = Quaternion.Euler(5.5f, 180f, 0f);
            camera.fieldOfView = 42f;
            camera.nearClipPlane = 0.05f;
            camera.farClipPlane = 60f;
            camera.backgroundColor = new Color(0.025f, 0.045f, 0.068f, 1f);
            EditorUtility.SetDirty(camera);
            EditorUtility.SetDirty(camera.transform);
        }
    }

    private static GameObject CreateCube(string name, Transform parent, Vector3 localPosition, Vector3 localEuler, Vector3 localScale, Material material)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.name = name;
        var collider = go.GetComponent<Collider>();
        if (collider != null)
            Object.DestroyImmediate(collider);
        go.transform.SetParent(parent, false);
        go.transform.localPosition = localPosition;
        go.transform.localRotation = Quaternion.Euler(localEuler);
        go.transform.localScale = localScale;
        if (go.TryGetComponent<Renderer>(out var renderer))
            renderer.sharedMaterial = material;
        return go;
    }

    private static Light CreateLight(string name, Transform parent, LightType type, Vector3 localPosition, Color color, float intensity, float range)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent, false);
        go.transform.localPosition = localPosition;
        var light = go.AddComponent<Light>();
        light.type = type;
        light.color = color;
        light.intensity = intensity;
        light.range = range;
        return light;
    }

    private static Light CreateRootLight(string name, LightType type, Vector3 position, Color color, float intensity, float range)
    {
        var go = new GameObject(name);
        go.transform.position = position;
        var light = go.AddComponent<Light>();
        light.type = type;
        light.color = color;
        light.intensity = intensity;
        light.range = range;
        return light;
    }
}
