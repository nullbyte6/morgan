"""Windows package management and scoped, recoverable application cleanup."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import uuid

_jobs = {}
_candidates = {}
_lock = threading.RLock()
_SHARED = {"microsoft", "windows", "packages", "programs", "temp", "cache",
           "google", "mozilla", "adobe", "common files", "arlo", ".arlo"}


def _result(status, **values):
    return json.dumps({"status": status, **values}, ensure_ascii=False)


def _argument(value):
    value = value.strip()
    if not value.strip() or value.startswith("-") or any(
            ord(c) < 32 for c in value):
        raise ValueError(
            "Specify a non-empty name or exact package ID, not command options")
    return value.strip()


def _winget():
    executable = shutil.which("winget")
    if not executable and os.environ.get("LOCALAPPDATA"):
        alias = Path(
            os.environ["LOCALAPPDATA"]) / "Microsoft/WindowsApps/winget.exe"
        if alias.is_file():
            executable = str(alias)
    if not executable:
        raise ValueError(
            "WinGet is unavailable. Install/update Microsoft App Installer and restart Arlo")
    return executable


def _start(arguments, mutation=False):
    if os.name != "nt":
        return _result("error", error="Application management requires Windows")
    with _lock:
        try:
            if mutation and any(
                    j["mutation"] and j["process"].poll() is None for j in
                    _jobs.values()):
                return _result("error",
                               error="An app operation is still running; check its job ID first")
            command = [_winget(), *arguments, "--accept-source-agreements",
                       "--disable-interactivity"]
            log = tempfile.TemporaryFile()
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                           stdout=log,
                                           stderr=subprocess.STDOUT,
                                           shell=False,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError:
                log.close()
                raise
            job_id = uuid.uuid4().hex
            _jobs[job_id] = {"process": process, "log": log,
                             "mutation": mutation}
            return _result("running", job_id=job_id, command=command,
                           instruction="Use get_app_operation until finished; do not repeat the operation")
        except (OSError, ValueError) as error:
            return _result("error", error=str(error))


def get_app_operation(job_id: str) -> str:
    """Check a winget operation in this Arlo session. Only completed means exit code zero."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return _result("unknown", error="Unknown job or Arlo restarted. "
                                            "Inspect installed apps before retrying")
        if "result" in job:
            return job["result"]
        code = job["process"].poll()
        if code is None:
            return _result("running", job_id=job_id)
        log = job["log"]
        length = log.seek(0, os.SEEK_END)
        log.seek(max(0, length - 24000))
        output = log.read().decode("utf-8", errors="replace")
        log.close()
        job["result"] = _result("completed" if code == 0 else "error",
                                job_id=job_id,
                                exit_code=code, output=output,
                                truncated=length > 24000,
                                instruction="Report winget output; errors or elevation requests require attention")
        return job["result"]


def search_apps(query: str, installed_only: bool = False) -> str:
    """Find winget package IDs. installed_only lists matching installed applications."""
    try:
        return _start(["list" if installed_only else "search", "--query",
                       _argument(query)])
    except ValueError as error:
        return _result("error", error=str(error))


def install_app(package_id: str, download_only: bool = False) -> str:
    """Download and install an exact winget package ID from search_apps; download_only saves to Downloads."""
    try:
        args = ["download" if download_only else "install", "--id",
                _argument(package_id),
                "--exact", "--source", "winget", "--accept-package-agreements"]
        if not download_only:
            args.append("--silent")
        return _start(args, mutation=True)
    except ValueError as error:
        return _result("error", error=str(error))


def uninstall_app(package_id: str, purge_portable: bool = False) -> str:
    """Uninstall an exact installed ID. purge_portable deletes portable package files only when requested."""
    try:
        args = ["uninstall", "--id", _argument(package_id), "--exact",
                "--silent"]
        if purge_portable:
            args.append("--purge")
        return _start(args, mutation=True)
    except ValueError as error:
        return _result("error", error=str(error))


def _roots():
    return [Path(os.environ[key]).absolute() for key in
            ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA")
            if os.environ.get(key)]


def _linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400)


def _safe(path, root):
    if path.parent != root or path.name.casefold() in _SHARED or path.name.startswith(
            "."):
        raise ValueError(
            "Only individual app data folders are eligible, never shared parent folders")
    for ancestor in (path, *path.parents):
        if _linked(ancestor):
            raise ValueError("Links and Windows junctions are excluded")
    if path.resolve().parent != root.resolve() or not path.is_dir():
        raise ValueError("App folder is outside its expected data root")


def scan_app_residues(app_name: str) -> str:
    """Find possible app data folders (not proof of orphan status). Return candidates for explicit selection."""
    term = app_name.strip().casefold()
    if len(term) < 3 or term in _SHARED or not re.fullmatch(r"[\w .+()-]+",
                                                            term):
        return _result("error",
                       error="Specify a distinctive app name of at least three characters")
    results, errors = [], []
    for root in _roots():
        try:
            for path in root.iterdir():
                if term not in path.name.casefold():
                    continue
                try:
                    _safe(path, root)
                    info = path.stat()
                    token = uuid.uuid4().hex
                    with _lock:
                        _candidates[token] = (path, root, info.st_dev,
                                              info.st_ino)
                    results.append({"candidate_id": token, "path": str(path)})
                except (OSError, ValueError):
                    continue
        except OSError as error:
            errors.append(str(error))
    return _result("ok", candidates=results, errors=errors,
                   instruction="Name matches may contain settings or user data of installed apps. Select exact folders before cleanup",
                   scope="Top-level LocalAppData, Roaming AppData and ProgramData folders only; no registry or system cleanup")


def clean_app_residue(candidate_id: str) -> str:
    """Move one explicitly selected scan candidate to the Recycle Bin; never pass invented paths or IDs."""
    with _lock:
        if any(j["mutation"] and j["process"].poll() is None for j in
               _jobs.values()):
            return _result("error",
                           error="Wait for the running app operation to finish before cleanup")
        candidate = _candidates.get(candidate_id)
        if not candidate:
            return _result("error",
                           error="Unknown candidate. Scan again and select a folder")
        path, root, device, inode = candidate
        try:
            _safe(path, root)
            info = path.stat()
            if (info.st_dev, info.st_ino) != (device, inode):
                raise ValueError("Folder changed since scan; scan again")

            def fail(error):
                raise error

            for current, directories, files in os.walk(path, followlinks=False,
                                                       onerror=fail):
                for name in directories + files:
                    if _linked(Path(current) / name):
                        raise ValueError(
                            "Folder contains links or junctions; cleanup skipped")
            from send2trash import send2trash
            send2trash(str(path))
            del _candidates[candidate_id]
            return _result("recycled", path=str(path),
                           recovery="Windows Recycle Bin",
                           disk_space_reclaimed=False)
        except ImportError:
            return _result("error",
                           error="Install Arlo requirements (Send2Trash) to enable recoverable cleanup")
        except (OSError, ValueError) as error:
            return _result("error", error=str(error))
