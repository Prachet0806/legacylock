# Local Windows baseline for the API and worker on a disposable SQLite database.
# This does not emulate Render's CPU quota or a Neon PostgreSQL connection.
param([int]$SampleSeconds = 12)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Backend .venv is required.' }
$basePython = & $python -c 'import sys, pathlib; print(pathlib.Path(sys.base_prefix) / "python.exe")'
if (-not (Test-Path -LiteralPath $basePython)) { throw 'Base Python interpreter is required.' }
$env:PYTHONPATH = Join-Path $PSScriptRoot '.venv\Lib\site-packages'

$benchDb = Join-Path $env:TEMP ("legacylock-resource-bench-{0}.db" -f [guid]::NewGuid())
$env:ENVIRONMENT = 'test'
$env:SESSION_SECRET = 'benchmark-only-secret-0123456789abcdef'
$env:SQLITE_FILE = $benchDb
$env:DATABASE_URL = 'sqlite:///' + $benchDb.Replace('\', '/')
$env:JWT_PRIVATE_KEY_PATH = Join-Path $PSScriptRoot 'keys\jwt_private.pem'
$env:JWT_PUBLIC_KEY_PATH = Join-Path $PSScriptRoot 'keys\jwt_public.pem'
$env:BACKGROUND_IN_API = 'false'
$env:MIGRATED_SCHEMA_ONLY = 'true'
$env:HEARTBEAT_ENABLED = 'true'
$env:DELIVERY_ENABLED = 'true'
$env:RELEASE_HOLD = 'true'
$env:RESEND_API_KEY = ''

Push-Location $PSScriptRoot
try {
    & $python -m alembic upgrade head *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Disposable schema migration failed.' }

    foreach ($mode in @('api', 'worker', 'combined', 'demo')) {
        $procs = @()
        try {
            $env:TASK_MODE = if ($mode -eq 'demo') { 'single_process_demo' } else { 'separate_worker' }
            if ($mode -in @('api', 'combined', 'demo')) {
                $procs += Start-Process -FilePath $basePython -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '18765', '--no-proxy-headers') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
            }
            if ($mode -in @('worker', 'combined')) {
                $procs += Start-Process -FilePath $basePython -ArgumentList @('worker.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
            }
            Start-Sleep -Seconds 3
            $samples = @()
            for ($i = 0; $i -lt $SampleSeconds; $i += 2) {
                $live = @($procs | ForEach-Object { Get-Process -Id $_.Id -ErrorAction Stop })
                $samples += [pscustomobject]@{
                    rss_mb = [math]::Round((($live | Measure-Object -Property WorkingSet64 -Sum).Sum / 1MB), 1)
                    cpu_seconds = [math]::Round((($live | Measure-Object -Property CPU -Sum).Sum), 3)
                }
                Start-Sleep -Seconds 2
            }
            [pscustomobject]@{
                mode = $mode
                rss_mb_min = ($samples | Measure-Object -Property rss_mb -Minimum).Minimum
                rss_mb_peak = ($samples | Measure-Object -Property rss_mb -Maximum).Maximum
                cpu_seconds_delta = [math]::Round(($samples[-1].cpu_seconds - $samples[0].cpu_seconds), 3)
                sample_seconds = $SampleSeconds
            } | ConvertTo-Json -Compress
        }
        finally {
            foreach ($proc in $procs) {
                Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
                $proc.WaitForExit(5000) | Out-Null
            }
        }
    }
}
finally {
    Pop-Location
    Remove-Item -LiteralPath $benchDb -ErrorAction SilentlyContinue
}
