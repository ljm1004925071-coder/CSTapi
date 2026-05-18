param(
    [switch]$QuitWhenDone
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[CST] $Message"
}

try {
    Write-Step "Creating COM object: CSTStudio.Application"
    $app = New-Object -ComObject CSTStudio.Application

    Write-Step "COM connection established"
    Write-Host ("Type: {0}" -f $app.GetType().FullName)

    $methods = $app | Get-Member -MemberType Method | Select-Object -ExpandProperty Name
    Write-Step "Available top-level methods"
    $methods | Sort-Object | ForEach-Object { Write-Host ("  - {0}" -f $_) }

    if ($QuitWhenDone) {
        Write-Step "Calling Quit()"
        $app.Quit()
    }

    Write-Step "Done"
}
catch {
    Write-Error ("CST connection test failed: {0}" -f $_.Exception.Message)
    exit 1
}
