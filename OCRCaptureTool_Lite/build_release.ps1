$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Version = '0.2.1'
$Edition = 'Lite'
$Name = 'OCRCaptureTool_Lite'
$ReleaseRoot = Join-Path $Root 'release'
$Zip = Join-Path $ReleaseRoot ($Name + '_v' + $Version + '.zip')
$Publish = Join-Path $Root 'publish_tmp'
$ModelsV6 = Join-Path $Root 'Models\v6'
$env:DOTNET_CLI_UI_LANGUAGE = 'en-US'
$env:DOTNET_NOLOGO = '1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
. (Join-Path $Root 'dotnet_bootstrap.ps1')

try {
    Write-Host '[1/5] Verifying / downloading OCR models...' -ForegroundColor Cyan
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'prepare_models.ps1') -NoGui
    if ($LASTEXITCODE -ne 0) { throw 'Model verification failed.' }

    Write-Host '[2/5] Publishing for Windows x64...' -ForegroundColor Cyan
    $sdk = Resolve-DotNetSdk -Root $Root -Status { param($p,$s,$d) Write-Host ("[{0}%] {1} - {2}" -f $p,$s,$d) }
    Remove-Item $Publish -Recurse -Force -ErrorAction SilentlyContinue
    $dotnet = $sdk.Path
    & $dotnet publish (Join-Path $Root 'OCRCaptureTool.csproj') -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -p:PublishReadyToRun=false -p:PublishTrimmed=false -p:DebugType=None -p:DebugSymbols=false -o $Publish
    if ($LASTEXITCODE -ne 0) { throw 'dotnet publish failed.' }

    Write-Host '[3/5] Removing unused model/runtime files...' -ForegroundColor Cyan
    # RapidOcrNet may bring default v5 assets; retain only its optional orientation classifier.
    foreach ($folder in @((Join-Path $Publish 'models\v5'), (Join-Path $Publish 'Models\v5'))) {
        if (Test-Path $folder) {
            Get-ChildItem $folder -File | Where-Object { $_.Name -ne 'ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx' } | Remove-Item -Force
        }
    }
    Get-ChildItem $Publish -Recurse -File | Where-Object { $_.Extension -in @('.pdb','.so','.dylib') -or $_.Name -match '^README([._-]|$)' } | Remove-Item -Force

    # The source project does not distribute models. Publish must include exactly
    # one copy of each model/dictionary under Models/v6/.
    $publishedModels = Join-Path $Publish 'Models\v6'
    New-Item -ItemType Directory -Force -Path $publishedModels | Out-Null
    foreach ($fileName in @('PP-OCRv6_det_small.onnx','PP-OCRv6_rec_small.onnx','ppocrv6_small_dict.txt')) {
        $source = Join-Path $ModelsV6 $fileName
        $destination = Join-Path $publishedModels $fileName
        if (-not (Test-Path -LiteralPath $source)) { throw "Missing model: $source" }
        if (-not (Test-Path -LiteralPath $destination)) { Copy-Item -LiteralPath $source -Destination $destination }
    }
    $files = @(Get-ChildItem $Publish -Recurse -File)
    $total = ($files | Measure-Object Length -Sum).Sum
    $report = New-Object 'System.Collections.Generic.List[string]'
    $report.Add('OCRCaptureTool ' + $Edition + ' release ' + $Version)
    $report.Add('Engine: .NET / WPF + RapidOcrNet + PP-OCRv6 Small')
    $report.Add(('Uncompressed portable release: {0:N1} MiB' -f ($total / 1MB)))
    $report.Add('This self-contained release includes the .NET runtime and OCR models.')
    $report.Add('')
    $report.Add('Largest files:')
    $files | Sort-Object Length -Descending | Select-Object -First 20 | ForEach-Object {
        $rel = $_.FullName.Substring($Publish.Length).TrimStart('\')
        $report.Add(('{0,8:N1} MiB   {1}' -f ($_.Length / 1MB), $rel))
    }
    [IO.File]::WriteAllLines((Join-Path $Publish 'release_report.txt'), $report, [Text.UTF8Encoding]::new($false))

    Write-Host '[4/5] Creating portable ZIP without duplicating the release folder...' -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $ReleaseRoot | Out-Null
    Remove-Item $Zip -Force -ErrorAction SilentlyContinue
    Add-Type -AssemblyName System.IO.Compression
    $stream = [IO.File]::Open($Zip, [IO.FileMode]::CreateNew)
    try {
        $archive = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create)
        try {
            Get-ChildItem $Publish -Recurse -File | ForEach-Object {
                $relative = $_.FullName.Substring($Publish.Length).TrimStart('\').Replace('\','/')
                # ZIP contains an unversioned top-level folder.
                $entry = $archive.CreateEntry(($Name + '/' + $relative), [IO.Compression.CompressionLevel]::Optimal)
                $inputStream = [IO.File]::OpenRead($_.FullName)
                try {
                    $outputStream = $entry.Open()
                    try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
                } finally { $inputStream.Dispose() }
            }
        } finally { $archive.Dispose() }
    } finally { $stream.Dispose() }

    Write-Host '[5/5] Release complete.' -ForegroundColor Green
    Write-Host ('Portable ZIP: ' + $Zip)
    Write-Host ('ZIP size: {0:N1} MiB' -f ((Get-Item $Zip).Length / 1MB))
    Write-Host 'No second copy of the published directory was created.'
} finally {
    # Eliminates one large temporary copy even if an error occurred.
    Remove-Item $Publish -Recurse -Force -ErrorAction SilentlyContinue
}
