<#
    ECCO Pro - shared Home Assistant SSH deployment safety helpers.

    Used by deploy-ha.ps1, deploy-dashboard.ps1 and test-ha-rollback.ps1 so
    that destination validation and rollback exist in exactly one place
    instead of being duplicated per script. Nothing in this module performs
    inverter writes, flashes firmware, or edits Home Assistant's internal
    .storage state - it only ever moves files under an explicit allowlist
    on the remote /config tree and inspects/reverts them. The Lovelace
    resource helpers only parse and describe a resource list that
    deploy-ha.ps1 has read back; they never change it. The dashboard
    preservation gate only copies files FROM the host (read-only) into a
    local temp folder it deletes again.

    Windows PowerShell 5.1 compatible. No external module dependencies.
#>

Set-StrictMode -Version Latest

# The site-local area on the host: the dashboard protection policy lives
# here and nothing is ever deployed into it (Test-EccoDeploymentDestination).
$script:EccoSiteLocalPrefix = '/config/ecco/site-local/'
$script:EccoDashboardPolicyPath = '/config/ecco/site-local/dashboard-protection.json'
$script:EccoDashboardsPrefix = '/config/ecco/dashboards/'
$script:EccoDefaultDashboardGate = 'DASHBOARD_PRESERVE_GATE'
# The optional local pin of the site's gate name, at the repository root
# (git-ignored): see Get-EccoDashboardGatePin.
$script:EccoDashboardGatePinFile = 'ecco_dashboard_gate.local.txt'

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

        One subtree inside the allowlist is refused: /config/ecco/site-local/,
        which holds the site's dashboard protection policy.
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

    # /config/ecco/site-local/ holds the site's own dashboard protection
    # policy (see Invoke-EccoDashboardPreservationGate). Nothing ECCO
    # renders belongs there, so no deployment may ever write over it - the
    # gate's policy cannot be replaced or removed by the tool it gates.
    if ($normalised.StartsWith($script:EccoSiteLocalPrefix, [System.StringComparison]::Ordinal) -or
        $normalised -eq $script:EccoSiteLocalPrefix.TrimEnd('/')) {
        throw "Remote destination may not be under $($script:EccoSiteLocalPrefix): it holds the site-local dashboard protection policy, which no deployment overwrites."
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
        [object]$RollbackCheckExitCode,

        # The destination is a dashboard file: add the reminder to read
        # back what Home Assistant serves (it caches YAML dashboards).
        [bool]$Dashboard = $false
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

    if ($Dashboard) {
        $lines.Add('DASHBOARD READ-BACK REQUIRED: Home Assistant serves a cached copy of a YAML dashboard until the file is newer than its cache. A restored backup is copied without cp -p and touched, but only a read-back proves what is served: read the served dashboard (websocket lovelace/config for this dashboard) and compare it with the file now on the host before reporting the rollback as complete.')
    }

    return ($lines -join "`n")
}

function Get-EccoLovelaceResourceUrl {
    <#
        The browser URL of a file deployed under /config/www/ecco/
        (/local/ecco/<file>), or $null for any other destination. Pure
        string logic, unit tested offline. Every such file is a Lovelace
        resource candidate, whatever the source path was: the documented
        content-addressed deploy copies dist/deploy/stage/<card>.<sha8>.js.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $prefix = '/config/www/ecco/'
    if ($Destination.StartsWith($prefix, [System.StringComparison]::Ordinal) -and $Destination.Length -gt $prefix.Length) {
        return '/local/ecco/' + $Destination.Substring($prefix.Length)
    }
    return $null
}

function ConvertFrom-EccoLovelaceResources {
    <#
        Parses the text of /config/.storage/lovelace_resources
        ({"data": {"items": [...]}}) into its resource items. Throws on
        anything else, so a wrong or truncated read is never mistaken for
        "no resources". Pure parsing - the caller does the read-only read.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Json
    )

    $doc = $Json | ConvertFrom-Json
    $data = if ($doc -and $doc.PSObject.Properties['data']) { $doc.data } else { $null }
    if (-not $data -or -not $data.PSObject.Properties['items']) {
        throw 'not a lovelace_resources storage file (no data.items)'
    }
    return , @($data.items)
}

