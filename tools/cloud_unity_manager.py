"""Manage a cloud Unity RenderStreaming runtime over Paramiko.

SSH credentials are read from:
  SEETA_SSH_HOST, SEETA_SSH_PORT, SEETA_SSH_USER, SEETA_SSH_PASSWORD
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import posixpath
import re
import shlex
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REMOTE_ROOT = "/tmp/MiraLink/unity"
DEFAULT_NVIDIA_FIX_DIR = "/tmp/MiraLink/nvidia-fix"
DEFAULT_NVIDIA_DOWNLOAD_BASE_URL = "https://download.nvidia.com/XFree86/Linux-x86_64"
NVIDIA_VERSION_PATTERN = r"\d{3}\.\d{2,3}(?:\.\d{2})?"
NVIDIA_VERSION_RE = re.compile(r"\b" + NVIDIA_VERSION_PATTERN + r"\b")


@dataclass(frozen=True)
class GLXReport:
    ok: bool
    vendor: str
    renderer: str
    issues: tuple[str, ...]


@dataclass(frozen=True)
class GPUPreflightReport:
    ok: bool
    kernel_version: str
    nvidia_smi_version: str
    gpu_pci_bus_id: str
    xorg_bus_id: str
    issues: tuple[str, ...]


@dataclass(frozen=True)
class NvidiaFixPaths:
    fix_dir: str
    cache_dir: str
    extract_dir: str
    xorg_module_dir: str
    xorg_conf: str
    current_version_file: str


def _first_line(text: str) -> str:
    for line in text.splitlines():
        value = line.strip()
        if value:
            return value
    return ""


def _version_set(text: str) -> set[str]:
    return set(NVIDIA_VERSION_RE.findall(text or ""))


def parse_nvidia_kernel_driver_version(text: str) -> str:
    match = re.search(r"Kernel Module\s+(" + NVIDIA_VERSION_PATTERN + r")", text or "")
    if match:
        return match.group(1)
    versions = sorted(_version_set(text))
    return versions[0] if versions else ""


def pci_bus_id_to_xorg_bus_id(pci_bus_id: str) -> str:
    value = _first_line(pci_bus_id)
    match = re.fullmatch(
        r"(?:(?P<domain>[0-9A-Fa-f]{8}):)?(?P<bus>[0-9A-Fa-f]{2}):"
        r"(?P<device>[0-9A-Fa-f]{2})\.(?P<function>[0-7])",
        value,
    )
    if not match:
        raise ValueError(f"invalid NVIDIA PCI bus id: {pci_bus_id!r}")
    bus = int(match.group("bus"), 16)
    device = int(match.group("device"), 16)
    function = int(match.group("function"), 10)
    return f"PCI:{bus}:{device}:{function}"


def _extract_glx_field(glxinfo: str, label: str) -> str:
    prefix = label.lower() + ":"
    for line in (glxinfo or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    return ""


def evaluate_glxinfo(glxinfo: str) -> GLXReport:
    vendor = _extract_glx_field(glxinfo, "OpenGL vendor string")
    renderer = _extract_glx_field(glxinfo, "OpenGL renderer string")
    issues: list[str] = []
    lowered = (glxinfo or "").lower()

    if not vendor:
        issues.append("glxinfo missing OpenGL vendor string")
    elif "nvidia" not in vendor.lower():
        issues.append(f"OpenGL vendor is not NVIDIA: {vendor}")
    if not renderer:
        issues.append("glxinfo missing OpenGL renderer string")
    elif "llvmpipe" in renderer.lower() or "software rasterizer" in renderer.lower():
        issues.append(f"OpenGL renderer is software: {renderer}")
    if "llvmpipe" in lowered and not any("llvmpipe" in issue.lower() for issue in issues):
        issues.append("OpenGL renderer output contains llvmpipe")
    return GLXReport(ok=not issues, vendor=vendor, renderer=renderer, issues=tuple(issues))


def evaluate_gpu_preflight(data: dict[str, str]) -> GPUPreflightReport:
    kernel_version = (
        data.get("kernel_version", "").strip()
        or parse_nvidia_kernel_driver_version(data.get("kernel_version_raw", ""))
    )
    nvidia_smi_version = _first_line(data.get("nvidia_smi_version", ""))
    gpu_pci_bus_id = _first_line(data.get("gpu_pci_bus_id", ""))
    issues: list[str] = []

    if not kernel_version:
        issues.append("NVIDIA kernel driver version not found")
    if not nvidia_smi_version:
        issues.append("nvidia-smi driver version not found")
    elif kernel_version and nvidia_smi_version != kernel_version:
        issues.append(
            f"nvidia-smi driver version mismatch: kernel {kernel_version}, nvidia-smi {nvidia_smi_version}"
        )

    xorg_bus_id = ""
    if not gpu_pci_bus_id:
        issues.append("GPU PCI bus id not found")
    else:
        try:
            xorg_bus_id = pci_bus_id_to_xorg_bus_id(gpu_pci_bus_id)
        except ValueError as exc:
            issues.append(str(exc))

    nvidia_devices = data.get("nvidia_devices", "")
    if "/dev/nvidiactl" not in nvidia_devices:
        issues.append("required NVIDIA device missing: /dev/nvidiactl")
    if not re.search(r"/dev/nvidia\d+\b", nvidia_devices):
        issues.append("required NVIDIA GPU device missing: /dev/nvidia[0-9]+")

    nvidia_drv_versions = _version_set(data.get("xorg_nvidia_drv_versions", ""))
    if not nvidia_drv_versions:
        issues.append("nvidia_drv.so version not found")
    elif kernel_version and kernel_version not in nvidia_drv_versions:
        found = ",".join(sorted(nvidia_drv_versions))
        issues.append(f"nvidia_drv.so version mismatch: kernel {kernel_version}, found {found}")

    glx_versions = _version_set(data.get("xorg_glx_versions", ""))
    if not glx_versions:
        issues.append("libglxserver_nvidia.so version not found")
    elif kernel_version and kernel_version not in glx_versions:
        found = ",".join(sorted(glx_versions))
        issues.append(f"libglxserver_nvidia.so version mismatch: kernel {kernel_version}, found {found}")

    zero_byte_paths = [line.strip() for line in data.get("zero_byte_paths", "").splitlines() if line.strip()]
    for path in zero_byte_paths:
        issues.append(f"zero-byte NVIDIA file: {path}")

    glxinfo = data.get("glxinfo", "")
    if "OpenGL vendor string" in glxinfo or "OpenGL renderer string" in glxinfo or "llvmpipe" in glxinfo.lower():
        glx_report = evaluate_glxinfo(glxinfo)
        issues.extend(glx_report.issues)

    return GPUPreflightReport(
        ok=not issues,
        kernel_version=kernel_version,
        nvidia_smi_version=nvidia_smi_version,
        gpu_pci_bus_id=gpu_pci_bus_id,
        xorg_bus_id=xorg_bus_id,
        issues=tuple(issues),
    )


def nvidia_fix_paths(fix_dir: str, version: str) -> NvidiaFixPaths:
    clean_fix_dir = fix_dir.rstrip("/")
    return NvidiaFixPaths(
        fix_dir=clean_fix_dir,
        cache_dir=posixpath.join(clean_fix_dir, "cache"),
        extract_dir=posixpath.join(clean_fix_dir, f"NVIDIA-Linux-x86_64-{version}"),
        xorg_module_dir=posixpath.join(clean_fix_dir, f"xorg-modules-{version}"),
        xorg_conf=posixpath.join(clean_fix_dir, "xorg-miralink-nvidia.conf"),
        current_version_file=posixpath.join(clean_fix_dir, "current-driver-version"),
    )


def nvidia_runtime_ld_path(paths: NvidiaFixPaths) -> str:
    return f"{paths.extract_dir}:/usr/lib/x86_64-linux-gnu:${{LD_LIBRARY_PATH:-}}"


def nvidia_runtime_ld_env(paths: NvidiaFixPaths) -> str:
    return f"{paths.extract_dir}:/usr/lib/x86_64-linux-gnu"


def nvidia_gl_preload(paths: NvidiaFixPaths) -> str:
    return posixpath.join(paths.extract_dir, "libGL.so.1.7.0")


def build_nvidia_xorg_start_command(
    args: argparse.Namespace,
    py: str,
) -> tuple[str, str, str]:
    version = getattr(args, "nvidia_driver_version", "").strip()
    if not version:
        raise RuntimeError("nvidia_driver_version is required for nvidia-xorg startup")
    paths = nvidia_fix_paths(args.nvidia_fix_dir, version)
    xorg_conf = args.nvidia_xorg_conf or paths.xorg_conf
    virtual_width = max(args.stream_width, 360)
    virtual_height = max(args.stream_height, 640)
    display_log = posixpath.join(args.remote_log_dir, "display.log")
    display_stdout = posixpath.join(args.remote_log_dir, "display.stdout.log")
    env_prefix = f"LD_LIBRARY_PATH={nvidia_runtime_ld_path(paths)}"

    ensure_virtual_cmd = (
        f"if test -f {shlex.quote(xorg_conf)}; then\n"
        f"{shlex.quote(py)} - {shlex.quote(xorg_conf)} {virtual_width} {virtual_height} <<'PY'\n"
        "import pathlib, re, sys\n"
        "path = pathlib.Path(sys.argv[1])\n"
        "target_w = int(sys.argv[2])\n"
        "target_h = int(sys.argv[3])\n"
        "text = path.read_text()\n"
        "match = re.search(r'(?im)^(\\s*Virtual\\s+)(\\d+)\\s+(\\d+)(\\s*)$', text)\n"
        "if match:\n"
        "    old_w = int(match.group(2))\n"
        "    old_h = int(match.group(3))\n"
        "    new_w = max(old_w, target_w)\n"
        "    new_h = max(old_h, target_h)\n"
        "    if (new_w, new_h) != (old_w, old_h):\n"
        "        text = text[:match.start()] + f'{match.group(1)}{new_w} {new_h}{match.group(4)}' + text[match.end():]\n"
        "        path.write_text(text)\n"
        "        print(f'updated Xorg Virtual {old_w}x{old_h} -> {new_w}x{new_h}')\n"
        "    else:\n"
        "        print(f'Xorg Virtual {old_w}x{old_h} covers target {target_w}x{target_h}')\n"
        "else:\n"
        "    print('Xorg Virtual line not found; leaving config unchanged')\n"
        "PY\n"
        "fi\n"
    )
    glx_assert = (
        "assert_nvidia_glx_or_exit() {\n"
        "  glx_out=$(DISPLAY=:99 "
        f"LD_LIBRARY_PATH={nvidia_runtime_ld_path(paths)} LD_PRELOAD={shlex.quote(nvidia_gl_preload(paths))} "
        "glxinfo -B 2>&1) || { echo \"$glx_out\"; exit 14; }\n"
        "  echo \"$glx_out\" | egrep 'OpenGL vendor|OpenGL renderer|OpenGL core profile version|direct rendering' || true\n"
        "  vendor=$(printf '%s\\n' \"$glx_out\" | awk -F': ' '/OpenGL vendor string:/ {print $2; exit}')\n"
        "  renderer=$(printf '%s\\n' \"$glx_out\" | awk -F': ' '/OpenGL renderer string:/ {print $2; exit}')\n"
        "  case \"$vendor\" in *NVIDIA*) ;; *) echo \"NVIDIA GLX check failed: vendor=$vendor\" >&2; exit 15 ;; esac\n"
        "  case \"$renderer\" in *llvmpipe*|*'software rasterizer'*) echo \"NVIDIA GLX check failed: renderer=$renderer\" >&2; exit 16 ;; esac\n"
        "}\n"
    )
    cmd = (
        ensure_virtual_cmd
        + "rm -f /tmp/.X99-lock /tmp/.X11-unix/X99\n"
        + glx_assert
        + f"LD_LIBRARY_PATH={nvidia_runtime_ld_path(paths)} "
        + f"nohup Xorg :99 -config {shlex.quote(xorg_conf)} "
        + f"-modulepath {shlex.quote(paths.xorg_module_dir)},/usr/lib/xorg/modules "
        + f"-logfile {shlex.quote(display_log)} "
        + "-noreset +extension GLX +extension RANDR +extension RENDER "
        + f">> {shlex.quote(display_stdout)} 2>&1 < /dev/null &\n"
        + "sleep 5\n"
        + "assert_nvidia_glx_or_exit\n"
    )
    return cmd, env_prefix, paths.xorg_module_dir


def _remote_json_probe_command() -> str:
    return r"""
