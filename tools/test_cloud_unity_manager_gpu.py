from __future__ import annotations

import argparse
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import cloud_unity_manager as manager


def test_parse_nvidia_kernel_driver_version() -> None:
    text = (
        "NVRM version: NVIDIA UNIX x86_64 Kernel Module  570.124.04  "
        "Wed Feb 19 01:11:59 UTC 2025\n"
    )

    assert manager.parse_nvidia_kernel_driver_version(text) == "570.124.04"


def test_pci_bus_to_xorg_bus_id() -> None:
    assert manager.pci_bus_id_to_xorg_bus_id("00000000:5E:00.0") == "PCI:94:0:0"


def test_nvidia_preflight_fails_when_xorg_userland_mismatches_kernel() -> None:
    report = manager.evaluate_gpu_preflight(
        {
            "kernel_version": "570.124.04",
            "nvidia_smi_version": "570.124.04",
            "gpu_pci_bus_id": "00000000:5E:00.0",
            "nvidia_devices": "/dev/nvidia0\n/dev/nvidiactl\n/dev/nvidia-modeset",
            "xorg_nvidia_drv_versions": "580.105.08",
            "xorg_glx_versions": "570.124.04",
            "zero_byte_paths": "",
            "glxinfo": "OpenGL vendor string: NVIDIA Corporation\nOpenGL renderer string: NVIDIA RTX 4090",
        }
    )

    assert not report.ok
    assert any("nvidia_drv.so version mismatch" in issue for issue in report.issues)


@pytest.mark.parametrize(
    "path",
    [
        "/usr/lib/xorg/modules/extensions/libglxserver_nvidia.so",
        "/usr/lib/x86_64-linux-gnu/libnvidia-gpucomp.so.570.124.04",
    ],
)
def test_nvidia_preflight_fails_on_zero_byte_critical_libraries(path: str) -> None:
    report = manager.evaluate_gpu_preflight(
        {
            "kernel_version": "570.124.04",
            "nvidia_smi_version": "570.124.04",
            "gpu_pci_bus_id": "00000000:5E:00.0",
            "nvidia_devices": "/dev/nvidia0\n/dev/nvidiactl\n/dev/nvidia-modeset",
            "xorg_nvidia_drv_versions": "570.124.04",
            "xorg_glx_versions": "570.124.04",
            "zero_byte_paths": path,
            "glxinfo": "OpenGL vendor string: NVIDIA Corporation\nOpenGL renderer string: NVIDIA RTX 4090",
        }
    )

    assert not report.ok
    assert any("zero-byte NVIDIA file" in issue for issue in report.issues)


def test_nvidia_glx_check_rejects_llvmpipe_renderer() -> None:
    report = manager.evaluate_glxinfo(
        "OpenGL vendor string: Mesa/X.org\n"
        "OpenGL renderer string: llvmpipe (LLVM 17.0.6, 256 bits)\n"
    )

    assert not report.ok
    assert "llvmpipe" in " ".join(report.issues)


def test_nvidia_glx_check_accepts_nvidia_renderer() -> None:
    report = manager.evaluate_glxinfo(
        "direct rendering: Yes\n"
        "OpenGL vendor string: NVIDIA Corporation\n"
        "OpenGL renderer string: NVIDIA GeForce RTX 4090/PCIe/SSE2\n"
    )

    assert report.ok
    assert report.vendor == "NVIDIA Corporation"
    assert "llvmpipe" not in report.renderer.lower()


def test_nvidia_preflight_accepts_nonzero_gpu_device_number() -> None:
    report = manager.evaluate_gpu_preflight(
        {
            "kernel_version": "570.124.04",
            "nvidia_smi_version": "570.124.04",
            "gpu_pci_bus_id": "00000000:5E:00.0",
            "nvidia_devices": "/dev/nvidia1\n/dev/nvidiactl\n/dev/nvidia-uvm",
            "xorg_nvidia_drv_versions": "570.124.04",
            "xorg_glx_versions": "570.124.04",
            "zero_byte_paths": "",
            "glxinfo": "OpenGL vendor string: NVIDIA Corporation\nOpenGL renderer string: NVIDIA RTX 3080 Ti",
        }
    )

    assert report.ok


def test_prepare_paths_are_isolated_by_driver_version() -> None:
    paths = manager.nvidia_fix_paths("/tmp/herunity/nvidia-fix", "570.124.04")

    assert paths.extract_dir == "/tmp/herunity/nvidia-fix/NVIDIA-Linux-x86_64-570.124.04"
    assert paths.xorg_module_dir == "/tmp/herunity/nvidia-fix/xorg-modules-570.124.04"
    assert paths.xorg_conf == "/tmp/herunity/nvidia-fix/xorg-herunity-nvidia.conf"


def test_prepare_command_accepts_versioned_glxserver_filename() -> None:
    cmd = manager._prepare_nvidia_xorg_command(
        fix_dir="/tmp/herunity/nvidia-fix",
        version="570.124.04",
        xorg_bus_id="PCI:94:0:0",
        virtual_width=360,
        virtual_height=640,
        download_base_url="https://download.nvidia.com/XFree86/Linux-x86_64",
    )

    assert "libglxserver_nvidia.so'*" in cmd or "libglxserver_nvidia.so*" in cmd
    assert 'ln -sfn "$extracted_glx"' in cmd


def test_start_command_uses_isolated_xorg_modulepath_and_glx_gate() -> None:
    args = argparse.Namespace(
        remote_root="/tmp/herunity/unity",
        remote_log_dir="/tmp/herunity/unity/logs",
        remote_build_dir="/tmp/herunity/unity/HerUnity-Build",
        signal_port=8080,
        stream_width=360,
        stream_height=640,
        nvidia_xorg_conf="/tmp/herunity/nvidia-fix/xorg-herunity-nvidia.conf",
        nvidia_fix_dir="/tmp/herunity/nvidia-fix",
        nvidia_driver_version="570.124.04",
    )

    cmd, env_prefix, _module_dir = manager.build_nvidia_xorg_start_command(args, "python3")

    assert "-modulepath /tmp/herunity/nvidia-fix/xorg-modules-570.124.04" in cmd
    assert "assert_nvidia_glx_or_exit" in cmd
    assert "llvmpipe" in cmd
    assert "/tmp/herunity/nvidia-fix/NVIDIA-Linux-x86_64-570.124.04" in env_prefix
    assert "LD_PRELOAD=/tmp/herunity/nvidia-fix/NVIDIA-Linux-x86_64-570.124.04/libGL.so.1.7.0" in cmd
    assert "\n|| true" not in cmd