function Format-EccoResourceReminder {
    <#
        The lines deploy-ha.ps1 prints after copying a file under
        /config/www/ecco/ (none for any other destination). Copying a card
        bundle changes nothing a dashboard loads until its Lovelace
        resource points at that file, and no ECCO tool edits resources, so
        the reminder names the card's PERSISTED resource and says plainly
        whether this copy is live. A resource loads the card when its URL's
        file name (query dropped) is <card>.js or <card>.<anything> - the
        same rule as ecco_deploy_preflight.py verify-resource. -Resources
        is the list read back after the copy, or $null when it could not be
        read (-ReadProblem says why). Pure string logic, unit tested offline.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [AllowNull()]
        [object[]]$Resources,

        [AllowNull()]
        [AllowEmptyString()]
        [string]$ReadProblem
    )

    $url = Get-EccoLovelaceResourceUrl -Destination $Destination
    if (-not $url) {
        return @()
    }
    $card = $url.Substring($url.LastIndexOf('/') + 1).Split('.')[0]
    $lines = New-Object System.Collections.Generic.List[string]

    if ($null -eq $Resources) {
        $lines.Add("RESOURCE UNKNOWN ${card}: the persisted resource list could not be read back ($ReadProblem). Whether any dashboard loads this file is not known.")
    } else {
        $cardResources = @()
        foreach ($r in $Resources) {
            $rUrl = if ($r -and $r.PSObject.Properties['url']) { [string]$r.url } else { '' }
            $rId = if ($r -and $r.PSObject.Properties['id']) { [string]$r.id } else { '' }
            $path = ($rUrl -split '[?#]', 2)[0]
            if ($path.Substring($path.LastIndexOf('/') + 1).Split('.')[0] -eq $card) {
                $cardResources += [pscustomobject]@{ Url = $rUrl; Path = $path; Id = $rId.Substring(0, [Math]::Min(8, $rId.Length)) }
            }
        }
        $listed = ($cardResources | ForEach-Object { "$($_.Url) (id $($_.Id))" }) -join ', '
        $pointing = @($cardResources | Where-Object { $_.Path -eq $url })
        if ($cardResources.Count -eq 0) {
            $lines.Add("RESOURCE NOT REGISTERED ${card}: no resource loads this card. This copy is NOT LIVE until a resource with URL $url (JavaScript module) is added.")
        } elseif ($pointing.Count -eq 0) {
            $lines.Add("RESOURCE NOT SWITCHED ${card}: the dashboards still load $listed. This copy is NOT LIVE until that resource is edited to $url.")
        } else {
            $lines.Add("RESOURCE ALREADY POINTS AT THIS FILE ${card}: $listed. Browsers may keep older cached bytes until a hard refresh.")
        }
        if ($cardResources.Count -gt 1) {
            $lines.Add("WARNING: $($cardResources.Count) resources load ${card}; exactly one is expected.")
        }
    }
    $lines.Add("Resource URL: $url")
    $lines.Add('Resource registration is manual: Settings -> Dashboards -> Resources.')
    $lines.Add('This script never edits Home Assistant .storage - no resource was registered automatically.')
    $lines.Add('Report the install as done only after the read-back gate passes: python tools/ecco_deploy_preflight.py verify-resource --plan <plan.json> --resources <fresh lovelace_resources read-back> --before <pre-change capture> --base-url <HA URL>')
    return $lines.ToArray()
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

        The restore is a plain `cp` followed by `touch`, never `cp -p`:
        Home Assistant keeps serving its cached copy of a YAML dashboard
        while the file is not newer than that cache, so a restore that
        brought back the backup's old modification time would leave the
        failed deployment on screen. For a dashboard destination (by its
        path, or -Dashboard when the preservation gate applied) the final
        message also asks for a lovelace/config read-back.
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
        [string]$Reason,

        [switch]$Dashboard
    )

    Write-Warning "Rolling back deployment: $Reason"

    $isDashboard = $Dashboard -or (Test-EccoDashboardDestinationPath -Destination $Destination)
    $backupDescription = if ($HadOriginal) { $BackupPath } else { 'none (new file)' }
    $restoreProblem = $null
    $restoreVerified = $false

    try {
        if ($HadOriginal) {
            Invoke-EccoRemoteCommand -SshHost $SshHost -Command "cp '$BackupPath' '$Destination' && touch '$Destination'"

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
        -RollbackCheckExitCode $rollbackCheckExitCode `
        -Dashboard $isDashboard

    throw $message
}

function Test-EccoDashboardDestinationPath {
    <#
        True when a (validated) destination is a dashboard file by its path:
        under /config/ecco/dashboards/ and ending .yaml or .yml. A
        destination the site policy names is a dashboard destination too;
        that half of the rule needs the policy and is decided by the guard's
        `classify` command inside Invoke-EccoDashboardPreservationGate. The
        same path rule is is_dashboard_path() in
        tools/ecco_dashboard_guard.py. Pure string logic, tested offline.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $prefix = $script:EccoDashboardsPrefix
    return ($Destination.StartsWith($prefix, [System.StringComparison]::Ordinal) -and
        $Destination.Length -gt $prefix.Length -and
        ($Destination.EndsWith('.yaml', [System.StringComparison]::OrdinalIgnoreCase) -or
         $Destination.EndsWith('.yml', [System.StringComparison]::OrdinalIgnoreCase)))
}

function Get-EccoGateProbeCommand {
    <#
        The read-only shell probe Copy-EccoRemoteFileForGate runs on the
        host for one absolute path. It prints exactly one word:
          present    - a regular file the SSH user can read;
          absent     - no file and no symlink at the path, PROVEN by its
                       nearest existing ancestor being a searchable
                       directory;
          unreadable - everything else: a symlink at the path (dangling
                       or not), a directory, an unreadable file, or an
                       ancestor that is not a searchable directory. A
                       failed stat (EACCES) makes [ -e ] false for a file
                       that exists, so "not there" alone is never absent.
        Only single-quoted words, no variables and no double quotes (an
        embedded double quote would be split by the native command line
        of Windows PowerShell 5.1): every ancestor is spelled out. The
        path must not contain a single quote. Pure string logic.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$RemotePath
    )

    if ($RemotePath.Contains("'") -or $RemotePath.Contains('"') -or -not $RemotePath.StartsWith('/') -or $RemotePath.EndsWith('/') -or $RemotePath.Contains('//')) {
        throw "Refusing to probe '$RemotePath': an absolute file path without quotes or empty segments is required."
    }
    $q = "'$RemotePath'"
    $command = "if [ -L $q ]; then printf unreadable; elif [ -e $q ]; then if [ -f $q ] && [ -r $q ]; then printf present; else printf unreadable; fi;"
    $cut = $RemotePath.LastIndexOf('/')
    while ($cut -gt 0) {
        $ancestor = "'" + $RemotePath.Substring(0, $cut) + "'"
        $command += " elif [ -e $ancestor ] || [ -L $ancestor ]; then if [ -d $ancestor ] && [ -x $ancestor ]; then printf absent; else printf unreadable; fi;"
        $cut = $RemotePath.LastIndexOf('/', $cut - 1)
    }
    $command += " elif [ -d '/' ] && [ -x '/' ]; then printf absent; else printf unreadable; fi"
    return $command
}

function Copy-EccoRemoteFileForGate {
    <#
        Read-only: copies one file from the host to a local path for the
        dashboard preservation gate. Returns 'present' (copied) or 'absent'
        (proven absent: see Get-EccoGateProbeCommand). Throws when the path
        is a symlink, a directory or an unreadable file, when an ancestor
        cannot be searched, or when ssh/scp fails - the gate turns every
        throw into BLOCKED, so an unusable file is never mistaken for an
        absent one. scp copies the exact bytes (a captured ssh `cat`
        would be re-decoded by the console code page).
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$RemotePath,

        [Parameter(Mandatory = $true)]
        [string]$LocalPath
    )

    $probe = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (Get-EccoGateProbeCommand -RemotePath $RemotePath) -Capture
    if ($probe.ExitCode -ne 0) {
        throw "Unable to inspect $RemotePath on the host (ssh exit code $($probe.ExitCode))."
    }
    $state = ($probe.Output -join '').Trim()
    if ($state.EndsWith('absent')) {
        return 'absent'
    }
    if (-not $state.EndsWith('present')) {
        throw "$RemotePath is not a readable regular file on the host, or its folder cannot be searched (a symlink, a directory, an unreadable file or folder)."
    }

    $remoteSpec = '{0}:{1}' -f $SshHost, $RemotePath
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & scp -q $remoteSpec $LocalPath
        $scpCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($scpCode -ne 0 -or -not (Test-Path -LiteralPath $LocalPath -PathType Leaf)) {
        throw "Unable to copy $RemotePath from the host (scp exit code $scpCode)."
    }
    return 'present'
}

function Read-EccoGateRemoteFile {
    # One read for the gate: the injected reader (offline tests) or the
    # ssh/scp copy. Anything but 'present' or 'absent' is an error.
    param(
        [string]$SshHost,
        [string]$RemotePath,
        [string]$LocalPath,
        [scriptblock]$RemoteFileReader
    )

    if ($RemoteFileReader) {
        $state = @(& $RemoteFileReader $RemotePath $LocalPath)
    } else {
        $state = @(Copy-EccoRemoteFileForGate -SshHost $SshHost -RemotePath $RemotePath -LocalPath $LocalPath)
    }
    $last = if ($state.Count -gt 0) { [string]$state[-1] } else { '' }
    if ($last -eq 'present') {
        if (-not (Test-Path -LiteralPath $LocalPath -PathType Leaf)) {
            throw "The read of $RemotePath reported a copy but no local copy exists."
        }
        return 'present'
    }
    if ($last -eq 'absent') {
        return 'absent'
    }
    throw "The read of $RemotePath returned an unexpected state."
}

function Invoke-EccoDashboardGuard {
    <#
        Runs tools/ecco_dashboard_guard.py with the given arguments and
        captures its output and exit code. A guard that cannot be started
        (no python on PATH) is exit code 2 with a BLOCKED first line, never
        a pass: $LASTEXITCODE is not trusted after a failed start.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Python,

        [Parameter(Mandatory = $true)]
        [string]$GuardPath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    foreach ($a in $Arguments) {
        if ([string]::IsNullOrEmpty($a)) {
            # Windows PowerShell 5.1 drops an empty native argument, which
            # would shift every argument after it.
            return [pscustomobject]@{ ExitCode = 2; Output = @('DASHBOARD_PRESERVE_GATE: BLOCKED', '  BLOCKED refused: an empty argument was passed to the guard') }
        }
        if ($a.Contains('"') -or $a.EndsWith('\')) {
            # Windows PowerShell 5.1 passes an embedded double quote (or a
            # trailing backslash before its own closing quote) verbatim, and
            # the C runtime then splits the argument into several: a crafted
            # value could add or override guard options.
            return [pscustomobject]@{ ExitCode = 2; Output = @('DASHBOARD_PRESERVE_GATE: BLOCKED', '  BLOCKED refused: an argument with a double quote or a trailing backslash cannot be passed to the guard safely') }
        }
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $output = @()
    $code = 2
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $Python -I -B -X utf8 $GuardPath @Arguments 2>&1)
        $code = $LASTEXITCODE
    }
    catch {
        return [pscustomobject]@{ ExitCode = 2; Output = @('DASHBOARD_PRESERVE_GATE: BLOCKED', "  BLOCKED refused: the guard could not be started with '$Python' ($($_.Exception.Message))") }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($null -eq $code) {
        $code = 2
    }
    $text = @($output | ForEach-Object { $_.ToString() })
    return [pscustomobject]@{ ExitCode = [int]$code; Output = $text }
}

function Format-EccoGateBlockedMessage {
    # The single terminating error of a BLOCKED gate: its first line names
    # the gate and BLOCKED, the guard's own lines follow.
    param(
        [Parameter(Mandatory = $true)]
        [string]$Gate,

        [Parameter(Mandatory = $true)]
        [string]$Reason,

        [string[]]$Detail = @()
    )

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("${Gate}: BLOCKED - $Reason")
    foreach ($d in $Detail) {
        $lines.Add([string]$d)
    }
    $lines.Add('Nothing was written to the host: no backup, no upload, no change.')
    return ($lines -join "`n")
}

function Invoke-EccoDashboardPreservationGate {
    <#
        The fail-closed dashboard preservation gate deploy-ha.ps1 runs
        BEFORE its first remote write (mkdir, backup, upload). Read-only on
        the host: it copies the site policy
        (/config/ecco/site-local/dashboard-protection.json), the live
        destination file and the persisted Lovelace resource list into a
        fresh local temp folder, runs tools/ecco_dashboard_guard.py
        `check`, and deletes the folder in a finally block (the copies may
        hold site values).

        - Policy absent: the generic layer only. Present but unreadable or
          malformed: BLOCKED.
        - A destination is gated when it is a dashboard path
          (Test-EccoDashboardDestinationPath) or the policy names it.
        - Live file absent: a new file has nothing to protect (PASS), unless
          the policy names it (BLOCKED).
        - Anything but guard exit 0 throws, with the guard's output, before
          the caller writes anything.

        - With a policy, every other destination it names must exist on the
          host (a mistyped destination protects nothing): BLOCKED otherwise.
        - The guard checks a private copy of the candidate; its sha256 is
          returned (CandidateSha256) and deploy-ha.ps1 installs only a file
          with that hash.
        - The guard's PASS line must name the gate classify determined.
        - -AllowDriftRecovery passes the guard's --allow-drift-recovery:
          live differing from the policy no longer blocks a candidate that
          carries the policy's protected layer exactly. The guard's WARNING
          lines are returned (Warnings) for the caller to print loudly.

        Returns the gate line, whether the gate applied, whether the policy
        names the destination (deploy-ha.ps1 then runs
        Invoke-EccoDashboardLiveVerification after the install) and the
        sha256 of the candidate, the live file and the resource list.
        -RemoteFileReader replaces the ssh/scp reads for offline tests:
        & $reader <remote path> <local path> -> 'present' | 'absent'.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [Parameter(Mandatory = $true)]
        [string]$CandidatePath,

        [Parameter(Mandatory = $true)]
        [string]$GuardPath,

        # The host's persisted Lovelace resource list, named by the caller.
        [Parameter(Mandatory = $true)]
        [string]$ResourcesPath,

        [string[]]$AcceptRemovedCardType = @(),

        [switch]$AllowDriftRecovery,

        [string]$PolicyPath = $script:EccoDashboardPolicyPath,

        [string]$Python = 'python',

        [scriptblock]$RemoteFileReader
    )

    $defaultGate = 'DASHBOARD_PRESERVE_GATE'
    foreach ($t in @($AcceptRemovedCardType)) {
        # Strictly custom:<name>. A value with a double quote and spaces
        # would be split into several guard options by the native command
        # line of Windows PowerShell 5.1 (it could override --destination);
        # the guard and Invoke-EccoDashboardGuard refuse such values too.
        if ($null -eq $t -or $t -cnotmatch '^custom:[A-Za-z0-9][A-Za-z0-9._-]*\z') {
            throw (Format-EccoGateBlockedMessage -Gate $defaultGate -Reason '-AcceptRemovedCardType takes custom card types only: custom:<name>, name [A-Za-z0-9][A-Za-z0-9._-]*.')
        }
    }

    $result = [pscustomobject]@{
        Applies                = $false
        GateLine               = 'not a dashboard destination: the dashboard preservation gate does not apply'
        Gate                   = $defaultGate
        PolicyState            = 'absent'
        PolicyNamesDestination = $false
        PolicyDestinations     = @()
        LiveState              = 'not read'
        LiveSha256             = $null
        ResourcesSha256        = $null
        CandidateSha256        = $null
        Warnings               = @()
        Output                 = @()
    }

    $work = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-dashboard-guard-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $localPolicy = Join-Path $work 'dashboard-protection.json'
        try {
            $result.PolicyState = Read-EccoGateRemoteFile -SshHost $SshHost -RemotePath $PolicyPath -LocalPath $localPolicy -RemoteFileReader $RemoteFileReader
        }
        catch {
            throw (Format-EccoGateBlockedMessage -Gate $defaultGate -Reason "the site policy $PolicyPath could not be read: $($_.Exception.Message)")
        }

        if ($result.PolicyState -eq 'present') {
            # classify must give a complete, well-formed answer: exit 0 with
            # one "yes" line, or exit 4 (never Python's crash code 1) with
            # the "no" line, and the list of every destination the policy
            # names. Anything else - a crash, a missing interpreter, a
            # refused policy - is BLOCKED, never "not a dashboard".
            $classify = Invoke-EccoDashboardGuard -Python $Python -GuardPath $GuardPath -Arguments @('classify', '--destination', $Destination, '--policy', $localPolicy)
            $out = @($classify.Output)
            $classifiedGate = $null
            if ($out.Count -gt 0 -and ([string]$out[0]) -cmatch '^gate: ([A-Z][A-Z0-9_]{2,63})$') {
                $classifiedGate = $Matches[1]
            }
            $yesEntry = @($out | Where-Object { $_ -ceq 'dashboard destination: yes (site policy entry)' }).Count -eq 1
            $yesPath = @($out | Where-Object { $_ -ceq 'dashboard destination: yes (under /config/ecco/dashboards/, .yaml / .yml)' }).Count -eq 1
            $no = @($out | Where-Object { $_ -ceq 'dashboard destination: no' }).Count -eq 1
            $countLines = @($out | Where-Object { $_ -cmatch '^policy destinations: [0-9]{1,6}$' })
            $listedDestinations = @($out | Where-Object { $_ -cmatch '^policy destination: /config/' } | ForEach-Object { $_.Substring('policy destination: '.Length) })
            $listed = ($countLines.Count -eq 1) -and ($listedDestinations.Count -gt 0) -and ([int]($countLines[0].Substring('policy destinations: '.Length)) -eq $listedDestinations.Count)
            $answeredYes = ($classify.ExitCode -eq 0) -and ($yesEntry -xor $yesPath) -and (-not $no)
            $answeredNo = ($classify.ExitCode -eq 4) -and $no -and (-not $yesEntry) -and (-not $yesPath)
            if (-not ($classifiedGate -and $listed -and ($answeredYes -or $answeredNo))) {
                $refusalGate = $defaultGate
                if ($out.Count -gt 0 -and ([string]$out[0]) -cmatch '^([A-Z][A-Z0-9_]{2,63}): BLOCKED$') {
                    $refusalGate = $Matches[1]
                }
                $policyRefused = ($classify.ExitCode -eq 2) -and (@($out | Where-Object { $_ -cmatch '^\s+BLOCKED refused: policy' }).Count -gt 0)
                if ($policyRefused) {
                    $reason = "the site policy $PolicyPath is not valid."
                } else {
                    $reason = "the dashboard guard could not run, or its answer was not understood, while classifying $Destination against the site policy (guard exit code $($classify.ExitCode))."
                }
                throw (Format-EccoGateBlockedMessage -Gate $refusalGate -Reason $reason -Detail $out)
            }
            $result.Gate = $classifiedGate
            $result.PolicyNamesDestination = $yesEntry
            $result.PolicyDestinations = $listedDestinations

            # Every other destination the policy names must exist on the
            # host: a mistyped destination (letter case, extension, folder)
            # would protect nothing, and the deployed file would fall to the
            # generic layer without a word.
            $probeIndex = 0
            foreach ($policyDestination in $listedDestinations) {
                if ($policyDestination -ceq $Destination) {
                    continue
                }
                $probeIndex++
                $probeLocal = Join-Path $work ('policy-destination-' + $probeIndex)
                try {
                    $policyDestinationState = Read-EccoGateRemoteFile -SshHost $SshHost -RemotePath $policyDestination -LocalPath $probeLocal -RemoteFileReader $RemoteFileReader
                }
                catch {
                    throw (Format-EccoGateBlockedMessage -Gate $result.Gate -Reason "the site policy protects $policyDestination, which could not be read on the host: $($_.Exception.Message)")
                }
                if ($policyDestinationState -ne 'present') {
                    throw (Format-EccoGateBlockedMessage -Gate $result.Gate -Reason "the site policy protects $policyDestination, but that file does not exist on the host (a mistyped destination protects nothing: correct the host policy).")
                }
            }
        }

        if (-not ((Test-EccoDashboardDestinationPath -Destination $Destination) -or $result.PolicyNamesDestination)) {
            return $result
        }
        $result.Applies = $true
        if (-not $result.PolicyNamesDestination) {
            $result.Gate = $defaultGate
        }

        # The guard checks a private copy of the candidate, and its sha256 is
        # returned: deploy-ha.ps1 uploads and installs only a file with this
        # hash, so the bytes installed are the bytes checked.
        $localCandidate = Join-Path $work 'candidate.yaml'
        try {
            Copy-Item -LiteralPath $CandidatePath -Destination $localCandidate -ErrorAction Stop
        }
        catch {
            throw (Format-EccoGateBlockedMessage -Gate $result.Gate -Reason "the candidate $CandidatePath could not be read: $($_.Exception.Message)")
        }
        $result.CandidateSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $localCandidate).Hash.ToLowerInvariant()
        Write-Host "Candidate SHA256          : $($result.CandidateSha256)"

        $localLive = Join-Path $work 'live.yaml'
        try {
            $result.LiveState = Read-EccoGateRemoteFile -SshHost $SshHost -RemotePath $Destination -LocalPath $localLive -RemoteFileReader $RemoteFileReader
        }
        catch {
            throw (Format-EccoGateBlockedMessage -Gate $result.Gate -Reason "the live dashboard $Destination could not be read: $($_.Exception.Message)")
        }
        if ($result.LiveState -eq 'absent') {
            if ($result.PolicyNamesDestination) {
                throw (Format-EccoGateBlockedMessage -Gate $result.Gate -Reason "the site policy protects $Destination, but that file does not exist on the host.")
            }
            $result.GateLine = "${defaultGate}: PASS (new file: nothing on the host to protect)"
            return $result
        }
        $result.LiveSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $localLive).Hash.ToLowerInvariant()
        Write-Host "Live dashboard SHA256     : $($result.LiveSha256)"

        $localResources = Join-Path $work 'lovelace_resources'
        try {
            $resourcesState = Read-EccoGateRemoteFile -SshHost $SshHost -RemotePath $ResourcesPath -LocalPath $localResources -RemoteFileReader $RemoteFileReader
        }
        catch {
            throw (Format-EccoGateBlockedMessage -Gate $result.Gate -Reason "the Lovelace resource list could not be read: $($_.Exception.Message)")
        }
        if ($resourcesState -eq 'present') {
            $result.ResourcesSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $localResources).Hash.ToLowerInvariant()
            Write-Host "Lovelace resources SHA256 : $($result.ResourcesSha256)"
        } else {
            Write-Host 'Lovelace resources SHA256 : none (no persisted resource list on the host)'
        }

        $arguments = @('check', '--destination', $Destination, '--live', $localLive, '--candidate', $localCandidate)
        if ($result.PolicyState -eq 'present') {
            $arguments += @('--policy', $localPolicy)
        }
        if ($resourcesState -eq 'present') {
            $arguments += @('--resources', $localResources)
        }
        foreach ($t in @($AcceptRemovedCardType)) {
            $arguments += @('--accept-removed-type', $t)
        }
        if ($AllowDriftRecovery) {
            $arguments += '--allow-drift-recovery'
        }
        $check = Invoke-EccoDashboardGuard -Python $Python -GuardPath $GuardPath -Arguments $arguments
        $result.Output = $check.Output
        $check.Output | ForEach-Object { Write-Host $_ }
        if ($check.ExitCode -ne 0) {
            throw (Format-EccoGateBlockedMessage -Gate $result.Gate -Reason "the dashboard preservation gate refused this deployment (guard exit code $($check.ExitCode))." -Detail $check.Output)
        }
        # The PASS line must name the gate classify determined: the site's
        # gate when the policy names the destination, the default otherwise.
        # A guard that passed under another gate checked something else.
        $expectedPass = "$($result.Gate): PASS"
        $first = if ($check.Output.Count -gt 0) { [string]$check.Output[0] } else { '' }
        if ($first -cne $expectedPass) {
            throw (Format-EccoGateBlockedMessage -Gate $result.Gate -Reason "the guard exited 0 without the expected line '$expectedPass'." -Detail $check.Output)
        }
        $result.GateLine = $first
        $result.Warnings = @($check.Output | Where-Object { ([string]$_) -cmatch '^\s+WARNING ' } | ForEach-Object { ([string]$_).Trim() })
        return $result
    }
    finally {
        try {
            Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Could not delete the gate's temporary folder $work (it may hold site values): $($_.Exception.Message)"
        }
    }
}

