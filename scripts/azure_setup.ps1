<#
.SYNOPSIS
    Create (or delete) the Azure storage the lake runs on, and point .env at it.

.DESCRIPTION
    Needs the Azure CLI (winget install Microsoft.AzureCLI) and `az login`.
    Creates, in one resource group:
      - a StorageV2 account with the hierarchical namespace on (ADLS Gen2, the
        data lake flavour Databricks, Fabric and Synapse use), locally redundant,
        HTTPS only, TLS 1.2+, no public blob access
      - the blob container the lake lives in
    then writes LAKE_BACKEND=azure and the connection string into .env (which git
    ignores), so `python -m greenidx all` runs against Azure.

    Cost: storage for this project is a few megabytes, so pennies a month.
    Delete everything afterwards with -Teardown.

.EXAMPLE
    .\scripts\azure_setup.ps1                  # create, with a generated account name
    .\scripts\azure_setup.ps1 -Account mylake01
    .\scripts\azure_setup.ps1 -Teardown        # delete the resource group and everything in it
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-greenidx",
    [string]$Location = "uksouth",
    # Storage account names are global: 3-24 lowercase letters and digits
    [ValidatePattern("^[a-z0-9]{3,24}$")]
    [string]$Account = ("greenidx" + (Get-Random -Minimum 10000 -Maximum 99999)),
    [string]$Container = "lake",
    [switch]$Teardown
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvFile = Join-Path $Root ".env"

function Invoke-Az([string[]]$Arguments) {
    # The CLI writes warnings to stderr: judge it by exit code only
    $ErrorActionPreference = "Continue"
    $out = & az @Arguments
    if ($LASTEXITCODE -ne 0) { throw "az $($Arguments[0..1] -join ' ') failed (exit code $LASTEXITCODE)" }
    return $out
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI not found: winget install Microsoft.AzureCLI, then open a new terminal"
}
$subscription = az account show --query name -o tsv 2>$null
if (-not $subscription) { throw "Not logged in: run az login" }
Write-Host "Subscription: $subscription"

if ($Teardown) {
    Write-Host "Deleting resource group $ResourceGroup and everything in it..."
    Invoke-Az @("group", "delete", "--name", $ResourceGroup, "--yes") | Out-Null
    Write-Host "Deleted. Set LAKE_BACKEND=local in .env to run locally again."
    return
}

# A new subscription has the storage service switched off, and then reports a
# misleading "SubscriptionNotFound": register it first (free, once per subscription)
$state = az provider show --namespace Microsoft.Storage --query registrationState -o tsv 2>$null
if ($state -ne "Registered") {
    Write-Host "Registering the Microsoft.Storage resource provider (once per subscription)..."
    Invoke-Az @("provider", "register", "--namespace", "Microsoft.Storage", "--wait") | Out-Null
}

Write-Host "Resource group $ResourceGroup ($Location)"
Invoke-Az @("group", "create", "--name", $ResourceGroup, "--location", $Location, "--output", "none") | Out-Null

Write-Host "Storage account $Account (ADLS Gen2)"
Invoke-Az @("storage", "account", "create", "--name", $Account, "--resource-group", $ResourceGroup,
    "--location", $Location, "--sku", "Standard_LRS", "--kind", "StorageV2", "--hns", "true",
    "--https-only", "true", "--min-tls-version", "TLS1_2", "--allow-blob-public-access", "false",
    "--output", "none") | Out-Null

$conn = Invoke-Az @("storage", "account", "show-connection-string", "--name", $Account,
    "--resource-group", $ResourceGroup, "--query", "connectionString", "--output", "tsv")

Write-Host "Container $Container"
Invoke-Az @("storage", "container", "create", "--name", $Container, "--connection-string", $conn,
    "--output", "none") | Out-Null

# .env: replace the lake settings, keep everything else
$settings = [ordered]@{ LAKE_BACKEND = "azure"; LAKE_CONTAINER = $Container; AZURE_STORAGE_CONNECTION_STRING = $conn }
$lines = if (Test-Path $EnvFile) { Get-Content $EnvFile | Where-Object { $_ -notmatch "^($($settings.Keys -join '|'))=" } } else { @() }
$lines += $settings.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
$lines | Set-Content $EnvFile -Encoding ascii
Write-Host "Wrote the connection to .env (git ignores it)." -ForegroundColor Green
Write-Host "Next: python -m greenidx all   (then .\scripts\azure_setup.ps1 -Teardown when done)"
