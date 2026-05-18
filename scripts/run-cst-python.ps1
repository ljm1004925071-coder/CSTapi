param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsList
)

$ErrorActionPreference = "Stop"
$pythonExe = "D:\CST\Python\python.exe"
$scriptPath = Join-Path $PSScriptRoot "test_cst_python.py"
$env:PATH = "D:\CST\AMD64;$env:PATH"
$env:PYTHONPATH = "D:\CST\AMD64\python_cst_libraries"

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Bundled CST Python not found: $pythonExe"
}

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Python test script not found: $scriptPath"
}

& $pythonExe $scriptPath @ArgsList
exit $LASTEXITCODE