function Invoke-EccoDashboardLiveVerification {
    <#
        The post-install half of the gate: re-reads the site policy and the
        installed destination (read-only, into a fresh temp folder deleted
        in a finally block) and runs the guard's `verify-live`. Never
        throws: returns Passed = $false with the reason, and deploy-ha.ps1
        sends a failure through Invoke-EccoDeploymentRollback.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [Parameter(Mandatory = $true)]
        [string]$GuardPath,

        [string]$PolicyPath = $script:EccoDashboardPolicyPath,

        [string]$Python = 'python',

        # The gate the pre-install check ran under (deploy-ha.ps1 passes
        # it): the PASS line must name it.
        [string]$ExpectedGate,

        [scriptblock]$RemoteFileReader
    )

    $result = [pscustomobject]@{ Passed = $false; GateLine = ''; Output = @() }
    $work = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-dashboard-verify-' + [guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Path $work | Out-Null
        $localPolicy = Join-Path $work 'dashboard-protection.json'
        $localLive = Join-Path $work 'live.yaml'
        if ((Read-EccoGateRemoteFile -SshHost $SshHost -RemotePath $PolicyPath -LocalPath $localPolicy -RemoteFileReader $RemoteFileReader) -ne 'present') {
            $result.Output = @("the site policy $PolicyPath is no longer on the host")
            return $result
        }
        if ((Read-EccoGateRemoteFile -SshHost $SshHost -RemotePath $Destination -LocalPath $localLive -RemoteFileReader $RemoteFileReader) -ne 'present') {
            $result.Output = @("the installed file $Destination is not on the host")
            return $result
        }
        $verify = Invoke-EccoDashboardGuard -Python $Python -GuardPath $GuardPath -Arguments @('verify-live', '--policy', $localPolicy, '--destination', $Destination, '--live', $localLive)
        $result.Output = $verify.Output
        $first = if ($verify.Output.Count -gt 0) { [string]$verify.Output[0] } else { '' }
        $result.GateLine = $first
        if ($ExpectedGate) {
            $result.Passed = ($verify.ExitCode -eq 0) -and ($first -ceq "${ExpectedGate}: PASS")
        } else {
            $result.Passed = ($verify.ExitCode -eq 0) -and ($first -cmatch '^[A-Z][A-Z0-9_]+: PASS$')
        }
        return $result
    }
    catch {
        $result.Passed = $false
        $result.Output = @($result.Output) + @("the post-install read failed: $($_.Exception.Message)")
        return $result
    }
    finally {
        if (Test-Path -LiteralPath $work) {
            try {
                Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction Stop
            }
            catch {
                Write-Warning "Could not delete the gate's temporary folder $work (it may hold site values): $($_.Exception.Message)"
            }
        }
    }
}

