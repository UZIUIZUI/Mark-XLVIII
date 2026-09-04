#vm_control.py
"""
Real virtual-machine control via the native CLI of whichever hypervisor is
installed: VMware Workstation/Player (vmrun), VirtualBox (VBoxManage), or
Hyper-V (PowerShell). Hypervisor is either given explicitly or auto-detected
by probing for each CLI tool on PATH.
"""
import platform
import shutil
import subprocess
import sys
import json
from pathlib import Path

_CLI_TIMEOUT = 60
_OS = platform.system()

_WIN_HIDE: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}
)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _load_config() -> dict:
    try:
        path = _base_dir() / "config" / "api_keys.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _vmrun_exe() -> str | None:
    configured = _load_config().get("vmrun_path", "")
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("vmrun")
    if found:
        return found
    if _OS == "Windows":
        default = Path(r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe")
        if default.exists():
            return str(default)
    return None


def _vboxmanage_exe() -> str | None:
    found = shutil.which("VBoxManage") or shutil.which("vboxmanage")
    if found:
        return found
    if _OS == "Windows":
        default = Path(r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe")
        if default.exists():
            return str(default)
    return None


def _detect_hypervisor() -> str | None:
    if _vboxmanage_exe():
        return "virtualbox"
    if _vmrun_exe():
        return "vmware"
    if _OS == "Windows" and shutil.which("powershell"):
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-Module -ListAvailable Hyper-V"],
                capture_output=True, text=True, timeout=10, **_WIN_HIDE,
            )
            if "Hyper-V" in (r.stdout or ""):
                return "hyperv"
        except Exception:
            pass
    return None


# ── VirtualBox ───────────────────────────────────────────────────────────────

def _vbox_run(args: list) -> subprocess.CompletedProcess:
    exe = _vboxmanage_exe()
    if not exe:
        raise RuntimeError("VBoxManage not found. Install VirtualBox or check PATH.")
    return subprocess.run([exe, *args], capture_output=True, text=True,
                           timeout=_CLI_TIMEOUT, **_WIN_HIDE)


def vbox_list(running_only: bool = False) -> str:
    try:
        r = _vbox_run(["list", "runningvms" if running_only else "vms"])
        out = r.stdout.strip()
        return out if out else "No virtual machines found."
    except FileNotFoundError:
        return "VBoxManage not found. Install VirtualBox or check PATH."
    except subprocess.TimeoutExpired:
        return "VBoxManage timed out."
    except Exception as e:
        return f"VirtualBox error: {e}"


def vbox_action(vm_name: str, action: str) -> str:
    try:
        if action == "start":
            r = _vbox_run(["startvm", vm_name, "--type", "headless"])
        elif action == "stop":
            r = _vbox_run(["controlvm", vm_name, "poweroff"])
        elif action == "shutdown":
            r = _vbox_run(["controlvm", vm_name, "acpipowerbutton"])
        elif action == "pause":
            r = _vbox_run(["controlvm", vm_name, "pause"])
        elif action == "resume":
            r = _vbox_run(["controlvm", vm_name, "resume"])
        elif action == "snapshot":
            r = _vbox_run(["snapshot", vm_name, "take", f"jarvis-{vm_name}"])
        else:
            return f"Unknown VirtualBox action: '{action}'"

        if r.returncode != 0:
            return f"VirtualBox '{action}' on '{vm_name}' failed: {r.stderr.strip()[:300]}"
        return f"VirtualBox: {action} → {vm_name} done."
    except FileNotFoundError:
        return "VBoxManage not found. Install VirtualBox or check PATH."
    except subprocess.TimeoutExpired:
        return f"VirtualBox '{action}' timed out."
    except Exception as e:
        return f"VirtualBox error: {e}"


# ── VMware (vmrun) ───────────────────────────────────────────────────────────

def _vmware_run(args: list) -> subprocess.CompletedProcess:
    exe = _vmrun_exe()
    if not exe:
        raise RuntimeError("vmrun not found. Install VMware Workstation/Player or check PATH.")
    return subprocess.run([exe, "-T", "ws", *args], capture_output=True, text=True,
                           timeout=_CLI_TIMEOUT, **_WIN_HIDE)


def vmware_list() -> str:
    try:
        r = _vmware_run(["list"])
        return r.stdout.strip() or "No running VMware VMs."
    except FileNotFoundError:
        return "vmrun not found. Install VMware Workstation/Player or check PATH."
    except subprocess.TimeoutExpired:
        return "vmrun timed out."
    except Exception as e:
        return f"VMware error: {e}"


def vmware_action(vmx_path: str, action: str) -> str:
    if not vmx_path or not Path(vmx_path).exists():
        return f"VMX file not found: {vmx_path}"
    try:
        if action == "start":
            r = _vmware_run(["start", vmx_path, "nogui"])
        elif action == "stop":
            r = _vmware_run(["stop", vmx_path, "hard"])
        elif action == "shutdown":
            r = _vmware_run(["stop", vmx_path, "soft"])
        elif action == "pause":
            r = _vmware_run(["pause", vmx_path])
        elif action == "resume":
            r = _vmware_run(["unpause", vmx_path])
        elif action == "snapshot":
            r = _vmware_run(["snapshot", vmx_path, "jarvis-snapshot"])
        else:
            return f"Unknown VMware action: '{action}'"

        if r.returncode != 0:
            return f"VMware '{action}' failed: {r.stderr.strip()[:300]}"
        return f"VMware: {action} → {Path(vmx_path).stem} done."
    except FileNotFoundError:
        return "vmrun not found. Install VMware Workstation/Player or check PATH."
    except subprocess.TimeoutExpired:
        return f"VMware '{action}' timed out."
    except Exception as e:
        return f"VMware error: {e}"


# ── Hyper-V (PowerShell) ─────────────────────────────────────────────────────

def _hyperv_ps(command: str) -> subprocess.CompletedProcess:
    if _OS != "Windows":
        raise RuntimeError("Hyper-V is only available on Windows.")
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=_CLI_TIMEOUT, **_WIN_HIDE,
    )


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def hyperv_list() -> str:
    try:
        r = _hyperv_ps("Get-VM | Format-Table Name, State, CPUUsage, MemoryAssigned -AutoSize")
        return r.stdout.strip() or "No Hyper-V VMs found."
    except RuntimeError as e:
        return str(e)
    except subprocess.TimeoutExpired:
        return "Hyper-V query timed out."
    except Exception as e:
        return f"Hyper-V error: {e}"


