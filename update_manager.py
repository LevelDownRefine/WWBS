"""Validate an onedir release before quitting; preserve user data during install."""
import hashlib
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
import tempfile
import sys
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit, urlunsplit

from local_settings import SETTINGS


def create_update_work(target: Path) -> Path:
    path = target/('.wwbs-update-work-'+uuid.uuid4().hex)
    try:
        path.mkdir()
    except OSError as exc:
        raise OSError('当前安装目录不可写，请以管理员身份运行软件后更新。原程序未改动。') from exc
    return path


def download_asset(asset: dict, destination: Path, *, version: str, progress=lambda *_: None,
                   cancelled=lambda: False, opener=urllib.request.urlopen, sleep=time.sleep) -> None:
    expected = int(asset.get('size') or 0)
    if expected < 0 or expected > 512*1024*1024:
        raise ValueError('安装包大小不符合预期')
    base = str(asset['browser_download_url'])
    errors = []
    for attempt in range(3):
        if cancelled():
            raise InterruptedError('更新已取消，原程序未改动')
        parts = urlsplit(base)
        if parts.scheme != 'https' or parts.hostname not in {'github.com', 'api.github.com'}:
            raise ValueError('安装包下载地址无效')
        query = parts.query+('&' if parts.query else '')+'wwbs_update='+str(time.time_ns())
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))
        headers = {'User-Agent': 'wwbs/'+version, 'Cache-Control': 'no-cache',
                   'Accept': 'application/octet-stream'}
        # The release-asset API is a second official download entry point.
        if attempt == 1 and asset.get('url'):
            api = urlsplit(str(asset['url']))
            if api.scheme == 'https' and api.hostname == 'api.github.com':
                url = str(asset['url'])
        request = urllib.request.Request(url, headers=headers)
        try:
            progress(0, expected)
            total = 0
            with opener(request, timeout=30) as response, destination.open('wb') as output:
                while True:
                    if cancelled():
                        raise InterruptedError('更新已取消，原程序未改动')
                    data = response.read(256*1024)
                    if not data:
                        break
                    if total == 0 and data[:4] != b'PK\x03\x04':
                        raise ValueError('下载入口未返回ZIP安装包')
                    total += len(data)
                    if total > (expected or 512*1024*1024):
                        raise ValueError('下载内容超过安装包标记大小')
                    output.write(data)
                    progress(total, expected)
            if not total or (expected and total != expected):
                raise ValueError('安装包下载不完整')
            return
        except InterruptedError:
            raise
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append(str(exc))
            if attempt < 2:
                sleep(.5*(attempt+1))
    raise RuntimeError('安装包下载失败（已重试3次）：'+errors[-1])


def signal_update_ready() -> None:
    """A new process acknowledges only after its main GUI has initialized."""
    filename = os.environ.pop("WWBS_UPDATE_READY", "")
    token = os.environ.pop("WWBS_UPDATE_TOKEN", "")
    if not filename or not re.fullmatch(r"[0-9a-f]{32}", token):
        return
    path = Path(filename).resolve()
    temporary = (path.parent.name.startswith('wwbs_update_')
                 and path.parent.parent == Path(tempfile.gettempdir()).resolve())
    beside_app = (re.fullmatch(r'\.wwbs-update-work-[0-9a-f]{32}', path.parent.name)
                  and getattr(sys, 'frozen', False)
                  and path.parent.parent == Path(sys.executable).resolve().parent)
    if path.name != 'ready' or not (temporary or beside_app):
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
$settingNames = @({', '.join(quote(Path(name)) for name in SETTINGS)})
$settingsSource = Join-Path $work 'settings'
$oldSettings = @()
$settingsBackedUp = $false
try {{
    $deadline = (Get-Date).AddSeconds(90)
    while (Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue) {{
        if ((Get-Date) -gt $deadline) {{ throw 'Old process did not exit; update cancelled.' }}
        Start-Sleep -Milliseconds 500
    }}
    New-Item -ItemType Directory -Path $backup | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $backup 'settings') | Out-Null
    foreach ($name in $settingNames) {{
        $path = Join-Path $target $name
        if (Test-Path -LiteralPath $path) {{
            Copy-Item -LiteralPath $path -Destination (Join-Path (Join-Path $backup 'settings') $name)
            $oldSettings += $name
        }}
    }}
    $settingsBackedUp = $true
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
    foreach ($name in $settingNames) {{
        $saved = Join-Path $settingsSource $name
        if (Test-Path -LiteralPath $saved) {{
            Copy-Item -LiteralPath $saved -Destination (Join-Path $target $name) -Force
        }}
    }}
    $exe = Join-Path $target 'wwbs.exe'
    $env:WWBS_UPDATE_READY = Join-Path $work 'ready'
    $env:WWBS_UPDATE_TOKEN = [guid]::NewGuid().ToString('N')
    $child = Start-Process -FilePath $exe -WorkingDirectory $target -WindowStyle Normal -PassThru
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
        if ($settingsBackedUp) {{ foreach ($name in $settingNames) {{
            $path = Join-Path $target $name
            if ($oldSettings -contains $name) {{
                Copy-Item -LiteralPath (Join-Path (Join-Path $backup 'settings') $name) -Destination $path -Force
            }} elseif ((Test-Path -LiteralPath $path) -and $backup -and (Test-Path -LiteralPath $backup)) {{
                Move-Item -LiteralPath $path -Destination (Join-Path $backup ('failed-' + $name))
            }}
        }} }}
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