set +e
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "python3 not found" >&2
  exit 2
fi
"$PY" - <<'PY'
import glob
import json
import os
import subprocess

def run(cmd):
    proc = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.stdout.strip()

def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""

def versions_for(paths):
    chunks = []
    for path in paths:
        if not os.path.exists(path) or os.path.isdir(path):
            continue
        chunks.append("== %s ==" % path)
        chunks.append(run("strings %s | grep -Eo '[0-9]{3}\\.[0-9]{2,3}(\\.[0-9]{2})?' | sort -u" % subprocess.list2cmdline([path])))
    return "\n".join(chunks)

zero_paths = []
for pattern in [
    "/usr/lib/xorg/modules/drivers/nvidia_drv.so*",
    "/usr/lib/xorg/modules/extensions/libglxserver_nvidia.so*",
    "/usr/lib/x86_64-linux-gnu/libnvidia-gpucomp.so*",
]:
    for path in glob.glob(pattern):
        try:
            if os.path.isfile(path) and os.path.getsize(path) == 0:
                zero_paths.append(path)
        except OSError:
            pass

data = {
    "kernel_version_raw": read("/proc/driver/nvidia/version"),
    "nvidia_smi_version": run("nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1"),
    "gpu_pci_bus_id": run("nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader | head -1"),
    "nvidia_devices": run("ls -l /dev/nvidia* 2>/dev/null"),
    "xorg_nvidia_drv_versions": versions_for(glob.glob("/usr/lib/xorg/modules/drivers/nvidia_drv.so*")),
    "xorg_glx_versions": versions_for(glob.glob("/usr/lib/xorg/modules/extensions/libglxserver_nvidia.so*")),
    "zero_byte_paths": "\n".join(sorted(zero_paths)),
    "glxinfo": run("DISPLAY=:99 glxinfo -B 2>&1") if run("command -v glxinfo >/dev/null 2>&1; echo $?") == "0" else "",
}
print(json.dumps(data))
PY
"""


def collect_gpu_preflight_data(client: paramiko.SSHClient) -> dict[str, str]:
    output = run(client, _remote_json_probe_command(), timeout=60)
    raw = output.strip().splitlines()[-1]
    data = json.loads(raw)
    data["kernel_version"] = parse_nvidia_kernel_driver_version(data.get("kernel_version_raw", ""))
    return {key: str(value) for key, value in data.items()}


def gpu_preflight(client: paramiko.SSHClient, args: argparse.Namespace) -> GPUPreflightReport:
    data = collect_gpu_preflight_data(client)
    report = evaluate_gpu_preflight(data)
    print(json.dumps({
        "ok": report.ok,
        "kernel_version": report.kernel_version,
        "nvidia_smi_version": report.nvidia_smi_version,
        "gpu_pci_bus_id": report.gpu_pci_bus_id,
        "xorg_bus_id": report.xorg_bus_id,
        "issues": list(report.issues),
    }, indent=2))
    if not report.ok:
        raise RuntimeError("GPU preflight failed")
    return report


def _shell_write_xorg_conf_command(path: str, bus_id: str, virtual_width: int, virtual_height: int) -> str:
    conf = f"""Section "ServerLayout"
    Identifier "MIRALINK"
    Screen 0 "Screen0" 0 0
