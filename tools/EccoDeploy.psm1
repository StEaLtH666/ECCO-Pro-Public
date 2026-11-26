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

    The Intelligence kit route (deploy-ha-kit.ps1, place-ha-site-file.ps1
    and deploy-ha.ps1 -Action Retire; the region "Intelligence kit route"
    below) writes only the exact files of a verified kit under
    /config/custom_components/ecco_intelligence/, stages under
    /config/ecco/staging/<stamp>/, backs up under /config/ecco-backups/,
    places the one site file, and never deletes anything: a replaced,
    failed or uninstalled tree is moved under the staging folder.

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
# The Intelligence site file and its runtime state (placed by
# place-ha-site-file.ps1 only), and the kit route's staging area: never a
# single-file deployment destination (Test-EccoDeploymentDestination).
$script:EccoIntelligencePrefix = '/config/ecco/intelligence/'
$script:EccoStagingPrefix = '/config/ecco/staging/'
# A harness-owned ssh configuration (ssh -F) for the L3 test instance only:
# Set-EccoSshConfigFile. $null means the user's normal ssh configuration.
$script:EccoSshConfigFile = $null

function Get-EccoSshConfigArguments {
    # The extra ssh/scp arguments every remote call carries: -F <file> when a
    # harness-owned configuration was set for -Target Test, nothing otherwise.
    if ($script:EccoSshConfigFile) {
        return @('-F', $script:EccoSshConfigFile)
    }
    return @()
}

function Set-EccoSshConfigFile {
    # Sets (or, with an empty value, clears) the ssh configuration file every
    # ssh and scp call of this module uses (ssh -F / scp -F). Validated by
    # Assert-EccoDeployTargetParameters first: -Target Test only.
    param(
        [AllowNull()]
        [AllowEmptyString()]
        [string]$Path
    )

    if ([string]::IsNullOrEmpty($Path)) {
        $script:EccoSshConfigFile = $null
        return
    }
    $script:EccoSshConfigFile = (Resolve-Path -LiteralPath $Path).Path
}

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

    $sshConfigArgs = @(Get-EccoSshConfigArguments)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        if ($Capture) {
            $result = @(& ssh -o BatchMode=yes @sshConfigArgs $SshHost $Command 2>&1)
            $code = $LASTEXITCODE
        } else {
            & ssh -o BatchMode=yes @sshConfigArgs $SshHost $Command
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

        Three subtrees inside the allowlist are refused:
            /config/ecco/site-local/    the site's dashboard protection policy;
            /config/ecco/intelligence/  the Intelligence site file and its
                                        state (place-ha-site-file.ps1 only);
            /config/ecco/staging/       the kit route's staging area
                                        (deploy-ha-kit.ps1 only).
        A sibling that merely shares the text (/config/ecco/intelligence-x/)
        is still an ordinary /config/ecco/ destination.
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

    # The Intelligence site file and its runtime state: only
    # place-ha-site-file.ps1 writes there (the site file, with its expected
    # sha256 and a verified backup); the runtime state is never written by any
    # tool. A single-file copy would be the manual-copy workaround.
    if ($normalised.StartsWith($script:EccoIntelligencePrefix, [System.StringComparison]::Ordinal) -or
        $normalised -eq $script:EccoIntelligencePrefix.TrimEnd('/')) {
        throw "Remote destination may not be under $($script:EccoIntelligencePrefix): it holds the Intelligence site file and state; the site file is placed only by tools/place-ha-site-file.ps1."
    }

    # The kit route's staging area: written only by deploy-ha-kit.ps1, which
    # verifies every staged file by its hash before a swap.
    if ($normalised.StartsWith($script:EccoStagingPrefix, [System.StringComparison]::Ordinal) -or
        $normalised -eq $script:EccoStagingPrefix.TrimEnd('/')) {
        throw "Remote destination may not be under $($script:EccoStagingPrefix): it is the Intelligence kit route's staging area (tools/deploy-ha-kit.ps1 only)."
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
        [bool]$Dashboard = $false,

        # The deployment was a drift recovery (-AllowDriftRecovery): its
        # backup is the drifted live file, so say that a restored backup
        # lacks the site policy's protected layer.
        [bool]$DriftRecovery = $false
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

    if ($DriftRecovery) {
        $lines.Add('DRIFT RECOVERY ROLLED BACK: this deployment was a drift recovery (-AllowDriftRecovery), so its backup is the drifted live file. A restored backup differs from the site policy at a protected pointer and does not carry the policy''s protected layer: do not report the site layer as intact. Deployments to this dashboard stay BLOCKED by the drift until a drift recovery completes.')
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
        message also asks for a lovelace/config read-back. -DriftRecovery
        (the gate passed a drift recovery) adds that the restored backup is
        the drifted live file, without the site policy's protected layer.
        -NewFileBackupNote (deploy-ha.ps1): for a new file, what the run's
        backup folder holds, so "Backup: none (new file)" never stands beside
        a folder the run created without naming it (review L3W-6).
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [AllowEmptyString()]
        [string]$BackupPath,

        [AllowEmptyString()]
        [string]$NewFileBackupNote = '',

        [Parameter(Mandatory = $true)]
        [bool]$HadOriginal,

        [Parameter(Mandatory = $true)]
        [string]$Reason,

        [switch]$Dashboard,

        [switch]$DriftRecovery
    )

    Write-Warning "Rolling back deployment: $Reason"

    $isDashboard = $Dashboard -or (Test-EccoDashboardDestinationPath -Destination $Destination)
    $backupDescription = if ($HadOriginal) { $BackupPath } elseif ($NewFileBackupNote) { "none (new file); $NewFileBackupNote" } else { 'none (new file)' }
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
        -Dashboard $isDashboard `
        -DriftRecovery ([bool]$DriftRecovery)

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
    $sshConfigArgs = @(Get-EccoSshConfigArguments)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & scp -q @sshConfigArgs $remoteSpec $LocalPath
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

        -ClassifyOnly (the Intelligence kit route, the site-file placement
        and deploy-ha.ps1 -Action Retire, which have no candidate to check):
        the same policy read, classify and policy-destination checks, then
        return without reading the live file or running `check`. Applies
        says whether the destination is a dashboard destination; those
        callers refuse a policy-named destination themselves.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        # Required unless -ClassifyOnly.
        [string]$CandidatePath,

        [Parameter(Mandatory = $true)]
        [string]$GuardPath,

        # The host's persisted Lovelace resource list, named by the caller
        # (required unless -ClassifyOnly, which never reads it).
        [string]$ResourcesPath,

        [string[]]$AcceptRemovedCardType = @(),

        [switch]$AllowDriftRecovery,

        [string]$PolicyPath = $script:EccoDashboardPolicyPath,

        [string]$Python = 'python',

        [scriptblock]$RemoteFileReader,

        [switch]$ClassifyOnly
    )

    $defaultGate = 'DASHBOARD_PRESERVE_GATE'
    if (-not $ClassifyOnly -and ([string]::IsNullOrEmpty($CandidatePath) -or [string]::IsNullOrEmpty($ResourcesPath))) {
        throw (Format-EccoGateBlockedMessage -Gate $defaultGate -Reason 'no candidate file or resource list path was given to the gate.')
    }
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
        if ($ClassifyOnly) {
            # No candidate and no live read: the caller refuses a
            # policy-named destination. An unprotected dashboard path is
            # reported under the default gate, so a site gate pin still
            # needs the one-run -ExpectedSiteGate DASHBOARD_PRESERVE_GATE.
            if ($result.PolicyNamesDestination) {
                $result.GateLine = "$($result.Gate): the site policy protects $Destination (classify only)"
            } else {
                $result.GateLine = "${defaultGate}: PASS (classify only: a dashboard path the site policy does not name)"
            }
            return $result
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
        throw (Format-EccoGateBlockedMessage -Gate $gate -Reason "$PinSource expects the site gate $ExpectedGate, but there is no site policy on the host ($script:EccoDashboardPolicyPath): it was moved aside or removed. Restore it. While the policy is deliberately aside (the owner procedure for a release that changes the protected card), pass -ExpectedSiteGate $($script:EccoDefaultDashboardGate) for this deployment only, and keep the pin: it protects again once the policy is back.")
    }
    return "Gate pin    : $ExpectedGate ($PinSource) - not a dashboard destination; site policy present: $($GateResult.PolicyState -eq 'present')"
}

# region Intelligence kit route (PR-5)
# ---------------------------------------------------------------------------
# The deploy route for the ECCO Intelligence integration: deploy-ha-kit.ps1
# (Plan, Install, Upgrade, Rollback, Uninstall), place-ha-site-file.ps1 and
# deploy-ha.ps1 -Action Retire, plus the -Target Test|Production guard every
# route shares.
#
# Rules this region keeps (Test-EccoDeploy.ps1 sections 17-24 check them):
#   - the only writes under /config/custom_components/ are the exact files
#     of a kit whose SHA256SUMS verified locally (the allowlist), into
#     /config/custom_components/ecco_intelligence only;
#   - staging under /config/ecco/staging/<stamp>/, never inside
#     custom_components/ (Home Assistant would load it as an integration);
#   - /config itself is resolved once, read-only, right after the ssh probe
#     (amendment A26: the SSH add-on's /config is a symlink): accepted only
#     as a real folder or a symlink that cd -P resolves to an existing real
#     folder; the resolved root is printed (Plan too) and checked unchanged
#     immediately before the first write, and inside every folder-creating
#     command;
#   - every folder is created one level at a time, never with a recursive
#     mkdir, after a symlink test of every path segment BELOW /config;
#   - nothing is ever deleted: no rm; a replaced, failed or uninstalled tree
#     is moved under the staging folder, a retired file into a backup folder;
#   - every Home Assistant CLI call is its own ssh command, and no route here
#     restarts Home Assistant (a restart stays separately gated);
#   - remote commands are single-quoted words only: no double quote and no
#     dollar sign (Windows PowerShell 5.1 splits embedded double quotes).
# ---------------------------------------------------------------------------

$script:EccoKitDomain = 'ecco_intelligence'
$script:EccoKitInstallPath = '/config/custom_components/ecco_intelligence'
$script:EccoKitSumsPackagePrefix = 'custom_components/ecco_intelligence/'
$script:EccoKitManifestSchema = 'ecco-intel-vendor-manifest/1'
$script:EccoKitFileNamePattern = '^[A-Za-z0-9_][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*\.(py|json)\z'
$script:EccoKitDirNamePattern = '^[a-z0-9_]+\z'
$script:EccoKitMaxDepth = 4
$script:EccoKitBackupCopyName = 'custom_components__ecco_intelligence'
$script:EccoIntelligenceDir = '/config/ecco/intelligence'
$script:EccoSiteFilePath = '/config/ecco/intelligence/site.local.json'
$script:EccoSiteStatePath = '/config/ecco/intelligence/state'
$script:EccoSiteFileMaxBytes = 262144
# The deepest nesting of arrays and objects the placement reads (review DRD-2): Python's json, which the runtime uses,
# refuses a nesting only when the interpreter runs out of recursion room, far deeper than this; Windows PowerShell 5.1's
# ConvertFrom-Json stops just past it. A site file nests about five deep.
$script:EccoSiteFileMaxDepth = 100
# 2^1024 - 2^970 in its 309 decimal digits: the least magnitude that Python's float() reads as an infinity and that
# float(int) refuses (both round past the largest double), so the runtime refuses every JSON number at or beyond it as a
# non-finite number (review DRD-2). Test-EccoDeploy.ps1 checks these digits against Python and System.Numerics.
$script:EccoDoubleOverflowDigits = '1797693134862315807937289714053034150799341327100378269361737789804449682927647509466490179775872070963' +
    '3028641669288791094655554785194040263065748867150582068190890200070838367627385484581771153176447573027' +
    '0069855571366959622842914819860834936475292719074168444365510704342711559699508093042880177904174497792'
# One strict JSON token (RFC 8259), anchored where the previous one ended
# (Get-EccoStrictJsonProblem): whitespace, a structural character, a string
# (no control character, only the JSON escapes), a number (no sign but a
# leading minus, no leading zero, no bare point) or true / false / null, each
# number and word followed by whitespace, a separator or the end.
$script:EccoJsonTokenRegex = New-Object System.Text.RegularExpressions.Regex (
    '\G(?:[ \t\n\r]+|[{}\[\]:,]|"(?>[^"\\\x00-\x1F]+|\\["\\/bfnrt]|\\u[0-9A-Fa-f]{4})*"|(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)(?=[ \t\n\r,\]}]|\z))',
    [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)
# The three non-finite constants Python's json reads and the runtime refuses.
$script:EccoJsonNonFiniteRegex = New-Object System.Text.RegularExpressions.Regex (
    '\G-?(?:NaN|Infinity)', [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)
$script:EccoStagingDir = '/config/ecco/staging'
$script:EccoBackupsDir = '/config/ecco-backups'
$script:EccoTestMarkerPath = '/config/.ecco_l3_test_instance'
$script:EccoTestMarkerPattern = '^ECCO-L3-TEST [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z'
$script:EccoTestMachine = 'ecco-l3-test'
$script:EccoProductionSshHost = 'ecco-ha'
$script:EccoConfigRoot = '/config'
# A resolved /config root: an absolute physical path of plain segments, safe
# inside single quotes; never '/' itself.
$script:EccoResolvedRootPattern = '^(/[A-Za-z0-9_][A-Za-z0-9_.-]*)+\z'
$script:EccoResolvedRootMaxLength = 200

function Format-EccoKitBlockedMessage {
    <#
        The single terminating error of a refused kit-route step. -Stage says
        what was written: NothingSent (refused locally, before any ssh call),
        NothingWritten (only read-only commands were sent) or
        StoppedBeforeSwap (folders may have been written, nothing installed
        changed; any listed in -Kept exist and are never deleted). -Step names
        the write a StoppedBeforeSwap message stops before: the swap, or
        Uninstall's move aside (review DRD-5).
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Reason,

        [ValidateSet('NothingSent', 'NothingWritten', 'StoppedBeforeSwap')]
        [string]$Stage = 'NothingWritten',

        [string[]]$Kept = @(),

        [ValidateSet('swap', 'move aside')]
        [string]$Step = 'swap'
    )

    $lines = New-Object System.Collections.Generic.List[string]
    if ($Stage -eq 'StoppedBeforeSwap') {
        $lines.Add("${Name}: STOPPED before the $Step - $Reason")
        $lines.Add("Nothing installed was changed: $($script:EccoKitInstallPath) is as it was.")
        if (@($Kept).Count -gt 0) {
            $lines.Add('Kept for inspection (nothing is deleted): ' + (@($Kept) -join ', '))
        }
    } else {
        $lines.Add("${Name}: BLOCKED - $Reason")
        if ($Stage -eq 'NothingSent') {
            $lines.Add('Nothing was sent to the host.')
        } else {
            $lines.Add('Nothing was written to the host: no folder, no upload, no change.')
        }
    }
    return ($lines -join "`n")
}

function Get-EccoBytesSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes
    )

    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (-join ($hasher.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }))
    }
    finally {
        $hasher.Dispose()
    }
}

function ConvertTo-EccoOrdinalSorted {
    # A string array sorted ordinally (case-sensitive, culture-free), unique.
    param(
        [AllowEmptyCollection()]
        [string[]]$Items = @()
    )

    $set = New-Object 'System.Collections.Generic.SortedSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($i in @($Items)) {
        [void]$set.Add($i)
    }
    return , ([string[]]@($set))
}

function New-EccoFileMap {
    # A package-relative path -> sha256 map, sorted ordinally.
    return , (New-Object 'System.Collections.Generic.SortedDictionary[string,string]' ([System.StringComparer]::Ordinal))
}

function Get-EccoParentDirs {
    # Every folder that holds one of the given relative paths ('a/b/c.py' ->
    # 'a', 'a/b'), sorted ordinally, so a parent always comes before its child.
    param(
        [AllowEmptyCollection()]
        [string[]]$Paths = @()
    )

    $set = New-Object 'System.Collections.Generic.SortedSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($p in @($Paths)) {
        $cut = $p.IndexOf('/')
        while ($cut -gt 0) {
            [void]$set.Add($p.Substring(0, $cut))
            $cut = $p.IndexOf('/', $cut + 1)
        }
    }
    # Always a string array, never unrolled to $null or a single string (a
    # flat package has no folder; [Array]::BinarySearch needs an array).
    $sorted = New-Object string[] $set.Count
    $set.CopyTo($sorted)
    return , $sorted
}

# --- the -Target guard -------------------------------------------------------

