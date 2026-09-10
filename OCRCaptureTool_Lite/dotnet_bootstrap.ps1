# Shared .NET SDK bootstrap for source run / release.
# Uses any installed SDK >= 8 (including .NET 9/10). If none exists, installs
# a private .NET 8 SDK under .dotnet so the project remains self-contained.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-UsableDotNetInfo {
    param([Parameter(Mandatory=$true)][string]$Exe)
    if (-not (Test-Path -LiteralPath $Exe) -and $Exe -ne 'dotnet') { return $null }
    try {
        $lines = @(& $Exe --list-sdks 2>$null)
        if (-not $lines -or $lines.Count -eq 0) { return $null }
        $usable = @()
        foreach ($line in $lines) {
            if ($line -match '^\s*(\d+)\.(\d+)\.(\d+)') {
                $major = [int]$Matches[1]
                if ($major -ge 8) { $usable += $line.Trim() }
            }
        }
        if ($usable.Count -eq 0) { return $null }
        return [pscustomobject]@{ Path=$Exe; Sdks=$lines; Usable=$usable; Selected=$usable[-1] }
    } catch { return $null }
}

function Resolve-DotNetSdk {
    param(
        [Parameter(Mandatory=$true)][string]$Root,
        [scriptblock]$Status
    )
    $system = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($system) {
        $info = Get-UsableDotNetInfo -Exe $system.Source
        if ($info) { return $info }
    }

    $localDir = Join-Path $Root '.dotnet'
    $localExe = Join-Path $localDir 'dotnet.exe'
    $localInfo = Get-UsableDotNetInfo -Exe $localExe
    if ($localInfo) { return $localInfo }

    if ($Status) { & $Status 36 '正在准备 .NET SDK' '未检测到 >= .NET 8 SDK，将自动安装工程私有 .NET 8 SDK；无需管理员权限。' }
    $cache = Join-Path $Root '.cache'
    New-Item -ItemType Directory -Force -Path $cache,$localDir | Out-Null
    $installer = Join-Path $cache 'dotnet-install.ps1'
    if (-not (Test-Path -LiteralPath $installer)) {
        if ($Status) { & $Status 38 '正在下载 .NET 官方安装器' '下载 dotnet-install.ps1；仅电脑没有可用 SDK 时执行一次。' }
        Invoke-WebRequest -UseBasicParsing -Uri 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installer
    }

    if ($Status) { & $Status 40 '正在安装本地 .NET 8 SDK' '安装到工程 .dotnet 目录；以后 run / Release 会直接复用。' }
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer -Channel '8.0' -Quality 'GA' -InstallDir $localDir -NoPath
    if ($LASTEXITCODE -ne 0) { throw "自动安装 .NET 8 SDK 失败（退出码 $LASTEXITCODE）。" }

    $localInfo = Get-UsableDotNetInfo -Exe $localExe
    if (-not $localInfo) { throw '自动安装完成，但仍未找到可用的 .NET SDK。' }
    return $localInfo
}