EndSection

Section "Device"
    Identifier "Device0"
    Driver "nvidia"
    VendorName "NVIDIA Corporation"
    BusID "{bus_id}"
    Option "AllowEmptyInitialConfiguration" "true"
    Option "UseDisplayDevice" "none"
EndSection

Section "Screen"
    Identifier "Screen0"
    Device "Device0"
    DefaultDepth 24
    Option "AllowEmptyInitialConfiguration" "true"
    SubSection "Display"
        Depth 24
        Virtual {virtual_width} {virtual_height}
    EndSubSection
EndSection
"""
    return f"cat > {shlex.quote(path)} <<'EOF'\n{conf}EOF\n"


def _prepare_nvidia_xorg_command(
    *,
    fix_dir: str,
    version: str,
    xorg_bus_id: str,
    virtual_width: int,
    virtual_height: int,
    download_base_url: str,
) -> str:
    paths = nvidia_fix_paths(fix_dir, version)
    run_name = f"NVIDIA-Linux-x86_64-{version}-no-compat32.run"
    sha_name = run_name + ".sha256sum"
    base = download_base_url.rstrip("/") + f"/{version}"
    run_url = f"{base}/{run_name}"
    sha_url = f"{base}/{sha_name}"
    run_path = posixpath.join(paths.cache_dir, run_name)
    sha_path = posixpath.join(paths.cache_dir, sha_name)
    module_driver_dir = posixpath.join(paths.xorg_module_dir, "drivers")
    module_extension_dir = posixpath.join(paths.xorg_module_dir, "extensions")
    extracted_driver = posixpath.join(paths.extract_dir, "nvidia_drv.so")
    extracted_glx = posixpath.join(paths.extract_dir, f"libglxserver_nvidia.so.{version}")

    return f"""
set -euo pipefail
mkdir -p {shlex.quote(paths.cache_dir)} {shlex.quote(module_driver_dir)} {shlex.quote(module_extension_dir)}
cd {shlex.quote(paths.cache_dir)}
if [ ! -s {shlex.quote(run_path)} ]; then
  curl -fL --retry 3 --connect-timeout 15 -o {shlex.quote(run_path)} {shlex.quote(run_url)}
fi
curl -fL --retry 3 --connect-timeout 15 -o {shlex.quote(sha_path)} {shlex.quote(sha_url)}
sha256sum -c {shlex.quote(sha_path)}
if [ ! -s {shlex.quote(extracted_driver)} ] || ! ls {shlex.quote(posixpath.join(paths.extract_dir, "libglxserver_nvidia.so"))}* >/dev/null 2>&1; then
  rm -rf {shlex.quote(paths.extract_dir)}
  sh {shlex.quote(run_path)} --extract-only --target {shlex.quote(paths.extract_dir)}
