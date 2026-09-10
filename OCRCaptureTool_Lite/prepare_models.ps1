param([switch]$CalledByRunner)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Models = Join-Path $Root 'Models\v6'
$LogDir = Join-Path $Root 'logs'
$LogFile = Join-Path $LogDir 'prepare_models.log'
New-Item -ItemType Directory -Force -Path $Models, $LogDir | Out-Null

$Specs = @(
    [pscustomobject]@{
        Name='PP-OCRv6 Small 检测模型'; File='PP-OCRv6_det_small.onnx'; Min=5000000L;
        Sha='090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f';
        Urls=@(
            'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv6/det/PP-OCRv6_det_small.onnx',
            'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/onnx/PP-OCRv6/det/PP-OCRv6_det_small.onnx'
        )
    },
    [pscustomobject]@{
        Name='PP-OCRv6 Small 识别模型'; File='PP-OCRv6_rec_small.onnx'; Min=10000000L;
        Sha='6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884';
        Urls=@(
            'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx',
            'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx'
        )
    },
    [pscustomobject]@{
        Name='PP-OCRv6 字典'; File='ppocrv6_small_dict.txt'; Min=50000L;
        Sha='b5f2bfe2bdd9448429e3e82b51c789775d9b42f2403d082b00662eb77e401c5d';
        Urls=@(
            'https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/ppocr/utils/dict/ppocrv6_dict.txt',
            'https://gitee.com/paddlepaddle/PaddleOCR/raw/main/ppocr/utils/dict/ppocrv6_dict.txt'
        )
    }
)

$GuiMode = [bool]$CalledByRunner
$GuiForm=$null; $GuiTitle=$null; $GuiDetail=$null; $GuiProgress=$null; $GuiPercent=$null
if ($GuiMode) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $GuiForm = New-Object System.Windows.Forms.Form
    $GuiForm.Text='OCRCaptureTool Lite · 校验/修复模型'; $GuiForm.StartPosition='CenterScreen'
    $GuiForm.FormBorderStyle=[System.Windows.Forms.FormBorderStyle]::FixedDialog; $GuiForm.MaximizeBox=$false
    $GuiForm.Width=560; $GuiForm.Height=205; $GuiForm.BackColor=[System.Drawing.Color]::FromArgb(24,28,36); $GuiForm.ForeColor=[System.Drawing.Color]::FromArgb(235,239,247)
    $GuiTitle=New-Object System.Windows.Forms.Label; $GuiTitle.Left=24; $GuiTitle.Top=22; $GuiTitle.Width=490; $GuiTitle.Height=28; $GuiTitle.Font=New-Object System.Drawing.Font('Microsoft YaHei UI',11,[System.Drawing.FontStyle]::Bold); $GuiTitle.Text='正在校验 PP-OCRv6 Small 模型'; $GuiForm.Controls.Add($GuiTitle)
    $GuiDetail=New-Object System.Windows.Forms.Label; $GuiDetail.Left=24; $GuiDetail.Top=58; $GuiDetail.Width=490; $GuiDetail.Height=35; $GuiDetail.Font=New-Object System.Drawing.Font('Microsoft YaHei UI',9); $GuiDetail.ForeColor=[System.Drawing.Color]::FromArgb(158,170,190); $GuiDetail.Text='优先使用工程内置模型或复用 ScreenAssistant 模型。'; $GuiForm.Controls.Add($GuiDetail)
    $GuiProgress=New-Object System.Windows.Forms.ProgressBar; $GuiProgress.Left=24; $GuiProgress.Top=105; $GuiProgress.Width=450; $GuiProgress.Height=10; $GuiProgress.Minimum=0; $GuiProgress.Maximum=100; $GuiForm.Controls.Add($GuiProgress)
    $GuiPercent=New-Object System.Windows.Forms.Label; $GuiPercent.Left=480; $GuiPercent.Top=98; $GuiPercent.Width=48; $GuiPercent.Height=25; $GuiPercent.TextAlign=[System.Drawing.ContentAlignment]::MiddleRight; $GuiPercent.Font=New-Object System.Drawing.Font('Segoe UI',9,[System.Drawing.FontStyle]::Bold); $GuiPercent.Text='0%'; $GuiForm.Controls.Add($GuiPercent)
    $hint=New-Object System.Windows.Forms.Label; $hint.Left=24; $hint.Top=132; $hint.Width=500; $hint.Height=25; $hint.Font=New-Object System.Drawing.Font('Microsoft YaHei UI',8); $hint.ForeColor=[System.Drawing.Color]::FromArgb(112,124,145); $hint.Text='模型完整时几秒内完成；只有缺失且本机找不到可复用模型时才联网。'; $GuiForm.Controls.Add($hint)
    $GuiForm.Show(); [System.Windows.Forms.Application]::DoEvents()
}
function Set-Gui([int]$p,[string]$title,[string]$detail){ if(-not $GuiMode -or $null -eq $GuiForm){return}; $v=[Math]::Max(0,[Math]::Min(100,$p)); $GuiProgress.Value=$v; $GuiPercent.Text="$v%"; if($title){$GuiTitle.Text=$title}; if($detail){$GuiDetail.Text=$detail}; [System.Windows.Forms.Application]::DoEvents() }
function Log([string]$m){ Add-Content -LiteralPath $LogFile -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),$m) -Encoding UTF8 }
function Hash-Ok($path,$sha){ if(-not(Test-Path -LiteralPath $path)){return $false}; $h=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant(); return $h -eq $sha.ToLowerInvariant() }
function Size-Text([long]$n){ if($n-ge 1MB){return ('{0:N1} MB' -f ($n/1MB))}; return ('{0:N1} KB' -f ($n/1KB)) }

