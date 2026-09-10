$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Version = '0.2.0'
$Name = "OCRCaptureTool_Lite_v$Version"
$ReleaseRoot = Join-Path $Root 'release'
$Final = Join-Path $ReleaseRoot $Name
$Zip = Join-Path $ReleaseRoot "$Name.zip"
$Publish = Join-Path $Root 'publish_tmp'
$ModelsV6 = Join-Path $Root 'Models\v6'

Write-Host 'OCRCaptureTool Lite publisher' -ForegroundColor Cyan
Write-Host "Version: $Version"
Write-Host 'Backend: .NET 8/WPF + RapidOcrNet + PP-OCRv6 Small'
Write-Host ''

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw '.NET 8 SDK was not found on the publishing PC.'
}

Write-Host '[1/5] Preparing PP-OCRv6 Small models...' -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'prepare_models.ps1') -CalledByRunner
if ($LASTEXITCODE -ne 0) { throw 'Model preparation failed.' }

Write-Host '[2/5] Publishing self-contained .NET/WPF application...' -ForegroundColor Cyan
Remove-Item $Publish -Recurse -Force -ErrorAction SilentlyContinue
& dotnet publish (Join-Path $Root 'OCRCaptureTool.csproj') -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=false -p:PublishReadyToRun=false -p:DebugType=None -p:DebugSymbols=false -o $Publish
if ($LASTEXITCODE -ne 0) { throw 'dotnet publish failed.' }

Write-Host '[3/5] Pruning unused bundled OCR models...' -ForegroundColor Cyan
# RapidOcrNet bundles a PP-OCRv5 set. PP-OCRv6 only reuses the orientation
# classifier, so v5 detector/recognizer/dictionaries are unnecessary weight.
$v5Candidates = @((Join-Path $Publish 'models\v5'), (Join-Path $Publish 'Models\v5'))
foreach ($v5 in $v5Candidates) {
    if (-not (Test-Path -LiteralPath $v5)) { continue }
    Get-ChildItem -LiteralPath $v5 -File | ForEach-Object {
        if ($_.Name -ne 'ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx') {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

# A win-x64 publish does not need Linux/macOS native binaries even when a NuGet
# dependency carries cross-platform assets. Remove them defensively.
Get-ChildItem -LiteralPath $Publish -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
    $_.Extension -in @('.so', '.dylib')
} | Remove-Item -Force -ErrorAction SilentlyContinue
foreach ($runtimeDir in @('linux','linux-x64','linux-arm64','osx','osx-x64','osx-arm64')) {
    Get-ChildItem -LiteralPath $Publish -Recurse -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "[\/]runtimes[\/]$([regex]::Escape($runtimeDir))([\/]|$)" } |
        Sort-Object FullName -Descending | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host '[4/5] Building release folder and size report...' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
Remove-Item $Final -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Final | Out-Null
Copy-Item "$Publish\*" $Final -Recurse -Force

$ModelOut = Join-Path $Final 'Models\v6'
New-Item -ItemType Directory -Force -Path $ModelOut | Out-Null
foreach ($name in @('PP-OCRv6_det_small.onnx','PP-OCRv6_rec_small.onnx','ppocrv6_small_dict.txt')) {
    Copy-Item (Join-Path $ModelsV6 $name) $ModelOut -Force
}
Copy-Item (Join-Path $Root '使用说明.txt') $Final -Force

$classifier = Get-ChildItem -LiteralPath $Final -Recurse -File -Filter 'ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx' | Select-Object -First 1
$Required = @(
  (Join-Path $Final 'OCRCaptureTool.exe'),
  (Join-Path $ModelOut 'PP-OCRv6_det_small.onnx'),
  (Join-Path $ModelOut 'PP-OCRv6_rec_small.onnx'),
  (Join-Path $ModelOut 'ppocrv6_small_dict.txt'),
  (Join-Path $Final '使用说明.txt')
)
foreach ($Path in $Required) { if (-not (Test-Path $Path)) { throw "Release file missing: $Path" } }
if (-not $classifier) { throw 'RapidOcrNet v5 orientation classifier was not found after publish.' }

$files = Get-ChildItem -LiteralPath $Final -Recurse -File
$totalBytes = ($files | Measure-Object Length -Sum).Sum
$report = New-Object System.Collections.Generic.List[string]
$report.Add("OCRCaptureTool Lite v$Version 发布报告")
$report.Add("Backend: .NET 8/WPF + RapidOcrNet 3.0.0 + PP-OCRv6 Small")
$report.Add(("Release folder size: {0:N1} MB" -f ($totalBytes / 1MB)))
$report.Add('')
$report.Add('Largest files TOP 20:')
$files | Sort-Object Length -Descending | Select-Object -First 20 | ForEach-Object {
    $relative = $_.FullName.Substring($Final.Length).TrimStart('\')
    $report.Add(("{0,9:N1} MB  {1}" -f ($_.Length / 1MB), $relative))
}
[System.IO.File]::WriteAllLines((Join-Path $Final '发布报告.txt'), $report, [System.Text.UTF8Encoding]::new($true))

Write-Host '[5/5] Creating compressed ZIP...' -ForegroundColor Cyan
Remove-Item $Zip -Force -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stream = [System.IO.File]::Open($Zip, [System.IO.FileMode]::Create)
try {
  $archive = New-Object System.IO.Compression.ZipArchive($stream, [System.IO.Compression.ZipArchiveMode]::Create)
  try {
    Get-ChildItem $Final -Recurse -File | ForEach-Object {
      $relative = $_.FullName.Substring($Final.Length).TrimStart('\')
      $entryName = "$Name/" + ($relative -replace '\\','/')
      # Previously the largest .onnx/.dll/.exe files were stored uncompressed,
      # inflating the transfer ZIP. Use real compression for every file.
      $entry = $archive.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
      $inStream = [System.IO.File]::OpenRead($_.FullName)
      try { $outStream = $entry.Open(); try { $inStream.CopyTo($outStream) } finally { $outStream.Dispose() } } finally { $inStream.Dispose() }
    }
  } finally { $archive.Dispose() }
} finally { $stream.Dispose() }

$zipBytes = (Get-Item -LiteralPath $Zip).Length
Remove-Item $Publish -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ''
Write-Host ("Publish complete. ZIP size: {0:N1} MB" -f ($zipBytes / 1MB)) -ForegroundColor Green
Write-Host $Zip
