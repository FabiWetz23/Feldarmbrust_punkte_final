param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$OutDir = "certs"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "create_tls_cert.py"

$pythonCandidates = @("python", "py")
$pythonCommand = $null

foreach ($candidate in $pythonCandidates) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $pythonCommand = $candidate
        break
    }
}

if (-not $pythonCommand) {
    Write-Error "Python wurde nicht gefunden. Installiere Python oder fuehre den Befehl in WSL mit python3 aus."
}

if ($pythonCommand -eq "py") {
    & py -3 $pythonScript $HostName $OutDir
} else {
    & $pythonCommand $pythonScript $HostName $OutDir
}