fi
test -s {shlex.quote(extracted_driver)}
extracted_glx=$(ls {shlex.quote(posixpath.join(paths.extract_dir, "libglxserver_nvidia.so"))}* | head -1)
test -s "$extracted_glx"
ln -sfn {shlex.quote(extracted_driver)} {shlex.quote(posixpath.join(module_driver_dir, "nvidia_drv.so"))}
ln -sfn "$extracted_glx" {shlex.quote(posixpath.join(module_extension_dir, "libglxserver_nvidia.so"))}
printf '%s' {shlex.quote(version)} > {shlex.quote(paths.current_version_file)}
{_shell_write_xorg_conf_command(paths.xorg_conf, xorg_bus_id, virtual_width, virtual_height)}
echo "prepared NVIDIA Xorg userland version={version} bus_id={xorg_bus_id} modulepath={paths.xorg_module_dir} conf={paths.xorg_conf}"
"""


def prepare_nvidia_xorg(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    data = collect_gpu_preflight_data(client)
    kernel_version = data.get("kernel_version", "").strip()
    if not kernel_version:
        raise RuntimeError("NVIDIA kernel driver version not found; cannot prepare Xorg userland")
    gpu_pci_bus_id = data.get("gpu_pci_bus_id", "").strip()
    xorg_bus_id = pci_bus_id_to_xorg_bus_id(gpu_pci_bus_id)
    virtual_width = max(args.stream_width, 360)
    virtual_height = max(args.stream_height, 640)
    cmd = _prepare_nvidia_xorg_command(
        fix_dir=args.nvidia_fix_dir,
        version=kernel_version,
        xorg_bus_id=xorg_bus_id,
        virtual_width=virtual_width,
        virtual_height=virtual_height,
        download_base_url=args.nvidia_download_base_url,
    )
    print(run(client, cmd, timeout=600))
    args.nvidia_driver_version = kernel_version
    args.nvidia_xorg_conf = nvidia_fix_paths(args.nvidia_fix_dir, kernel_version).xorg_conf


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def env_int(name: str) -> int:
    raw = env_required(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer; got {raw!r}") from exc


def connect() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=env_required("SEETA_SSH_HOST"),
        port=env_int("SEETA_SSH_PORT"),
        username=env_required("SEETA_SSH_USER"),
        password=env_required("SEETA_SSH_PASSWORD"),
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    return client


def redact_text(text: str, values: list[str] | tuple[str, ...] = ()) -> str:
    result = text
    for value in values:
        if value:
            result = result.replace(value, "***REDACTED***")
    return result


def run(
    client: paramiko.SSHClient,
    command: str,
    *,
    timeout: int = 60,
    check: bool = True,
    redact_values: list[str] | tuple[str, ...] = (),
) -> str:
    wrapped = "bash -lc " + shlex.quote(command)
    stdin, stdout, stderr = client.exec_command(wrapped, timeout=timeout)
    del stdin
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    text = (out + err).strip()
    if check and status != 0:
        raise RuntimeError(
            f"remote command failed ({status}): "
            f"{redact_text(command, redact_values)}\n{redact_text(text, redact_values)}"
        )
    return redact_text(text, redact_values)


def ensure_dirs(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    run(
        client,
        "mkdir -p "
        + " ".join(
            shlex.quote(path)
            for path in [
                args.remote_root,
                args.remote_build_dir,
                args.remote_signalling_dir,
                args.remote_log_dir,
                args.remote_run_dir,
            ]
        ),
    )


def upload_file(
    client: paramiko.SSHClient,
    local_path: Path,
    remote_path: str,
    *,
    mode: int | None = None,
) -> None:
    if not local_path.is_file():
        raise RuntimeError(f"local file not found: {local_path}")
    run(client, f"mkdir -p {shlex.quote(posixpath.dirname(remote_path))}")
    with client.open_sftp() as sftp:
        sftp.put(str(local_path), remote_path)
        if mode is not None:
            sftp.chmod(remote_path, mode)
    print(f"uploaded {local_path} -> {remote_path}")


def write_remote_text(
    client: paramiko.SSHClient,
    remote_path: str,
    text: str,
    *,
    mode: int | None = None,
    label: str | None = None,
) -> None:
    run(client, f"mkdir -p {shlex.quote(posixpath.dirname(remote_path))}")
    with client.open_sftp() as sftp:
        with sftp.open(remote_path, "w") as handle:
            handle.write(text)
        if mode is not None:
            sftp.chmod(remote_path, mode)
    printable = label or remote_path
    print(f"wrote {printable} len={len(text)} -> {remote_path}")


def require_turn_config(args: argparse.Namespace, turn_urls: str, turn_username: str, turn_credential: str) -> None:
    if args.ice_transport_policy.lower() != "relay":
        return
    missing = []
    if not turn_urls:
        missing.append("TURN_URLS/--turn-urls")
    if not turn_username:
        missing.append("TURN_USERNAME/--turn-username")
    if not turn_credential:
        missing.append("TURN_CREDENTIAL/--turn-credential")
    if missing:
        raise RuntimeError(
            "ICE relay mode requires complete TURN config: " + ", ".join(missing)
        )


def remote_turn_credential_path(args: argparse.Namespace) -> str:
    return posixpath.join(args.remote_run_dir, "turn_credential.txt")


def upload_signalling(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    ensure_dirs(client, args)
    upload_file(
        client,
        ROOT / "tools" / "server_v3.py",
        posixpath.join(args.remote_signalling_dir, "server_v3.py"),
        mode=0o644,
    )
    upload_file(
        client,
        ROOT / "frontend" / "avatar_touch.html",
        posixpath.join(args.remote_signalling_dir, "frontend", "avatar_touch.html"),
        mode=0o644,
    )


def mkdir_remote(client: paramiko.SSHClient, remote_path: str) -> None:
    run(client, f"mkdir -p {shlex.quote(remote_path)}")


def upload_build(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    local_build_dir = Path(args.local_build_dir).resolve()
    exe = local_build_dir / "MiraLink.x86_64"
    data_dir = local_build_dir / "MiraLink_Data"
    player = local_build_dir / "UnityPlayer.so"
    missing = [str(path) for path in [exe, data_dir, player] if not path.exists()]
    if missing:
        raise RuntimeError("local build is incomplete: " + ", ".join(missing))

    ensure_dirs(client, args)
    archive_path = None
    try:
        fd, raw_archive_path = tempfile.mkstemp(prefix="MIRALINK-build-", suffix=".tar.gz")
        os.close(fd)
        archive_path = Path(raw_archive_path)
        print(f"packing build archive: {archive_path}")
        with tarfile.open(archive_path, "w:gz") as tar:
            for path in sorted(local_build_dir.rglob("*")):
                tar.add(path, arcname=path.relative_to(local_build_dir).as_posix())

        size_mb = archive_path.stat().st_size / 1048576
        remote_archive = posixpath.join(args.remote_root, "MiraLink-Build.tar.gz")
        print(f"uploading archive ({size_mb:.1f} MB) -> {remote_archive}")
        uploaded_marks: set[int] = set()

        def progress(sent: int, total: int) -> None:
            if not total:
                return
            mark = int(sent * 100 / total)
            bucket = mark // 10 * 10
            if bucket in uploaded_marks or bucket <= 0:
                return
            uploaded_marks.add(bucket)
            print(f"upload {bucket}%")

        with client.open_sftp() as sftp:
            sftp.put(str(archive_path), remote_archive, callback=progress)

        print("extracting remote build")
        extract_cmd = f"""
