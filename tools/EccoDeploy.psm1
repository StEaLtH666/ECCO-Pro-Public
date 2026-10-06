<#
    ECCO Pro - shared Home Assistant SSH deployment safety helpers.

    Used by deploy-ha.ps1, deploy-dashboard.ps1 and test-ha-rollback.ps1 so
    that destination validation and rollback exist in exactly one place
    instead of being duplicated per script. Nothing in this module performs
    inverter writes, flashes firmware, or edits Home Assistant's internal
    .storage state - it only ever moves files under an explicit allowlist
    on the remote /config tree and inspects/reverts them.

    Windows PowerShell 5.1 compatible. No external module dependencies.
#>

Set-StrictMode -Version Latest

function Invoke-EccoRemoteCommand {
    <#
        Runs one command on the configured SSH host and either streams it
        (default) or captures its output/exit code (-Capture) for the
        caller to branch on. Centralises the Windows PowerShell 5.1 quirk
        where $ErrorActionPreference='Stop' can turn an *expected*
        non-zero remote exit code (a failed `ha core check`, for example)
        into a terminating error before $LASTEXITCODE can be inspected.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Command,

        [switch]$Capture
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        if ($Capture) {
            $result = @(& ssh -o BatchMode=yes $SshHost $Command 2>&1)
            $code = $LASTEXITCODE
        } else {
            & ssh -o BatchMode=yes $SshHost $Command
            $code = $LASTEXITCODE
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($Capture) {
        $textResult = @($result | ForEach-Object { $_.ToString() })
        return [pscustomobject]@{
            Output   = $textResult
            ExitCode = $code
        }
    }

    if ($code -ne 0) {
        throw "Remote command failed: $Command"
    }
}

function Invoke-EccoRemoteCommandBestEffort {
    <#
        Same as Invoke-EccoRemoteCommand but never throws. Used only for
        cleanup steps (removing a stray .tmp file, etc.) that run while an
        earlier, more informative error is already in flight - a cleanup
        failure must never mask the real failure that triggered it.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    try {
        Invoke-EccoRemoteCommand -SshHost $SshHost -Command $Command
    }
    catch {
        Write-Warning "Best-effort cleanup command failed (continuing): $Command"
        Write-Warning $_.Exception.Message
    }
}

function Test-EccoDeploymentDestination {
    <#
        Validates and normalises a remote deployment destination. Pure
        string logic - makes no SSH calls, so it is safe and fast to unit
        test offline. Returns the normalised destination on success or
        throws a specific, descriptive error on the first rule violated.

        The allowlist is intentionally exactly three prefixes and is not
        broadened by this function under any circumstance:
            /config/packages/
            /config/ecco/
            /config/www/ecco/

        /config/www/ecco/ exists specifically for committed frontend dist
        assets (Lovelace custom cards) served back to the browser as
        /local/ecco/<file> - see deploy-ha.ps1's frontend-asset path and
        deployment/ha-manifest.yaml's frontend_assets section. It is
        deliberately NOT the same as the bare /config/www/ root: an
        arbitrary file under /config/www/ is served to every browser that
        loads the Lovelace UI, so only the ecco/ subdirectory is allowed,
        never /config/www/ itself.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Destination
    )

    if ([string]::IsNullOrEmpty($Destination)) {
        throw 'Remote destination must not be empty.'
    }

    # Windows-style separators are the only "direction" variant we accept
    # from a caller; normalise before every other check so nothing below
    # has to reason about backslashes.
    $normalised = $Destination.Replace('\', '/')

    foreach ($ch in $normalised.ToCharArray()) {
        $code = [int]$ch
        if ($code -le 0x1F -or $code -eq 0x7F) {
            throw 'Remote destination may not contain control characters.'
        }
    }

    if ($normalised -ne $normalised.Trim()) {
        throw 'Remote destination may not have leading or trailing whitespace.'
    }

    if ($normalised.Contains("'")) {
        throw 'Remote destination may not contain a single quote.'
    }

    if ($normalised.Contains('//')) {
        throw 'Remote destination may not contain repeated path separators.'
    }

    # Single-dot path segments ("/./" or a trailing "/.") are rejected
    # outright. No legitimate destination under the allowlist ever needs
    # one, and refusing them removes an entire class of normalisation
    # tricks rather than trying to enumerate every way one could be used.
    if ($normalised -match '(^|/)\.(/|$)') {
        throw 'Remote destination may not contain a "." path segment.'
    }

    # Parent-directory traversal ("../", "/..", or a leading "..").
    if ($normalised -match '(^|/)\.\.(/|$)') {
        throw 'Remote destination may not contain path traversal.'
    }

    # Ordinal, case-sensitive, and each allowlist prefix ends in "/" so a
    # sibling directory that merely shares the prefix text (for example
    # "/config/packages-evil/x" or "/config/www/ecco-evil/x") cannot match -
    # StartsWith requires the literal separator immediately after
    # "packages"/"ecco"/"www/ecco" too.
    $allowedDestination =
        $normalised.StartsWith('/config/packages/', [System.StringComparison]::Ordinal) -or
        $normalised.StartsWith('/config/ecco/', [System.StringComparison]::Ordinal) -or
        $normalised.StartsWith('/config/www/ecco/', [System.StringComparison]::Ordinal)

    if (-not $allowedDestination) {
        throw 'Remote destination must be under /config/packages/, /config/ecco/, or /config/www/ecco/.'
    }

    return $normalised
}

function Assert-EccoCleanWorkingTree {
    <#
        Requires a clean `git status --porcelain` in the given repo root
        so that a normal deployment always matches a committed revision.
        Callers that need to deliberately test an uncommitted change must
        not call this at all - see the -AllowDirtyWorkingTree switch on
        deploy-ha.ps1 / deploy-dashboard.ps1.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    Push-Location $RepoRoot
    try {
        & git rev-parse --is-inside-work-tree *> $null
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to verify a clean working tree: not inside a Git working tree.'
        }

        $dirty = @(& git status --porcelain)
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to verify a clean working tree: git status failed.'
        }

        if ($dirty.Count -gt 0) {
            Write-Host 'Working tree is not clean:'
            $dirty | ForEach-Object { Write-Host "  $_" }
            throw 'Refusing to deploy from an uncommitted working tree. Commit/stash your changes, or pass -AllowDirtyWorkingTree to deliberately deploy an uncommitted change.'
        }
    }
    finally {
        Pop-Location
    }
}

