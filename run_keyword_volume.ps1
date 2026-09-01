param([switch]$DryRun)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runnerPath = Join-Path $projectRoot "scripts\run_keyword_volume.py"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python virtual environment not found: $pythonPath"
}
$runnerArgs = @($runnerPath)
if ($DryRun) { $runnerArgs += "--dry-run" }
& $pythonPath @runnerArgs
exit $LASTEXITCODE
