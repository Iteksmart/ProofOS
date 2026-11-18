# Ship new ProofOS WAL segments to Backblaze B2 every 15 minutes (scheduled task "ProofOS WAL Shipping").
# Keeps offsite data loss under an hour together with Postgres' 30-minute archive_timeout.
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$key = Join-Path $env:USERPROFILE '.proofos\backup-encryption.key'
$remote = 'b2proofos:proofos-backups-itechsmart/proofos'
$log = Join-Path $repo 'backups\wal-ship.log'
$python = (Get-Command python -ErrorAction Stop).Source

# Keep the log small: it gets a line every 15 minutes.
if ((Test-Path $log) -and (Get-Item $log).Length -gt 2MB) { Move-Item $log "$log.old" -Force }
$out = & $python (Join-Path $repo 'scripts\pitr.py') ship --encrypt-key $key --rclone-remote $remote 2>&1 | ForEach-Object { "$_" }
$code = $LASTEXITCODE
"$(Get-Date -Format o) exit $code :: $($out -join ' | ')" | Add-Content $log
exit $code
