<#
    .SYNOPSIS
    MittaAI Developer Startup Script

    .DESCRIPTION
    This script prepares the development environment for MittaAI's SlothAI framework. It checks for necessary tools,
    verifies the existence and activation of the 'slothai' Conda environment, sets up firewall rules via gcloud,
    checks if ngrok is running, and starts a Flask application. Designed for ease of setup for developers.

    .REQUIREMENTS
    - Conda must be installed and accessible from the current PATH.
    - Google Cloud SDK (gcloud) must be installed and configured.
    - An active internet connection to retrieve the public IP and interact with Google Cloud services.
    - Ngrok must be installed if requiring external access to the Flask application.

    .NOTES
    Copyright Mitta Corp. and Kord Campbell, 2024
    Version: 1.0

    .EXAMPLE
    To run this script, navigate to the script's directory and execute:
    ./MittaAIDevStartup.ps1

#>

$envName = "slothai" # The name of the Conda environment you're checking for

# Function to check if a command exists
function Test-CommandExists {
    param (
        [string]$Command
    )
    $exists = $false
    try {
        if (Get-Command $Command -ErrorAction Stop) {
            $exists = $true
        }
    } catch {
        $exists = $false
    }
    return $exists
}

# Check if Conda is installed by checking for the 'conda' command
if (Test-CommandExists -Command "conda") {
    # Run 'conda info --envs' and search for the environment name
    $envExists = conda info --envs | Select-String $envName

    if ($envExists) {
        Write-Host "The Conda environment '$envName' exists."
    } else {
        Write-Host "The Conda environment '$envName' does not exist."
        Write-Host "Use 'conda create -n slothai python=3.10' to create the environment."
        exit
    }
} else {
    Write-Host "Conda is not installed or not available in the current PATH. Please install Conda or check your installation."
    exit
}

# Check if gcloud is installed by checking for the 'gcloud' command
if (Test-CommandExists -Command "gcloud") {
    Write-Host "gcloud is installed."
    # Additional gcloud specific operations can be performed here if necessary
} else {
    Write-Host "gcloud is not installed or not available in the current PATH. Please install Google Cloud SDK or check your installation."
    exit
}

# Get your public IP address
$MY_IP = Invoke-RestMethod -Uri "https://ipinfo.io/ip"

$env:GOOGLE_APPLICATION_CREDENTIALS="./credentials.json"

# Replace periods with hyphens to create a valid name
$FIREWALL_RULE_NAME = "allow-sloth-$($MY_IP -replace '\.', '-')"

# Replace "sloth" with your actual network tag
$NETWORK_TAG = "sloth"

# Check if the firewall rule already exists
try {
    $existingRule = gcloud compute firewall-rules describe $FIREWALL_RULE_NAME --format="value(name)" --project=YOUR_PROJECT_ID --quiet 2>$null
    if ($existingRule) {
        Write-Host "Firewall rule '$FIREWALL_RULE_NAME' already exists."
    }
} catch {
    # If the rule doesn't exist, the command to check will throw an error, so we catch that and proceed to create the rule
    gcloud compute firewall-rules create $FIREWALL_RULE_NAME `
        --action=ALLOW `
        --direction=INGRESS `
        --target-tags=$NETWORK_TAG `
        --source-ranges=$MY_IP `
        --rules=tcp:8787 `
        --quiet 2>$null
    Write-Host "Created firewall rule '$FIREWALL_RULE_NAME'."
}

# Check if ngrok is running
$ngrokProcess = Get-Process ngrok -ErrorAction SilentlyContinue
if (-not $ngrokProcess) {
    Write-Host "Ngrok is not running. Please start it with 'ngrok http --subdomain=<your_subdomain> 8080' to expose the app."
    exit
} else {
    Write-Host "Ngrok is currently running."
}

if ($env:CONDA_DEFAULT_ENV -eq "slothai") {
    Write-Host "The 'slothai' environment is active."
} else {
    Write-Host "The 'slothai' environment is not active."
    Write-Host "Please run 'conda activate slothai' then restart the dev script."
    exit
}

# Start the Flask application
flask --app SlothAI run --with-threads --port 8080 --debug