function Assert-EccoDeployTargetParameters {
    <#
        The local half of the -Target guard (amendment A10), checked before any
        ssh call. -Target Test|Production is mandatory whenever -SshHost is not
        the production alias 'ecco-ha', and always with -RequireTarget (the
        kit commands). -SshConfigFile (a harness-owned ssh configuration for
        the isolated L3 test instance, used as ssh -F / scp -F) is accepted
        with -Target Test only. The alias must be a plain host alias (no
        leading '-', so it can never become an ssh option). Returns the
        normalised target. Pure local logic.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$SshHost,

        [AllowNull()]
        [AllowEmptyString()]
        [string]$Target,

        [AllowNull()]
        [AllowEmptyString()]
        [string]$SshConfigFile,

        [switch]$RequireTarget
    )

    if ($SshHost -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}\z') {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Stage NothingSent -Reason "-SshHost '$SshHost' is not a plain ssh host alias ([A-Za-z0-9][A-Za-z0-9._@-]*).")
    }
    if ([string]::IsNullOrEmpty($Target)) {
        if ($RequireTarget) {
            throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Stage NothingSent -Reason '-Target Test|Production is required: say which Home Assistant this run is meant for.')
        }
        if ($SshHost -cne $script:EccoProductionSshHost) {
            throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Stage NothingSent -Reason "-SshHost '$SshHost' is not the production alias '$($script:EccoProductionSshHost)': -Target Test|Production is required.")
        }
        $Target = 'Production'
    }
    if ($Target -ieq 'Test') {
        $Target = 'Test'
    } elseif ($Target -ieq 'Production') {
        $Target = 'Production'
    } else {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Stage NothingSent -Reason "-Target must be Test or Production, not '$Target'.")
    }
    if (-not [string]::IsNullOrEmpty($SshConfigFile)) {
        if ($Target -ne 'Test') {
            throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Stage NothingSent -Reason '-SshConfigFile (a harness-owned ssh configuration) is accepted with -Target Test only; production uses your normal ssh configuration.')
        }
        if ($SshConfigFile.Contains('"') -or $SshConfigFile.EndsWith('\') -or -not (Test-Path -LiteralPath $SshConfigFile -PathType Leaf)) {
            throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Stage NothingSent -Reason "-SshConfigFile '$SshConfigFile' is not an existing file (or it holds a double quote or ends in a backslash).")
        }
    }
    return $Target
}

function Get-EccoSshResolvedHostName {
    # The host name ssh would connect to for an alias (ssh -G: reads the ssh
    # configuration only, opens no connection). $null when it cannot be read.
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost
    )

    $sshConfigArgs = @(Get-EccoSshConfigArguments)
    $previousErrorActionPreference = $ErrorActionPreference
    $out = @()
    $code = 1
    try {
        $ErrorActionPreference = 'Continue'
        $out = @(& ssh @sshConfigArgs -G $SshHost 2>&1)
        $code = $LASTEXITCODE
    }
    catch {
        return $null
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($code -ne 0) {
        return $null
    }
    foreach ($line in $out) {
        if (([string]$line) -cmatch '^hostname (\S+)\s*\z') {
            return $Matches[1]
        }
    }
    return $null
}

function Test-EccoLoopbackHostName {
    # True for a loopback host name: localhost, 127.0.0.0/8 or ::1.
    param(
        [AllowEmptyString()]
        [string]$HostName
    )

    $h = $HostName.Trim('[', ']')
    return (($h -ieq 'localhost') -or ($h -cmatch '^127\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\z') -or ($h -eq '::1') -or ($h -eq '0:0:0:0:0:0:0:1'))
}

function Get-EccoHaMachine {
    # The machine name Home Assistant reports (ha core info --raw-json, its
    # own ssh command, read-only): data.machine, or $null when unreadable.
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost
    )

    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command 'ha core info --raw-json' -Capture
    if ($r.ExitCode -ne 0) {
        return $null
    }
    $text = (@($r.Output) -join "`n")
    $a = $text.IndexOf('{')
    $b = $text.LastIndexOf('}')
    if ($a -lt 0 -or $b -le $a) {
        return $null
    }
    try {
        $doc = $text.Substring($a, $b - $a + 1) | ConvertFrom-Json
    }
    catch {
        return $null
    }
    if ($doc -and $doc.PSObject.Properties['data'] -and $doc.data -and $doc.data.PSObject.Properties['machine']) {
        $machine = [string]$doc.data.machine
        if ($machine -cmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\z') {
            return $machine
        }
    }
    return $null
}

function Assert-EccoDeployTarget {
    <#
        The remote half of the -Target guard (amendment A10; test-HA note),
        read-only, run after the ssh probe and before the first remote write:
          Test       - the alias resolves (ssh -G) to a loopback address, the
                       marker /config/.ecco_l3_test_instance is a regular file
                       holding exactly 'ECCO-L3-TEST <uuid>', and Home
                       Assistant reports the machine 'ecco-l3-test';
          Production - the alias does not resolve to loopback, the marker is
                       proven absent, and the machine is readable and is not
                       'ecco-l3-test'.
        Throws DEPLOY_TARGET: BLOCKED otherwise; returns the line to print.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Test', 'Production')]
        [string]$Target
    )

    $resolved = Get-EccoSshResolvedHostName -SshHost $SshHost
    if (-not $resolved) {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "ssh -G could not resolve the alias '$SshHost' to a host name.")
    }
    $loopback = Test-EccoLoopbackHostName -HostName $resolved
    if ($Target -eq 'Test' -and -not $loopback) {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "-Target Test, but '$SshHost' does not resolve to a loopback address: the isolated test instance listens on this PC only.")
    }
    if ($Target -eq 'Production' -and $loopback) {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "-Target Production, but '$SshHost' resolves to a loopback address (the isolated test instance runs on this PC).")
    }

    $probe = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (Get-EccoGateProbeCommand -RemotePath $script:EccoTestMarkerPath) -Capture
    if ($probe.ExitCode -ne 0) {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "the test-instance marker $($script:EccoTestMarkerPath) could not be inspected (ssh exit code $($probe.ExitCode)).")
    }
    $markerState = ((@($probe.Output) -join '').Trim())
    $markerText = $null
    if ($markerState.EndsWith('present')) {
        $read = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "head -c 200 '$($script:EccoTestMarkerPath)'" -Capture
        if ($read.ExitCode -eq 0) {
            $markerText = ((@($read.Output) -join "`n").Trim())
        }
        $markerState = 'present'
    } elseif ($markerState.EndsWith('absent')) {
        $markerState = 'absent'
    } else {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "the test-instance marker $($script:EccoTestMarkerPath) is not a readable regular file and not proven absent (a symlink, a folder or an unreadable path).")
    }

    if ($Target -eq 'Production' -and $markerState -eq 'present') {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "-Target Production, but the test-instance marker $($script:EccoTestMarkerPath) is present: this host is the isolated L3 test instance.")
    }
    if ($Target -eq 'Test') {
        if ($markerState -ne 'present') {
            throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "-Target Test, but the test-instance marker $($script:EccoTestMarkerPath) is absent: refusing to treat this host as the test instance.")
        }
        if ($null -eq $markerText -or $markerText -cnotmatch $script:EccoTestMarkerPattern) {
            throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "-Target Test, but the test-instance marker does not hold exactly 'ECCO-L3-TEST <uuid>'.")
        }
    }

    $machine = Get-EccoHaMachine -SshHost $SshHost
    if (-not $machine) {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason 'the machine name could not be read from Home Assistant (ha core info --raw-json).')
    }
    if ($Target -eq 'Test' -and $machine -cne $script:EccoTestMachine) {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "-Target Test, but Home Assistant reports the machine '$machine', not '$($script:EccoTestMachine)'.")
    }
    if ($Target -eq 'Production' -and $machine -ceq $script:EccoTestMachine) {
        throw (Format-EccoKitBlockedMessage -Name 'DEPLOY_TARGET' -Reason "-Target Production, but Home Assistant reports the test machine '$machine'.")
    }

    if ($Target -eq 'Test') {
        return "Target      : Test - loopback host, marker $($markerText.Substring(13, 8))..., machine $machine"
    }
    return "Target      : Production - not loopback, no test-instance marker, machine $machine"
}

# --- the kit, checked locally before any ssh -----------------------------

function Test-EccoKitPackagePath {
    <#
        The rule for one path inside the integration folder (as listed in a
        kit's SHA256SUMS below custom_components/ecco_intelligence/, or in a
        backup's BACKUP_SHA256SUMS): at most 4 levels, folders [a-z0-9_]
        (never __pycache__), files .py or .json named
        [A-Za-z0-9_][A-Za-z0-9_-]*(.[A-Za-z0-9_-]+)*. Returns $null when the
        path is allowed, else the reason. Pure string logic.
    #>
    param(
        [AllowEmptyString()]
        [string]$Path
    )

    if ([string]::IsNullOrEmpty($Path)) {
        return 'an empty path'
    }
    if ($Path.Contains('\')) {
        return 'a backslash'
    }
    if ($Path.StartsWith('/')) {
        return 'an absolute path'
    }
    $segments = $Path.Split('/')
    if ($segments.Count -gt $script:EccoKitMaxDepth) {
        return "more than $($script:EccoKitMaxDepth) levels"
    }
    for ($i = 0; $i -lt $segments.Count; $i++) {
        $s = $segments[$i]
        if ($s -eq '') {
            return 'an empty path segment'
        }
        if ($s -eq '.' -or $s -eq '..') {
            return "a '$s' segment"
        }
        if ($i -lt $segments.Count - 1) {
            if ($s -cnotmatch $script:EccoKitDirNamePattern) {
                return "the folder name '$s' (only [a-z0-9_])"
            }
            if ($s -ceq '__pycache__') {
                return 'a __pycache__ folder'
            }
        } elseif ($s -cnotmatch $script:EccoKitFileNamePattern) {
            return "the file name '$s' (only .py and .json files named [A-Za-z0-9_-] with dots)"
        }
    }
    return $null
}

function ConvertFrom-EccoSumsText {
    <#
        Parses a sha256sum-format list strictly: printable ASCII and LF only,
        a final newline, every line exactly '<64 lower-case hex>  <path>', no
        duplicate and no two paths that differ only by letter case. Kit form
        (default): each path is VENDOR_MANIFEST.json or
        custom_components/ecco_intelligence/<allowed path>, compared
        case-sensitively. -PackageRelative (a backup's BACKUP_SHA256SUMS):
        each path is an allowed path inside the integration folder. Returns
        the entries in file order; throws on the first refusal.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes,

        [Parameter(Mandatory = $true)]
        [string]$Label,

        [switch]$PackageRelative
    )

    if ($Bytes.Length -eq 0) {
        throw "$Label is empty."
    }
    foreach ($b in $Bytes) {
        if ($b -eq 13) {
            throw "$Label has a carriage return: only LF line endings are accepted."
        }
        if (($b -lt 32 -and $b -ne 10) -or $b -gt 126) {
            throw "$Label holds a byte that is not printable ASCII."
        }
    }
    if ($Bytes[$Bytes.Length - 1] -ne 10) {
        throw "$Label does not end with a newline."
    }
    $text = [System.Text.Encoding]::ASCII.GetString($Bytes)
    $lines = $text.Substring(0, $text.Length - 1).Split([char]10)
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $seenCase = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $entries = New-Object System.Collections.Generic.List[object]
    $n = 0
    foreach ($line in $lines) {
        $n++
        if ($line -cnotmatch '^([0-9a-f]{64})  (\S+)\z') {
            throw "$Label line ${n}: not '<sha256>  <path>'."
        }
        $digest = $Matches[1]
        $path = $Matches[2]
        if ($PackageRelative) {
            $reason = Test-EccoKitPackagePath -Path $path
        } elseif ($path -ceq 'VENDOR_MANIFEST.json') {
            $reason = $null
        } elseif ($path.StartsWith($script:EccoKitSumsPackagePrefix, [System.StringComparison]::Ordinal)) {
            $reason = Test-EccoKitPackagePath -Path $path.Substring($script:EccoKitSumsPackagePrefix.Length)
        } else {
            $reason = "outside $($script:EccoKitSumsPackagePrefix) (paths are compared case-sensitively)"
        }
        if ($reason) {
            throw "$Label line $n ($path): refused - $reason."
        }
        if (-not $seen.Add($path)) {
            throw "$Label line $n ($path): a duplicate path."
        }
        if (-not $seenCase.Add($path)) {
            throw "$Label line $n ($path): collides with another path when letter case is ignored."
        }
        $entries.Add([pscustomobject]@{ Sha256 = $digest; Path = $path })
    }
    return , $entries.ToArray()
}

function Get-EccoLocalTree {
    # Every file and folder under a local root (relative, '/' separators). A
    # reparse point (junction or symlink) anywhere is refused and never
    # followed: the walk is done one folder at a time.
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $files = New-Object System.Collections.Generic.List[string]
    $dirs = New-Object System.Collections.Generic.List[string]
    $stack = New-Object System.Collections.Stack
    $stack.Push(@('', $Root))
    while ($stack.Count -gt 0) {
        $pair = $stack.Pop()
        foreach ($item in @(Get-ChildItem -LiteralPath $pair[1] -Force -ErrorAction Stop)) {
            $rel = if ($pair[0]) { $pair[0] + '/' + $item.Name } else { $item.Name }
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "the kit holds a reparse point (a junction or symlink): $rel"
            }
            if ($item.PSIsContainer) {
                $dirs.Add($rel)
                $stack.Push(@($rel, $item.FullName))
            } else {
                $files.Add($rel)
            }
        }
    }
    return [pscustomobject]@{ Files = (ConvertTo-EccoOrdinalSorted -Items $files.ToArray()); Dirs = (ConvertTo-EccoOrdinalSorted -Items $dirs.ToArray()) }
}

function Read-EccoStrictUtf8 {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        throw "$Label starts with a byte-order mark."
    }
    try {
        return (New-Object System.Text.UTF8Encoding($false, $true)).GetString($Bytes)
    }
    catch {
        throw "$Label is not valid UTF-8."
    }
}