set -e
rm -rf {shlex.quote(args.remote_build_dir)}
mkdir -p {shlex.quote(args.remote_build_dir)}
tar -xzf {shlex.quote(remote_archive)} -C {shlex.quote(args.remote_build_dir)}
chmod +x {shlex.quote(posixpath.join(args.remote_build_dir, 'MiraLink.x86_64'))}
test -x {shlex.quote(posixpath.join(args.remote_build_dir, 'MiraLink.x86_64'))}
test -d {shlex.quote(posixpath.join(args.remote_build_dir, 'MiraLink_Data'))}
test -f {shlex.quote(posixpath.join(args.remote_build_dir, 'UnityPlayer.so'))}
"""
        run(client, extract_cmd, timeout=180)
        print(f"build uploaded to {args.remote_build_dir}")
    finally:
        if archive_path and archive_path.exists():
            archive_path.unlink()


def remote_python_snippet() -> str:
    return r"""
if [ -x /data/miniconda/envs/torch/bin/python3 ]; then
  PY=/data/miniconda/envs/torch/bin/python3
else
  PY=$(command -v python3)
fi
if [ -z "$PY" ]; then
  echo "python3 not found" >&2
  exit 2
fi
echo "$PY"
"""


def start_cloud_runtime(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    upload_signalling(client, args)
    exe_path = posixpath.join(args.remote_build_dir, "MiraLink.x86_64")
    check_build = (
        f"test -x {shlex.quote(exe_path)} "
        f"&& test -d {shlex.quote(posixpath.join(args.remote_build_dir, 'MiraLink_Data'))} "
        f"&& test -f {shlex.quote(posixpath.join(args.remote_build_dir, 'UnityPlayer.so'))}"
    )
    run(
        client,
        check_build
        + " || { echo 'Unity build missing or incomplete. Run upload-build after local build.' >&2; exit 3; }",
    )

    py = run(client, remote_python_snippet()).strip().splitlines()[-1]
    install_websockets = (
        f"{shlex.quote(py)} -c 'import websockets' "
        f"|| {shlex.quote(py)} -m pip install websockets"
    )
    run(client, install_websockets, timeout=120)

    if args.display_server == "xvfb":
        if args.install_xvfb:
            install_display = (
                "command -v Xvfb >/dev/null 2>&1 "
                "&& test -e /usr/lib/x86_64-linux-gnu/libX11.so "
                "|| (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y xvfb libx11-dev)"
            )
        else:
            install_display = (
                "command -v Xvfb >/dev/null 2>&1 "
                "&& test -e /usr/lib/x86_64-linux-gnu/libX11.so"
            )
    else:
        if not args.nvidia_driver_version:
            data = collect_gpu_preflight_data(client)
            args.nvidia_driver_version = data.get("kernel_version", "").strip()
        if not args.nvidia_driver_version:
            raise RuntimeError("NVIDIA driver version not found. Run gpu-preflight first.")
        paths = nvidia_fix_paths(args.nvidia_fix_dir, args.nvidia_driver_version)
        args.nvidia_xorg_conf = args.nvidia_xorg_conf or paths.xorg_conf
        install_display = f"""
command -v Xorg >/dev/null 2>&1
command -v glxinfo >/dev/null 2>&1
test -s {shlex.quote(posixpath.join(paths.extract_dir, 'nvidia_drv.so'))}
ls {shlex.quote(posixpath.join(paths.extract_dir, 'libglxserver_nvidia.so'))}* >/dev/null 2>&1
test -L {shlex.quote(posixpath.join(paths.xorg_module_dir, 'drivers', 'nvidia_drv.so'))}
test -L {shlex.quote(posixpath.join(paths.xorg_module_dir, 'extensions', 'libglxserver_nvidia.so'))}
test -s {shlex.quote(args.nvidia_xorg_conf)}
"""
    run(client, install_display, timeout=180)

    signal_py = posixpath.join(args.remote_signalling_dir, "server_v3.py")
    unity_log = posixpath.join(args.remote_log_dir, "unity.log")
    unity_stdout = posixpath.join(args.remote_log_dir, "unity.stdout.log")
    sig_log = posixpath.join(args.remote_log_dir, "signalling.log")
    display_log = posixpath.join(args.remote_log_dir, "display.log")
    turn_urls = args.turn_urls or os.environ.get("TURN_URLS", "")
    turn_username = args.turn_username or os.environ.get("TURN_USERNAME", "")
    turn_credential = args.turn_credential or os.environ.get("TURN_CREDENTIAL", "")
    require_turn_config(args, turn_urls, turn_username, turn_credential)
    remote_credential_file = remote_turn_credential_path(args)
    if turn_credential:
        write_remote_text(
            client,
            remote_credential_file,
            turn_credential,
            mode=0o600,
            label="TURN credential",
        )
    signalling_env = {
        "PORT": str(args.signal_port),
        "BACKEND_WS": args.backend_ws_url,
        "ICE_TRANSPORT_POLICY": args.ice_transport_policy,
    }
    if turn_urls:
        signalling_env["TURN_URLS"] = turn_urls
    if turn_username:
        signalling_env["TURN_USERNAME"] = turn_username
    if turn_credential:
        signalling_env["TURN_CREDENTIAL"] = turn_credential
    signalling_env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in signalling_env.items()
    )
    unity_cuda = args.unity_cuda_visible_devices.strip()
    if unity_cuda.lower() == "inherit":
        unity_env = {}
        unity_cuda_log = "inherit"
    else:
        unity_env = {"CUDA_VISIBLE_DEVICES": unity_cuda}
        unity_cuda_log = unity_cuda
    unity_env["ICE_TRANSPORT_POLICY"] = args.ice_transport_policy
    if turn_urls:
        unity_env["TURN_URLS"] = turn_urls
    if turn_username:
        unity_env["TURN_USERNAME"] = turn_username
    if turn_credential:
        unity_env["TURN_CREDENTIAL"] = turn_credential

    unity_args = [
        "-RenderOffscreen",
        "-force-glcore",
        "-screen-width",
        str(args.screen_width),
        "-screen-height",
        str(args.screen_height),
        "-screen-fullscreen",
        "0",
        "-signalingType",
        "websocket",
        "-signalingUrl",
        f"ws://127.0.0.1:{args.signal_port}",
        "-backendWsUrl",
        args.backend_ws_url,
        "-videoCodec",
        args.video_codec,
        "-streamWidth",
        str(args.stream_width),
        "-streamHeight",
        str(args.stream_height),
        "-streamFps",
        str(args.stream_fps),
        "-streamBitrateMin",
        str(args.stream_bitrate_min),
        "-streamBitrateMax",
        str(args.stream_bitrate_max),
        "-iceTransportPolicy",
        args.ice_transport_policy,
    ]
    for turn_url in [value.strip() for value in turn_urls.split(",") if value.strip()]:
        unity_args.extend(["-iceServerUrl", turn_url])
    unity_args.extend(["-logfile", unity_log])
    unity_args_text = " ".join(shlex.quote(value) for value in unity_args)
    stop_old_cmd = r"""
