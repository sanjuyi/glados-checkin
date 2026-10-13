#Requires -Version 5.1
<#
    push-to-github.ps1 - one-click helper: make this folder a Git repo and push it to GitHub.

    Usage (PowerShell, from this folder or anywhere):
        powershell -ExecutionPolicy Bypass -File .\push-to-github.ps1
        powershell -ExecutionPolicy Bypass -File .\push-to-github.ps1 -RepoName glados-checkin -Visibility private

    What it does:
        1. git init (branch main) if this folder is not a repo yet
        2. make sure user.name / user.email are set (asks you once if missing)
        3. commit all files
        4. create the GitHub repo + push:
             - via GitHub CLI (gh) if it is installed and logged in
             - otherwise it opens the GitHub "new repository" page, asks you to paste the repo URL,
               then pushes with Git Credential Manager (a browser login window pops up the first time)

    Notes:
        * Messages are English on purpose: Windows PowerShell 5.1 reads .ps1 files as ANSI,
          so Chinese text inside a script without a BOM would show as garbled characters.
        * git and gh write progress/warnings to stderr. Windows PowerShell would turn that into a
          fatal error under $ErrorActionPreference = 'Stop' (this actually broke the first version of
          this script), so it runs in 'Continue' mode and checks $LASTEXITCODE explicitly instead.
#>
[CmdletBinding()]
param(
    [string] $RepoName = 'glados-checkin',
    [ValidateSet('public', 'private')]
    [string] $Visibility = 'public',
    [string] $RemoteUrl = '',
    [string] $GitUserName = '',
    [string] $GitUserEmail = ''
)

$ErrorActionPreference = 'Continue'
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoDir

$script:toolExit = 0

function Info($text) { Write-Host $text -ForegroundColor Cyan }
function Ok($text) { Write-Host $text -ForegroundColor Green }
function Warn($text) { Write-Host $text -ForegroundColor Yellow }

function Run-Tool {
    <#  Runs a native command, merges its streams, returns output lines, sets $script:toolExit. #>
    param(
        [Parameter(Mandatory = $true)][string] $Tool,
        [string[]] $ToolArgs = @(),
        [switch] $ShowOutput,
        [switch] $Quiet
    )
    $output = & $Tool @ToolArgs 2>&1 | ForEach-Object { "$_" }
    $script:toolExit = $LASTEXITCODE
    if ($ShowOutput) { $output | ForEach-Object { Write-Host "    $_" } }
    elseif (-not $Quiet -and $script:toolExit -ne 0 -and $output) {
        $output | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    return $output
}

function Clean-Output {
    <#  Drops empty lines and git warning/error noise, so output can be parsed safely. #>
    param([string[]] $Lines)
    if (-not $Lines) { return @() }
    return @($Lines | Where-Object {
            $_ -and $_.Trim() -and $_.Trim() -notmatch '^(error|warning|fatal|hint):'
        })
}

function Invoke-Git {
    param([string[]] $GitArgs = @(), [switch] $ShowOutput, [switch] $Quiet)
    return Run-Tool -Tool 'git' -ToolArgs $GitArgs -ShowOutput:$ShowOutput -Quiet:$Quiet
}

Info "==> Working folder: $repoDir"

# ---------------------------------------------------------------- git present
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'git not found. Install Git for Windows first: https://git-scm.com/download/win'
}

# ---------------------------------------------------------------- init repo
if (Test-Path (Join-Path $repoDir '.git')) {
    Info '==> Existing git repo detected'
} else {
    Info '==> git init (branch: main)'
    Invoke-Git @('init', '-b', 'main') -Quiet | Out-Null
    if ($script:toolExit -ne 0) {
        Invoke-Git @('init') -Quiet | Out-Null
        Invoke-Git @('checkout', '-b', 'main') -Quiet | Out-Null
    }
}

# ---------------------------------------------------------------- identity
$currentName = Clean-Output (Invoke-Git @('config', 'user.name') -Quiet) | Select-Object -First 1
$currentMail = Clean-Output (Invoke-Git @('config', 'user.email') -Quiet) | Select-Object -First 1

if (-not $GitUserName -and -not $currentName) {
    $GitUserName = Read-Host 'Your git user name (shows up in commit messages, e.g. your-github-login)'
}
if (-not $GitUserEmail -and -not $currentMail) {
    $GitUserEmail = Read-Host 'Your git email (e.g. you@example.com)'
}
if ($GitUserName) { Invoke-Git @('config', 'user.name', $GitUserName) -Quiet | Out-Null }
if ($GitUserEmail) { Invoke-Git @('config', 'user.email', $GitUserEmail) -Quiet | Out-Null }