function Test-EccoKitManifest {
    <#
        Verifies an Intelligence kit directory locally, before any ssh call
        (PR-5 design, "Kit verification"):
          - the sha256 of SHA256SUMS equals -ExpectedSumsSha256 (recorded
            offline from the build and the L3 run);
          - SHA256SUMS parses strictly (ConvertFrom-EccoSumsText);
          - the directory holds exactly SHA256SUMS plus the listed files and
            their folders: nothing extra, nothing missing, no reparse point;
          - every listed file has its listed hash;
          - the two VENDOR_MANIFEST.json copies are byte-identical, with the
            schema, the package and a git_sha of 7-40 lower-case hex digits;
          - manifest.json names the domain ecco_intelligence.
        The allowlist is the returned PackageFiles (package-relative path ->
        sha256) and PackageDirs: no remote write ever names anything else.
        Throws on the first refusal.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Kit,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ExpectedSumsSha256
    )

    if ($ExpectedSumsSha256 -cnotmatch '^[0-9a-f]{64}\z') {
        throw '-ExpectedSumsSha256 must be 64 lower-case hex digits (the sha256 of the kit''s SHA256SUMS, recorded offline).'
    }
    if (-not (Test-Path -LiteralPath $Kit -PathType Container)) {
        throw "The kit $Kit is not a folder."
    }
    $kitItem = Get-Item -LiteralPath $Kit -Force
    if (($kitItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "The kit folder $Kit is a reparse point (a junction or symlink)."
    }
    $kitRoot = $kitItem.FullName
    $sumsPath = Join-Path $kitRoot 'SHA256SUMS'
    if (-not (Test-Path -LiteralPath $sumsPath -PathType Leaf)) {
        throw 'The kit has no SHA256SUMS file.'
    }
    $sumsBytes = [System.IO.File]::ReadAllBytes($sumsPath)
    $sumsSha = Get-EccoBytesSha256 -Bytes $sumsBytes
    if ($sumsSha -cne $ExpectedSumsSha256) {
        throw "The kit's SHA256SUMS has sha256 $sumsSha, not the expected $ExpectedSumsSha256."
    }
    $entries = ConvertFrom-EccoSumsText -Bytes $sumsBytes -Label 'SHA256SUMS'

    $listed = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::Ordinal)
    foreach ($e in $entries) {
        $listed[$e.Path] = $e.Sha256
    }
    foreach ($required in @('VENDOR_MANIFEST.json', ($script:EccoKitSumsPackagePrefix + 'VENDOR_MANIFEST.json'), ($script:EccoKitSumsPackagePrefix + 'manifest.json'))) {
        if (-not $listed.ContainsKey($required)) {
            throw "The kit's SHA256SUMS does not list $required."
        }
    }

    $tree = Get-EccoLocalTree -Root $kitRoot
    $expectedFiles = ConvertTo-EccoOrdinalSorted -Items (@($listed.Keys) + @('SHA256SUMS'))
    $expectedDirs = Get-EccoParentDirs -Paths @($listed.Keys)
    $extra = @($tree.Files | Where-Object { [Array]::BinarySearch($expectedFiles, $_, [System.StringComparer]::Ordinal) -lt 0 })
    $missing = @($expectedFiles | Where-Object { [Array]::BinarySearch($tree.Files, $_, [System.StringComparer]::Ordinal) -lt 0 })
    $extraDirs = @($tree.Dirs | Where-Object { [Array]::BinarySearch($expectedDirs, $_, [System.StringComparer]::Ordinal) -lt 0 })
    if ($extra.Count -gt 0) {
        throw "The kit holds a file SHA256SUMS does not list: $($extra[0])"
    }
    if ($missing.Count -gt 0) {
        throw "The kit is missing a file SHA256SUMS lists: $($missing[0])"
    }
    if ($extraDirs.Count -gt 0) {
        throw "The kit holds a folder no listed file needs: $($extraDirs[0])"
    }

    $bytes = [long]0
    foreach ($e in $entries) {
        $local = Join-Path $kitRoot ($e.Path.Replace('/', '\'))
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $local).Hash.ToLowerInvariant()
        if ($actual -cne $e.Sha256) {
            throw "The kit file $($e.Path) does not match its SHA256SUMS line (listed $($e.Sha256.Substring(0, 12)), actual $($actual.Substring(0, 12)))."
        }
        $bytes += (Get-Item -LiteralPath $local -Force).Length
    }

    $rootManifest = [System.IO.File]::ReadAllBytes((Join-Path $kitRoot 'VENDOR_MANIFEST.json'))
    $packageManifest = [System.IO.File]::ReadAllBytes((Join-Path $kitRoot 'custom_components\ecco_intelligence\VENDOR_MANIFEST.json'))
    if ((Get-EccoBytesSha256 -Bytes $rootManifest) -cne (Get-EccoBytesSha256 -Bytes $packageManifest)) {
        throw 'The two VENDOR_MANIFEST.json copies of the kit differ.'
    }
    try {
        $manifest = (Read-EccoStrictUtf8 -Bytes $rootManifest -Label 'VENDOR_MANIFEST.json') | ConvertFrom-Json
    }
    catch {
        throw "VENDOR_MANIFEST.json cannot be read as JSON: $($_.Exception.Message)"
    }
    $schema = if ($manifest.PSObject.Properties['schema']) { [string]$manifest.schema } else { '' }
    $package = if ($manifest.PSObject.Properties['package']) { [string]$manifest.package } else { '' }
    if ($schema -cne $script:EccoKitManifestSchema -or $package -cne $script:EccoKitSumsPackagePrefix.TrimEnd('/')) {
        throw "VENDOR_MANIFEST.json is not an $($script:EccoKitManifestSchema) manifest for $($script:EccoKitSumsPackagePrefix.TrimEnd('/'))."
    }
    $gitSha = if ($manifest.PSObject.Properties['git_sha'] -and $null -ne $manifest.git_sha) { [string]$manifest.git_sha } else { $null }
    if ($null -eq $gitSha -or $gitSha -cnotmatch '^[0-9a-f]{7,40}\z') {
        throw 'VENDOR_MANIFEST.json has no git_sha (7-40 lower-case hex digits): build the kit with --git-sha.'
    }
    if (-not $manifest.PSObject.Properties['modules']) {
        throw 'VENDOR_MANIFEST.json has no modules list.'
    }

    $haManifestBytes = [System.IO.File]::ReadAllBytes((Join-Path $kitRoot 'custom_components\ecco_intelligence\manifest.json'))
    try {
        $haManifest = (Read-EccoStrictUtf8 -Bytes $haManifestBytes -Label 'manifest.json') | ConvertFrom-Json
    }
    catch {
        throw "manifest.json cannot be read as JSON: $($_.Exception.Message)"
    }
    $domain = if ($haManifest.PSObject.Properties['domain']) { [string]$haManifest.domain } else { '' }
    if ($domain -cne $script:EccoKitDomain) {
        throw "manifest.json names the domain '$domain', not '$($script:EccoKitDomain)'."
    }
    $version = if ($haManifest.PSObject.Properties['version']) { [string]$haManifest.version } else { '' }

    $packageFiles = New-EccoFileMap
    foreach ($e in $entries) {
        if ($e.Path.StartsWith($script:EccoKitSumsPackagePrefix, [System.StringComparison]::Ordinal)) {
            $packageFiles[$e.Path.Substring($script:EccoKitSumsPackagePrefix.Length)] = $e.Sha256
        }
    }
    return [pscustomobject]@{
        KitRoot      = $kitRoot
        PackageRoot  = (Join-Path $kitRoot 'custom_components\ecco_intelligence')
        SumsSha256   = $sumsSha
        SumsBytes    = $sumsBytes
        Entries      = $entries
        PackageFiles = $packageFiles
        PackageDirs  = (Get-EccoParentDirs -Paths @($packageFiles.Keys))
        Bytes        = $bytes
        GitSha       = $gitSha
        Version      = $version
        Manifest     = $manifest
    }
}

function ConvertTo-EccoCanonicalJson {
    # A stable text form of a parsed JSON value, for equality checks.
    param(
        [AllowNull()]
        [object]$Value
    )

    return ($Value | ConvertTo-Json -Depth 50 -Compress)
}

function Test-EccoKitEquivalence {
    <#
        Kit equivalence (amendment A3): the kit to install is equivalent to the
        L3-tested reference kit when every SHA256SUMS line is identical except
        the two VENDOR_MANIFEST.json lines, and the two manifests are equal
        except git_sha (so their modules lists match). The reference needs
        only its SHA256SUMS (whose sha256 must equal -ReferenceSumsSha256, the
        value recorded from the L3 run) and its VENDOR_MANIFEST.json (which
        must match its own SHA256SUMS line). Returns IDENTICAL (the same
        SHA256SUMS bytes) or EQUIVALENT; throws otherwise. Local only.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [object]$KitInfo,

        [Parameter(Mandatory = $true)]
        [string]$ReferenceKit,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ReferenceSumsSha256
    )

    if ($ReferenceSumsSha256 -cnotmatch '^[0-9a-f]{64}\z') {
        throw '-ReferenceSumsSha256 must be 64 lower-case hex digits (the sha256 of the L3-tested kit''s SHA256SUMS).'
    }
    $refSumsPath = Join-Path $ReferenceKit 'SHA256SUMS'
    $refManifestPath = Join-Path $ReferenceKit 'VENDOR_MANIFEST.json'
    foreach ($p in @($refSumsPath, $refManifestPath)) {
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
            throw "The reference kit has no $([System.IO.Path]::GetFileName($p))."
        }
        if (((Get-Item -LiteralPath $p -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "The reference kit's $([System.IO.Path]::GetFileName($p)) is a reparse point."
        }
    }
    $refSumsBytes = [System.IO.File]::ReadAllBytes($refSumsPath)
    $refSumsSha = Get-EccoBytesSha256 -Bytes $refSumsBytes
    if ($refSumsSha -cne $ReferenceSumsSha256) {
        throw "The reference kit's SHA256SUMS has sha256 $refSumsSha, not the recorded $ReferenceSumsSha256."
    }
    $refEntries = ConvertFrom-EccoSumsText -Bytes $refSumsBytes -Label 'the reference SHA256SUMS'
    $manifestPaths = @('VENDOR_MANIFEST.json', ($script:EccoKitSumsPackagePrefix + 'VENDOR_MANIFEST.json'))

    $refMap = New-EccoFileMap
    foreach ($e in $refEntries) {
        $refMap[$e.Path] = $e.Sha256
    }
    foreach ($m in $manifestPaths) {
        if (-not $refMap.ContainsKey($m)) {
            throw "The reference SHA256SUMS does not list $m."
        }
    }
    if ($refMap[$manifestPaths[0]] -cne $refMap[$manifestPaths[1]]) {
        throw 'The reference SHA256SUMS lists two different VENDOR_MANIFEST.json copies.'
    }
    $refManifestBytes = [System.IO.File]::ReadAllBytes($refManifestPath)
    if ((Get-EccoBytesSha256 -Bytes $refManifestBytes) -cne $refMap[$manifestPaths[0]]) {
        throw 'The reference VENDOR_MANIFEST.json does not match its SHA256SUMS line.'
    }

    if ((Get-EccoBytesSha256 -Bytes $KitInfo.SumsBytes) -ceq $refSumsSha) {
        return [pscustomobject]@{ Result = 'IDENTICAL'; Line = "Equivalence : IDENTICAL to the L3-tested kit (SHA256SUMS $($refSumsSha.Substring(0, 12)))" }
    }

    $kitMap = New-EccoFileMap
    foreach ($e in $KitInfo.Entries) {
        $kitMap[$e.Path] = $e.Sha256
    }
    foreach ($path in @($kitMap.Keys) + @($refMap.Keys)) {
        if ($manifestPaths -ccontains $path) {
            continue
        }
        if (-not $kitMap.ContainsKey($path)) {
            throw "NOT EQUIVALENT to the L3-tested kit: the kit lacks $path."
        }
        if (-not $refMap.ContainsKey($path)) {
            throw "NOT EQUIVALENT to the L3-tested kit: the kit adds $path."
        }
        if ($kitMap[$path] -cne $refMap[$path]) {
            throw "NOT EQUIVALENT to the L3-tested kit: $path differs."
        }
    }

    try {
        $refManifest = (Read-EccoStrictUtf8 -Bytes $refManifestBytes -Label 'the reference VENDOR_MANIFEST.json') | ConvertFrom-Json
    }
    catch {
        throw "The reference VENDOR_MANIFEST.json cannot be read as JSON: $($_.Exception.Message)"
    }
    if (-not $refManifest.PSObject.Properties['modules']) {
        throw 'NOT EQUIVALENT to the L3-tested kit: the reference manifest has no modules list.'
    }
    if ((ConvertTo-EccoCanonicalJson -Value $KitInfo.Manifest.modules) -cne (ConvertTo-EccoCanonicalJson -Value $refManifest.modules)) {
        throw 'NOT EQUIVALENT to the L3-tested kit: the manifests'' modules lists differ.'
    }
    $a = $KitInfo.Manifest.PSObject.Copy()
    $b = $refManifest.PSObject.Copy()
    $a.git_sha = $null
    $b.git_sha = $null
    if ((ConvertTo-EccoCanonicalJson -Value $a) -cne (ConvertTo-EccoCanonicalJson -Value $b)) {
        throw 'NOT EQUIVALENT to the L3-tested kit: the manifests differ in more than git_sha.'
    }
    $refGit = if ($refManifest.PSObject.Properties['git_sha']) { [string]$refManifest.git_sha } else { '' }
    return [pscustomobject]@{ Result = 'EQUIVALENT'; Line = "Equivalence : EQUIVALENT to the L3-tested kit (SHA256SUMS $($refSumsSha.Substring(0, 12))): only git_sha differs ($refGit -> $($KitInfo.GitSha))" }
}

