$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]

$script:AsTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -like 'IAsyncOperation*'
    } |
    Select-Object -First 1
if ($null -eq $script:AsTask) { throw 'Could not locate the WinRT IAsyncOperation AsTask adapter.' }

function Wait-WinRtOperation {
    param(
        [Parameter(Mandatory = $true)][object]$Operation,
        [Parameter(Mandatory = $true)][type]$ResultType
    )
    $task = $script:AsTask.MakeGenericMethod([type[]]@($ResultType)).Invoke($null, [object[]]@($Operation))
    $task.GetAwaiter().GetResult()
}

$script:AvailableLanguages = @(
    [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages |
        ForEach-Object { [string]$_.LanguageTag }
)
$script:Engines = @{}

function Get-OcrEngine {
    param([Parameter(Mandatory = $true)][string]$LanguageTag)
    if ($script:Engines.ContainsKey($LanguageTag)) { return $script:Engines[$LanguageTag] }
    if ($script:AvailableLanguages -notcontains $LanguageTag) {
        throw "OCR language '$LanguageTag' is unavailable. Installed: $($script:AvailableLanguages -join ', ')"
    }
    $language = [Windows.Globalization.Language]::new($LanguageTag)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    if ($null -eq $engine) { throw "Windows.Media.Ocr could not create language '$LanguageTag'." }
    $script:Engines[$LanguageTag] = $engine
    return $engine
}

$null = Get-OcrEngine -LanguageTag 'zh-Hans-CN'
$script:MaxImageDimension = [int][Windows.Media.Ocr.OcrEngine]::MaxImageDimension

function Write-JsonLine {
    param([Parameter(Mandatory = $true)][object]$Value)
    [Console]::Out.WriteLine((ConvertTo-Json -InputObject $Value -Depth 8 -Compress))
    [Console]::Out.Flush()
}

Write-JsonLine ([ordered]@{
    ready = $true
    language = 'zh-Hans-CN'
    available_languages = $script:AvailableLanguages
    max_image_dimension = $script:MaxImageDimension
    engine = 'Windows.Media.Ocr'
})

while ($null -ne ($line = [Console]::In.ReadLine())) {
    $stage = 'parse-request'
    try {
        $request = $line | ConvertFrom-Json
        $path = [System.IO.Path]::GetFullPath([string]$request.path)
        $languageTag = [string]$request.language
        if (-not $languageTag) { $languageTag = 'zh-Hans-CN' }
        $engine = Get-OcrEngine -LanguageTag $languageTag
        $sourceMode = 'storage-file'
        $stream = $null
        $stage = 'get-storage-file'
        try {
            $file = Wait-WinRtOperation `
                ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) `
                ([Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime])
            $stage = 'open-storage-file'
            $stream = Wait-WinRtOperation `
                ($file.OpenReadAsync()) `
                ([Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime])
        } catch {
            if ($null -ne $stream) { $stream.Dispose() }
            $sourceMode = 'memory-stream-fallback'
            $stage = 'read-image-bytes'
            $bytes = [System.IO.File]::ReadAllBytes($path)
            $stream = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
            $writer = [Windows.Storage.Streams.DataWriter]::new($stream)
            $writer.WriteBytes($bytes)
            $stage = 'write-memory-stream'
            $null = Wait-WinRtOperation ($writer.StoreAsync()) ([uint32])
            $null = $writer.DetachStream()
            $writer.Dispose()
            $stream.Seek([uint64]0)
        }
        try {
            $stage = 'decode-bitmap'
            $decoder = Wait-WinRtOperation `
                ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) `
                ([Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime])

            $stage = 'decode-software-bitmap'
            $bitmap = Wait-WinRtOperation `
                ($decoder.GetSoftwareBitmapAsync(
                    [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
                    [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied
                )) `
                ([Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime])
            try {
                $stage = 'recognize'
                $result = Wait-WinRtOperation `
                    ($engine.RecognizeAsync($bitmap)) `
                    ([Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime])
                $lines = @($result.Lines | ForEach-Object { [string]$_.Text })
                $wordCount = 0
                foreach ($ocrLine in $result.Lines) {
                    $wordCount += @($ocrLine.Words).Count
                }
                Write-JsonLine ([ordered]@{
                    ok = $true
                    request_id = $request.request_id
                    language = $languageTag
                    text = ($lines -join "`n")
                    line_count = $lines.Count
                    word_count = $wordCount
                    confidence_available = $false
                    source_width = [int]$decoder.PixelWidth
                    source_height = [int]$decoder.PixelHeight
                    recognized_width = [int]$decoder.PixelWidth
                    recognized_height = [int]$decoder.PixelHeight
                    source_mode = $sourceMode
                })
            } finally {
                if ($null -ne $bitmap) { $bitmap.Dispose() }
            }
        } finally {
            if ($null -ne $stream) { $stream.Dispose() }
        }
    } catch {
        Write-JsonLine ([ordered]@{
            ok = $false
            request_id = $request.request_id
            stage = $stage
            error = $_.Exception.ToString()
        })
    }
}