function Get-EccoDashboardGatePinPath {
    # The optional local gate pin file of a checkout (git-ignored).
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    return (Join-Path $RepoRoot $script:EccoDashboardGatePinFile)
}

function Get-EccoDashboardGatePin {
    <#
        Reads the optional local gate pin: one gate name (the site policy's
        "gate"), blank lines and # comment lines ignored. Returns $null when
        the file does not exist. Throws when it exists but is not a plain
        file holding exactly one name [A-Z][A-Z0-9_]{2,63}: a pin that
        cannot be read must never silently mean "no pin". Local file only;
        nothing is read from the host.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "The local dashboard gate pin $Path is not a file."
    }
    try {
        $raw = @(Get-Content -LiteralPath $Path -Encoding UTF8 -ErrorAction Stop)
    }
    catch {
        throw "The local dashboard gate pin $Path could not be read: $($_.Exception.Message)"
    }
    $names = @($raw | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
    if ($names.Count -ne 1 -or $names[0] -cnotmatch '^[A-Z][A-Z0-9_]{2,63}\z') {
        throw "The local dashboard gate pin $Path must hold exactly one gate name ([A-Z][A-Z0-9_]{2,63}; blank and # comment lines are ignored)."
    }
    return $names[0]
}

function Assert-EccoDashboardGatePin {
    <#
        The optional gate pin, checked right after
        Invoke-EccoDashboardPreservationGate and before the first remote
        write. With a pin (-ExpectedGate):
          - a dashboard destination (the gate applied) must have run and
            passed under exactly that gate, so a host policy that was moved
            aside, replaced, or no longer names the destination cannot fall
            back to DASHBOARD_PRESERVE_GATE without a word;
          - any other destination needs the site policy present on the host
            unless the pin is DASHBOARD_PRESERVE_GATE itself.
        DASHBOARD_PRESERVE_GATE as the pin states that this deployment
        deliberately targets a dashboard the site policy does not protect.
        No pin: nothing to check ($null). Throws the gate's BLOCKED message;
        returns the line to print otherwise. Pure logic on the gate result.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [object]$GateResult,

        [AllowNull()]
        [AllowEmptyString()]
        [string]$ExpectedGate,

        [string]$PinSource = 'the gate pin'
    )

    if ([string]::IsNullOrEmpty($ExpectedGate)) {
        return $null
    }
    $gate = [string]$GateResult.Gate
    if ($ExpectedGate -cnotmatch '^[A-Z][A-Z0-9_]{2,63}\z') {
        throw (Format-EccoGateBlockedMessage -Gate $gate -Reason "$PinSource is not a gate name ([A-Z][A-Z0-9_]{2,63}).")
    }
    if ($GateResult.Applies) {
        $line = [string]$GateResult.GateLine
        if (($gate -cne $ExpectedGate) -or -not ($line -ceq "${ExpectedGate}: PASS" -or $line.StartsWith("${ExpectedGate}: PASS (", [System.StringComparison]::Ordinal))) {
            throw (Format-EccoGateBlockedMessage -Gate $gate -Reason "$PinSource expects this dashboard destination to pass under $ExpectedGate, but the gate ran under $gate ('$line'). The host's site policy ($script:EccoDashboardPolicyPath) may have been moved aside or replaced, or it no longer names this destination: restore it. For a dashboard the site deliberately does not protect, pass -ExpectedSiteGate $($script:EccoDefaultDashboardGate) for this deployment.")
        }
        return "Gate pin    : $ExpectedGate ($PinSource) - matched"
    }
    if ($ExpectedGate -cne $script:EccoDefaultDashboardGate -and $GateResult.PolicyState -ne 'present') {
        throw (Format-EccoGateBlockedMessage -Gate $gate -Reason "$PinSource expects the site gate $ExpectedGate, but there is no site policy on the host ($script:EccoDashboardPolicyPath): it was moved aside or removed. Restore it, or remove the pin to deploy without it.")
    }
    return "Gate pin    : $ExpectedGate ($PinSource) - not a dashboard destination; site policy present: $($GateResult.PolicyState -eq 'present')"
}

Export-ModuleMember -Function `
    Invoke-EccoRemoteCommand, `
    Invoke-EccoRemoteCommandBestEffort, `
    Test-EccoDeploymentDestination, `
    Assert-EccoCleanWorkingTree, `
    Format-EccoRollbackResultMessage, `
    Get-EccoLovelaceResourceUrl, `
    ConvertFrom-EccoLovelaceResources, `
    Format-EccoResourceReminder, `
    Invoke-EccoDeploymentRollback, `
    Test-EccoDashboardDestinationPath, `
    Get-EccoGateProbeCommand, `
    Copy-EccoRemoteFileForGate, `
    Invoke-EccoDashboardGuard, `
    Format-EccoGateBlockedMessage, `
    Invoke-EccoDashboardPreservationGate, `
    Invoke-EccoDashboardLiveVerification, `
    Get-EccoDashboardGatePinPath, `
    Get-EccoDashboardGatePin, `
    Assert-EccoDashboardGatePin
