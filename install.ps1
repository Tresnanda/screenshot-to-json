param(
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$AppName = "ss2json"
$RepoSlug = "Tresnanda/screenshot-to-json"
$RepoUrl = "https://github.com/$RepoSlug"
$RepoSpec = "git+https://github.com/Tresnanda/screenshot-to-json.git"

function Confirm-Step($Prompt, $DefaultYes = $true) {
    if ($Yes) { return $true }
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $DefaultYes }
    return @("y", "yes") -contains $answer.ToLowerInvariant()
}

function Offer-StarRepo {
    if ($Yes) {
        Write-Host "Star it here: $RepoUrl"
        return
    }
    if (-not (Confirm-Step "If $AppName helps you, star the GitHub repo now?" $true)) {
        Write-Host "Star it here: $RepoUrl"
        return
    }
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        try {
            & gh auth status *> $null
            if ($LASTEXITCODE -eq 0) {
                & gh repo star $RepoSlug *> $null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "[ok] Starred $RepoUrl"
                    return
                }
            }
        } catch {}
    }
    if ($env:GITHUB_TOKEN) {
        try {
            Invoke-RestMethod `
                -Method Put `
                -Uri "https://api.github.com/user/starred/$RepoSlug" `
                -Headers @{
                    "Accept" = "application/vnd.github+json"
                    "Authorization" = "Bearer $env:GITHUB_TOKEN"
                    "X-GitHub-Api-Version" = "2022-11-28"
                } *> $null
            Write-Host "[ok] Starred $RepoUrl"
            return
        } catch {}
    }
    Write-Host "Couldn't auto-star from this terminal."
    Write-Host "Star it here: $RepoUrl"
}

function Read-Choice($Prompt, $Default) {
    if ($Yes) { return $Default }
    $answer = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer
}

function Find-Python {
    foreach ($candidate in @("py", "python3", "python")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { return $candidate }
    }
    throw "Python 3 is required."
}

function Read-SecretText($Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Save-UserSecret($Name, $Value) {
    [Environment]::SetEnvironmentVariable($Name, $Value, "User")
    Set-Item -Path "Env:$Name" -Value $Value
    Write-Host "[ok] Saved $Name as a user environment variable"
    Write-Host "Open a new terminal before using it in another session."
}

function Save-ProviderConfig($Provider, $BaseUrl, $Model) {
    $configDir = Join-Path $env:APPDATA $AppName
    New-Item -ItemType Directory -Force -Path $configDir *> $null
    $configPath = Join-Path $configDir "config.toml"
    @(
        "# $AppName AI defaults. Store API keys in environment variables, not here.",
        "provider = `"$Provider`"",
        "base_url = `"$BaseUrl`"",
        "model = `"$Model`""
    ) | Set-Content -Path $configPath -Encoding UTF8
    Write-Host "[ok] Saved vision AI default to $configPath"
}

function Get-ProviderEnvKey($Provider) {
    switch ($Provider) {
        "openai" { return "OPENAI_API_KEY" }
        "gemini" { return "GEMINI_API_KEY" }
        "openrouter" { return "OPENROUTER_API_KEY" }
    }
}

function Get-ProviderBaseUrl($Provider) {
    switch ($Provider) {
        "gemini" { return "https://generativelanguage.googleapis.com/v1beta/openai/" }
        "openrouter" { return "https://openrouter.ai/api/v1" }
        default {
            if ($env:OPENAI_BASE_URL) { return $env:OPENAI_BASE_URL }
            return "https://api.openai.com/v1"
        }
    }
}

function Get-ProviderModel($Provider) {
    switch ($Provider) {
        "gemini" { return "gemini-3.5-flash" }
        "openrouter" { return "openai/gpt-4o" }
        default { return "gpt-4o" }
    }
}

