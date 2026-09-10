param([switch]$DebugMode)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Join-Path $Root 'OCRCaptureTool.csproj'
$Models = Join-Path $Root 'Models'
$LogDir = Join-Path $Root 'logs'
$LogFile = Join-Path $LogDir 'run.log'
$BuildSchema = 'full-v021-dotnet-auto-medium'
$BuildSchemaFile = Join-Path $LogDir 'build_schema.txt'
$env:DOTNET_CLI_UI_LANGUAGE = 'en-US'
$env:DOTNET_NOLOGO = '1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
. (Join-Path $Root 'dotnet_bootstrap.ps1')

$Form=$null; $StageLabel=$null; $DetailLabel=$null; $Progress=$null; $PercentLabel=$null
function Log([string]$Text) { Add-Content -LiteralPath $LogFile -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),$Text) -Encoding UTF8; if($DebugMode){Write-Host $Text} }
function Open-ProgressWindow {
    if($null -ne $script:Form){return}
    Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $script:Form=New-Object System.Windows.Forms.Form; $script:Form.Text='OCRCaptureTool Full · 启动'; $script:Form.StartPosition='CenterScreen'; $script:Form.FormBorderStyle='FixedDialog'; $script:Form.MaximizeBox=$false; $script:Form.MinimizeBox=$true; $script:Form.Width=580; $script:Form.Height=220; $script:Form.BackColor=[Drawing.Color]::FromArgb(23,27,35); $script:Form.ForeColor=[Drawing.Color]::FromArgb(237,241,247)
    $title=New-Object Windows.Forms.Label; $title.Left=24;$title.Top=18;$title.Width=510;$title.Height=24;$title.Font=New-Object Drawing.Font('Microsoft YaHei UI',11,[Drawing.FontStyle]::Bold);$title.Text='OCRCaptureTool Full · v0.2.1';$script:Form.Controls.Add($title)
    $script:StageLabel=New-Object Windows.Forms.Label;$script:StageLabel.Left=24;$script:StageLabel.Top=55;$script:StageLabel.Width=510;$script:StageLabel.Height=26;$script:StageLabel.Font=New-Object Drawing.Font('Microsoft YaHei UI',10,[Drawing.FontStyle]::Bold);$script:StageLabel.Text='正在启动…';$script:Form.Controls.Add($script:StageLabel)
    $script:DetailLabel=New-Object Windows.Forms.Label;$script:DetailLabel.Left=24;$script:DetailLabel.Top=84;$script:DetailLabel.Width=510;$script:DetailLabel.Height=34;$script:DetailLabel.Font=New-Object Drawing.Font('Microsoft YaHei UI',9);$script:DetailLabel.ForeColor=[Drawing.Color]::FromArgb(158,170,190);$script:DetailLabel.Text='检查工程状态…';$script:Form.Controls.Add($script:DetailLabel)
    $script:Progress=New-Object Windows.Forms.ProgressBar;$script:Progress.Left=24;$script:Progress.Top=132;$script:Progress.Width=455;$script:Progress.Height=12;$script:Progress.Minimum=0;$script:Progress.Maximum=100;$script:Progress.Value=0;$script:Progress.Style='Continuous';$script:Form.Controls.Add($script:Progress)
    $script:PercentLabel=New-Object Windows.Forms.Label;$script:PercentLabel.Left=488;$script:PercentLabel.Top=125;$script:PercentLabel.Width=48;$script:PercentLabel.Height=26;$script:PercentLabel.TextAlign='MiddleRight';$script:PercentLabel.Font=New-Object Drawing.Font('Segoe UI',9,[Drawing.FontStyle]::Bold);$script:PercentLabel.Text='0%';$script:Form.Controls.Add($script:PercentLabel)
    $hint=New-Object Windows.Forms.Label;$hint.Left=24;$hint.Top=157;$hint.Width=510;$hint.Height=20;$hint.Font=New-Object Drawing.Font('Microsoft YaHei UI',8);$hint.ForeColor=[Drawing.Color]::FromArgb(112,124,145);$hint.Text='run 会自动检查模型、SDK 和编译缓存；已有内容不会重复安装。';$script:Form.Controls.Add($hint)
    $script:Form.Show(); [Windows.Forms.Application]::DoEvents()
}
function Set-Progress([int]$Percent,[string]$Stage,[string]$Detail){Open-ProgressWindow;$v=[Math]::Max(0,[Math]::Min(100,$Percent));$script:Progress.Value=$v;$script:PercentLabel.Text="$v%";if($Stage){$script:StageLabel.Text=$Stage};if($Detail){$script:DetailLabel.Text=$Detail};[Windows.Forms.Application]::DoEvents();Log ("{0}% | {1} | {2}" -f $v,$Stage,$Detail)}
function Pump-Progress{if($null -ne $script:Form){[Windows.Forms.Application]::DoEvents()}}
function Close-ProgressWindow{if($null -ne $script:Form){try{$script:Form.Close();$script:Form.Dispose()}catch{};$script:Form=$null}}
function Fail([string]$Message){Log "ERROR: $Message";Close-ProgressWindow;Add-Type -AssemblyName PresentationFramework -ErrorAction SilentlyContinue;[Windows.MessageBox]::Show("$Message`n`n详细日志：$LogFile",'OCRCaptureTool Full','OK','Error')|Out-Null;exit 1}
function Run-CmdStep([string]$Command,[string]$OutputFile,[int]$Percent,[string]$Stage,[string]$Detail){Set-Progress $Percent $Stage $Detail;Remove-Item -LiteralPath $OutputFile -Force -ErrorAction SilentlyContinue;$psi=New-Object Diagnostics.ProcessStartInfo;$psi.FileName='cmd.exe';$psi.Arguments="/d /s /c chcp 65001 >nul & $Command > `"$OutputFile`" 2>&1";$psi.WorkingDirectory=$Root;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$p=[Diagnostics.Process]::Start($psi);while(-not $p.HasExited){Pump-Progress;Start-Sleep -Milliseconds 120};$p.WaitForExit();$output=if(Test-Path -LiteralPath $OutputFile){Get-Content -LiteralPath $OutputFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue}else{''};if($output){Add-Content -LiteralPath $LogFile -Value $output -Encoding UTF8};return @{ExitCode=$p.ExitCode;Output=$output}}

try {
    Log 'Launcher started.'
    Set-Progress 2 '正在检查工程' '检查 PP-OCRv6 Medium 模型、.NET SDK 与已有编译缓存…'
    $requiredModels=@('v6\PP-OCRv6_det_medium.onnx','v6\PP-OCRv6_rec_medium.onnx','v6\ppocrv6_medium_dict.txt')
    $missing=@($requiredModels|Where-Object{-not(Test-Path -LiteralPath (Join-Path $Models $_))})
    if($missing.Count -gt 0){
        Set-Progress 5 '正在修复 OCR 模型' ("缺少："+($missing -join ', ')+'；优先复用本机已有模型。')
        Close-ProgressWindow
        $prepare=Join-Path $Root 'prepare_models.ps1';$psi=New-Object Diagnostics.ProcessStartInfo;$psi.FileName='powershell.exe';$psi.Arguments="-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$prepare`" -CalledByRunner";$psi.WorkingDirectory=$Root;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$p=[Diagnostics.Process]::Start($psi);$p.WaitForExit();if($p.ExitCode -ne 0){Fail '模型准备失败，请查看 logs\prepare_models.log。'}
        Set-Progress 30 'OCR 模型准备完成' 'Medium DET、REC、字典均已就绪。'
    } else { Set-Progress 12 'OCR 模型已就绪' '检测模型、识别模型和字典均已存在，不重复下载。' }

    Set-Progress 34 '正在检查 .NET SDK' '支持任意 >= .NET 8 SDK；.NET 9/10 可直接构建 net8.0，不强制安装 8.x。'
    $sdkInfo=Resolve-DotNetSdk -Root $Root -Status { param($p,$s,$d) Set-Progress $p $s $d }
    $DotnetExe=$sdkInfo.Path
    $sdkText=($sdkInfo.Sdks -join "`n");Log "Installed/usable SDKs: $sdkText"
    Set-Progress 44 '.NET SDK 已就绪' ($sdkInfo.Selected+' · 使用 '+$DotnetExe)

    $cached=if(Test-Path -LiteralPath $BuildSchemaFile){(Get-Content -LiteralPath $BuildSchemaFile -Raw -ErrorAction SilentlyContinue).Trim()}else{''}
    $forceClean=$cached -ne $BuildSchema
    if($forceClean){Set-Progress 46 '正在清理旧编译缓存' '工程结构已变化，清理 bin/obj 后只重建一次。';Remove-Item (Join-Path $Root 'bin'),(Join-Path $Root 'obj') -Recurse -Force -ErrorAction SilentlyContinue;Log "Build schema changed: '$cached' -> '$BuildSchema'."}

    $exeCandidates=@((Join-Path $Root 'bin\Release\net8.0-windows10.0.19041.0\OCRCaptureTool.exe'),(Join-Path $Root 'bin\Release\net8.0-windows\OCRCaptureTool.exe'))
    $exe=$exeCandidates|Where-Object{Test-Path -LiteralPath $_}|Select-Object -First 1
    $needBuild=$true
    if($exe -and -not $forceClean){$exeTime=(Get-Item $exe).LastWriteTimeUtc;$sources=Get-ChildItem $Root -Recurse -File -Include *.cs,*.xaml,*.csproj|Where-Object{$_.FullName -notmatch '\\(bin|obj|release)\\'};$newer=$sources|Where-Object{$_.LastWriteTimeUtc -gt $exeTime}|Select-Object -First 1;$needBuild=$null -ne $newer}
    $q='"'+$DotnetExe+'"'
    if($needBuild){
        $restoreLog=Join-Path $LogDir 'restore.log';$r=Run-CmdStep "$q restore `"$Project`" --nologo" $restoreLog 50 '正在恢复 .NET 依赖' '仅恢复 RapidOcrNet、ONNX Runtime、SkiaSharp 与 WPF 依赖；不安装 Python/Paddle。';if($r.ExitCode -ne 0){$tail=$r.Output;if($tail.Length -gt 5000){$tail=$tail.Substring($tail.Length-5000)};Fail("NuGet 依赖恢复失败。`n`n"+$tail.Trim())}
        $buildLog=Join-Path $LogDir 'build.log';$b=Run-CmdStep "$q build `"$Project`" -c Release --no-restore --nologo" $buildLog 68 '正在编译主程序' '编译 WPF、截图、历史记录和 RapidOcrNet OCR 模块…';if($b.ExitCode -ne 0){$tail=$b.Output;if($tail.Length -gt 7000){$tail=$tail.Substring($tail.Length-7000)};Fail("编译失败。`n`n"+$tail.Trim()+"`n`n完整输出：$buildLog")}
        Set-Progress 84 '编译完成' '正在定位 OCRCaptureTool.exe 并检查模型输出…';$exe=$exeCandidates|Where-Object{Test-Path -LiteralPath $_}|Select-Object -First 1;Set-Content -LiteralPath $BuildSchemaFile -Value $BuildSchema -Encoding UTF8
    } else {Set-Progress 84 '使用已有编译缓存' '源码没有变化，跳过 NuGet restore 和 WPF 编译。'}
    if(-not $exe){Fail '编译完成后仍未找到 OCRCaptureTool.exe。'}
    $exeDir=Split-Path -Parent $exe
    foreach($name in $requiredModels){$out=Join-Path (Join-Path $exeDir 'Models') $name;if(-not(Test-Path -LiteralPath $out)){Fail "编译输出缺少模型文件：$out"}}

    Set-Progress 90 '正在启动 OCRCaptureTool Full' '启动主程序；主窗口真正显示后才判定成功。'
    $token=[Guid]::NewGuid().ToString('N');$ready=Join-Path $LogDir ("app_ready_{0}.flag" -f $token);$failure=$ready+'.error';Remove-Item $ready,$failure -Force -ErrorAction SilentlyContinue
    $psi=New-Object Diagnostics.ProcessStartInfo;$psi.FileName=$exe;$psi.Arguments="--ready-file `"$ready`"";$psi.WorkingDirectory=$exeDir;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true;$app=[Diagnostics.Process]::Start($psi);Log("Started PID {0}; waiting for READY: {1}" -f $app.Id,$ready)
    Set-Progress 92 '正在加载 OCR 模型' 'PP-OCRv6 Medium 正在建立 DET / REC ONNX 会话；程序自身窗口继续显示具体进度。';Start-Sleep -Milliseconds 350;Pump-Progress
    if($app.HasExited){$ft=if(Test-Path $failure){Get-Content $failure -Raw -Encoding UTF8}else{''};Fail("主程序在 READY 前退出，退出码：$($app.ExitCode)。`n`n$ft")}
    Close-ProgressWindow
    $deadline=[DateTime]::UtcNow.AddMinutes(2)
    while([DateTime]::UtcNow -lt $deadline){if(Test-Path $ready){$t=Get-Content $ready -Raw -Encoding UTF8 -ErrorAction SilentlyContinue;Log("Main window READY: "+$t.Trim());Remove-Item $ready,$failure -Force -ErrorAction SilentlyContinue;exit 0};if(Test-Path $failure){$ft=Get-Content $failure -Raw -Encoding UTF8 -ErrorAction SilentlyContinue;Remove-Item $ready,$failure -Force -ErrorAction SilentlyContinue;Fail("主程序启动失败。`n`n"+$ft.Trim())};if($app.HasExited){Fail("主程序在 READY 前退出，退出码：$($app.ExitCode)。`n`n请查看 %LOCALAPPDATA%\OCRCaptureTool\logs\startup_trace.log")};Start-Sleep -Milliseconds 150}
    Fail '主程序仍在运行，但 2 分钟内未报告 READY。请查看 startup_trace.log。'
} catch { Close-ProgressWindow; Fail $_.Exception.Message }
