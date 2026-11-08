[CmdletBinding()]
param(
    [switch]$RequireClean,

    # The Python that runs tools/validate_repo.py (it needs PyYAML).
    # deploy-ha.ps1 and deploy-ha-kit.ps1 pass their own -Python, so a route
    # never falls back to the python on PATH without a word (review L3W-5).
    # Without it: the python on PATH, else the py launcher. The interpreter
    # used is always printed.
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# -Python is resolved here, in the caller's location, before this script
# moves to the repository root: a relative -Python names the same file the
# route's own `& $Python` calls (the guard, the rebuild) run, never one under
# the repository root (review DRD-6). An application runs by its full path.
$givenPython = @()
$pythonCommand = $Python
if ($Python) {
    $givenPython = @(Get-Command -Name $Python -ErrorAction SilentlyContinue)
    if ($givenPython.Count -gt 0 -and $givenPython[0].CommandType -eq 'Application' -and $givenPython[0].Source) {
        $pythonCommand = $givenPython[0].Source
    }
}

Push-Location $repoRoot
try {
    Write-Host 'ECCO validation'
    Write-Host "Repository: $repoRoot"

    & git rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Not inside a Git working tree.'
    }

    Write-Host '[1/4] git diff --check'
    & git diff --check
    if ($LASTEXITCODE -ne 0) {
        throw 'git diff --check failed.'
    }

    Write-Host '[2/4] working-tree state'
    $dirty = @(& git status --porcelain)
    if ($RequireClean -and $dirty.Count -gt 0) {
        $dirty | ForEach-Object { Write-Host "  $_" }
        throw 'Working tree is not clean.'
    }
    if ($dirty.Count -gt 0) {
        Write-Warning 'Working tree has local changes. Validation will continue.'
    } else {
        Write-Host 'Working tree clean.'
    }

    Write-Host '[3/4] PowerShell syntax'
    $psFiles = @(Get-ChildItem -Path (Join-Path $repoRoot 'tools') -Include '*.ps1', '*.psm1' -File -Recurse)
    foreach ($file in $psFiles) {
        $tokens = $null
        $parseIssues = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $file.FullName,
            [ref]$tokens,
            [ref]$parseIssues
        ) | Out-Null

        if ($parseIssues -and $parseIssues.Count -gt 0) {
            foreach ($issue in $parseIssues) {
                Write-Host "  $($file.Name):$($issue.Extent.StartLineNumber): $($issue.Message)"
            }
            throw "PowerShell parse failed: $($file.Name)"
        }
    }
    Write-Host "PowerShell scripts parsed: $($psFiles.Count)"

    Write-Host '[4/4] repository static validator'
    $validator = Join-Path $repoRoot 'tools\validate_repo.py'
    if ($Python) {
        # Exactly the interpreter the caller named, resolved above as the
        # caller's own `& $Python` calls resolve it; a name that does not
        # resolve stops here (never the python on PATH instead).
        if ($givenPython.Count -eq 0) {
            throw "The Python given with -Python was not found: $Python"
        }
        $shown = if ($givenPython[0].Source) { $givenPython[0].Source } else { $Python }
        Write-Host "Python: $shown (-Python)"
        & $pythonCommand $validator
    } else {
        $pathPython = Get-Command python -ErrorAction SilentlyContinue
        if ($pathPython) {
            Write-Host "Python: $($pathPython.Source) (the python on PATH; no -Python given)"
            & python $validator
        } else {
            $py = Get-Command py -ErrorAction SilentlyContinue
            if (-not $py) {
                throw 'Python was not found. Install Python or add it to PATH.'
            }
            Write-Host 'Python: py -3 (the py launcher; no -Python given)'
            & py -3 $validator
        }
    }

    if ($LASTEXITCODE -ne 0) {
        throw 'Repository static validation failed.'
    }

    Write-Host 'ECCO validation PASSED'
}
finally {
    Pop-Location
}