def hyperv_action(vm_name: str, action: str) -> str:
    safe_name = _ps_quote(vm_name)
    cmd_map = {
        "start":    f"Start-VM -Name '{safe_name}'",
        "stop":     f"Stop-VM -Name '{safe_name}' -TurnOff -Force",
        "shutdown": f"Stop-VM -Name '{safe_name}' -Force",
        "pause":    f"Suspend-VM -Name '{safe_name}'",
        "resume":   f"Resume-VM -Name '{safe_name}'",
        "snapshot": f"Checkpoint-VM -Name '{safe_name}' -SnapshotName 'jarvis-{safe_name}'",
    }
    if action not in cmd_map:
        return f"Unknown Hyper-V action: '{action}'"
    try:
        r = _hyperv_ps(cmd_map[action])
        if r.returncode != 0:
            return f"Hyper-V '{action}' on '{vm_name}' failed: {r.stderr.strip()[:300]}"
        return f"Hyper-V: {action} → {vm_name} done."
    except RuntimeError as e:
        return str(e)
    except subprocess.TimeoutExpired:
        return f"Hyper-V '{action}' timed out."
    except Exception as e:
        return f"Hyper-V error: {e}"


# ── Public entry point ───────────────────────────────────────────────────────

def manage_vm(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        hypervisor : vmware | virtualbox | hyperv (optional — auto-detected
                     from installed CLI tools if omitted)
        action     : start | stop | shutdown | pause | resume | snapshot | list
        vm_name    : VM name (VirtualBox/Hyper-V) — required unless action='list'
        vmx_path   : path to .vmx file (VMware only) — required unless action='list'
    """
    params     = parameters or {}
    hypervisor = params.get("hypervisor", "").lower().strip() or _detect_hypervisor()
    action     = params.get("action", "").lower().strip()
    vm_name    = params.get("vm_name", "")
    vmx_path   = params.get("vmx_path", "")

    if player:
        player.write_log(f"[VM] {hypervisor}:{action} {vm_name or vmx_path}")

    if not hypervisor:
        return (
            "No hypervisor detected (VirtualBox/VMware/Hyper-V). Install one, "
            "or pass hypervisor='vmware'|'virtualbox'|'hyperv' explicitly."
        )

    try:
        if hypervisor == "virtualbox":
            if action == "list":
                return vbox_list()
            if not vm_name:
                return "vm_name is required for VirtualBox actions."
            return vbox_action(vm_name, action)

        if hypervisor == "vmware":
            if action == "list":
                return vmware_list()
            if not vmx_path:
                return "vmx_path is required for VMware actions."
            return vmware_action(vmx_path, action)

        if hypervisor == "hyperv":
            if action == "list":
                return hyperv_list()
            if not vm_name:
                return "vm_name is required for Hyper-V actions."
            return hyperv_action(vm_name, action)

        return f"Unknown hypervisor: '{hypervisor}'"

    except Exception as e:
        return f"manage_vm failed: {e}"