function Assert-EccoKitGitSha {
    # The kit's git_sha must be this checkout's HEAD, exactly (40 hex digits):
    # the kit was built from the committed tree the route runs from.
    param(
        [Parameter(Mandatory = $true)]
        [object]$KitInfo,

        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $head = ((@(& git -C $RepoRoot rev-parse HEAD 2>&1) -join '').Trim())
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($code -ne 0 -or $head -cnotmatch '^[0-9a-f]{40}\z') {
        throw 'The HEAD of this checkout could not be read.'
    }
    if ($KitInfo.GitSha -cne $head) {
        throw "The kit was built from $($KitInfo.GitSha), not from this checkout's HEAD $head (build it with --git-sha (git rev-parse HEAD) from this commit)."
    }
    return $head
}

function Invoke-EccoKitRebuildCheck {
    <#
        Rebuilds the kit from this checkout with the frozen CLI
        (python tools/build_ha_integration.py --out <new temp folder>
        --git-sha <sha>) and requires SHA256SUMS bytes identical to the kit's.
        A checkout without the build tool cannot prove the kit: BLOCKED. The
        temporary folder is deleted afterwards (it holds only the rebuild).
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$Python,

        [Parameter(Mandatory = $true)]
        [object]$KitInfo
    )

    $builder = Join-Path $RepoRoot 'tools\build_ha_integration.py'
    if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) {
        throw 'The frozen build tool tools/build_ha_integration.py is not in this checkout: the kit cannot be rebuilt and compared. Run the route from a checkout that holds the Intelligence sources the kit was built from.'
    }
    if ($Python.Contains('"') -or $Python.EndsWith('\')) {
        throw '-Python cannot hold a double quote or end in a backslash.'
    }
    $out = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-kit-rebuild-' + [guid]::NewGuid().ToString('N'))
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $buildOutput = @(& $Python -I -B -X utf8 $builder --out $out --git-sha $KitInfo.GitSha 2>&1 | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($code -ne 0) {
            throw "The rebuild failed (exit code $code): $((@($buildOutput) | Select-Object -Last 2) -join ' ')"
        }
        $rebuilt = Join-Path $out 'SHA256SUMS'
        if (-not (Test-Path -LiteralPath $rebuilt -PathType Leaf)) {
            throw 'The rebuild wrote no SHA256SUMS.'
        }
        $rebuiltSha = Get-EccoBytesSha256 -Bytes ([System.IO.File]::ReadAllBytes($rebuilt))
        if ($rebuiltSha -cne $KitInfo.SumsSha256) {
            throw "A rebuild of this checkout gives SHA256SUMS $($rebuiltSha.Substring(0, 12)), not the kit's $($KitInfo.SumsSha256.Substring(0, 12)): the kit is not this tree."
        }
        return "rebuild of this checkout: identical SHA256SUMS"
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Remove-Item -LiteralPath $out -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --- read-only host probes ------------------------------------------------

function Test-EccoRemoteSafePath {
    # An absolute path under /config whose segments are safe inside single
    # quotes: [A-Za-z0-9_.][A-Za-z0-9_.-]*, never '.' or '..'.
    param(
        [AllowEmptyString()]
        [string]$Path
    )

    if ($Path -cnotmatch '^/config(/[A-Za-z0-9_.][A-Za-z0-9_.-]*)*\z') {
        return $false
    }
    foreach ($s in $Path.Split('/')) {
        if ($s -eq '.' -or $s -eq '..') {
            return $false
        }
    }
    return $true
}

function Assert-EccoRemoteSafePath {
    param(
        [AllowEmptyString()]
        [string]$Path
    )

    if (-not (Test-EccoRemoteSafePath -Path $Path)) {
        throw "Refusing the remote path '$Path': an absolute path under /config with plain segments is required."
    }
}

function Assert-EccoBelowConfigRoot {
    # /config itself is never symlink-tested per segment (amendment A26: it
    # is a symlink on the SSH add-on); it is resolved by
    # Get-EccoRemoteConfigRoot. Only the segments below it are tested one by
    # one. A programming error, refused before anything is sent.
    param(
        [AllowEmptyString()]
        [string]$Path
    )

    if ($Path -ceq $script:EccoConfigRoot) {
        throw "Refusing to test $($script:EccoConfigRoot) itself per segment: it is resolved once by Get-EccoRemoteConfigRoot (amendment A26), and only the segments below it are symlink-tested."
    }
}

# --- the /config root (amendment A26) ----------------------------------------

function Get-EccoConfigRootProbeCommand {
    <#
        The read-only probe of /config (amendment A26), one remote command
        of single-quoted words (pure string logic). It prints 'root link',
        'root dir', 'root other' or 'root absent' ([ -L ] first, so a
        symlink is never reported as the folder it points to), then
        'resolved <physical path>' only when cd -P can enter /config - a
        real folder, or a symlink (chain) ending in an existing folder -
        and finally ECCO_ROOT_END. A dangling symlink, one to a file and a
        symlink loop cannot be entered, so they print no resolved line.
        cd -P and pwd -P are POSIX and BusyBox ash built-ins; readlink -f is
        not used (it also resolves a dangling symlink).
    #>

    $c = $script:EccoConfigRoot
    return "if [ -L '$c' ]; then echo 'root link'; elif [ -d '$c' ]; then echo 'root dir'; elif [ -e '$c' ]; then echo 'root other'; else echo 'root absent'; fi; ( cd -P '$c' && printf 'resolved ' && pwd -P ); echo ECCO_ROOT_END"
}

function ConvertFrom-EccoConfigRootProbe {
    <#
        Reads the /config probe's output (pure logic). /config is accepted
        only as a real folder (its physical path is /config) or as a symlink
        that resolved to an existing real folder whose physical path is a
        plain absolute path; anything else is refused. Returns Kind (link,
        dir, other, absent or unknown), Resolved (the physical path, $null
        when refused), Problem ($null when accepted, else why not) and Line
        (the "Config root" line every route prints).
    #>
    param(
        [AllowEmptyCollection()]
        [AllowNull()]
        [string[]]$Output = @()
    )

    $c = $script:EccoConfigRoot
    $kinds = New-Object System.Collections.Generic.List[string]
    $resolvedLines = New-Object System.Collections.Generic.List[string]
    $ended = 0
    foreach ($line in @($Output)) {
        $s = ([string]$line).TrimEnd("`r", "`n")
        if ($s -cmatch '^root (link|dir|other|absent)\z') {
            $kinds.Add($Matches[1])
        } elseif ($s.StartsWith('resolved ', [System.StringComparison]::Ordinal)) {
            $resolvedLines.Add($s.Substring(9))
        } elseif ($s -ceq 'ECCO_ROOT_END') {
            $ended++
        }
    }
    $kind = if ($kinds.Count -eq 1) { $kinds[0] } else { 'unknown' }
    $resolved = $null
    $problem = $null
    if ($ended -ne 1 -or $kinds.Count -ne 1 -or $resolvedLines.Count -gt 1) {
        $problem = "the probe of $c returned an incomplete or unexpected answer"
    } elseif ($kind -eq 'absent') {
        $problem = "$c does not exist on the host"
    } elseif ($kind -eq 'other') {
        $problem = "$c is neither a folder nor a symlink (a file or a special file)"
    } elseif ($resolvedLines.Count -eq 0) {
        $problem = if ($kind -eq 'link') {
            "$c is a symlink that does not resolve to an existing folder (dangling, pointing to a file or another non-folder, or a symlink loop)"
        } else {
            "$c is a folder the ssh user cannot enter"
        }
    } else {
        $candidate = $resolvedLines[0]
        if ($candidate.Length -gt $script:EccoResolvedRootMaxLength -or $candidate -cnotmatch $script:EccoResolvedRootPattern) {
            $problem = "$c resolves to a path that is not a plain absolute path of [A-Za-z0-9_.-] segments"
        } elseif ($kind -eq 'dir' -and $candidate -cne $c) {
            $problem = "$c is a folder whose physical path is $candidate, not ${c}: not understood"
        } else {
            $resolved = $candidate
        }
    }
    $line = if ($problem) {
        "Config root : REFUSED - $problem"
    } elseif ($kind -eq 'link') {
        "Config root : $c -> $resolved (a symlink to a real folder, resolved with cd -P; checked unchanged before the first write)"
    } else {
        "Config root : $c (a real folder; checked unchanged before the first write)"
    }
    return [pscustomobject]@{ Kind = $kind; Resolved = $resolved; Problem = $problem; Line = $line }
}

function Get-EccoRemoteConfigRoot {
    <#
        Read-only (amendment A26): runs the /config probe right after the ssh
        probe, before anything else is read under /config, and returns the
        accepted root (Kind, Resolved, Line). Throws <Name>: BLOCKED (nothing
        written) when /config is not a real folder or a symlink that resolves
        to an existing real folder, or when the probe fails.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (Get-EccoConfigRootProbeCommand) -Capture
    if ($r.ExitCode -ne 0) {
        throw (Format-EccoKitBlockedMessage -Name $Name -Reason "$($script:EccoConfigRoot) could not be inspected (ssh exit code $($r.ExitCode)).")
    }
    $root = ConvertFrom-EccoConfigRootProbe -Output @($r.Output)
    if ($root.Problem) {
        throw (Format-EccoKitBlockedMessage -Name $Name -Reason "$($root.Problem): $($script:EccoConfigRoot) must be a real folder or a symlink that resolves to an existing real folder.")
    }
    return $root
}

function Assert-EccoRemoteConfigRootUnchanged {
    <#
        Read-only, immediately before a route's first write (amendment A26):
        /config must still resolve to -ConfigRoot, the root the read-only
        checks resolved and printed. Throws <Name>: BLOCKED (nothing written)
        otherwise. The first write command repeats the test itself
        (Get-EccoConfigRootGuardCommand), so no gap is left in between.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$ConfigRoot,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (Get-EccoConfigRootProbeCommand) -Capture
    $now = if ($r.ExitCode -eq 0) { ConvertFrom-EccoConfigRootProbe -Output @($r.Output) } else { $null }
    if ($null -eq $now -or $now.Problem -or $now.Resolved -cne $ConfigRoot) {
        $nowText = if ($null -eq $now) { "unknown (ssh exit code $($r.ExitCode))" } elseif ($now.Problem) { "refused ($($now.Problem))" } else { $now.Resolved }
        throw (Format-EccoKitBlockedMessage -Name $Name -Reason "the $($script:EccoConfigRoot) root changed between the read-only checks and the first write: it resolved to $ConfigRoot, now $nowText.")
    }
}

function Get-EccoConfigRootGuardCommand {
    <#
        The test every folder-creating command starts with (amendment A26;
        pure string logic): /config must still resolve (cd -P, pwd -P) to
        exactly -ConfigRoot. One pipeline of single-quoted words; grep -Fqx
        compares the whole line literally, and fails on no output (a /config
        that no longer resolves).
    #>
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ConfigRoot
    )

    if ($ConfigRoot.Length -gt $script:EccoResolvedRootMaxLength -or $ConfigRoot -cnotmatch $script:EccoResolvedRootPattern) {
        throw "Refusing the /config root '$ConfigRoot': a plain absolute path (the resolved root) is required."
    }
    return "( cd -P '$($script:EccoConfigRoot)' && pwd -P ) | grep -Fqx '$ConfigRoot'"
}

function Get-EccoSafeMkdirCommand {
    <#
        One remote command that creates folders without a recursive mkdir
        (amendment A15): it first checks that /config still resolves to
        -ConfigRoot (amendment A26), then every -MustExist path must be a
        real folder (never a symlink); each -MayCreate path is created when
        absent and must then be a real folder; each -MustCreate path is
        created and must not exist before (a used stamp is refused). Pass
        parents before children: the checks run in order, so no mkdir ever
        runs below a symlinked segment. /config itself is never one of the
        paths. The command ends with ECCO_MKDIR_OK only when every step held.
    #>
    param(
        # The resolved /config root (Get-EccoRemoteConfigRoot).
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ConfigRoot,

        [string[]]$MustExist = @(),
        [string[]]$MayCreate = @(),
        [string[]]$MustCreate = @(),

        # Leave the ECCO_MKDIR_OK marker off (the caller chains its own step).
        [switch]$NoMarker
    )

    $parts = New-Object System.Collections.Generic.List[string]
    $parts.Add((Get-EccoConfigRootGuardCommand -ConfigRoot $ConfigRoot))
    foreach ($p in @($MustExist)) {
        Assert-EccoRemoteSafePath -Path $p
        Assert-EccoBelowConfigRoot -Path $p
        $parts.Add("[ -d '$p' ] && [ ! -L '$p' ]")
    }
    foreach ($p in @($MayCreate)) {
        Assert-EccoRemoteSafePath -Path $p
        Assert-EccoBelowConfigRoot -Path $p
        $parts.Add("[ ! -L '$p' ] && { [ -d '$p' ] || mkdir '$p'; } && [ ! -L '$p' ]")
    }
    foreach ($p in @($MustCreate)) {
        Assert-EccoRemoteSafePath -Path $p
        Assert-EccoBelowConfigRoot -Path $p
        $parts.Add("[ ! -e '$p' ] && [ ! -L '$p' ] && mkdir '$p' && [ ! -L '$p' ]")
    }
    if ($NoMarker) {
        return ($parts -join ' && ')
    }
    return (($parts -join ' && ') + ' && echo ECCO_MKDIR_OK')
}

function Get-EccoRemotePathStates {
    <#
        Read-only: the state of each path in one ssh command - link (a
        symlink, dangling or not), dir (a searchable folder), file (a regular
        file), other, or absent. Every segment of a path the kit route writes
        below is listed by the caller, so a symlinked segment anywhere below
        /config is seen (amendment A15). /config itself is never asked here:
        it is a symlink on the SSH add-on and is resolved once by
        Get-EccoRemoteConfigRoot (amendment A26). Returns a case-sensitive
        map.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string[]]$Paths
    )

    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($p in $Paths) {
        Assert-EccoRemoteSafePath -Path $p
        Assert-EccoBelowConfigRoot -Path $p
        $parts.Add("if [ -L '$p' ]; then echo 'link $p'; elif [ -d '$p' ]; then if [ -x '$p' ]; then echo 'dir $p'; else echo 'other $p'; fi; elif [ -f '$p' ]; then echo 'file $p'; elif [ -e '$p' ]; then echo 'other $p'; else echo 'absent $p'; fi")
    }
    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (($parts -join '; ') + '; echo ECCO_STATES_END') -Capture
    if ($r.ExitCode -ne 0) {
        throw "The host paths could not be inspected (ssh exit code $($r.ExitCode))."
    }
    $states = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::Ordinal)
    $ended = $false
    foreach ($line in @($r.Output)) {
        $s = ([string]$line).TrimEnd()
        if ($s -ceq 'ECCO_STATES_END') {
            $ended = $true
        } elseif ($s -cmatch '^(link|dir|file|other|absent) (/\S*)\z') {
            $states[$Matches[2]] = $Matches[1]
        }
    }
    foreach ($p in $Paths) {
        if (-not $ended -or -not $states.ContainsKey($p)) {
            throw 'The host path inspection returned an incomplete answer.'
        }
    }
    return , $states
}

function Test-EccoRemoteRelativeName {
    # A relative path reported by the host is safe to name in a later
    # single-quoted command: segments [A-Za-z0-9_][A-Za-z0-9_.-]* only.
    param(
        [AllowEmptyString()]
        [string]$Path
    )

    foreach ($s in $Path.Split('/')) {
        if ($s -cnotmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]*\z') {
            return $false
        }
    }
    return $true
}

function Get-EccoKitRemoteTree {
    <#
        Read-only: lists a folder on the host (find -type d, -type f, and
        everything else, without following symlinks) and hashes its regular
        files outside __pycache__ (one sha256sum command). Returns State
        (absent, link, other or dir), Dirs and Files (package-relative,
        __pycache__ left out), Pycache (the __pycache__ folders and their
        .pyc files Home Assistant may have written) and Others (anything not
        a folder or a regular file: refused by every caller). Throws when a
        name is not safe to quote or the answer is incomplete.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Root,

        [switch]$NoHashes
    )

    Assert-EccoRemoteSafePath -Path $Root
    $q = "'$Root'"
    $command = "if [ -L $q ]; then echo ECCO_TREE_LINK; elif [ -d $q ]; then echo ECCO_TREE_D && find $q -type d && echo ECCO_TREE_F && find $q -type f && echo ECCO_TREE_O && find $q ! -type d ! -type f && echo ECCO_TREE_END; elif [ -e $q ]; then echo ECCO_TREE_OTHER; else echo ECCO_TREE_ABSENT; fi"
    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command $command -Capture
    if ($r.ExitCode -ne 0) {
        throw "$Root could not be listed on the host (ssh exit code $($r.ExitCode))."
    }
    $lines = @($r.Output | ForEach-Object { ([string]$_).TrimEnd() } | Where-Object { $_ -ne '' })
    $empty = [pscustomobject]@{ State = 'absent'; Root = $Root; Dirs = [string[]]@(); Files = (New-EccoFileMap); Pycache = [string[]]@(); Others = [string[]]@() }
    foreach ($word in @('ABSENT', 'LINK', 'OTHER')) {
        if ($lines.Count -eq 1 -and $lines[0] -ceq "ECCO_TREE_$word") {
            $empty.State = $word.ToLowerInvariant()
            return $empty
        }
    }
    $section = ''
    $dirs = New-Object System.Collections.Generic.List[string]
    $files = New-Object System.Collections.Generic.List[string]
    $others = New-Object System.Collections.Generic.List[string]
    $ended = $false
    foreach ($line in $lines) {
        if ($line -ceq 'ECCO_TREE_D') { $section = 'D'; continue }
        if ($line -ceq 'ECCO_TREE_F' -and $section -eq 'D') { $section = 'F'; continue }
        if ($line -ceq 'ECCO_TREE_O' -and $section -eq 'F') { $section = 'O'; continue }
        if ($line -ceq 'ECCO_TREE_END' -and $section -eq 'O') { $ended = $true; $section = 'X'; continue }
        if ($section -eq '' -or $section -eq 'X') {
            throw "The listing of $Root holds an unexpected line."
        }
        if ($line -ceq $Root) {
            if ($section -eq 'D') { continue }
            throw "The listing of $Root is not understood."
        }
        if (-not $line.StartsWith($Root + '/', [System.StringComparison]::Ordinal)) {
            throw "The listing of $Root names a path outside it (or a name with a line break)."
        }
        $rel = $line.Substring($Root.Length + 1)
        if (-not (Test-EccoRemoteRelativeName -Path $rel)) {
            throw "$Root holds a name that is not safe to handle (only [A-Za-z0-9_.-], not starting with a dot): refused."
        }
        switch ($section) {
            'D' { $dirs.Add($rel) }
            'F' { $files.Add($rel) }
            'O' { $others.Add($rel) }
        }
    }
    if (-not $ended) {
        throw "The listing of $Root is incomplete."
    }

    $pycache = New-Object System.Collections.Generic.List[string]
    $plainDirs = New-Object System.Collections.Generic.List[string]
    foreach ($d in $dirs) {
        $segs = $d.Split('/')
        if ($segs[-1] -ceq '__pycache__' -and @($segs | Where-Object { $_ -ceq '__pycache__' }).Count -eq 1) {
            $pycache.Add($d)
        } else {
            $plainDirs.Add($d)
        }
    }
    $plainFiles = New-Object System.Collections.Generic.List[string]
    foreach ($f in $files) {
        $segs = $f.Split('/')
        if ($segs.Count -ge 2 -and $segs[-2] -ceq '__pycache__' -and $segs[-1].EndsWith('.pyc', [System.StringComparison]::Ordinal) -and
            @($segs | Where-Object { $_ -ceq '__pycache__' }).Count -eq 1) {
            $pycache.Add($f)
        } else {
            $plainFiles.Add($f)
        }
    }

    # sha256sum prints '<hash>  <path>', or '<hash> *<path>' in binary mode (the GNU format's mode marker).
    $map = New-EccoFileMap
    if (-not $NoHashes -and $plainFiles.Count -gt 0) {
        $quoted = @($plainFiles | ForEach-Object { "'$Root/$_'" })
        $h = Invoke-EccoRemoteCommand -SshHost $SshHost -Command ('sha256sum ' + ($quoted -join ' ') + ' && echo ECCO_HASH_END') -Capture
        if ($h.ExitCode -ne 0) {
            throw "The files under $Root could not be hashed on the host (ssh exit code $($h.ExitCode))."
        }
        $hashEnded = $false
        foreach ($line in @($h.Output)) {
            $s = ([string]$line).TrimEnd()
            if ($s -ceq 'ECCO_HASH_END') {
                $hashEnded = $true
            } elseif ($s -cmatch '^([0-9a-f]{64}) [ *](/\S+)\z' -and $Matches[2].StartsWith($Root + '/', [System.StringComparison]::Ordinal)) {
                $map[$Matches[2].Substring($Root.Length + 1)] = $Matches[1]
            }
        }
        foreach ($f in $plainFiles) {
            if (-not $hashEnded -or -not $map.ContainsKey($f)) {
                throw "The hashes of the files under $Root are incomplete."
            }
        }
    } elseif ($NoHashes) {
        foreach ($f in $plainFiles) {
            $map[$f] = ''
        }
    }
    return [pscustomobject]@{
        State   = 'dir'
        Root    = $Root
        Dirs    = (ConvertTo-EccoOrdinalSorted -Items $plainDirs.ToArray())
        Files   = $map
        Pycache = (ConvertTo-EccoOrdinalSorted -Items $pycache.ToArray())
        Others  = (ConvertTo-EccoOrdinalSorted -Items $others.ToArray())
    }
}

