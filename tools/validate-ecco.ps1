[CmdletBinding()]
param(
    [switch]$RequireClean
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

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
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & python (Join-Path $repoRoot 'tools\validate_repo.py')
    } else {
        $py = Get-Command py -ErrorAction SilentlyContinue
        if (-not $py) {
            throw 'Python was not found. Install Python or add it to PATH.'
        }
        & py -3 (Join-Path $repoRoot 'tools\validate_repo.py')
    }

    if ($LASTEXITCODE -ne 0) {
        throw 'Repository static validation failed.'
    }

    Write-Host 'ECCO validation PASSED'
}
finally {
    Pop-Location
}
