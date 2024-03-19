# Function to display help message
function Show-Help {
    Write-Host "Usage: deploy.ps1 [OPTIONS]"
    Write-Host "Deploy your application."
    Write-Host "Options:"
    Write-Host " -h, --help         Display this help message."
    Write-Host " -s, --staging      Deploy to the staging environment."
    Write-Host " -p, --production   Deploy to the production environment."
}

# Default environment
$environment = ""
$filename = "default"

# Parse command-line arguments
$args | ForEach-Object {
    switch ($_) {
        "-h" { Show-Help; exit 0 }
        "--help" { Show-Help; exit 0 }
        "-s" { $environment = "staging"; break }
        "--staging" { $environment = "staging"; break }
        "-p" { $environment = "production"; break }
        "--production" { $environment = "production"; break }
        "--*" { Write-Error "Invalid option: '$_'"; exit 1 }
        default { break }
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Deploy based on the selected environment
if ($environment) {
    Write-Host "Deploying to $environment environment..."
    if ($environment -eq "staging") {
        gcloud app deploy "$scriptDir\..\app.yaml" --no-promote --version staging
    }
    elseif ($environment -eq "production") {
        gcloud app deploy "$scriptDir\..\app.yaml" --version production
    }
    exit 0
}
else {
    Write-Error "ERROR: Deployment environment not set. Set a deployment environment by using one of the flags below."
    Show-Help
}