param(
    [int]$StartupDelaySeconds = 3,
    [switch]$TryLaunchExeFirst,
    [string]$CstExePath = "D:\CST\AMD64\CST DESIGN ENVIRONMENT_AMD64.exe",
    [switch]$QuitWhenDone
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[CST] $Message"
}

try {
    if ($TryLaunchExeFirst) {
        if (-not (Test-Path -LiteralPath $CstExePath)) {
            throw "CST executable not found: $CstExePath"
        }

        Write-Step "Launching CST executable"
        Start-Process -FilePath $CstExePath | Out-Null
        Start-Sleep -Seconds $StartupDelaySeconds
    }

    Write-Step "Creating COM object: CSTStudio.Application"
    $app = New-Object -ComObject CSTStudio.Application

    Write-Step "Trying NewMWS()"
    $project = $app.NewMWS()

    if ($null -eq $project) {
        throw "NewMWS() returned null"
    }

    Write-Step "NewMWS() succeeded"
    Write-Host ("Project COM type: {0}" -f $project.GetType().FullName)

    $projectMethods = $project | Get-Member -MemberType Method | Select-Object -ExpandProperty Name
    Write-Step "Available project methods"
    $projectMethods | Sort-Object | ForEach-Object { Write-Host ("  - {0}" -f $_) }

    if ($QuitWhenDone) {
        Write-Step "Calling Quit()"
        $app.Quit()
    }

    Write-Step "Done"
}
catch {
    Write-Error ("CST NewMWS test failed: {0}" -f $_.Exception.Message)
    exit 1
}