function Compare-EccoKitTree {
    # $null when a remote tree (with __pycache__ left out) holds exactly the
    # expected files with their hashes and exactly their folders, and nothing
    # that is not a folder or a regular file; the first difference otherwise.
    param(
        [Parameter(Mandatory = $true)]
        [object]$Tree,

        [Parameter(Mandatory = $true)]
        [object]$ExpectedFiles
    )

    if ($Tree.State -ne 'dir') {
        return "$($Tree.Root) is $($Tree.State) on the host"
    }
    if (@($Tree.Others).Count -gt 0) {
        return "$($Tree.Root) holds something that is not a folder or a regular file: $(@($Tree.Others)[0])"
    }
    $expectedDirs = Get-EccoParentDirs -Paths @($ExpectedFiles.Keys)
    foreach ($d in @($Tree.Dirs)) {
        if ([Array]::BinarySearch($expectedDirs, $d, [System.StringComparer]::Ordinal) -lt 0) {
            return "$($Tree.Root) holds an unexpected folder: $d"
        }
    }
    foreach ($d in $expectedDirs) {
        if ([Array]::BinarySearch($Tree.Dirs, $d, [System.StringComparer]::Ordinal) -lt 0) {
            return "$($Tree.Root) lacks the folder: $d"
        }
    }
    foreach ($f in @($Tree.Files.Keys)) {
        if (-not $ExpectedFiles.ContainsKey($f)) {
            return "$($Tree.Root) holds an unexpected file: $f"
        }
    }
    foreach ($f in @($ExpectedFiles.Keys)) {
        if (-not $Tree.Files.ContainsKey($f)) {
            return "$($Tree.Root) lacks the file: $f"
        }
        if ($Tree.Files[$f] -cne $ExpectedFiles[$f]) {
            return "$($Tree.Root)/$f does not have the expected sha256"
        }
    }
    return $null
}

function Get-EccoProtectedSnapshot {
    <#
        Read-only: the sha256 of the Intelligence site file and the
        device:inode of its state folder (never their content). The kit route
        compares it before and after a write: neither may change. These two
        paths are named by no other kit-route command.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost
    )

    $s = $script:EccoSiteFilePath
    $t = $script:EccoSiteStatePath
    $command = "if [ -L '$s' ]; then echo 'site link'; elif [ -f '$s' ]; then printf 'site '; sha256sum '$s' | cut -d ' ' -f 1; elif [ -e '$s' ]; then echo 'site other'; else echo 'site absent'; fi; " +
        "if [ -L '$t' ]; then echo 'state link'; elif [ -d '$t' ]; then printf 'state '; stat -c '%d:%i' '$t'; elif [ -e '$t' ]; then echo 'state other'; else echo 'state absent'; fi; echo ECCO_SNAPSHOT_END"
    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command $command -Capture
    if ($r.ExitCode -ne 0) {
        throw "The protected site file and state folder could not be inspected (ssh exit code $($r.ExitCode))."
    }
    $site = @($r.Output | ForEach-Object { ([string]$_).TrimEnd() } | Where-Object { $_ -cmatch '^site (link|other|absent|[0-9a-f]{64})\z' })
    $state = @($r.Output | ForEach-Object { ([string]$_).TrimEnd() } | Where-Object { $_ -cmatch '^state (link|other|absent|[0-9]+:[0-9]+)\z' })
    $ended = @($r.Output | Where-Object { ([string]$_).TrimEnd() -ceq 'ECCO_SNAPSHOT_END' }).Count -eq 1
    if (-not $ended -or $site.Count -ne 1 -or $state.Count -ne 1) {
        throw 'The protected site file and state folder inspection returned an incomplete answer.'
    }
    return [pscustomobject]@{ Site = $site[0].Substring(5); State = $state[0].Substring(6); Text = "$($site[0]); $($state[0])" }
}

function Get-EccoConfigEntryCount {
    # Read-only: how many lines of Home Assistant's config-entry store (-Path,
    # named by the caller) name ecco_intelligence; only the count leaves the
    # host. -1 when unknown.
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Assert-EccoRemoteSafePath -Path $Path
    $f = $Path
    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "if [ -L '$f' ]; then echo ECCO_ENTRIES_LINK; elif [ -f '$f' ]; then grep -c 'ecco_intelligence' '$f' || true; echo ECCO_ENTRIES_END; else echo ECCO_ENTRIES_NOFILE; fi" -Capture
    if ($r.ExitCode -ne 0) {
        return -1
    }
    $lines = @($r.Output | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ -ne '' })
    if ($lines.Count -eq 2 -and $lines[1] -ceq 'ECCO_ENTRIES_END' -and $lines[0] -cmatch '^[0-9]{1,6}\z') {
        return [int]$lines[0]
    }
    return -1
}

function Get-EccoRemoteFsFacts {
    # Read-only: the device of custom_components and of ecco/ (one device, so
    # every rename is atomic) and the free space under /config in KiB.
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost
    )

    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "stat -c '%d %n' '/config/custom_components' '/config/ecco' && df -k '/config' && echo ECCO_FS_END" -Capture
    if ($r.ExitCode -ne 0) {
        throw "The file system facts could not be read (ssh exit code $($r.ExitCode))."
    }
    $devices = @{}
    $available = $null
    $ended = $false
    foreach ($line in @($r.Output)) {
        $s = ([string]$line).TrimEnd()
        if ($s -cmatch '^([0-9]+) (/config/custom_components|/config/ecco)\z') {
            $devices[$Matches[2]] = $Matches[1]
        } elseif ($s -cmatch '\s([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)%\s+\S') {
            $available = [long]$Matches[3]
        } elseif ($s -ceq 'ECCO_FS_END') {
            $ended = $true
        }
    }
    if (-not $ended -or $devices.Count -ne 2 -or $null -eq $available) {
        throw 'The file system facts (stat -c %d, df -k) were not understood.'
    }
    return [pscustomobject]@{
        SameDevice   = ($devices['/config/custom_components'] -ceq $devices['/config/ecco'])
        Device       = $devices['/config/ecco']
        AvailableKiB = $available
    }
}

function Get-EccoRemoteFileSha256 {
    # Read-only: the sha256 of one host file, or $null.
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Assert-EccoRemoteSafePath -Path $Path
    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "sha256sum '$Path' | cut -d ' ' -f 1" -Capture
    if ($r.ExitCode -ne 0 -or @($r.Output).Count -eq 0) {
        return $null
    }
    $last = ([string]@($r.Output)[-1]).Trim()
    if ($last -cmatch '^[0-9a-f]{64}\z') {
        return $last
    }
    return $null
}

function Read-EccoRemoteTextFile {
    # Read-only: a small text file from the host through scp (exact bytes)
    # into a fresh temporary file, returned as bytes; the copy is deleted.
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Assert-EccoRemoteSafePath -Path $Path
    $local = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-kit-read-' + [guid]::NewGuid().ToString('N'))
    $sshConfigArgs = @(Get-EccoSshConfigArguments)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & scp -q @sshConfigArgs ('{0}:{1}' -f $SshHost, $Path) $local
        $code = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($code -ne 0 -or -not (Test-Path -LiteralPath $local -PathType Leaf)) {
            throw "$Path could not be copied from the host (scp exit code $code)."
        }
        return , ([System.IO.File]::ReadAllBytes($local))
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Remove-Item -LiteralPath $local -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-EccoNonDashboardGate {
    <#
        The dashboard preservation gate for a route that never writes a
        dashboard (the kit route and the site-file placement): the gate's
        policy read and classify (-ClassifyOnly) must say the destination is
        not a dashboard destination, the policy must name nothing under
        -RefusePolicyPrefix, and the gate pin applies exactly as in
        deploy-ha.ps1: with a site gate pinned and the policy moved aside,
        the run is refused unless -ExpectedSiteGate DASHBOARD_PRESERVE_GATE
        is given for this run. Read-only. Throws BLOCKED; returns the lines.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [Parameter(Mandatory = $true)]
        [string]$GuardPath,

        [Parameter(Mandatory = $true)]
        [string]$Python,

        [AllowNull()]
        [AllowEmptyString()]
        [string]$ExpectedGate,

        [string]$PinSource = 'the gate pin',

        [Parameter(Mandatory = $true)]
        [string]$RefusePolicyPrefix,

        [Parameter(Mandatory = $true)]
        [string]$Route
    )

    $gate = Invoke-EccoDashboardPreservationGate -SshHost $SshHost -Destination $Destination -GuardPath $GuardPath -Python $Python -ClassifyOnly
    if ($gate.Applies) {
        throw (Format-EccoGateBlockedMessage -Gate $gate.Gate -Reason "$Destination is a dashboard destination (by its path or because the site policy names it): $Route never writes a dashboard.")
    }
    foreach ($named in @($gate.PolicyDestinations)) {
        if (([string]$named).StartsWith($RefusePolicyPrefix, [System.StringComparison]::Ordinal)) {
            throw (Format-EccoGateBlockedMessage -Gate $gate.Gate -Reason "the site policy names $named, under $RefusePolicyPrefix, which $Route writes: correct the host policy.")
        }
    }
    $pinLine = Assert-EccoDashboardGatePin -GateResult $gate -ExpectedGate $ExpectedGate -PinSource $PinSource
    return [pscustomobject]@{ GateLine = $gate.GateLine; PinLine = $pinLine; PolicyState = $gate.PolicyState }
}

# --- writes: staging, backup, swap, rollback ------------------------------

function Get-EccoKitSwapCommand {
    <#
        The swap as one remote command, with markers (pure string logic):
          -PreviousPath set (Upgrade, restore over an installed tree): the
          installed folder is renamed to the previous path, then the staged
          folder into place - ECCO_SWAP_MOVED after the first rename,
          ECCO_SWAP_DONE after the second. Each rename runs only when its
          target does not exist (mv into an existing folder would nest).
          No -PreviousPath (Install): the staged folder is renamed into
          place when nothing is there.
          -MoveAside (Uninstall): the installed folder is renamed to
          -PreviousPath and nothing replaces it.
    #>
    param(
        [AllowEmptyString()]
        [string]$NewRoot = '',

        [AllowEmptyString()]
        [string]$PreviousPath = '',

        [switch]$MoveAside
    )

    $p = $script:EccoKitInstallPath
    if ($MoveAside) {
        $parent = $PreviousPath.Substring(0, $PreviousPath.LastIndexOf('/'))
        return "[ -d '$parent' ] && [ ! -L '$parent' ] && [ ! -e '$PreviousPath' ] && [ ! -L '$PreviousPath' ] && [ -d '$p' ] && [ ! -L '$p' ] && mv '$p' '$PreviousPath' && echo ECCO_SWAP_DONE"
    }
    if ($PreviousPath) {
        $parent = $PreviousPath.Substring(0, $PreviousPath.LastIndexOf('/'))
        return "[ -d '$parent' ] && [ ! -L '$parent' ] && [ ! -e '$PreviousPath' ] && [ ! -L '$PreviousPath' ] && [ -d '$p' ] && [ ! -L '$p' ] && [ -d '$NewRoot' ] && [ ! -L '$NewRoot' ] && mv '$p' '$PreviousPath' && echo ECCO_SWAP_MOVED && [ ! -e '$p' ] && [ ! -L '$p' ] && mv '$NewRoot' '$p' && echo ECCO_SWAP_DONE"
    }
    return "[ ! -e '$p' ] && [ ! -L '$p' ] && [ -d '$NewRoot' ] && [ ! -L '$NewRoot' ] && mv '$NewRoot' '$p' && echo ECCO_SWAP_DONE"
}

