param(
    [switch]$DebugMode
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Join-Path $Root 'OCRCaptureTool.csproj'
$Models = Join-Path $Root 'Models'
$LogDir = Join-Path $Root 'logs'
$LogFile = Join-Path $LogDir 'run.log'
$BuildSchema = 'lite-v020-full-ui-pixelmatch-capturefix-v3'
$BuildSchemaFile = Join-Path $LogDir 'build_schema.txt'
$env:DOTNET_CLI_UI_LANGUAGE = 'en-US'
$env:DOTNET_NOLOGO = '1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Form = $null
$StageLabel = $null
$DetailLabel = $null
$Progress = $null
$PercentLabel = $null

function Log([string]$Text) {
    Add-Content -LiteralPath $LogFile -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Text) -Encoding UTF8
    if ($DebugMode) { Write-Host $Text }
}

function Open-ProgressWindow {
    if ($null -ne $script:Form) { return }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $script:Form = New-Object System.Windows.Forms.Form
    $script:Form.Text = 'OCRCaptureTool Lite · 启动'
    $script:Form.StartPosition = 'CenterScreen'
    $script:Form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $script:Form.MaximizeBox = $false
    $script:Form.MinimizeBox = $true
    $script:Form.Width = 580
    $script:Form.Height = 220
    $script:Form.BackColor = [System.Drawing.Color]::FromArgb(23, 27, 35)
    $script:Form.ForeColor = [System.Drawing.Color]::FromArgb(237, 241, 247)

    $title = New-Object System.Windows.Forms.Label
    $title.Left = 24; $title.Top = 18; $title.Width = 510; $title.Height = 24
    $title.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 11, [System.Drawing.FontStyle]::Bold)
    $title.Text = 'OCRCaptureTool Lite · v0.2.0'
    $script:Form.Controls.Add($title)

    $script:StageLabel = New-Object System.Windows.Forms.Label
    $script:StageLabel.Left = 24; $script:StageLabel.Top = 55; $script:StageLabel.Width = 510; $script:StageLabel.Height = 26
    $script:StageLabel.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold)
    $script:StageLabel.Text = '正在启动…'
    $script:Form.Controls.Add($script:StageLabel)

    $script:DetailLabel = New-Object System.Windows.Forms.Label
    $script:DetailLabel.Left = 24; $script:DetailLabel.Top = 84; $script:DetailLabel.Width = 510; $script:DetailLabel.Height = 34
    $script:DetailLabel.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)
    $script:DetailLabel.ForeColor = [System.Drawing.Color]::FromArgb(158, 170, 190)
    $script:DetailLabel.Text = '检查工程状态…'
    $script:Form.Controls.Add($script:DetailLabel)

    $script:Progress = New-Object System.Windows.Forms.ProgressBar
    $script:Progress.Left = 24; $script:Progress.Top = 132; $script:Progress.Width = 455; $script:Progress.Height = 12
    $script:Progress.Minimum = 0; $script:Progress.Maximum = 100; $script:Progress.Value = 0
    $script:Progress.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
    $script:Form.Controls.Add($script:Progress)

    $script:PercentLabel = New-Object System.Windows.Forms.Label
    $script:PercentLabel.Left = 488; $script:PercentLabel.Top = 125; $script:PercentLabel.Width = 48; $script:PercentLabel.Height = 26
    $script:PercentLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
    $script:PercentLabel.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
    $script:PercentLabel.Text = '0%'
    $script:Form.Controls.Add($script:PercentLabel)

    $hint = New-Object System.Windows.Forms.Label
    $hint.Left = 24; $hint.Top = 157; $hint.Width = 510; $hint.Height = 20
    $hint.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 8)
    $hint.ForeColor = [System.Drawing.Color]::FromArgb(112, 124, 145)
    $hint.Text = '模型和编译缓存存在时会自动跳过对应步骤。'
    $script:Form.Controls.Add($hint)

    $script:Form.Show()
    [System.Windows.Forms.Application]::DoEvents()
}