function Ensure-ProviderKey($Provider) {
    $keyName = Get-ProviderEnvKey $Provider
    if ([Environment]::GetEnvironmentVariable($keyName)) {
        Write-Host "[ok] $keyName already set"
        return
    }
    if ($Yes) { return }
    Write-Host ""
    Write-Host "$keyName was not found."
    Write-Host "1) Paste API key now"
    Write-Host "2) Show me the env var command"
    Write-Host "3) Skip key setup"
    $choice = Read-Choice "Choice" "1"
    switch ($choice) {
        "1" {
            $apiKey = Read-SecretText "Enter $keyName"
            if (-not [string]::IsNullOrWhiteSpace($apiKey)) {
                Save-UserSecret $keyName $apiKey
            } else {
                Write-Host "[info] Empty key skipped"
            }
        }
        "2" {
            Write-Host "Run this later:"
            Write-Host "  [Environment]::SetEnvironmentVariable(`"$keyName`", `"your-api-key`", `"User`")"
        }
        default {
            Write-Host "[info] Skipped API key setup"
        }
    }
}

function Get-DefaultAIChoice {
    if ($env:OPENAI_API_KEY) { return "1" }
    if ($env:GEMINI_API_KEY -or $env:GOOGLE_API_KEY) { return "2" }
    if ($env:OPENROUTER_API_KEY) { return "3" }
    return "4"
}

function Setup-AIDefaults {
    if ($Yes) { return }
    Write-Host ""
    Write-Host "Choose vision AI default:"
    Write-Host "1) OpenAI API"
    Write-Host "2) Gemini API"
    Write-Host "3) OpenRouter API"
    Write-Host "4) Skip AI setup"
    $choice = Read-Choice "Choice" (Get-DefaultAIChoice)
    switch ($choice) {
        "1" { Ensure-ProviderKey "openai"; Save-ProviderConfig "openai" (Get-ProviderBaseUrl "openai") (Get-ProviderModel "openai") }
        "2" { Ensure-ProviderKey "gemini"; Save-ProviderConfig "gemini" (Get-ProviderBaseUrl "gemini") (Get-ProviderModel "gemini") }
        "3" { Ensure-ProviderKey "openrouter"; Save-ProviderConfig "openrouter" (Get-ProviderBaseUrl "openrouter") (Get-ProviderModel "openrouter") }
        default { Write-Host "[info] Skipped AI setup. You can run: $AppName config" }
    }
}

Write-Host "Install ss2json"
Write-Host "This checks Python, installs with pipx, and can set a vision AI default."
$Python = Find-Python
Write-Host "[ok] Python: $(& $Python --version 2>&1)"
if ($IsMacOS) {
    if (Get-Command screencapture -ErrorAction SilentlyContinue) {
        Write-Host "[ok] screencapture found"
    } else {
        Write-Host "[warn] screencapture not found"
    }
    if (Get-Command pngpaste -ErrorAction SilentlyContinue) {
        Write-Host "[ok] pngpaste found"
    } else {
        Write-Host "[info] pngpaste not found; clipboard mode may need: brew install pngpaste"
    }
}

try {
    & $Python -m pipx --version *> $null
    Write-Host "[ok] pipx found"
} catch {
    if (Confirm-Step "Install pipx with this Python?" $true) {
        & $Python -m pip install --user pipx
        & $Python -m pipx ensurepath *> $null
    } else {
        throw "Install pipx and rerun this installer."
    }
}

Setup-AIDefaults

Write-Host "Installing $AppName from GitHub..."
& $Python -m pipx install --force $RepoSpec
if (Get-Command $AppName -ErrorAction SilentlyContinue) {
    & $AppName --help *> $null
    Write-Host "[ok] $AppName installed"
} else {
    Write-Host "[warn] $AppName installed, but pipx bin dir may not be on PATH."
    Write-Host "Run: python -m pipx ensurepath"
}

Offer-StarRepo
Write-Host "Run ss2json in your terminal to start the guided extraction flow."
