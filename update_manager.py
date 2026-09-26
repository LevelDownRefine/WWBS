"""Validate an onedir release before quitting; preserve user data during install."""
import hashlib
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
import tempfile


def signal_update_ready() -> None:
    """A new process acknowledges only after its main GUI has initialized."""
    filename = os.environ.pop("WWBS_UPDATE_READY", "")
    token = os.environ.pop("WWBS_UPDATE_TOKEN", "")
    if not filename or not re.fullmatch(r"[0-9a-f]{32}", token):
        return
    path = Path(filename).resolve()
    if (path.name != "ready" or not path.parent.name.startswith("wwbs_update_")
            or path.parent.parent != Path(tempfile.gettempdir()).resolve()):
        return
    path.write_text(token, encoding="ascii")


def prepare_update(archive: Path, destination: Path, expected_size=0, digest="") -> Path:
    if expected_size and archive.stat().st_size != expected_size:
        raise ValueError("更新包大小不符，下载可能不完整，原程序未改动。")
    if digest:
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            raise ValueError("无法识别更新包校验格式。")
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest.split(":", 1)[1].lower():
            raise ValueError("更新包 SHA-256 校验失败，原程序未改动。")
    with zipfile.ZipFile(archive) as package:
        seen = set()
        total = 0
        for item in package.infolist():
            name = item.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith("/") or any(p in {"..", "."} or ":" in p
                    or p.endswith((" ", ".")) for p in parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("更新包含不安全路径。")
            key = name.rstrip("/").casefold()
            if key in seen:
                raise ValueError("更新包含重复路径。")
            seen.add(key)
            total += item.file_size
            if total > 2 * 1024 ** 3:
                raise ValueError("更新包解压大小超出限制。")
        bad = package.testzip()
        if bad:
            raise ValueError("更新包 CRC 校验失败。")
        package.extractall(destination)
    roots = [p.parent for p in destination.rglob("wwbs.exe")]
    roots = [p for p in roots if (p / "_internal" / "base_library.zip").is_file()
             and any((p / "_internal").glob("python3*.dll"))]
    if len(roots) != 1:
        raise ValueError("更新包必须包含唯一的 wwbs.exe 和完整 _internal 运行库。")
    return roots[0]


def install_script(staged: Path, target: Path, work: Path, process_id: int, notify_failure: bool = True) -> str:
    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"
    # Keep backups and logs even after a successful start. No recursive deletion.
    return f"""$ErrorActionPreference = 'Stop'
$source = {quote(staged.resolve())}
$target = {quote(target.resolve())}
$work = {quote(work.resolve())}
$log = Join-Path $work 'update.log'
$backup = Join-Path $target ('.wwbs-update-backup-' + [guid]::NewGuid().ToString('N'))
$old = @()
$installed = @()
try {{
    $deadline = (Get-Date).AddSeconds(90)
    while (Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue) {{
        if ((Get-Date) -gt $deadline) {{ throw 'Old process did not exit; update cancelled.' }}
        Start-Sleep -Milliseconds 500
    }}
    New-Item -ItemType Directory -Path $backup | Out-Null
    foreach ($name in @('wwbs.exe', '_internal')) {{
        $dest = [IO.Path]::GetFullPath((Join-Path $target $name))
        $prefix = [IO.Path]::GetFullPath($target).TrimEnd('\\') + '\\'
        if (-not $dest.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {{ throw 'Unsafe target path' }}
        if (Test-Path -LiteralPath $dest) {{
            Move-Item -LiteralPath $dest -Destination (Join-Path $backup $name)
            $old += $name
        }}
        $installed += $name
        Copy-Item -LiteralPath (Join-Path $source $name) -Destination $dest -Recurse
    }}
    $exe = Join-Path $target 'wwbs.exe'
    $env:WWBS_UPDATE_READY = Join-Path $work 'ready'
    $env:WWBS_UPDATE_TOKEN = [guid]::NewGuid().ToString('N')
    $child = Start-Process -FilePath $exe -WorkingDirectory $target -WindowStyle Hidden -PassThru
    $deadline = (Get-Date).AddSeconds(45)
    while ($true) {{
        if ($child.HasExited) {{ throw 'New process exited during startup.' }}
        if ((Test-Path -LiteralPath $env:WWBS_UPDATE_READY) -and
            (([IO.File]::ReadAllText($env:WWBS_UPDATE_READY)) -eq $env:WWBS_UPDATE_TOKEN)) {{ break }}
        if ((Get-Date) -gt $deadline) {{ throw 'New GUI did not acknowledge startup within 45 seconds.' }}
        Start-Sleep -Milliseconds 250
    }}
    "Update copied and process started. Backup: $backup" | Out-File -LiteralPath $log -Encoding utf8
}} catch {{
    $failure = $_.ToString()
    try {{
        if ($child -and -not $child.HasExited) {{ $child.Kill(); $child.WaitForExit() }}
        foreach ($name in $installed) {{
            $dest = Join-Path $target $name
            if (Test-Path -LiteralPath $dest) {{
                Move-Item -LiteralPath $dest -Destination (Join-Path $backup ('failed-' + $name))
            }}
        }}
        foreach ($name in $old) {{
            Move-Item -LiteralPath (Join-Path $backup $name) -Destination (Join-Path $target $name)
        }}
        $failure += "`nOriginal files restored. Please restart WWBS manually."
    }} catch {{ $failure += "`nRollback incomplete: " + $_.ToString() }}
    $failure | Out-File -LiteralPath $log -Encoding utf8
    if ({'$true' if notify_failure else '$false'}) {{
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show("Update failed. Log: $log`n$failure", 'WWBS update') | Out-Null
    }}
    exit 1
}}
"""