function Format-EccoRollbackResultMessage {
    <#
        Pure string-formatting for Invoke-EccoDeploymentRollback's final
        error message. Deliberately separated out so the wording rules -
        most importantly, never asserting "was rolled back" as a plain
        fact when the restore could not actually be confirmed - can be
        unit tested offline with synthetic outcomes, without opening an
        SSH connection.

        The literal phrase "was rolled back" is used ONLY when
        RestoreVerified is $true. test-ha-rollback.ps1 depends on that
        exact phrase to detect a confirmed rollback; do not change it
        without updating that script's detection to match.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Reason,

        [Parameter(Mandatory = $true)]
        [string]$BackupDescription,

        [Parameter(Mandatory = $true)]
        [bool]$RestoreVerified,

        [AllowNull()]
        [AllowEmptyString()]
        [string]$RestoreProblem,

        [Parameter(Mandatory = $true)]
        [bool]$RollbackCheckRan,

        [AllowNull()]
        [object]$RollbackCheckExitCode
    )

    $lines = New-Object System.Collections.Generic.List[string]

    if ($RestoreVerified) {
        $lines.Add("Deployment failed and was rolled back: $Reason")
    } else {
        $lines.Add("Deployment failed and rollback could NOT be confirmed successful: $Reason")
    }
    $lines.Add("Backup: $BackupDescription")

    if ($RestoreVerified) {
        $lines.Add('Rollback verification: OK')
    } else {
        $lines.Add("Rollback verification: FAILED - $RestoreProblem")
    }

    $checkFailedOrUnknown = (-not $RollbackCheckRan) -or ($null -eq $RollbackCheckExitCode) -or ([int]$RollbackCheckExitCode -ne 0)

    if (-not $RollbackCheckRan) {
        $lines.Add('Post-rollback Home Assistant check: could not be run (SSH transport failure).')
    } elseif ([int]$RollbackCheckExitCode -ne 0) {
        $lines.Add('Post-rollback Home Assistant check: did not pass. This may mean Home Assistant configuration is genuinely unhealthy, or that SSH/the remote host was unavailable - see output above.')
    } else {
        $lines.Add('Post-rollback Home Assistant check: passed.')
    }

    if ((-not $RestoreVerified) -and $checkFailedOrUnknown) {
        $lines.Add('NOTE: both the rollback step and the post-rollback check failed to complete cleanly. This combination often means SSH or the remote host itself is unavailable, not that Home Assistant configuration is broken. Verify SSH connectivity independently before assuming otherwise, and do not treat this as a confirmed successful rollback.')
    }

    return ($lines -join "`n")
}