function Send-EccoKitFiles {
    # One scp per folder with the exact kit file names (no recursive copy)
    # into the staged tree, whose folders already exist.
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [object]$KitInfo,

        [Parameter(Mandatory = $true)]
        [string]$RemoteRoot
    )

    $byDir = New-Object 'System.Collections.Generic.SortedDictionary[string,object]' ([System.StringComparer]::Ordinal)
    foreach ($rel in @($KitInfo.PackageFiles.Keys)) {
        $cut = $rel.LastIndexOf('/')
        $dir = if ($cut -lt 0) { '' } else { $rel.Substring(0, $cut) }
        if (-not $byDir.ContainsKey($dir)) {
            $byDir[$dir] = New-Object System.Collections.Generic.List[string]
        }
        $byDir[$dir].Add($rel)
    }
    $sshConfigArgs = @(Get-EccoSshConfigArguments)
    foreach ($dir in @($byDir.Keys)) {
        $locals = @($byDir[$dir] | ForEach-Object { Join-Path $KitInfo.PackageRoot ($_.Replace('/', '\')) })
        $remoteDir = if ($dir) { "$RemoteRoot/$dir" } else { $RemoteRoot }
        Assert-EccoRemoteSafePath -Path $remoteDir
        $spec = '{0}:{1}/' -f $SshHost, $remoteDir
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & scp -q @sshConfigArgs @locals $spec
            $code = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($code -ne 0) {
            throw "the upload of $(@($locals).Count) file(s) to $remoteDir failed (scp exit code $code)"
        }
    }
}

function Backup-EccoKitInstalled {
    <#
        The verified backup of the installed integration: cp -R into
        <backup>/custom_components__ecco_intelligence, then its hash list
        (__pycache__ left out) must equal the installed list read before, and
        BACKUP_SHA256SUMS (written locally from that list, uploaded, re-hashed
        on the host) records it for Rollback -BackupStamp.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [object]$InstalledFiles,

        [Parameter(Mandatory = $true)]
        [string]$BackupDir
    )

    $p = $script:EccoKitInstallPath
    $copy = "$BackupDir/$($script:EccoKitBackupCopyName)"
    $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "[ -d '$BackupDir' ] && [ ! -L '$BackupDir' ] && [ ! -e '$copy' ] && [ ! -L '$copy' ] && [ -d '$p' ] && [ ! -L '$p' ] && cp -R '$p' '$copy' && echo ECCO_BACKUP_COPIED" -Capture
    if ($r.ExitCode -ne 0 -or @($r.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_BACKUP_COPIED' }).Count -ne 1) {
        throw "the backup copy into $copy failed (ssh exit code $($r.ExitCode))"
    }
    $diff = Compare-EccoKitTree -Tree (Get-EccoKitRemoteTree -SshHost $SshHost -Root $copy) -ExpectedFiles $InstalledFiles
    if ($diff) {
        throw "the backup does not verify: $diff"
    }
    $text = -join (@($InstalledFiles.Keys) | ForEach-Object { "$($InstalledFiles[$_])  $_`n" })
    $bytes = [System.Text.Encoding]::ASCII.GetBytes($text)
    $local = Join-Path ([System.IO.Path]::GetTempPath()) ('ecco-kit-backup-sums-' + [guid]::NewGuid().ToString('N'))
    $sshConfigArgs = @(Get-EccoSshConfigArguments)
    try {
        [System.IO.File]::WriteAllBytes($local, $bytes)
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & scp -q @sshConfigArgs $local ('{0}:{1}/BACKUP_SHA256SUMS' -f $SshHost, $BackupDir)
            $code = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }
    finally {
        Remove-Item -LiteralPath $local -Force -ErrorAction SilentlyContinue
    }
    if ($code -ne 0) {
        throw "the upload of BACKUP_SHA256SUMS failed (scp exit code $code)"
    }
    if ((Get-EccoRemoteFileSha256 -SshHost $SshHost -Path "$BackupDir/BACKUP_SHA256SUMS") -cne (Get-EccoBytesSha256 -Bytes $bytes)) {
        throw 'BACKUP_SHA256SUMS does not verify on the host'
    }
    return $copy
}

function Invoke-EccoKitRollback {
    <#
        The single rollback routine of the kit route, for every failure once
        the swap has started (a swap whose result is unknown, a failed
        in-place verification, a changed protected snapshot, a failed
        `ha core check`). It reads the installed folder first, then:
          - it holds the previous tree: nothing to undo;
          - nothing installed and nothing was installed before: nothing to
            undo;
          - it holds the new tree: it is moved to <staging>/failed/, then
            the previous tree (if any) is renamed back into place;
          - it is absent and the previous tree is where the swap put it:
            renamed back into place;
          - anything else: nothing is touched, ROLLBACK NOT CONFIRMED.
        Then it verifies the result, runs `ha core check` again (its own ssh
        command) and throws through Format-EccoRollbackResultMessage, which
        says "was rolled back" only when the result was verified. Nothing is
        deleted. -NewFiles $null means the new state is "nothing installed"
        (Uninstall); -PreviousFiles $null means nothing was installed before.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [AllowNull()]
        [object]$NewFiles,

        [AllowEmptyString()]
        [string]$PreviousPath = '',

        [AllowNull()]
        [object]$PreviousFiles,

        [Parameter(Mandatory = $true)]
        [string]$StagingDir,

        # The resolved /config root of the run (amendment A26): the folder
        # the rollback creates is created only while /config still resolves
        # to it.
        [Parameter(Mandatory = $true)]
        [string]$ConfigRoot,

        [Parameter(Mandatory = $true)]
        [string]$BackupDescription,

        [Parameter(Mandatory = $true)]
        [string]$Reason
    )

    # -NewFiles $null is Uninstall, whose step is a move aside, not a swap (review L3W-6).
    Write-Warning "Rolling back the Intelligence kit $(if ($null -eq $NewFiles) { 'move aside' } else { 'swap' }): $Reason"
    $p = $script:EccoKitInstallPath
    $failedDir = "$StagingDir/failed"
    $restoreVerified = $false
    $restoreProblem = $null
    try {
        $now = Get-EccoKitRemoteTree -SshHost $SshHost -Root $p
        $matchesPrevious = ($null -ne $PreviousFiles) -and ($null -eq (Compare-EccoKitTree -Tree $now -ExpectedFiles $PreviousFiles))
        $matchesNew = ($null -ne $NewFiles) -and ($null -eq (Compare-EccoKitTree -Tree $now -ExpectedFiles $NewFiles))
        if ($matchesPrevious) {
            Write-Host 'Rollback: the installed folder already holds the previous tree - nothing to undo.'
        } elseif ($now.State -eq 'absent' -and $null -eq $PreviousFiles) {
            Write-Host 'Rollback: nothing is installed, as before - nothing to undo.'
        } else {
            if ($matchesNew) {
                $move = Invoke-EccoRemoteCommand -SshHost $SshHost -Command ((Get-EccoSafeMkdirCommand -ConfigRoot $ConfigRoot -MustExist @($StagingDir) -MayCreate @($failedDir) -NoMarker) +" && [ ! -e '$failedDir/$($script:EccoKitDomain)' ] && [ ! -L '$failedDir/$($script:EccoKitDomain)' ] && [ -d '$p' ] && [ ! -L '$p' ] && mv '$p' '$failedDir/$($script:EccoKitDomain)' && echo ECCO_ROLLBACK_MOVED_FAILED") -Capture
                if ($move.ExitCode -ne 0 -or @($move.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_ROLLBACK_MOVED_FAILED' }).Count -ne 1) {
                    throw "the new tree could not be moved to $failedDir (ssh exit code $($move.ExitCode); a symlinked segment, or /config no longer resolving to $ConfigRoot)"
                }
                Write-Host "Rollback: the new tree was moved to $failedDir/$($script:EccoKitDomain)"
                $now = Get-EccoKitRemoteTree -SshHost $SshHost -Root $p -NoHashes
            }
            if ($now.State -ne 'absent') {
                throw "the installed folder holds neither the new nor the previous tree; nothing was touched - inspect $p by hand"
            }
            if ($null -ne $PreviousFiles) {
                if (-not $PreviousPath) {
                    throw 'the previous tree is not where the swap put it'
                }
                $back = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "[ -d '$PreviousPath' ] && [ ! -L '$PreviousPath' ] && [ ! -e '$p' ] && [ ! -L '$p' ] && mv '$PreviousPath' '$p' && echo ECCO_ROLLBACK_RESTORED" -Capture
                if ($back.ExitCode -ne 0 -or @($back.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_ROLLBACK_RESTORED' }).Count -ne 1) {
                    throw "the previous tree could not be renamed back from $PreviousPath (ssh exit code $($back.ExitCode))"
                }
                Write-Host "Rollback: the previous tree was renamed back from $PreviousPath"
            }
        }

        $final = Get-EccoKitRemoteTree -SshHost $SshHost -Root $p
        if ($null -ne $PreviousFiles) {
            $diff = Compare-EccoKitTree -Tree $final -ExpectedFiles $PreviousFiles
            if ($diff) {
                $restoreProblem = "the restored folder does not verify: $diff"
            } else {
                $restoreVerified = $true
            }
        } elseif ($final.State -eq 'absent') {
            $restoreVerified = $true
        } else {
            $restoreProblem = "$p is still $($final.State) on the host"
        }
    }
    catch {
        $restoreProblem = "ROLLBACK NOT CONFIRMED - $($_.Exception.Message)"
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
        # A transport failure only; the message below says the check did not run.
    }

    throw (Format-EccoRollbackResultMessage -Reason $Reason -BackupDescription $BackupDescription -RestoreVerified $restoreVerified -RestoreProblem $restoreProblem -RollbackCheckRan $rollbackCheckRan -RollbackCheckExitCode $rollbackCheckExitCode)
}

function Invoke-EccoKitWrite {
    <#
        The writing half of deploy-ha-kit.ps1 (Install, Upgrade, Rollback
        -BackupStamp as Restore, Uninstall), after every read-only check
        passed. In order:
          0. /config still resolves to -ConfigRoot, the root the read-only
             checks printed (amendment A26; a read-only re-probe - BLOCKED,
             nothing written, otherwise);
          1. folders: staging/<stamp> with new/ or restore/ or uninstalled/,
             previous/ when a tree is installed, and ecco-backups/<stamp> -
             one level at a time after a symlink test of every segment
             below /config, in one command that first checks the root again;
          2. stage the new tree (one scp per folder of exact files, or a cp of
             the listed backup files) and verify it on the host: exactly the
             allowlist, every hash;
          3. a verified backup of the installed tree (BACKUP_SHA256SUMS);
          4. the swap (Get-EccoKitSwapCommand; for Uninstall the move aside,
             reported as such, never as a swap);
          5. verify in place (__pycache__ ignored; for Uninstall the folder
             absent and the moved tree verified), the protected snapshot
             unchanged, and `ha core check` (its own ssh command).
        A failure in 1-3 stops before the swap: nothing installed changed.
        A failure in 1 (the folder-creating command did not report success)
        names no folder as kept, because they may not have been created;
        once it succeeded, a failure in 2-3 keeps this run's stamp folders
        for inspection (review DR3-2). A failure from step 4 on goes to
        Invoke-EccoKitRollback. Nothing is deleted. Never restarts Home
        Assistant.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Install', 'Upgrade', 'Restore', 'Uninstall')]
        [string]$Mode,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[0-9]{8}-[0-9]{6}\z')]
        [string]$Stamp,

        [Parameter(Mandatory = $true)]
        [object]$Installed,

        [Parameter(Mandatory = $true)]
        [object]$Snapshot,

        # The resolved /config root the read-only checks printed (amendment
        # A26; Get-EccoRemoteConfigRoot .Resolved).
        [Parameter(Mandatory = $true)]
        [string]$ConfigRoot,

        [object]$KitInfo,

        [object]$RestoreFiles,

        [string]$RestoreFrom
    )

    $p = $script:EccoKitInstallPath
    $staging = "$($script:EccoStagingDir)/$Stamp"
    $backupDir = "$($script:EccoBackupsDir)/$Stamp"
    $hasInstalled = $Installed.State -eq 'dir'
    $newFiles = $null
    $newRoot = ''
    if ($Mode -eq 'Install' -or $Mode -eq 'Upgrade') {
        $newFiles = $KitInfo.PackageFiles
        $newRoot = "$staging/new/$($script:EccoKitDomain)"
    } elseif ($Mode -eq 'Restore') {
        $newFiles = $RestoreFiles
        $newRoot = "$staging/restore/$($script:EccoKitDomain)"
    }
    $previousPath = ''
    if ($hasInstalled) {
        $previousPath = if ($Mode -eq 'Uninstall') { "$staging/uninstalled/$($script:EccoKitDomain)" } else { "$staging/previous/$($script:EccoKitDomain)" }
    }
    $kept = New-Object System.Collections.Generic.List[string]
    # Uninstall moves the installed folder aside and puts nothing in its place: its lines say so, never "swap" or
    # "in place" (reviews L3W-6 and DRD-5, amendments A49 and A52).
    $step = if ($Mode -eq 'Uninstall') { 'move aside' } else { 'swap' }

    # 0. The /config root is unchanged since the read-only checks (A26).
    Assert-EccoRemoteConfigRootUnchanged -SshHost $SshHost -ConfigRoot $ConfigRoot -Name 'INTELLIGENCE_KIT'

    # 1. Folders, never with a recursive mkdir (A15), behind the root test (A26).
    $mustCreate = New-Object System.Collections.Generic.List[string]
    $mustCreate.Add($staging)
    if ($newRoot) {
        $mustCreate.Add($newRoot.Substring(0, $newRoot.LastIndexOf('/')))
        $mustCreate.Add($newRoot)
        foreach ($d in (Get-EccoParentDirs -Paths @($newFiles.Keys))) {
            $mustCreate.Add("$newRoot/$d")
        }
    }
    $mayCreate = New-Object System.Collections.Generic.List[string]
    $mayCreate.Add($script:EccoStagingDir)
    if ($hasInstalled) {
        $mustCreate.Add($previousPath.Substring(0, $previousPath.LastIndexOf('/')))
        $mayCreate.Add($script:EccoBackupsDir)
        $mustCreate.Add($backupDir)
    }
    $mkdir = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (Get-EccoSafeMkdirCommand -ConfigRoot $ConfigRoot -MustExist @('/config/ecco') -MayCreate $mayCreate.ToArray() -MustCreate $mustCreate.ToArray()) -Capture
    if ($mkdir.ExitCode -ne 0 -or @($mkdir.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_MKDIR_OK' }).Count -ne 1) {
        # Review DR3-2 (amendment A40): without ECCO_MKDIR_OK this run may have created none of its folders, or only some,
        # and a used stamp's folder belongs to an earlier run, so no folder is named as kept. Both lines name only the
        # folders this run tried to create (review DR4R-2, amendment A43): an Install creates no backup folder.
        $folders = if ($mustCreate.Contains($backupDir)) { 'staging and backup folders' } else { 'staging folder' }
        $stopped = Format-EccoKitBlockedMessage -Name 'INTELLIGENCE_KIT' -Stage StoppedBeforeSwap -Step $step -Reason "the $folders could not be created safely (/config no longer resolving to $ConfigRoot, a symlinked segment, a stamp already used, or no permission; ssh exit code $($mkdir.ExitCode))."
        throw ($stopped + "`n" + "The folder-creating command did not report success, so this run's $folders (stamp $Stamp) may not have been created, or only in part, and no folder is listed as kept. Nothing was deleted.")
    }
    # Only now, after the folder-creating command reported success, are this run's stamp folders kept for inspection.
    $kept.Add($staging)
    if ($hasInstalled) {
        $kept.Add($backupDir)
    }

    try {
        # 2. Stage and verify the new tree.
        if ($Mode -eq 'Install' -or $Mode -eq 'Upgrade') {
            Write-Host "Uploading $(@($newFiles.Keys).Count) files to $newRoot (one scp per folder)..."
            Send-EccoKitFiles -SshHost $SshHost -KitInfo $KitInfo -RemoteRoot $newRoot
        } elseif ($Mode -eq 'Restore') {
            Write-Host "Copying the $(@($newFiles.Keys).Count) listed backup files to $newRoot..."
            $copies = @($newFiles.Keys | ForEach-Object { "cp '$RestoreFrom/$_' '$newRoot/$_'" })
            $cp = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (($copies -join ' && ') + ' && echo ECCO_RESTORE_STAGED') -Capture
            if ($cp.ExitCode -ne 0 -or @($cp.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_RESTORE_STAGED' }).Count -ne 1) {
                throw "the restore copy into $newRoot failed (ssh exit code $($cp.ExitCode))"
            }
        }
        if ($newRoot) {
            $staged = Get-EccoKitRemoteTree -SshHost $SshHost -Root $newRoot
            $diff = Compare-EccoKitTree -Tree $staged -ExpectedFiles $newFiles
            if (-not $diff -and @($staged.Pycache).Count -gt 0) {
                $diff = "$newRoot holds __pycache__ entries"
            }
            if ($diff) {
                throw "the staged copy does not verify on the host: $diff"
            }
            Write-Host "Staged copy verified on the host: $(@($newFiles.Keys).Count) files, every sha256."
        }

        # 3. The verified backup of the installed tree.
        if ($hasInstalled) {
            $copy = Backup-EccoKitInstalled -SshHost $SshHost -InstalledFiles $Installed.Files -BackupDir $backupDir
            Write-Host "Backup verified: $copy (BACKUP_SHA256SUMS, $(@($Installed.Files.Keys).Count) files)"
            $again = Get-EccoKitRemoteTree -SshHost $SshHost -Root $p
            $changed = Compare-EccoKitTree -Tree $again -ExpectedFiles $Installed.Files
            if ($changed) {
                throw "the installed folder changed after it was read: $changed"
            }
        }
    }
    catch {
        throw (Format-EccoKitBlockedMessage -Name 'INTELLIGENCE_KIT' -Stage StoppedBeforeSwap -Step $step -Kept $kept.ToArray() -Reason $_.Exception.Message)
    }

    # 4. The swap. From here on, every failure goes through the one rollback.
    $rollback = @{
        SshHost           = $SshHost
        NewFiles          = $newFiles
        PreviousPath      = $previousPath
        PreviousFiles     = $(if ($hasInstalled) { $Installed.Files } else { $null })
        StagingDir        = $staging
        ConfigRoot        = $ConfigRoot
        BackupDescription =$(if ($hasInstalled) { "$backupDir/$($script:EccoKitBackupCopyName) (verified, BACKUP_SHA256SUMS)" } else { 'none (nothing was installed before)' })
    }
    if ($Mode -eq 'Uninstall') {
        $swapCommand = Get-EccoKitSwapCommand -PreviousPath $previousPath -MoveAside
    } else {
        $swapCommand = Get-EccoKitSwapCommand -NewRoot $newRoot -PreviousPath $previousPath
    }
    $swap = Invoke-EccoRemoteCommand -SshHost $SshHost -Command $swapCommand -Capture
    if ($swap.ExitCode -ne 0 -or @($swap.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_SWAP_DONE' }).Count -ne 1) {
        Invoke-EccoKitRollback @rollback -Reason "the $step did not complete, or its result could not be confirmed (ssh exit code $($swap.ExitCode)): the installed folder may already have changed."
    }
    if ($Mode -eq 'Uninstall') {
        Write-Host "Moved aside (not deleted): $p -> $previousPath"
    } else {
        Write-Host "Swap done: $p"
    }

    # 5. Verify in place, the protected snapshot, and ha core check.
    $failure = $null
    try {
        if ($Mode -eq 'Uninstall') {
            $now = Get-EccoKitRemoteTree -SshHost $SshHost -Root $p -NoHashes
            if ($now.State -ne 'absent') {
                $failure = "$p is still $($now.State) after the move aside"
            } else {
                $moved = Compare-EccoKitTree -Tree (Get-EccoKitRemoteTree -SshHost $SshHost -Root $previousPath) -ExpectedFiles $Installed.Files
                if ($moved) {
                    $failure = "the moved tree does not verify: $moved"
                }
            }
        } else {
            $inPlace = Compare-EccoKitTree -Tree (Get-EccoKitRemoteTree -SshHost $SshHost -Root $p) -ExpectedFiles $newFiles
            if ($inPlace) {
                $failure = "the installed folder does not verify in place: $inPlace"
            }
        }
        if (-not $failure) {
            if ($Mode -eq 'Uninstall') {
                Write-Host "Verified: $p is absent, and the moved tree at $previousPath matches the installed one (every sha256; __pycache__ ignored)."
            } else {
                Write-Host 'Verified in place (every sha256; __pycache__ ignored).'
            }
            $after = Get-EccoProtectedSnapshot -SshHost $SshHost
            if ($after.Text -cne $Snapshot.Text) {
                $failure = 'the protected site file or state folder changed during the write'
            }
        }
    }
    catch {
        $failure = "the result could not be verified: $($_.Exception.Message)"
    }
    if ($failure) {
        Invoke-EccoKitRollback @rollback -Reason $failure
    }

    Write-Host 'Running Home Assistant configuration check...'
    $check = Invoke-EccoRemoteCommand -SshHost $SshHost -Command 'ha core check' -Capture
    $check.Output | ForEach-Object { Write-Host $_ }
    if ($check.ExitCode -ne 0) {
        Invoke-EccoKitRollback @rollback -Reason "Home Assistant configuration check failed after the $step."
    }

    return [pscustomobject]@{
        Stamp        = $Stamp
        StagingDir   = $staging
        BackupDir    = $(if ($hasInstalled) { "$backupDir/$($script:EccoKitBackupCopyName)" } else { $null })
        PreviousPath = $previousPath
    }
}

# --- the site file --------------------------------------------------------

function Test-EccoJsonNumberBeyondDouble {
    <#
        Pure string logic for one JSON number token (the number form of
        EccoJsonTokenRegex): $true when its magnitude is at least
        2^1024 - 2^970, where Python's float() gives an infinity and
        float(int) refuses, so the runtime refuses it as a non-finite number
        (1e999, 1.797693134862315808e308, an integer of 309 digits or more
        from that value, or past Python's integer digit limit); $false for
        every number a double holds (1.7976931348623157e308, 1e-999, 0e999).
        Exact: no floating-point arithmetic, so no rounding of its own
        (review DRD-2).
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $t = $Token
    if ($t.StartsWith('-')) {
        $t = $t.Substring(1)
    }
    $ePos = $t.IndexOfAny([char[]]'eE')
    $mantissa = if ($ePos -ge 0) { $t.Substring(0, $ePos) } else { $t }
    $dot = $mantissa.IndexOf('.')
    $intPart = if ($dot -ge 0) { $mantissa.Substring(0, $dot) } else { $mantissa }
    $digits = if ($dot -ge 0) { $intPart + $mantissa.Substring($dot + 1) } else { $mantissa }
    $significant = $digits.TrimStart('0')
    if ($significant.Length -eq 0) {
        return $false
    }
    # The value is 0.<significant> x 10^k.
    [long]$k = $intPart.Length - ($digits.Length - $significant.Length)
    if ($ePos -ge 0) {
        $exponent = $t.Substring($ePos + 1)
        $negative = $exponent.StartsWith('-')
        $exponent = $exponent.TrimStart('+', '-').TrimStart('0')
        if ($exponent.Length -gt 9) {
            # An exponent of a billion or more: far beyond the double range, or (negative) a finite zero.
            return (-not $negative)
        }
        if ($exponent.Length -gt 0) {
            if ($negative) { $k -= [long]$exponent } else { $k += [long]$exponent }
        }
    }
    if ($k -ge 310) {
        return $true
    }
    if ($k -le 308) {
        return $false
    }
    # 10^308 <= value < 10^309, as is the bound: compare the first 309 significant digits, padded with zeros.
    $first = if ($significant.Length -ge 309) { $significant.Substring(0, 309) } else { $significant.PadRight(309, '0') }
    return ([string]::CompareOrdinal($first, $script:EccoDoubleOverflowDigits) -ge 0)
}

function Get-EccoStrictJsonProblem {
    <#
        Pure string logic: $null when -Text is exactly one strict JSON value
        (RFC 8259) that the runtime's json.loads reads, otherwise what the
        first problem is:
          'NonFinite'  NaN, Infinity or -Infinity (which Python's json reads
                       and the runtime refuses, review P1);
          'NotStrict'  a token strict JSON does not allow (a bare word, a
                       single quote, a comment, +1, .5, 01, 1., a control
                       character or an unknown escape inside a string);
          'NotJson'    tokens out of JSON order: a missing or extra comma or
                       colon, a key that is not a string, an unclosed or
                       unmatched bracket, nothing at all or more than one
                       value (review DRD-2);
          'TooDeep'    arrays and objects nested more than
                       EccoSiteFileMaxDepth deep (review DRD-2);
          'OutOfRange' a number beyond the double range, which the runtime
                       refuses as non-finite (Test-EccoJsonNumberBeyondDouble,
                       review DRD-2).
        The tokens are checked first, then their order, depth and numbers in
        one pass. Windows PowerShell's ConvertFrom-Json accepts several of
        these forms; the runtime refuses every one, so the placement refuses
        them before anything is sent, whatever ConvertFrom-Json does. Never
        returns any of the text.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Text
    )

    # Every token matches where the previous one ended (\G), so the matches
    # cover the text from its start up to the first token that is not JSON.
    $end = 0
    $tokens = $script:EccoJsonTokenRegex.Matches($Text)
    if ($tokens.Count -gt 0) {
        $last = $tokens[$tokens.Count - 1]
        $end = $last.Index + $last.Length
    }
    if ($end -ne $Text.Length) {
        if ($script:EccoJsonNonFiniteRegex.Match($Text, $end).Success) {
            return 'NonFinite'
        }
        return 'NotStrict'
    }

    # The order of the tokens. $state is what may come next: 0 a value (at the
    # start, after a colon or after a comma in an array), 1 a value or ']'
    # (after '['), 2 a key or '}' (after '{'), 3 a key (after a comma in an
    # object), 4 a colon (after a key), 5 a comma or the closing bracket
    # (after a value inside an array or object), 6 nothing (after the one
    # value). $open holds 123 ('{') or 91 ('[') for each open bracket.
    $max = $script:EccoSiteFileMaxDepth
    $open = New-Object 'int[]' ($max)
    $depth = 0
    $state = 0
    foreach ($m in $tokens) {
        $v = $m.Value
        $c = [int]$v[0]
        if ($c -eq 32 -or $c -eq 9 -or $c -eq 10 -or $c -eq 13) {
            continue
        }
        if ($c -eq 123 -or $c -eq 91) {
            if ($state -gt 1) { return 'NotJson' }
            if ($depth -ge $max) { return 'TooDeep' }
            $open[$depth] = $c
            $depth++
            $state = if ($c -eq 123) { 2 } else { 1 }
        } elseif ($c -eq 125 -or $c -eq 93) {
            $opener = if ($c -eq 125) { 123 } else { 91 }
            if (-not (($state -eq 5 -and $open[$depth - 1] -eq $opener) -or ($c -eq 125 -and $state -eq 2) -or ($c -eq 93 -and $state -eq 1))) {
                return 'NotJson'
            }
            $depth--
            $state = if ($depth -eq 0) { 6 } else { 5 }
        } elseif ($c -eq 58) {
            if ($state -ne 4) { return 'NotJson' }
            $state = 0
        } elseif ($c -eq 44) {
            if ($state -ne 5) { return 'NotJson' }
            $state = if ($open[$depth - 1] -eq 123) { 3 } else { 0 }
        } elseif ($c -eq 34) {
            if ($state -eq 2 -or $state -eq 3) {
                $state = 4
            } elseif ($state -le 1) {
                $state = if ($depth -eq 0) { 6 } else { 5 }
            } else {
                return 'NotJson'
            }
        } else {
            # A number, true, false or null. A number of at most 300 characters
            # without an exponent is below 10^300; any other is measured.
            if ($state -gt 1) { return 'NotJson' }
            if (($c -eq 45 -or ($c -ge 48 -and $c -le 57)) -and ($v.Length -gt 300 -or $v.IndexOfAny([char[]]'eE') -ge 0) -and
                (Test-EccoJsonNumberBeyondDouble -Token $v)) {
                return 'OutOfRange'
            }
            $state = if ($depth -eq 0) { 6 } else { 5 }
        }
    }
    if ($state -ne 6) {
        return 'NotJson'
    }
    return $null
}

function Test-EccoSiteFile {
    <#
        The local checks of place-ha-site-file.ps1 before any ssh call: the
        site file is a regular file (not a reparse point) outside every git
        working tree, at most 256 KiB, UTF-8 without a byte-order mark, a JSON
        object in strict JSON (Get-EccoStrictJsonProblem: no NaN, Infinity
        or -Infinity, review P1; no number beyond the double range, JSON
        order, at most EccoSiteFileMaxDepth deep, review DRD-2), and its
        sha256 equals -ExpectedSha256 (recorded offline first). It refuses
        every file the runtime's SITE_FILE check refuses, and a few the
        runtime reads (ConvertFrom-Json's own refusals; fail-closed). Returns
        the full path, size and sha256 - never the content.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ExpectedSha256,

        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}\z') {
        throw '-ExpectedSha256 must be 64 lower-case hex digits (the site file''s sha256, recorded offline).'
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "The site file $Path is not a file."
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'The site file is a reparse point (a symlink): pass the real file.'
    }
    $full = $item.FullName
    $repoPrefix = $RepoRoot.TrimEnd('\', '/') + '\'
    if ($full.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'The site file is inside this repository: a site file never enters a repository.'
    }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $inside = ((@(& git -C $item.DirectoryName rev-parse --is-inside-work-tree 2>&1) -join '').Trim())
        $gitCode = $LASTEXITCODE
    }
    catch {
        $inside = ''
        $gitCode = 1
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($gitCode -eq 0 -and $inside -ceq 'true') {
        throw 'The site file is inside a git working tree: a site file never enters a repository.'
    }
    if ($item.Length -le 0 -or $item.Length -gt $script:EccoSiteFileMaxBytes) {
        throw "The site file is $($item.Length) bytes: it must be 1 to $($script:EccoSiteFileMaxBytes) bytes (the runtime's safety cap)."
    }
    $bytes = [System.IO.File]::ReadAllBytes($full)
    $text = Read-EccoStrictUtf8 -Bytes $bytes -Label 'The site file'
    if (-not $text.TrimStart().StartsWith('{')) {
        throw 'The site file is not a JSON object.'
    }
    # Before ConvertFrom-Json, which reads NaN, Infinity, -Infinity and other
    # forms that are not JSON and that the runtime refuses (review P1, A49),
    # so the verdict never rests on what ConvertFrom-Json reads (review DRD-2).
    $jsonProblem = Get-EccoStrictJsonProblem -Text $text
    if ($jsonProblem -ceq 'NonFinite') {
        throw 'The site file holds NaN, Infinity or -Infinity, which is not JSON: the runtime refuses it (SITE_FILE FAIL).'
    }
    if ($jsonProblem -ceq 'OutOfRange') {
        throw 'The site file holds a number beyond the double range (such as 1e999, or an integer too large for a double): the runtime reads it as non-finite and refuses it (SITE_FILE FAIL).'
    }
    if ($jsonProblem -ceq 'TooDeep') {
        throw "The site file nests arrays and objects more than $($script:EccoSiteFileMaxDepth) deep: the placement reads no deeper (the runtime reads deeper, but a site file nests about five deep)."
    }
    if ($jsonProblem -ceq 'NotJson') {
        throw 'The site file is not valid JSON (a missing or extra comma or colon, a key that is not a string, a bracket not closed or not matched, or nothing or more than one value at the top): the runtime refuses it (SITE_FILE FAIL).'
    }
    if ($jsonProblem) {
        throw 'The site file is not strict JSON (a bare word, a single quote, a comment, a number such as +1, .5, 01 or 1., or a control character or an unknown escape inside a string): the runtime refuses it (SITE_FILE FAIL).'
    }
    try {
        $doc = $text | ConvertFrom-Json
    }
    catch {
        # Strict JSON the runtime reads, refused here as well (fail-closed).
        throw 'The site file is strict JSON, but Windows PowerShell''s ConvertFrom-Json cannot read it (for example two keys that differ only in case, or an empty key): the placement refuses it.'
    }
    if ($null -eq $doc -or $doc -isnot [System.Management.Automation.PSCustomObject]) {
        throw 'The site file is not a JSON object.'
    }
    $sha = Get-EccoBytesSha256 -Bytes $bytes
    if ($sha -cne $ExpectedSha256) {
        throw "The site file has sha256 $sha, not the expected $ExpectedSha256."
    }
    return [pscustomobject]@{ FullPath = $full; Size = $item.Length; Sha256 = $sha }
}

function Invoke-EccoSiteFileRollback {
    <#
        The placement's rollback, for a failure at or after the rename into
        place: restores the verified backup (cp, then its hash must equal the
        original's), or - for a first placement - moves a placed file into
        the backup folder (never deleted), or, when no file reached the
        destination (a rename that never ran), says that nothing was placed.
        The upload's temporary file (-TempPath) is never deleted or moved:
        while the host still holds it (the rename never ran), the message
        names it as left in place. A moved-aside file is named only after it
        was seen on the host (review DR-4, amendment A37). Throws a message
        that says "was rolled back" only when the result was verified.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [bool]$HadOriginal,

        [AllowEmptyString()]
        [string]$OriginalSha256,

        [Parameter(Mandatory = $true)]
        [string]$BackupDir,

        [Parameter(Mandatory = $true)]
        [string]$Reason,

        # place-ha-site-file.ps1's upload: <site file>.ecco-upload-<stamp>.tmp in the integration folder. It is only read
        # here, through Get-EccoRemotePathStates (which refuses an unsafe path); there is deliberately no parameter
        # validation, so a malformed value can never stop the rollback itself from running.
        [Parameter(Mandatory = $true)]
        [string]$TempPath
    )

    Write-Warning "Rolling back the site file placement: $Reason"
    $dest = $script:EccoSiteFilePath
    $backup = "$BackupDir/config__ecco__intelligence__site.local.json"
    $failed = "$BackupDir/site.local.json.failed-placement"
    $verified = $false
    $problem = $null
    $movedAside = $false
    $tempState = $null
    try {
        if ($HadOriginal) {
            $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "[ -f '$backup' ] && [ ! -L '$backup' ] && [ ! -L '$dest' ] && [ ! -d '$dest' ] && cp '$backup' '$dest' && echo ECCO_SITE_RESTORED" -Capture
            if ($r.ExitCode -ne 0 -or @($r.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_SITE_RESTORED' }).Count -ne 1) {
                throw "the backup could not be copied back (ssh exit code $($r.ExitCode))"
            }
            if ((Get-EccoRemoteFileSha256 -SshHost $SshHost -Path $dest) -ceq $OriginalSha256) {
                $verified = $true
            } else {
                $problem = 'the restored site file does not have the original sha256'
            }
        } else {
            # Two outcomes, each with its own marker: a file at the destination moved aside, or no file there at all
            # (the rename never ran), which is never reported as a move.
            $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "if [ -e '$dest' ] || [ -L '$dest' ]; then [ -f '$dest' ] && [ ! -L '$dest' ] && [ ! -e '$failed' ] && mv '$dest' '$failed' && echo ECCO_SITE_MOVED_ASIDE; else echo ECCO_SITE_NOT_PLACED; fi" -Capture
            $marks = @($r.Output | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ -ceq 'ECCO_SITE_MOVED_ASIDE' -or $_ -ceq 'ECCO_SITE_NOT_PLACED' })
            if ($r.ExitCode -ne 0 -or $marks.Count -ne 1) {
                throw "the placed file could not be moved to $failed (ssh exit code $($r.ExitCode))"
            }
            $movedAside = $marks[0] -ceq 'ECCO_SITE_MOVED_ASIDE'
            $probe = @($dest, $TempPath)
            if ($movedAside) {
                $probe += $failed
            }
            $states = Get-EccoRemotePathStates -SshHost $SshHost -Paths $probe
            $tempState = $states[$TempPath]
            if ($states[$dest] -ne 'absent') {
                $problem = "$dest is still $($states[$dest]) on the host"
            } elseif ($movedAside -and $states[$failed] -ne 'file') {
                $problem = "the moved-aside file $failed is $($states[$failed]) on the host, not a regular file"
            } else {
                $verified = $true
            }
        }
    }
    catch {
        $problem = "the rollback step itself failed: $($_.Exception.Message)"
    }
    # The upload's temporary file, read-only and best effort when not read above; it is never deleted or moved. A failed
    # read changes nothing above: the message then says its state is unknown.
    if ($null -eq $tempState) {
        try {
            $tempState = (Get-EccoRemotePathStates -SshHost $SshHost -Paths @($TempPath))[$TempPath]
        }
        catch {
            $tempState = $null
        }
    }
    $lines = New-Object System.Collections.Generic.List[string]
    if ($verified) {
        $lines.Add("Site file placement failed and was rolled back: $Reason")
        if ($HadOriginal) {
            $lines.Add("Restored: the previous site file (sha256 $($OriginalSha256.Substring(0, 12))) from $backup")
        } elseif ($movedAside) {
            $lines.Add("Moved aside (not deleted): the placed file is now $failed")
        } else {
            $lines.Add("Nothing placed: no site file is at $dest, as before the run, so nothing was moved aside.")
        }
    } else {
        $lines.Add("Site file placement failed and rollback could NOT be confirmed successful: $Reason")
        $lines.Add("Rollback verification: FAILED - $problem")
        $lines.Add("Backup folder: $BackupDir")
    }
    if ($tempState -ceq 'file') {
        $lines.Add("Left in place (nothing deleted): the upload $TempPath, the new site file verified on upload, was never renamed into place.")
    } elseif ($null -eq $tempState) {
        $lines.Add("Upload: the state of $TempPath could not be read; if the rename did not run, the new site file is still there (nothing was deleted).")
    } elseif ($tempState -cne 'absent') {
        $lines.Add("Upload: $TempPath is $tempState on the host, left as it is (nothing was deleted).")
    }
    $lines.Add('The integration reads the site file only at a config-entry reload or a restart; neither was performed.')
    throw ($lines -join "`n")
}

function Move-EccoRejectedSiteUpload {
    <#
        The placement's rejected upload (scp failed, or the upload's sha256 on
        the host did not match), before any rename: one captured command
        moves the temporary upload into this run's backup folder, never
        deletes it, and answers with exactly one marker - ECCO_UPLOAD_MOVED_ASIDE
        (a regular file was moved), ECCO_UPLOAD_KEPT (a regular file, but the
        move's own guards refused it, so it was not moved), ECCO_UPLOAD_OTHER
        (something other than a regular file is at the upload path; left as
        it is) or ECCO_UPLOAD_ABSENT (nothing is there). The move runs only
        into the run's backup folder as a real folder (never a symlink) and
        only when nothing is at the new path, so nothing nests or is
        overwritten. Returns the one line the STOPPED message carries. It
        names only what the marker shows, a moved file only once it is seen
        at its new path, and without exactly one marker (a lost connection, a
        failed move) it names both places the upload may be (review DR3-1,
        amendment A40; the guards' own marker, review DR4R-1, amendment A43).
        Never throws.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$TempPath,

        [Parameter(Mandatory = $true)]
        [string]$BackupDir
    )

    $rejected = "$BackupDir/site.local.json.upload-rejected"
    $detail = $null
    try {
        foreach ($path in @($TempPath, $BackupDir, $rejected)) {
            Assert-EccoRemoteSafePath -Path $path
            Assert-EccoBelowConfigRoot -Path $path
        }
        # The guards refusing the move answer ECCO_UPLOAD_KEPT; a failed mv answers no marker (review DR4R-1, amendment A43).
        $r = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "if [ -f '$TempPath' ] && [ ! -L '$TempPath' ]; then if [ -d '$BackupDir' ] && [ ! -L '$BackupDir' ] && [ ! -e '$rejected' ] && [ ! -L '$rejected' ]; then mv '$TempPath' '$rejected' && echo ECCO_UPLOAD_MOVED_ASIDE; else echo ECCO_UPLOAD_KEPT; fi; elif [ -e '$TempPath' ] || [ -L '$TempPath' ]; then echo ECCO_UPLOAD_OTHER; else echo ECCO_UPLOAD_ABSENT; fi" -Capture
        $marks = @($r.Output | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ -ceq 'ECCO_UPLOAD_MOVED_ASIDE' -or $_ -ceq 'ECCO_UPLOAD_KEPT' -or $_ -ceq 'ECCO_UPLOAD_OTHER' -or $_ -ceq 'ECCO_UPLOAD_ABSENT' })
        if ($r.ExitCode -ne 0 -or $marks.Count -ne 1) {
            $detail = "no single answer from the host (a lost connection or a failed move); ssh exit code $($r.ExitCode)"
        } elseif ($marks[0] -ceq 'ECCO_UPLOAD_ABSENT') {
            return "No upload is on the host: $TempPath is absent, so nothing was moved aside."
        } elseif ($marks[0] -ceq 'ECCO_UPLOAD_KEPT') {
            return "Left in place (nothing deleted): $TempPath; this run's backup folder $BackupDir is missing or not a real folder, or something is already at $rejected, so it was not moved aside."
        } elseif ($marks[0] -ceq 'ECCO_UPLOAD_OTHER') {
            return "Left in place (nothing deleted): $TempPath is on the host but is not a regular file, so it was not moved aside."
        } else {
            # The move answered its marker; the moved file is named only once it is seen at its new path.
            $state = $null
            try {
                $state = (Get-EccoRemotePathStates -SshHost $SshHost -Paths @($rejected))[$rejected]
            }
            catch {
                $state = $null
            }
            if ($state -ceq 'file') {
                return "The rejected upload was moved aside (not deleted): it is now $rejected."
            }
            $detail = if ($null -eq $state) { "the move answered, but $rejected could not be read on the host" } else { "the move answered, but $rejected is $state on the host, not a regular file" }
        }
    }
    catch {
        $detail = "the move step itself failed: $($_.Exception.Message)"
    }
    return "The rejected upload's move aside could not be confirmed ($detail). Nothing was deleted: an upload that reached the host is still $TempPath, or $rejected if the move ran."
}

# --- deploy-ha.ps1 -Action Retire -------------------------------------------

function Test-EccoRetireDestination {
    <#
        The exact files deploy-ha.ps1 -Action Retire may move into a backup
        folder: the PR-6 Intelligence files only - its packages
        (/config/packages/ecco_intelligence[_<part>].yaml), its dashboard
        (/config/ecco/dashboards/ecco_intelligence[_<part>].yaml) and its
        card (/config/www/ecco/ecco-intelligence-card[.<sha8>].js). The
        destination must already have passed Test-EccoDeploymentDestination.
        Extending this list is a safety-gate change. Pure string logic.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $patterns = @(
        '^/config/packages/ecco_intelligence(_[a-z0-9]+)*\.yaml\z',
        '^/config/ecco/dashboards/ecco_intelligence(_[a-z0-9]+)*\.yaml\z',
        '^/config/www/ecco/ecco-intelligence-card(\.[0-9a-f]{8})?\.js\z')
    foreach ($pattern in $patterns) {
        if ($Destination -cmatch $pattern) {
            return $Destination
        }
    }
    throw "-Action Retire moves only the Intelligence files PR-6 installs (/config/packages/ecco_intelligence*.yaml, /config/ecco/dashboards/ecco_intelligence*.yaml, /config/www/ecco/ecco-intelligence-card[.<sha8>].js); '$Destination' is not one of them."
}

function Invoke-EccoRetireFile {
    <#
        deploy-ha.ps1 -Action Retire, after the target guard: an exact-file
        move of one Intelligence file into /config/ecco-backups/<stamp>/ -
        never rm. Read-only checks first: the gate's policy read and classify
        (a file the site policy names is never retired; a dashboard path it
        does not name is reported under DASHBOARD_PRESERVE_GATE, so a pinned
        site gate needs the one-run -ExpectedSiteGate DASHBOARD_PRESERVE_GATE),
        the gate pin, a symlink test of every segment below /config to the
        file (/config itself was resolved by the caller right after the ssh
        probe, amendment A26), the file a regular file, and for a card file
        no Lovelace resource still loading it. Then, after a re-check that
        /config still resolves to -ConfigRoot, the backup folder (no
        recursive mkdir, behind the same root test), the move, its
        verification, and `ha core check`; a failure - a connection lost
        before the read-back included, when the message says the
        configuration check was not run - restores the file through
        Invoke-EccoDeploymentRollback (a copy back from the backup, which
        stays). Never restarts Home Assistant.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SshHost,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [Parameter(Mandatory = $true)]
        [string]$GuardPath,

        [Parameter(Mandatory = $true)]
        [string]$Python,

        [AllowNull()]
        [AllowEmptyString()]
        [string]$ExpectedGate,

        [string]$PinSource = 'the gate pin',

        # The host's persisted Lovelace resource list (named by the caller,
        # read only, for a card file).
        [Parameter(Mandatory = $true)]
        [string]$ResourcesPath,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[0-9]{8}-[0-9]{6}\z')]
        [string]$Stamp,

        # The resolved /config root (Get-EccoRemoteConfigRoot .Resolved),
        # read by the caller right after the ssh probe (amendment A26).
        [Parameter(Mandatory = $true)]
        [string]$ConfigRoot
    )

    $Destination = Test-EccoRetireDestination -Destination (Test-EccoDeploymentDestination -Destination $Destination)
    Write-Host 'Running the dashboard preservation gate (read-only, classify)...'
    $gate = Invoke-EccoDashboardPreservationGate -SshHost $SshHost -Destination $Destination -GuardPath $GuardPath -Python $Python -ClassifyOnly
    if ($gate.PolicyNamesDestination) {
        throw (Format-EccoGateBlockedMessage -Gate $gate.Gate -Reason "the site policy protects ${Destination}: a protected file is never retired.")
    }
    Write-Host $gate.GateLine
    $pinLine = Assert-EccoDashboardGatePin -GateResult $gate -ExpectedGate $ExpectedGate -PinSource $PinSource
    if ($pinLine) {
        Write-Host $pinLine
    }

    # Every segment below /config (A15); /config itself is the resolved root (A26).
    $segments = New-Object System.Collections.Generic.List[string]
    $cut = $Destination.IndexOf('/', $script:EccoConfigRoot.Length + 1)
    while ($cut -gt 0) {
        $segments.Add($Destination.Substring(0, $cut))
        $cut = $Destination.IndexOf('/', $cut + 1)
    }
    $segments.Add($Destination)
    $segments.Add($script:EccoBackupsDir)
    $states = Get-EccoRemotePathStates -SshHost $SshHost -Paths $segments.ToArray()
    foreach ($s in $segments) {
        $want = if ($s -ceq $Destination) { @('file') } elseif ($s -ceq $script:EccoBackupsDir) { @('dir', 'absent') } else { @('dir') }
        if ($want -notcontains $states[$s]) {
            throw (Format-EccoKitBlockedMessage -Name 'RETIRE' -Reason "$s is $($states[$s]) on the host (expected $($want -join ' or ')): every segment must be a real folder and the file a regular file, never a symlink.")
        }
    }

    $url = Get-EccoLovelaceResourceUrl -Destination $Destination
    if ($url) {
        $resourcesState = Get-EccoRemotePathStates -SshHost $SshHost -Paths @($ResourcesPath)
        $state = $resourcesState[$ResourcesPath]
        if ($state -eq 'file') {
            $items = ConvertFrom-EccoLovelaceResources -Json ([System.Text.Encoding]::UTF8.GetString((Read-EccoRemoteTextFile -SshHost $SshHost -Path $ResourcesPath)))
            foreach ($item in @($items)) {
                $rUrl = if ($item -and $item.PSObject.Properties['url']) { [string]$item.url } else { '' }
                if ((($rUrl -split '[?#]', 2)[0]) -ceq $url) {
                    throw (Format-EccoKitBlockedMessage -Name 'RETIRE' -Reason "a Lovelace resource still loads ${url}: remove that resource in the UI (Settings -> Dashboards -> Resources) first, then retire the file.")
                }
            }
        } elseif ($state -ne 'absent') {
            throw (Format-EccoKitBlockedMessage -Name 'RETIRE' -Reason "the Lovelace resource list $ResourcesPath is $state on the host: whether a resource still loads the card is unknown.")
        }
    }

    $originalSha = Get-EccoRemoteFileSha256 -SshHost $SshHost -Path $Destination
    if (-not $originalSha) {
        throw (Format-EccoKitBlockedMessage -Name 'RETIRE' -Reason "$Destination could not be hashed on the host.")
    }
    $backupDir = "$($script:EccoBackupsDir)/$Stamp"
    $backupPath = "$backupDir/" + ($Destination.TrimStart('/') -replace '/', '__')
    Assert-EccoRemoteConfigRootUnchanged -SshHost $SshHost -ConfigRoot $ConfigRoot -Name 'RETIRE'
    $mkdir = Invoke-EccoRemoteCommand -SshHost $SshHost -Command (Get-EccoSafeMkdirCommand -ConfigRoot $ConfigRoot -MayCreate @($script:EccoBackupsDir) -MustCreate @($backupDir)) -Capture
    if ($mkdir.ExitCode -ne 0 -or @($mkdir.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_MKDIR_OK' }).Count -ne 1) {
        throw "RETIRE: STOPPED - the backup folder $backupDir could not be created safely (/config no longer resolving to $ConfigRoot, a symlinked segment, a stamp already used, or no permission). $Destination was not moved."
    }

    Write-Host "Moving $Destination to $backupPath (no rm)..."
    $move = Invoke-EccoRemoteCommand -SshHost $SshHost -Command "[ -f '$Destination' ] && [ ! -L '$Destination' ] && [ ! -e '$backupPath' ] && [ ! -L '$backupPath' ] && mv '$Destination' '$backupPath' && echo ECCO_RETIRE_MOVED" -Capture
    $moved = ($move.ExitCode -eq 0) -and (@($move.Output | Where-Object { ([string]$_).Trim() -ceq 'ECCO_RETIRE_MOVED' }).Count -eq 1)
    $isDashboard = [bool]$gate.Applies
    if (-not $moved) {
        Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $true -Dashboard:$isDashboard -Reason "The move into the backup folder failed, or its result could not be confirmed (ssh exit code $($move.ExitCode))."
    }
    # The read-back. A transport failure here (ssh dropped right after the
    # move) leaves the host state unknown: the file may already have moved.
    # It goes through the same rollback as a mismatch, and the message says
    # that the configuration check after the move was not run.
    $verifyProblem = $null
    try {
        $after = Get-EccoRemotePathStates -SshHost $SshHost -Paths @($Destination, $backupPath)
        $backupSha = Get-EccoRemoteFileSha256 -SshHost $SshHost -Path $backupPath
    }
    catch {
        $verifyProblem = $_.Exception.Message
    }
    if ($verifyProblem) {
        Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $true -Dashboard:$isDashboard -Reason "The read-back after the move into the backup folder failed: $verifyProblem This may be an ssh/transport failure: the file may already have moved. The Home Assistant configuration check after the move was not run."
    }
    if ($after[$Destination] -ne 'absent' -or $after[$backupPath] -ne 'file' -or $backupSha -cne $originalSha) {
        $shaText = if (-not $backupSha) { 'could not be read (a possible ssh/transport failure: the file may already have moved)' } elseif ($backupSha -ceq $originalSha) { 'matches the original' } else { 'differs from the original' }
        Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $true -Dashboard:$isDashboard -Reason "The retired file could not be verified in the backup folder (destination $($after[$Destination]), backup $($after[$backupPath]), its sha256 $shaText). The Home Assistant configuration check after the move was not run."
    }
    Write-Host "Retired file verified in the backup folder: sha256 $originalSha"

    Write-Host 'Running Home Assistant configuration check...'
    $check = Invoke-EccoRemoteCommand -SshHost $SshHost -Command 'ha core check' -Capture
    $check.Output | ForEach-Object { Write-Host $_ }
    if ($check.ExitCode -ne 0) {
        Invoke-EccoDeploymentRollback -SshHost $SshHost -Destination $Destination -BackupPath $backupPath -HadOriginal $true -Dashboard:$isDashboard -Reason 'Home Assistant configuration check failed after the file was retired.'
    }
    return [pscustomobject]@{ Destination = $Destination; BackupPath = $backupPath; Sha256 = $originalSha; GateLine = $gate.GateLine; PinLine = $pinLine }
}

# endregion Intelligence kit route (PR-5)

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
    Assert-EccoDashboardGatePin, `
    Get-EccoSshConfigArguments, `
    Set-EccoSshConfigFile, `
    Format-EccoKitBlockedMessage, `
    Get-EccoBytesSha256, `
    Get-EccoParentDirs, `
    Assert-EccoDeployTargetParameters, `
    Get-EccoSshResolvedHostName, `
    Test-EccoLoopbackHostName, `
    Assert-EccoDeployTarget, `
    Test-EccoKitPackagePath, `
    ConvertFrom-EccoSumsText, `
    Test-EccoKitManifest, `
    Test-EccoKitEquivalence, `
    Assert-EccoKitGitSha, `
    Invoke-EccoKitRebuildCheck, `
    Test-EccoRemoteSafePath, `
    Get-EccoConfigRootProbeCommand, `
    ConvertFrom-EccoConfigRootProbe, `
    Get-EccoRemoteConfigRoot, `
    Assert-EccoRemoteConfigRootUnchanged, `
    Get-EccoConfigRootGuardCommand, `
    Get-EccoSafeMkdirCommand, `
    Get-EccoRemotePathStates, `
    Get-EccoKitRemoteTree, `
    Compare-EccoKitTree, `
    Get-EccoProtectedSnapshot, `
    Get-EccoConfigEntryCount, `
    Get-EccoRemoteFsFacts, `
    Get-EccoRemoteFileSha256, `
    Read-EccoRemoteTextFile, `
    Invoke-EccoNonDashboardGate, `
    Get-EccoKitSwapCommand, `
    Invoke-EccoKitRollback, `
    Invoke-EccoKitWrite, `
    Test-EccoJsonNumberBeyondDouble, `
    Get-EccoStrictJsonProblem, `
    Test-EccoSiteFile, `
    Invoke-EccoSiteFileRollback, `
    Move-EccoRejectedSiteUpload, `
    Test-EccoRetireDestination, `
    Invoke-EccoRetireFile