$name = Clean-Output (Invoke-Git @('config', 'user.name') -Quiet) | Select-Object -First 1
$mail = Clean-Output (Invoke-Git @('config', 'user.email') -Quiet) | Select-Object -First 1
if (-not $name -or -not $mail) { throw 'git user.name / user.email are still empty, aborted.' }
Ok "==> commit identity: $name <$mail>"

# ---------------------------------------------------------------- commit
Info '==> Staging and committing files'
Invoke-Git @('add', '-A') -Quiet | Out-Null
$staged = Clean-Output (Invoke-Git @('diff', '--cached', '--name-only') -Quiet)

if ($staged.Count -gt 0) {
    $commitOut = Invoke-Git @('commit', '-m', 'chore: add GLaDOS auto check-in workflow') -Quiet
    if ($script:toolExit -ne 0) { throw ("git commit failed:`n" + ($commitOut -join "`n")) }
    Ok "==> Committed $($staged.Count) file(s)"
} else {
    Info '==> Nothing new to commit'
}

# ---------------------------------------------------------------- remote + push
$originUrl = Clean-Output (Invoke-Git @('remote', 'get-url', 'origin') -Quiet) | Select-Object -First 1
$hasOrigin = [bool]$originUrl
$pushed = $false

if ($hasOrigin) {
    Ok "==> origin already set: $originUrl"
} elseif ($RemoteUrl) {
    Invoke-Git @('remote', 'add', 'origin', $RemoteUrl) -Quiet | Out-Null
    if ($script:toolExit -ne 0) { throw "Could not add remote '$RemoteUrl'." }
    Ok "==> origin added: $RemoteUrl"
} else {
    $ghReady = $false
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        Run-Tool -Tool 'gh' -ToolArgs @('auth', 'status') -Quiet | Out-Null
        if ($script:toolExit -eq 0) { $ghReady = $true }
    }

    if ($ghReady) {
        Info "==> Creating GitHub repo '$RepoName' ($Visibility) via gh and pushing"
        Run-Tool -Tool 'gh' -ToolArgs @('repo', 'create', $RepoName, "--$Visibility", '--source', '.', '--push') -ShowOutput | Out-Null
        if ($script:toolExit -eq 0) { $pushed = $true }
        else { Warn '==> gh repo create failed (a repo with this name may already exist), falling back to manual mode' }
    }

    if (-not $pushed) {
        Warn '==> GitHub CLI (gh) is not available / not logged in. Manual mode:'
        $newUrl = "https://github.com/new?name=$RepoName"
        Info "    1. A browser will open now. Create an EMPTY repo named '$RepoName'."
        Info '       Do NOT add a README / .gitignore / license there.'
        Info "    2. Copy its HTTPS URL, it looks like: https://github.com/<you>/$RepoName.git"
        Start-Process $newUrl
        $RemoteUrl = (Read-Host 'Paste the repo HTTPS URL here, then press Enter').Trim()
        if ([string]::IsNullOrWhiteSpace($RemoteUrl)) { throw 'No remote URL given, aborted.' }
        Invoke-Git @('remote', 'add', 'origin', $RemoteUrl) -Quiet | Out-Null
        if ($script:toolExit -ne 0) { throw "Could not add remote '$RemoteUrl'." }
        Ok "==> origin added: $RemoteUrl"
    }
}

if (-not $pushed) {
    Info '==> git push -u origin main'
    Warn '    (the first push may open a browser window to sign in to GitHub - that is Git Credential Manager)'
    $pushOut = Invoke-Git @('push', '-u', 'origin', 'main')
    if ($script:toolExit -ne 0) {
        throw ("Push failed. Check the remote URL and your GitHub login, then run: git push -u origin main`n" +
            ($pushOut -join "`n"))
    }
}

Ok ''
Ok '==> Done. The remaining steps must be done in the browser:'
Ok ''
Ok '  1) Repo -> Settings -> Secrets and variables -> Actions -> New repository secret'
Ok '       GLADOS_COOKIE_1   = the cookie you copied from glados.rocks'
Ok '         (it must contain BOTH koa:sess and koa:sess.sig, joined with "; ")'
Ok '       (optional) GLADOS_COOKIE_2 / _3 ... for more accounts (numbering must be consecutive)'
Ok '       (optional) TG_BOT_TOKEN, TG_CHAT_ID for Telegram notifications'
Ok ''
Ok '  2) Repo -> Actions tab -> if it says workflows are disabled, click "I understand my workflows, go ahead and enable them"'
Ok ''
Ok '  3) Repo -> Actions -> "GLaDOS auto check-in" -> Run workflow (button on the right) to test once'
Ok '     The run page shows a result summary; after that it runs by itself daily at 01:00 UTC (09:00 Beijing).'