targets=""
for p in $(ps -eo pid=); do
  [ "$p" = "$$" ] && continue
  cmdline=$(tr '\0' ' ' </proc/$p/cmdline 2>/dev/null || true)
  case "$cmdline" in
    *MiraLink.x86_64*|*server_v3.py*|*"Xvfb :99"*|*"Xorg :99"*) targets="$targets $p"; kill "$p" 2>/dev/null || true ;;
  esac
done
if [ -n "$targets" ]; then
  for i in $(seq 1 30); do
    alive=""
    for p in $targets; do
      kill -0 "$p" 2>/dev/null && alive="$alive $p"
    done
    [ -z "$alive" ] && break
    sleep 0.2
  done
  for p in $targets; do
    kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true
  done
fi
"""
    run(client, stop_old_cmd, timeout=30, check=False)

    if args.display_server == "xvfb":
        xvfb_screen = args.xvfb_screen
        if not xvfb_screen:
            xvfb_screen = f"{args.screen_width}x{args.screen_height}x24"
        display_start_cmd = (
            f"nohup Xvfb :99 -screen 0 {shlex.quote(xvfb_screen)} "
            f">> {shlex.quote(display_log)} 2>&1 < /dev/null &\n"
            "sleep 1\n"
        )
        display_label = f"Xvfb screen={xvfb_screen}"
        display_process_pattern = "[X]vfb :99"
    else:
        display_start_cmd, _nvidia_env_prefix, module_dir = build_nvidia_xorg_start_command(args, py)
        display_label = f"NVIDIA Xorg conf={args.nvidia_xorg_conf} modulepath={module_dir}"
        display_process_pattern = "[X]org :99"
        unity_env["LD_LIBRARY_PATH"] = f"{args.remote_build_dir}:{nvidia_runtime_ld_env(nvidia_fix_paths(args.nvidia_fix_dir, args.nvidia_driver_version))}"
        unity_env["LD_PRELOAD"] = nvidia_gl_preload(nvidia_fix_paths(args.nvidia_fix_dir, args.nvidia_driver_version))

    unity_env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in unity_env.items()
    )
    if unity_env_prefix:
        unity_env_prefix += " "

    start_cmd = f"""
set -e
mkdir -p {shlex.quote(args.remote_log_dir)}
sleep 1
: > {shlex.quote(sig_log)}
: > {shlex.quote(display_log)}
: > {shlex.quote(unity_log)}
: > {shlex.quote(unity_stdout)}
{signalling_env_prefix} nohup {shlex.quote(py)} -u {shlex.quote(signal_py)} >> {shlex.quote(sig_log)} 2>&1 < /dev/null &
for i in $(seq 1 30); do
  curl -sS --max-time 2 http://127.0.0.1:{args.signal_port}/health >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sS --max-time 5 http://127.0.0.1:{args.signal_port}/health
{display_start_cmd}
chmod +x {shlex.quote(exe_path)}
cd {shlex.quote(args.remote_build_dir)}
echo "Unity env: CUDA_VISIBLE_DEVICES={unity_cuda_log}" >> {shlex.quote(unity_stdout)}
echo "Unity CUDA note: CUDA_VISIBLE_DEVICES only limits CUDA compute visibility; OpenGL rendering is selected by DISPLAY=:99 Xorg/NVIDIA." >> {shlex.quote(unity_stdout)}
echo "Unity display: {display_label}" >> {shlex.quote(unity_stdout)}
echo "Unity ICE: policy={shlex.quote(args.ice_transport_policy)} turnUrls={'set' if turn_urls else 'empty'} turnUsername={'set' if turn_username else 'empty'} turnCredentialLen={len(turn_credential)}" >> {shlex.quote(unity_stdout)}
{unity_env_prefix}DISPLAY=:99 XDG_RUNTIME_DIR=/tmp nohup ./MiraLink.x86_64 {unity_args_text} >> {shlex.quote(unity_stdout)} 2>&1 < /dev/null &
sleep 2
ps -eo pid,ppid,stat,cmd | egrep '[H]erUnity.x86_64|[s]erver_v3.py|{display_process_pattern}' || true
"""
    print(run(client, start_cmd, timeout=60, redact_values=(turn_credential,)))


def check_turn(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    expected = args.expected_turn_credential or os.environ.get("TURN_CREDENTIAL", "")
    if not expected:
        raise RuntimeError("--expected-turn-credential or TURN_CREDENTIAL is required")
    expected_b64 = base64.b64encode(expected.encode("utf-8")).decode("ascii")
    remote_credential_file = remote_turn_credential_path(args)
    cmd = f"""