function Set-Progress([int]$Percent, [string]$Stage, [string]$Detail) {
    Open-ProgressWindow
    $value = [Math]::Max(0, [Math]::Min(100, $Percent))
    $script:Progress.Value = $value
    $script:PercentLabel.Text = "$value%"
    if ($Stage) { $script:StageLabel.Text = $Stage }
    if ($Detail) { $script:DetailLabel.Text = $Detail }
    [System.Windows.Forms.Application]::DoEvents()
    Log ("{0}% | {1} | {2}" -f $value, $Stage, $Detail)
}

function Pump-Progress {
    if ($null -ne $script:Form) { [System.Windows.Forms.Application]::DoEvents() }
}

function Close-ProgressWindow {
    if ($null -ne $script:Form) {
        try { $script:Form.Close(); $script:Form.Dispose() } catch { }
        $script:Form = $null
    }
}

function Fail([string]$Message) {
    Log "ERROR: $Message"
    Close-ProgressWindow
    Add-Type -AssemblyName PresentationFramework -ErrorAction SilentlyContinue
    [System.Windows.MessageBox]::Show("$Message`n`n详细日志：$LogFile", 'OCRCaptureTool Lite', 'OK', 'Error') | Out-Null
    exit 1
}

function Run-CmdStep([string]$Command, [string]$OutputFile, [int]$Percent, [string]$Stage, [string]$Detail) {
    Set-Progress $Percent $Stage $Detail
    Remove-Item -LiteralPath $OutputFile -Force -ErrorAction SilentlyContinue
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'cmd.exe'
    $psi.Arguments = "/d /s /c chcp 65001 >nul & $Command > `"$OutputFile`" 2>&1"
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    while (-not $p.HasExited) { Pump-Progress; Start-Sleep -Milliseconds 120 }
    $p.WaitForExit()
    $output = if (Test-Path -LiteralPath $OutputFile) { Get-Content -LiteralPath $OutputFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue } else { '' }
    if ($output) { Add-Content -LiteralPath $LogFile -Value $output -Encoding UTF8 }
    return @{ ExitCode = $p.ExitCode; Output = $output }
}

try {
    Log 'Launcher started.'
    Set-Progress 2 '正在检查工程' '检查 PP-OCRv6 Small 模型、.NET SDK 与已有编译缓存…'

    $requiredModels = @('v6\PP-OCRv6_det_small.onnx','v6\PP-OCRv6_rec_small.onnx','v6\ppocrv6_small_dict.txt')
    $missing = @($requiredModels | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Models $_)) })
    if ($missing.Count -gt 0) {
        Set-Progress 5 '正在修复 OCR 模型' ("缺少：" + ($missing -join ', ') + '；优先复用附近 ScreenAssistant 模型。')
        Close-ProgressWindow
        $prepareScript = Join-Path $Root 'prepare_models.ps1'
        $preparePsi = New-Object System.Diagnostics.ProcessStartInfo
        $preparePsi.FileName = 'powershell.exe'
        $preparePsi.Arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$prepareScript`" -CalledByRunner"
        $preparePsi.WorkingDirectory = $Root
        $preparePsi.UseShellExecute = $false
        $preparePsi.CreateNoWindow = $true
        $prepareProcess = [System.Diagnostics.Process]::Start($preparePsi)
        $prepareProcess.WaitForExit()
        if ($prepareProcess.ExitCode -ne 0) { Fail '模型准备失败，请查看 logs\prepare_models.log。' }
        Set-Progress 36 'OCR 模型准备完成' 'Small DET、Small REC、PP-OCRv6 字典均已就绪。'
    } else {
        Set-Progress 12 'OCR 模型已就绪' '检测模型、识别模型和中文字典均已缓存，不重复下载。'
    }

    Set-Progress 16 '正在检查 .NET 8 SDK' '确认源码工程具备 WPF 编译环境…'
    $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
    if (-not $dotnet) {
        Fail '.NET 8 SDK 未安装，因此源码工程无法编译。发布给朋友的成品版不需要 SDK。'
    }
    $sdkList = (& dotnet --list-sdks 2>$null) -join "`n"
    Log "Installed SDKs: $sdkList"
    if ($sdkList -notmatch '(?m)^8\.') { Fail "没有检测到 .NET 8 SDK。`n当前检测到：`n$sdkList" }
    Set-Progress 22 '.NET 8 SDK 检查完成' (($sdkList -split "`n" | Select-Object -First 1) + ' · 准备检查编译缓存')

    # One-time clean rebuild whenever the startup/build schema changes. This
    # prevents stale WPF App.g.cs/BAML from resurrecting an old StartupUri.
    $cachedSchema = if (Test-Path -LiteralPath $BuildSchemaFile) {
        (Get-Content -LiteralPath $BuildSchemaFile -Raw -ErrorAction SilentlyContinue).Trim()
    } else { '' }
    $forceCleanBuild = $cachedSchema -ne $BuildSchema
    if ($forceCleanBuild) {
        Set-Progress 25 '正在清理旧 WPF 编译缓存' '删除旧 bin/obj，确保使用当前 App.xaml 与显式 Program.Main 启动链…'
        Remove-Item -LiteralPath (Join-Path $Root 'bin') -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $Root 'obj') -Recurse -Force -ErrorAction SilentlyContinue
        Log "Build schema changed: '$cachedSchema' -> '$BuildSchema'. bin/obj cleaned."
    }

    $exeCandidates = @(
        (Join-Path $Root 'bin\Release\net8.0-windows10.0.19041.0\OCRCaptureTool.exe'),
        (Join-Path $Root 'bin\Release\net8.0-windows\OCRCaptureTool.exe')
    )
    $exe = $exeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

    $needBuild = $true
    if ($exe -and -not $forceCleanBuild) {
        $exeTime = (Get-Item -LiteralPath $exe).LastWriteTimeUtc
        $sources = Get-ChildItem -LiteralPath $Root -Recurse -File -Include *.cs,*.xaml,*.csproj | Where-Object { $_.FullName -notmatch '\\(bin|obj|release)\\' }
        $newer = $sources | Where-Object { $_.LastWriteTimeUtc -gt $exeTime } | Select-Object -First 1
        $needBuild = $null -ne $newer
    }

    if ($needBuild) {
        $restoreLog = Join-Path $LogDir 'restore.log'
        $restore = Run-CmdStep "dotnet restore `"$Project`" --nologo" $restoreLog 30 '正在恢复 .NET 依赖' '检查/恢复 RapidOcrNet、ONNX Runtime、SkiaSharp 与 WPF 编译依赖…'
        if ($restore.ExitCode -ne 0) {
            $tail = $restore.Output; if ($tail.Length -gt 5000) { $tail = $tail.Substring($tail.Length - 5000) }
            Fail ("NuGet 依赖恢复失败。`n`n" + $tail.Trim())
        }

        $buildLog = Join-Path $LogDir 'build.log'
        $build = Run-CmdStep "dotnet build `"$Project`" -c Release --no-restore --nologo" $buildLog 55 '正在编译 Lite 主程序' '编译 C#、WPF/XAML、物理像素截图模块和 RapidOcrNet OCR 模块…'
        if ($build.ExitCode -ne 0) {
            $tail = $build.Output; if ($tail.Length -gt 7000) { $tail = $tail.Substring($tail.Length - 7000) }
            Fail ("编译失败。`n`n" + $tail.Trim() + "`n`n完整输出：$buildLog")
        }
        Set-Progress 82 '编译完成' '正在定位 OCRCaptureTool.exe 并检查输出文件…'
        $exe = $exeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        Set-Content -LiteralPath $BuildSchemaFile -Value $BuildSchema -Encoding UTF8
    } else {
        Set-Progress 82 '使用已有编译缓存' '源码没有变化，跳过 NuGet restore 和 WPF 编译。'
    }

    if (-not $exe) { Fail '编译完成后仍未找到 OCRCaptureTool.exe。' }
    $exeDir = Split-Path -Parent $exe
    foreach ($name in $requiredModels) {
        $outModel = Join-Path (Join-Path $exeDir 'Models') $name
        if (-not (Test-Path -LiteralPath $outModel)) {
            Fail "编译输出缺少模型文件：$outModel"
        }
    }

    Set-Progress 90 '正在启动 OCRCaptureTool Lite' '启动 WPF 程序；只有主界面真正显示后才会判定启动成功…'
    $runToken = [Guid]::NewGuid().ToString('N')
    $readyFile = Join-Path $LogDir ("app_ready_{0}.flag" -f $runToken)
    $failureFile = $readyFile + '.error'
    Remove-Item -LiteralPath $readyFile,$failureFile -Force -ErrorAction SilentlyContinue

    $appPsi = New-Object System.Diagnostics.ProcessStartInfo
    $appPsi.FileName = $exe
    $appPsi.Arguments = "--ready-file `"$readyFile`""
    $appPsi.WorkingDirectory = $exeDir
    $appPsi.UseShellExecute = $false
    $appPsi.CreateNoWindow = $true
    $app = [System.Diagnostics.Process]::Start($appPsi)
    Log ("Started PID {0}; waiting for READY handshake: {1}" -f $app.Id, $readyFile)

    Set-Progress 92 '等待程序启动窗口' 'Lite 正在加载 RapidOcrNet + PP-OCRv6 Small；程序自身窗口会继续显示 0–100% 进度。'
    Start-Sleep -Milliseconds 450
    Pump-Progress

    if ($app.HasExited) {
        $exit = $app.ExitCode
        $failureText = if (Test-Path -LiteralPath $failureFile) { Get-Content -LiteralPath $failureFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue } else { '' }
        $trace = Join-Path $env:LOCALAPPDATA 'OCRCaptureToolLite\logs\startup_trace.log'
        $bootstrap = Join-Path $env:LOCALAPPDATA 'OCRCaptureToolLite\logs\bootstrap_trace.log'
        $extra = if ($failureText) { "`n`n$failureText" } else { "`n`n入口日志：$bootstrap`n启动跟踪：$trace" }
        Fail "主程序在主界面显示前就退出了，退出码：$exit。$extra"
    }

    # Do not let the source-launcher window cover the real WPF model-loading
    # window. From this point the application itself owns the visible progress.
    Close-ProgressWindow
    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $readyFile) {
            $readyText = Get-Content -LiteralPath $readyFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
            Log ("Main window READY: {0}" -f $readyText.Trim())
            Remove-Item -LiteralPath $readyFile,$failureFile -Force -ErrorAction SilentlyContinue
            exit 0
        }
        if (Test-Path -LiteralPath $failureFile) {
            $failureText = Get-Content -LiteralPath $failureFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $readyFile,$failureFile -Force -ErrorAction SilentlyContinue
            Fail ("主程序启动失败。`n`n" + $failureText.Trim())
        }
        if ($app.HasExited) {
            $exit = $app.ExitCode
            $trace = Join-Path $env:LOCALAPPDATA 'OCRCaptureToolLite\logs\startup_trace.log'
            $bootstrap = Join-Path $env:LOCALAPPDATA 'OCRCaptureToolLite\logs\bootstrap_trace.log'
            Fail "主程序在报告主界面 READY 之前退出，退出码：$exit。`n`n入口日志：$bootstrap`n启动跟踪：$trace"
        }
        Start-Sleep -Milliseconds 150
    }

    $trace = Join-Path $env:LOCALAPPDATA 'OCRCaptureToolLite\logs\startup_trace.log'
    Fail "主程序进程仍在运行，但主界面一直没有报告 READY。`n`n请查看：$trace"
}
catch {
    Close-ProgressWindow
    Fail $_.Exception.Message
}
