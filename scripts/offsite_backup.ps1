# Nightly ProofOS offsite backup: dump + ledger export, encrypt, upload to Backblaze B2, keep 7 local copies.
# Registered as the "ProofOS Offsite Backup" scheduled task. Safe to run by hand any time.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$key = Join-Path $env:USERPROFILE '.proofos\backup-encryption.key'
$remote = 'b2proofos:proofos-backups-itechsmart/proofos'
$logDir = Join-Path $repo 'backups'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir 'offsite-backup.log'
$python = (Get-Command python -ErrorAction Stop).Source

"=== $(Get-Date -Format o) start" | Add-Content $log
$ErrorActionPreference = 'Continue'  # python writes progress to stderr-free stdout; keep its errors as log lines
& $python (Join-Path $repo 'scripts\backup.py') --encrypt-key $key --rclone-remote $remote --keep-local 7 2>&1 |
  ForEach-Object { "$_" } | Add-Content $log
$code = $LASTEXITCODE
# Point-in-time recovery: a fresh physical base backup each night, then ship any WAL not yet offsite.
& $python (Join-Path $repo 'scripts\pitr.py') basebackup --encrypt-key $key --rclone-remote $remote --keep-local 3 2>&1 |
  ForEach-Object { "$_" } | Add-Content $log
if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }
& $python (Join-Path $repo 'scripts\pitr.py') ship --encrypt-key $key --rclone-remote $remote 2>&1 |
  ForEach-Object { "$_" } | Add-Content $log
if ($LASTEXITCODE -ne 0) { $code = $LASTEXITCODE }
"=== $(Get-Date -Format o) exit $code" | Add-Content $log
exit $code