set +e
expected=$(printf '%s' {shlex.quote(expected_b64)} | base64 -d)
expected_len=${{#expected}}
expected_sha=$(printf '%s' "$expected" | sha256sum | awk '{{print substr($1,1,12)}}')
ok=0
echo "expected len=$expected_len sha256_12=$expected_sha"

file_value=""
if [ -f {shlex.quote(remote_credential_file)} ]; then
  file_value=$(cat {shlex.quote(remote_credential_file)})
  file_value=${{file_value%$'\\n'}}
  file_len=${{#file_value}}
  file_sha=$(printf '%s' "$file_value" | sha256sum | awk '{{print substr($1,1,12)}}')
  echo "file {shlex.quote(remote_credential_file)} len=$file_len sha256_12=$file_sha"
  [ "$file_value" = "$expected" ] || ok=1
else
  echo "file {shlex.quote(remote_credential_file)} missing"
  ok=1
fi

check_proc() {{
  label="$1"
  pattern="$2"
  found=0
  for pid in $(pgrep -f "$pattern" 2>/dev/null); do
    [ "$pid" = "$$" ] && continue
    [ -r "/proc/$pid/environ" ] || continue
    value=$(tr '\\0' '\\n' < "/proc/$pid/environ" | awk -F= '$1=="TURN_CREDENTIAL" {{print substr($0, index($0,$2))}}' | tail -1)
    if [ -n "$value" ]; then
      found=1
      value_len=${{#value}}
      value_sha=$(printf '%s' "$value" | sha256sum | awk '{{print substr($1,1,12)}}')
      comm=$(ps -p "$pid" -o comm= 2>/dev/null)
      echo "$label pid=$pid comm=$comm len=$value_len sha256_12=$value_sha"
      [ "$value" = "$expected" ] || ok=1
    fi
  done
  if [ "$found" -eq 0 ]; then
    echo "$label TURN_CREDENTIAL missing"
    ok=1
  fi
}}

check_proc signalling '[s]erver_v3.py'
check_proc unity '[H]erUnity.x86_64'
echo "__turn_check_status=$ok"
exit 0
"""
    output = run(
        client,
        cmd,
        timeout=30,
        check=False,
        redact_values=(expected, expected_b64),
    )
    print(output)
    if "__turn_check_status=0" not in output:
        raise RuntimeError("TURN credential consistency check failed")
    if "len=" not in output:
        raise RuntimeError("TURN credential consistency check did not find required runtime values")


def health(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    cmd = f"""
set +e
ok=0
echo "ASR:"
curl -sS --max-time 5 http://127.0.0.1:{args.asr_port}/health || ok=1
echo
echo "IndexTTS:"
curl -sS --max-time 5 http://127.0.0.1:{args.tts_port}/health || ok=1
echo
echo "Signalling:"
curl -sS --max-time 5 http://127.0.0.1:{args.signal_port}/health || true
echo
exit $ok
"""
    print(run(client, cmd, timeout=30))


def status(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    remote_credential_file = remote_turn_credential_path(args)
    paths = nvidia_fix_paths(args.nvidia_fix_dir, args.nvidia_driver_version) if args.nvidia_driver_version else None
    isolated_ld = nvidia_runtime_ld_path(paths) if paths else (
        f"$(test -f {shlex.quote(posixpath.join(args.nvidia_fix_dir, 'current-driver-version'))} "
        f"&& v=$(cat {shlex.quote(posixpath.join(args.nvidia_fix_dir, 'current-driver-version'))}) "
        f"&& printf '%s' {shlex.quote(args.nvidia_fix_dir)}/NVIDIA-Linux-x86_64-$v:/usr/lib/x86_64-linux-gnu:'${{LD_LIBRARY_PATH:-}}' "
        "|| printf '%s' /usr/lib/x86_64-linux-gnu:'${LD_LIBRARY_PATH:-}')"
    )
    gl_preload = nvidia_gl_preload(paths) if paths else (
        f"$(test -f {shlex.quote(posixpath.join(args.nvidia_fix_dir, 'current-driver-version'))} "
        f"&& v=$(cat {shlex.quote(posixpath.join(args.nvidia_fix_dir, 'current-driver-version'))}) "
        f"&& printf '%s' {shlex.quote(args.nvidia_fix_dir)}/NVIDIA-Linux-x86_64-$v/libGL.so.1.7.0 "
        "|| true)"
    )
    cmd = f"""
set +e
echo "== processes =="
ps -eo pid,ppid,stat,cmd | egrep '[H]erUnity.x86_64|[s]erver_v3.py|[X]vfb :99|[X]org :99|[u]vicorn|[t]urnserver' || true
echo
echo "== unity cpu =="
ps -eo pid,comm,etime,%cpu,%mem,args --sort=-%cpu | awk 'NR==1 || /[H]erUnity.x86_64/ {{print}}' || true
echo
echo "== listening =="
ss -ltnp '( sport = :{args.asr_port} or sport = :{args.tts_port} or sport = :{args.signal_port} or sport = :8100 or sport = :3478 )' 2>/dev/null || true
echo
echo "== display glx =="
if command -v glxinfo >/dev/null 2>&1; then
  DISPLAY=:99 LD_LIBRARY_PATH={isolated_ld} LD_PRELOAD={gl_preload} glxinfo -B 2>&1 | sed -n '/display:/p;/direct rendering:/p;/OpenGL vendor string:/p;/OpenGL renderer string:/p;/OpenGL version string:/p'
else
  echo "glxinfo missing"
fi
echo
echo "== turn credential consistency hints =="
if [ -f {shlex.quote(remote_credential_file)} ]; then
  file_value=$(cat {shlex.quote(remote_credential_file)})
  file_value=${{file_value%$'\\n'}}
  file_len=${{#file_value}}
  file_sha=$(printf '%s' "$file_value" | sha256sum | awk '{{print substr($1,1,12)}}')
  echo "file {shlex.quote(remote_credential_file)} len=$file_len sha256_12=$file_sha"
else
  echo "file {shlex.quote(remote_credential_file)} missing"
fi
for label_pattern in "signalling:[s]erver_v3.py" "unity:[H]erUnity.x86_64"; do
  label=${{label_pattern%%:*}}
  pattern=${{label_pattern#*:}}
  found=0
  for pid in $(pgrep -f "$pattern" 2>/dev/null); do
    [ -r "/proc/$pid/environ" ] || continue
    value=$(tr '\\0' '\\n' < "/proc/$pid/environ" | awk -F= '$1=="TURN_CREDENTIAL" {{print substr($0, index($0,$2))}}' | tail -1)
    [ -n "$value" ] || continue
    found=1
    value_len=${{#value}}
    value_sha=$(printf '%s' "$value" | sha256sum | awk '{{print substr($1,1,12)}}')
    comm=$(ps -p "$pid" -o comm= 2>/dev/null)
    echo "$label pid=$pid comm=$comm len=$value_len sha256_12=$value_sha"
  done
  [ "$found" -eq 1 ] || echo "$label TURN_CREDENTIAL missing"
done
echo
echo "== health =="
curl -sS --max-time 3 http://127.0.0.1:{args.asr_port}/health || true
echo
curl -sS --max-time 3 http://127.0.0.1:{args.tts_port}/health || true
echo
curl -sS --max-time 3 http://127.0.0.1:{args.signal_port}/health || true
echo
echo "== recent unity log =="
grep -a -i -E 'Renderer:|Vendor:|Version:|RenderStreamingRuntimeConfig|NetworkClient|Connected to|codec|encoder|NVENC|NvEnc|error|failed|Signaling|IceConnectionState|ConnectionState' {shlex.quote(posixpath.join(args.remote_log_dir, 'unity.log'))} 2>/dev/null | tail -120 || true
echo
echo "== recent unity stdout =="
tail -40 {shlex.quote(posixpath.join(args.remote_log_dir, 'unity.stdout.log'))} 2>/dev/null || true
echo
echo "== display log =="
grep -a -E 'OpenGL vendor|OpenGL renderer|NVIDIA\\(0\\)|NVIDIA GLX|Renderer:|\\((EE|WW)\\)' {shlex.quote(posixpath.join(args.remote_log_dir, 'display.log'))} 2>/dev/null | tail -80 || true
echo
echo "== recent signalling log =="
tail -80 {shlex.quote(posixpath.join(args.remote_log_dir, 'signalling.log'))} 2>/dev/null | sed -E 's/(turn_credential=)[^&[:space:]]+/\\1***MASKED***/g; s/(TURN_CREDENTIAL=)[^[:space:]]+/\\1***MASKED***/g' || true
"""
    print(run(client, cmd, timeout=30, check=False))


def stop(client: paramiko.SSHClient, args: argparse.Namespace) -> None:
    cmd = f"""
for p in $(ps -eo pid=); do
  [ "$p" = "$$" ] && continue
  cmdline=$(tr '\0' ' ' </proc/$p/cmdline 2>/dev/null || true)
  case "$cmdline" in
    *MiraLink.x86_64*|*server_v3.py*|*"Xvfb :99"*|*"Xorg :99"*) kill "$p" 2>/dev/null || true ;;
  esac
done
echo stopped
"""
    print(run(client, cmd, timeout=30, check=False))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=[
            "health",
            "status",
            "start",
            "stop",
            "upload-signalling",
            "upload-build",
            "check-turn",
            "gpu-preflight",
            "prepare-nvidia-xorg",
        ],
    )
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--remote-build-dir", default="")
    parser.add_argument("--remote-signalling-dir", default="")
    parser.add_argument("--remote-log-dir", default="")
    parser.add_argument("--remote-run-dir", default="")
    parser.add_argument("--local-build-dir", default=str(ROOT.parent / "MiraLink-Build-GL"))
    parser.add_argument("--signal-port", type=int, default=8080)
    parser.add_argument("--asr-port", type=int, default=9002)
    parser.add_argument("--tts-port", type=int, default=9001)
    parser.add_argument("--backend-ws-url", default="ws://127.0.0.1:8100/ws/avatar")
    parser.add_argument("--ice-transport-policy", default="all")
    parser.add_argument("--turn-urls", default="")
    parser.add_argument("--turn-username", default="")
    parser.add_argument("--turn-credential", default="")
    parser.add_argument("--expected-turn-credential", default="")
    parser.add_argument("--display-server", choices=["xvfb", "nvidia-xorg"], default="xvfb")
    parser.add_argument(
        "--nvidia-xorg-conf",
        default=posixpath.join(DEFAULT_NVIDIA_FIX_DIR, "xorg-miralink-nvidia.conf"),
    )
    parser.add_argument("--nvidia-fix-dir", default=DEFAULT_NVIDIA_FIX_DIR)
    parser.add_argument("--nvidia-driver-version", default="")
    parser.add_argument("--nvidia-download-base-url", default=DEFAULT_NVIDIA_DOWNLOAD_BASE_URL)
    parser.add_argument("--xvfb-screen", default="")
    parser.add_argument("--screen-width", type=int, default=0)
    parser.add_argument("--screen-height", type=int, default=0)
    parser.add_argument("--video-codec", default="vp8")
    parser.add_argument("--stream-width", type=int, default=240)
    parser.add_argument("--stream-height", type=int, default=426)
    parser.add_argument("--stream-fps", type=float, default=8)
    parser.add_argument("--stream-bitrate-min", type=int, default=80)
    parser.add_argument("--stream-bitrate-max", type=int, default=300)
    parser.add_argument(
        "--unity-cuda-visible-devices",
        default="-1",
        help="CUDA_VISIBLE_DEVICES for the Unity process only. Use 'inherit' to leave it unchanged.",
    )
    parser.add_argument("--no-install-xvfb", action="store_true")
    args = parser.parse_args(argv)
    args.remote_build_dir = args.remote_build_dir or posixpath.join(args.remote_root, "MiraLink-Build")
    args.remote_signalling_dir = args.remote_signalling_dir or posixpath.join(args.remote_root, "signalling")
    args.remote_log_dir = args.remote_log_dir or posixpath.join(args.remote_root, "logs")
    args.remote_run_dir = args.remote_run_dir or posixpath.join(args.remote_root, "run")
    args.screen_width = args.screen_width or args.stream_width
    args.screen_height = args.screen_height or args.stream_height
    args.install_xvfb = not args.no_install_xvfb
    if args.nvidia_driver_version and not args.nvidia_xorg_conf:
        args.nvidia_xorg_conf = nvidia_fix_paths(args.nvidia_fix_dir, args.nvidia_driver_version).xorg_conf
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    client = None
    try:
        client = connect()
        if args.action == "health":
            health(client, args)
        elif args.action == "status":
            status(client, args)
        elif args.action == "start":
            start_cloud_runtime(client, args)
        elif args.action == "stop":
            stop(client, args)
        elif args.action == "upload-signalling":
            upload_signalling(client, args)
        elif args.action == "upload-build":
            upload_build(client, args)
        elif args.action == "check-turn":
            check_turn(client, args)
        elif args.action == "gpu-preflight":
            gpu_preflight(client, args)
        elif args.action == "prepare-nvidia-xorg":
            prepare_nvidia_xorg(client, args)
        else:
            raise RuntimeError(f"unknown action: {args.action}")
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