function Find-ReusableModel($spec){
    $parent=Split-Path -Parent $Root
    $candidateRoots = New-Object System.Collections.Generic.List[string]
    Get-ChildItem -LiteralPath $parent -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'ScreenAssistant|OCRCaptureTool' -and $_.FullName -ne $Root } | ForEach-Object { $candidateRoots.Add($_.FullName) }
    foreach($extra in @(
        (Join-Path $env:LOCALAPPDATA 'ScreenAssistant'),
        (Join-Path $env:LOCALAPPDATA 'LonzilTools\ScreenAssistant')
    )) { if($extra -and (Test-Path -LiteralPath $extra)){ $candidateRoots.Add($extra) } }
    foreach($base in $candidateRoots){
        try {
            $files=Get-ChildItem -LiteralPath $base -Recurse -File -Filter $spec.File -ErrorAction SilentlyContinue
            foreach($file in $files){ if($file.Length -ge $spec.Min -and (Hash-Ok $file.FullName $spec.Sha)){ return $file.FullName } }
        } catch {}
    }
    return $null
}


$script:WheelTried = $false
function Try-RapidOcrWheelModels {
    if ($script:WheelTried) { return }
    $script:WheelTried = $true

    $needOnnx = @()
    foreach ($candidate in ($Specs | Where-Object { $_.File -like '*.onnx' })) {
        $candidatePath = Join-Path $Models $candidate.File
        if (-not ((Test-Path -LiteralPath $candidatePath) -and (Hash-Ok $candidatePath $candidate.Sha))) { $needOnnx += $candidate }
    }
    if ($needOnnx.Count -eq 0) { return }

    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
    $wheelUrl = 'https://files.pythonhosted.org/packages/55/ed/0ee9b9281986974be9d2406ae0134c8d7c91d2fc613f16ffda9701eeda6f/rapidocr-3.9.2-py3-none-any.whl'
    $wheelSha = '04d6b8d151f823d930bd91910555f57bea897c0c44fa6794267b94cf9c1ef9a0'
    $wheel = Join-Path $Models '.rapidocr-3.9.2-py3-none-any.whl'
    try {
        if (-not ((Test-Path -LiteralPath $wheel) -and (Hash-Ok $wheel $wheelSha))) {
            Remove-Item -LiteralPath $wheel -Force -ErrorAction SilentlyContinue
            Set-Gui 36 '正在获取 RapidOCR Small 离线模型包' '优先从 PyPI CDN 获取一次性模型包；只解出 DET / REC，不安装 Python。'
            $handler=New-Object System.Net.Http.HttpClientHandler; $handler.AllowAutoRedirect=$true
            $client=New-Object System.Net.Http.HttpClient($handler); $client.Timeout=[TimeSpan]::FromMinutes(12); $client.DefaultRequestHeaders.UserAgent.ParseAdd('OCRCaptureTool/0.2.0')
            try {
                $response=$client.GetAsync($wheelUrl,[System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult(); $response.EnsureSuccessStatusCode()
                $total=$response.Content.Headers.ContentLength; $input=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult(); $output=[IO.File]::Open($wheel,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
                try { $buffer=New-Object byte[] (1024*1024); [long]$done=0; while(($read=$input.Read($buffer,0,$buffer.Length))-gt 0){ $output.Write($buffer,0,$read); $done+=$read; if($total -and $total-gt 0){$pct=[Math]::Min(100,[int](100*$done/$total)); Set-Gui (36+[int](22*$pct/100)) '正在获取 RapidOCR Small 离线模型包' ((Size-Text $done)+' / '+(Size-Text $total))} } } finally {$output.Dispose();$input.Dispose()}
            } finally {$client.Dispose();$handler.Dispose()}
            if (-not (Hash-Ok $wheel $wheelSha)) { throw 'RapidOCR wheel SHA-256 校验失败。' }
        }

        Set-Gui 60 '正在从离线模型包提取 DET / REC' '不安装 Python，只把 PP-OCRv6 Small ONNX 模型复制到工程。'
        $zip=[System.IO.Compression.ZipFile]::OpenRead($wheel)
        try {
            foreach($spec in $Specs | Where-Object { $_.File -like '*.onnx' }) {
                $target=Join-Path $Models $spec.File
                if ((Test-Path -LiteralPath $target) -and (Hash-Ok $target $spec.Sha)) { continue }
                $entry=$zip.Entries | Where-Object { $_.FullName.EndsWith('/'+$spec.File,[System.StringComparison]::OrdinalIgnoreCase) -or $_.FullName.Equals($spec.File,[System.StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1
                if ($null -eq $entry) { continue }
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$target,$true)
                if (-not ((Get-Item -LiteralPath $target).Length -ge $spec.Min -and (Hash-Ok $target $spec.Sha))) { Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue }
            }
        } finally { $zip.Dispose() }
        Log 'RapidOCR PyPI wheel fallback completed.'
    } catch {
        Log ('RapidOCR wheel fallback failed: '+$_.Exception.Message)
    } finally {
        Remove-Item -LiteralPath $wheel -Force -ErrorAction SilentlyContinue
    }
}

function Download-Model($spec,$target,[int]$base,[int]$span){
    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    $errors=@()
    foreach($url in $spec.Urls){
        $tmp="$target.download"; Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        try{
            Log "download $($spec.Name) from $url"; Set-Gui $base "正在联网修复 $($spec.Name)" '本机没有找到可复用模型，正在连接模型源…'
            $handler=New-Object System.Net.Http.HttpClientHandler; $handler.AllowAutoRedirect=$true
            $client=New-Object System.Net.Http.HttpClient($handler); $client.Timeout=[TimeSpan]::FromMinutes(15); $client.DefaultRequestHeaders.UserAgent.ParseAdd('OCRCaptureTool/0.2.0')
            try{
                $response=$client.GetAsync($url,[System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult(); $response.EnsureSuccessStatusCode()
                $total=$response.Content.Headers.ContentLength; $input=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult(); $output=[IO.File]::Open($tmp,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
                try{ $buffer=New-Object byte[] (1024*1024); [long]$done=0; while(($read=$input.Read($buffer,0,$buffer.Length))-gt 0){ $output.Write($buffer,0,$read); $done+=$read; if($total -and $total-gt 0){$pct=[Math]::Min(100,[int](100*$done/$total)); Set-Gui ($base+[int]($span*$pct/100)) "正在联网修复 $($spec.Name)" ((Size-Text $done)+' / '+(Size-Text $total))} } } finally {$output.Dispose();$input.Dispose()}
            } finally {$client.Dispose();$handler.Dispose()}
            if((Get-Item -LiteralPath $tmp).Length -lt $spec.Min -or -not(Hash-Ok $tmp $spec.Sha)){throw '下载完成但 SHA-256/大小校验失败。'}
            Move-Item -LiteralPath $tmp -Destination $target -Force; return
        }catch{ $errors += "$url -> $($_.Exception.Message)"; Log ($errors[-1]); Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    }
    throw ($spec.Name+" 修复失败。`n"+($errors -join "`n"))
}

try{
    Write-Host 'OCRCaptureTool Lite - PP-OCRv6 Small 模型校验/修复' -ForegroundColor Cyan
    Write-Host '版本：0.2.0'; Write-Host "模型目录：$Models"; Write-Host '完整模型不会重复下载；优先从附近 ScreenAssistant 直接复用。'; Write-Host ''
    for($i=0;$i-lt $Specs.Count;$i++){
        $spec=$Specs[$i]; $target=Join-Path $Models $spec.File; $base=5+[int](90*$i/$Specs.Count); $next=5+[int](90*($i+1)/$Specs.Count); $span=$next-$base
        Set-Gui $base ("正在校验 "+$spec.Name) $spec.File
        if((Test-Path -LiteralPath $target) -and (Get-Item -LiteralPath $target).Length -ge $spec.Min -and (Hash-Ok $target $spec.Sha)){
            Write-Host ("[OK] {0} 已在工程内 ({1})" -f $spec.Name,(Size-Text (Get-Item $target).Length)) -ForegroundColor Green; Log "$($spec.Name) bundled/local OK"; Set-Gui $next ("已找到 "+$spec.Name) '工程内文件完整，不需要联网。'; continue
        }
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        $reuse=Find-ReusableModel $spec
        if($reuse){
            Copy-Item -LiteralPath $reuse -Destination $target -Force
            Write-Host ("[OK] {0} 已从本机复用：{1}" -f $spec.Name,$reuse) -ForegroundColor Green; Log "$($spec.Name) reused from $reuse"; Set-Gui $next ("已复用 "+$spec.Name) '直接复制本机已有模型，不需要联网。'; continue
        }
        if ($spec.File -like '*.onnx') {
            Try-RapidOcrWheelModels
            if ((Test-Path -LiteralPath $target) -and (Get-Item -LiteralPath $target).Length -ge $spec.Min -and (Hash-Ok $target $spec.Sha)) {
                Write-Host ("[OK] {0} 已从 RapidOCR 官方离线模型包提取" -f $spec.Name) -ForegroundColor Green; Log "$($spec.Name) extracted from RapidOCR wheel"; Set-Gui $next ("已准备 "+$spec.Name) '从单个离线模型包提取完成。'; continue
            }
        }
        Write-Host ("[INFO] 本机未找到可复用的 {0}，开始单文件联网修复。" -f $spec.Name) -ForegroundColor Yellow
        Download-Model $spec $target $base $span
        Write-Host ("[OK] {0} 下载并校验完成" -f $spec.Name) -ForegroundColor Green
    }
    $dict=Join-Path $Models 'ppocrv6_small_dict.txt'; $lines=(Get-Content -LiteralPath $dict -Encoding UTF8 | Measure-Object -Line).Lines; if($lines-lt 18000){throw "字典异常：只有 $lines 行。"}
    Set-Gui 100 '模型校验完成' 'PP-OCRv6 Small DET / REC / 字典均已就绪。'; Write-Host ''; Write-Host '模型校验完成。' -ForegroundColor Green; Log 'model verification completed'
    if($GuiMode -and $GuiForm){Start-Sleep -Milliseconds 250; $GuiForm.Close();$GuiForm.Dispose()}; exit 0
}catch{
    Log ('FAILED: '+$_.Exception.ToString()); Write-Host '';Write-Host '模型准备失败。' -ForegroundColor Red;Write-Host $_.Exception.Message -ForegroundColor Red;Write-Host "日志：$LogFile"
    if($GuiMode -and $GuiForm){$GuiForm.Close();$GuiForm.Dispose();[System.Windows.Forms.MessageBox]::Show("模型准备失败。`r`n`r`n$($_.Exception.Message)`r`n`r`n日志：$LogFile",'OCRCaptureTool Lite','OK','Error')|Out-Null}; exit 1
}
