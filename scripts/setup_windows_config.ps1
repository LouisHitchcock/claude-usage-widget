# Configure optional Codex provider without discarding other widget settings.
param([string]$ConfigPath = (Join-Path $env:USERPROFILE ".config\claude-usage\config.json"))
$ErrorActionPreference = "Stop"
$parent = Split-Path -Parent $ConfigPath
if (!(Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

$config = [ordered]@{}
if (Test-Path -LiteralPath $ConfigPath) {
    $raw = [System.IO.File]::ReadAllText($ConfigPath)
    if (![string]::IsNullOrWhiteSpace($raw)) {
        # A malformed config must not be overwritten.
        $parsed = ConvertFrom-Json -InputObject $raw
        if ($null -eq $parsed -or $parsed -isnot [pscustomobject]) {
            throw "Configuration must contain a JSON object"
        }
        $config = $parsed
    }
}
if ($config -is [System.Collections.IDictionary]) {
    $config["providers"] = @("claude", "codex")
} else {
    # Add-Member works whether or not providers already exists.
    $config | Add-Member -NotePropertyName providers -NotePropertyValue @("claude", "codex") -Force
}
$json = ConvertTo-Json -InputObject $config -Depth 100
$tmp = "$ConfigPath.tmp"
[System.IO.File]::WriteAllText($tmp, $json + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
Move-Item -LiteralPath $tmp -Destination $ConfigPath -Force
Write-Host "Enabled Claude and Codex in $ConfigPath"
