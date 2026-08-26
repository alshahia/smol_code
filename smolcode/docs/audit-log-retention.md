# Audit log retention

**Status:** active
**Date:** 2026-08-19
**Related:** `docs/security.md` section 9, `docs/decisions/0009-m7-polish-security-review.md`

## 1. Why this doc

`smolcode --tier full_access "..."` writes one JSON object per line to
`logs/audit.jsonl` (default; `SMOLCODE_AUDIT_LOG` overrides). The file is
**append-only** by design -- `AuditSink` rejects any mode other than `a`
or `a+` (decision 0006). However, the file will grow without bound unless
**retention** is configured by an external tool.

This document ships a **reference rotation policy** (logrotate on Linux,
a PowerShell scheduled-task script on Windows). smolcode itself does not
rotate the log; rotation is the operator's responsibility, just as it is
for `syslog`, `journald`, and most application logs.

## 2. Retention policy

| Tier           | Retention | Reasoning |
|----------------|-----------|-----------|
| `full_access`  | **365 days** | The only tier whose audit log is required (per security.md section 9). One year covers most compliance ask ("show me what your agent did in Q1") without indefinite storage. |
| `elevated`     | 90 days  | Elevated runs are not written to the audit log by default; this applies if you opt in via a custom AuditSink. |
| `restricted`   | 30 days  | Restricted runs are not written to the audit log by default; DEBUG-level INFO logs cover the operational record. |

**Rotation cadence:** daily. **Compression:** gzip (`audit.jsonl-YYYYMMDD.gz`).
**Minimum on disk:** 30 days compressed, in case the rotation target (S3,
cold storage) is offline.

## 3. Linux: logrotate

Save as `/etc/logrotate.d/smolcode` (Debian/Ubuntu) or
`/etc/logrotate.d/smolcode` (RHEL/Fedora):

```conf
# /etc/logrotate.d/smolcode
# Rotate the smolcode full_access audit log daily, keep 365 days,
# compress with gzip, and do not fail if the log is missing.

<path-to-repo>/logs/audit.jsonl {
    daily
    rotate 365
    missingok
    notifempty
    compress
    delaycompress
    dateext
    dateformat -%Y%m%d
    extension .jsonl
    create 0640 <user> <group>
    sharedscripts
    postrotate
        # Optional: trigger a sync to cold storage here.
        # e.g. aws s3 sync <path-to-repo>/logs/ s3://my-bucket/smolcode-audit/
    endscript
}
```

Test the policy without waiting a day:

```bash
sudo logrotate -d /etc/logrotate.d/smolcode     # dry-run
sudo logrotate -f /etc/logrotate.d/smolcode     # force rotation now
ls -lh <path-to-repo>/logs/                       # verify .gz + .jsonl
```

## 4. Windows: PowerShell scheduled task

Save the script below as `scripts/rotate-audit-log.ps1` and register it
with Task Scheduler to run **daily at 00:05 local time**. The script:

1. Renames `logs\audit.jsonl` to `logs\audit-YYYYMMDD.jsonl` if the file
   is non-empty.
2. Compresses the renamed file to `.gz` (uses `[System.IO.Compression]`
   + `zlib`; no extra modules required).
3. Removes compressed files older than 365 days.

```powershell
# scripts/rotate-audit-log.ps1
# Daily rotation of the smolcode full_access audit log.
# Register via Task Scheduler -> "Create Task..." -> Trigger: Daily 00:05.

param(
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot/..").Path,
    [int]$RetentionDays = 365
)

$ErrorActionPreference = "Stop"
$logDir  = Join-Path $RepoRoot "logs"
$logFile = Join-Path $logDir  "audit.jsonl"
$stamp   = Get-Date -Format "yyyyMMdd"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 0)) {
    $rotated = Join-Path $logDir ("audit-{0}.jsonl" -f $stamp)
    Move-Item -Path $logFile -Destination $rotated -Force

    # gzip via .NET (no external tools required).
    $gz = "$rotated.gz"
    $src = [System.IO.File]::OpenRead($rotated)
    $dst = [System.IO.File]::Create($gz)
    $gzStream = New-Object System.IO.Compression.GzipStream(
        $dst, [System.IO.Compression.CompressionMode]::Compress)
    $src.CopyTo($gzStream)
    $gzStream.Close(); $dst.Close(); $src.Close()
    Remove-Item $rotated -Force
    Write-Host ("Rotated audit log -> {0}" -f $gz)
} else {
    Write-Host "No audit log to rotate."
}

# Delete old compressed logs.
Get-ChildItem -Path $logDir -Filter "audit-*.jsonl.gz" | Where-Object {
    $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays)
} | Remove-Item -Force

Write-Host ("Retention: {0} days" -f $RetentionDays)
```