function Invoke-EccoDeploymentRollback {
    <#
        The single rollback routine for every failure that can occur once
        a new file has already been moved into place at $Destination, or
        whose move result is ambiguous because the SSH command reporting
        it failed: a failed post-install SHA256 verification, a failed
        `ha core check`, or a failed/uncertain move itself (SSH may have
        dropped after the remote `mv` already completed). Handles both
        "there was a previous file" (restore the backup) and "this was a
        brand new file" (remove it), verifies the restored state where
        practical, re-runs `ha core check`, and always throws a single
        terminating error that names the backup path so it is never lost
        from the failure output - even if a step of the rollback itself
        fails. Never claims a confirmed successful rollback when it
        cannot actually confirm one - see Format-EccoRollbackResultMessage.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [AllowEmptyString()]
        [string]$BackupPath,

        [Parameter(Mandatory = $true)]
        [bool]$HadOriginal,

        [Parameter(Mandatory = $true)]
        [string]$Reason
    )

    Write-Warning "Rolling back deployment: $Reason"

    $backupDescription = if ($HadOriginal) { $BackupPath } else { 'none (new file)' }
    $restoreProblem = $null
    $restoreVerified = $false

    try {
        if ($HadOriginal) {
            Invoke-EccoRemoteCommand -SshHost $SshHost -Command "cp -p '$BackupPath' '$Destination'"

            $backupHashResult = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "sha256sum '$BackupPath' | cut -d ' ' -f 1" -Capture
            $destHashResult = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "sha256sum '$Destination' | cut -d ' ' -f 1" -Capture

            $backupOk = $backupHashResult.ExitCode -eq 0 -and $backupHashResult.Output.Count -gt 0
            $destOk = $destHashResult.ExitCode -eq 0 -and $destHashResult.Output.Count -gt 0

            if ($backupOk -and $destOk -and (($backupHashResult.Output[-1]).Trim() -eq ($destHashResult.Output[-1]).Trim())) {
                $restoreVerified = $true
            } else {
                $restoreProblem = 'Restored file hash could not be confirmed to match the backup.'
            }
        } else {
            Invoke-EccoRemoteCommand -SshHost $SshHost -Command "rm -f '$Destination'"

            $existsCheck = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "if [ -e '$Destination' ]; then printf yes; else printf no; fi" -Capture
            if ($existsCheck.ExitCode -eq 0 -and (($existsCheck.Output -join '').Trim().EndsWith('no'))) {
                $restoreVerified = $true
            } else {
                $restoreProblem = 'New file could not be confirmed removed.'
            }
        }
    }
    catch {
        $restoreProblem = "Rollback restore/remove step itself failed: $($_.Exception.Message)"
    }

    $rollbackCheckRan = $false
    $rollbackCheckExitCode = $null
    try {
        $rollbackCheck = Invoke-EccoRemoteCommand -SshHost $SshHost -Command 'ha core check' -Capture
        $rollbackCheck.Output | ForEach-Object { Write-Host $_ }
        $rollbackCheckRan = $true
        $rollbackCheckExitCode = $rollbackCheck.ExitCode
    }
    catch {
        # ha core check itself is Invoke-EccoRemoteCommand's -Capture form,
        # which does not throw on a non-zero exit - only fall here on a
        # genuine transport failure. Keep going so the final message below
        # still reports everything gathered so far.
    }

    $message = Format-EccoRollbackResultMessage `
        -Reason $Reason `
        -BackupDescription $backupDescription `
        -RestoreVerified $restoreVerified `
        -RestoreProblem $restoreProblem `
        -RollbackCheckRan $rollbackCheckRan `
        -RollbackCheckExitCode $rollbackCheckExitCode

    throw $message
}

Export-ModuleMember -Function `
    Invoke-EccoRemoteCommand, `
    Invoke-EccoRemoteCommandBestEffort, `
    Test-EccoDeploymentDestination, `
    Assert-EccoCleanWorkingTree, `
    Format-EccoRollbackResultMessage, `
    Invoke-EccoDeploymentRollback