Register the task:

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\rotate-audit-log.ps1`""
$trigger = New-ScheduledTaskTrigger -Daily -At "00:05"
Register-ScheduledTask -TaskName "smolcode-rotate-audit" `
    -Action $action -Trigger $trigger -Description "Daily smolcode audit log rotation"
```

## 5. macOS: launchd

Save as `~/Library/LaunchAgents/com.smolcode.rotate-audit.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>com.smolcode.rotate-audit</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/path/to/smolcode/scripts/rotate_audit_log.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>5</integer></dict>
</dict>
</plist>
```

Then run the cross-platform helper `scripts/rotate_audit_log.py` (the
launchd plist invokes it under `/usr/local/bin/python3`):

```python
# scripts/rotate_audit_log.py -- referenced by launchd; on Linux
# call this from /etc/cron.daily/smolcode-rotate-audit instead of logrotate.
import gzip, os, shutil, sys, time
from pathlib import Path

repo = Path(os.environ.get("SMOLCODE_REPO", ".")).resolve()
log = repo / "logs" / "audit.jsonl"
retention_days = int(os.environ.get("SMOLCODE_AUDIT_RETENTION_DAYS", "365"))

if log.exists() and log.stat().st_size > 0:
    stamp = time.strftime("%Y%m%d")
    rotated = repo / "logs" / f"audit-{stamp}.jsonl"
    log.rename(rotated)
    with rotated.open("rb") as src, gzip.open(rotated.with_suffix(".jsonl.gz"), "wb") as dst:
        shutil.copyfileobj(src, dst)
    rotated.unlink()
    print(f"rotated {rotated.name}")

for old in (repo / "logs").glob("audit-*.jsonl.gz"):
    age_days = (time.time() - old.stat().st_mtime) / 86400
    if age_days > retention_days:
        old.unlink()
        print(f"deleted {old.name}")
```

## 6. Verifying the rotation

After rotation:

```bash
# Linux / macOS
ls -lh <repo>/logs/
# expect: audit.jsonl (small, just-created) and audit-20260819.jsonl.gz

# Windows
Get-ChildItem <repo>\logs\ | Format-Table Name, Length, LastWriteTime
```

## 7. Cold storage (optional)

The `postrotate` block in the logrotate config (and the equivalent hook in
the PowerShell / launchd scripts) is the natural place to push rotated
logs to immutable cold storage. Recommended destinations:

* **AWS S3 + Object Lock** (compliance mode): 7-year retention is one
  bucket policy away.
* **Azure Blob with immutable storage policy**: same idea, different API.
* **GCS with a retention policy** on the bucket.

smolcode does not implement upload itself; the operator's cold-storage
pipeline is the authoritative archive.

## 8. What retention does NOT cover

* **Tamper detection.** A rotation script that simply deletes the old file
  provides no tamper evidence. For tamper-evident retention, push the
  rotated `.gz` file to an immutable store (above). Optionally sign each
  rotated file with `gpg --detach-sign` before upload so a third party
  can verify integrity.
* **Forensic chain-of-custody.** The `AuditSink` records `{ts, event,
  pid, tier, task, ...}` per `docs/security.md` section 9, but does not
  hash-chain entries. That is deferred to v1.1 per the M5 audit-event
  format decision (0008).
* **Restoring old entries.** smolcode does not currently read back from
  the audit log; tools that surface the log (`smolcode audit ls`, in v1.1)
  will read from the rotated `.gz` files transparently.

## 9. References

* `docs/security.md` section 9 -- audit log schema, append-only invariant.
* `docs/decisions/0006-m4-elevated-full-access-tiers.md` -- AuditSink design.
* `docs/decisions/0009-m7-polish-security-review.md` -- this milestone.
* `smolcode/src/smolcode/audit.py` -- `AuditSink`, `default_audit_path`.
* Linux `logrotate(8)` man page.
* Windows: "Create a Scheduled Task" (Microsoft Docs).