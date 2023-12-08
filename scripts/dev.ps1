# Get your public IP address
$MY_IP = Invoke-RestMethod -Uri "https://ipinfo.io/ip"

$env:GOOGLE_APPLICATION_CREDENTIALS="./credentials.json"

# Replace periods with hyphens to create a valid name
$FIREWALL_RULE_NAME = "allow-sloth-$($MY_IP -replace '\.', '-')"

# Replace "sloth" with your actual network tag
$NETWORK_TAG = "sloth"

# Check if the firewall rule already exists
$existingRule = gcloud compute firewall-rules describe $FIREWALL_RULE_NAME --format="value(name)" --project=YOUR_PROJECT_ID 2>$null

if (-not $existingRule) {
    # Create a firewall rule allowing incoming traffic from your IP address if it doesn't exist
    gcloud compute firewall-rules create $FIREWALL_RULE_NAME `
        --action=ALLOW `
        --direction=INGRESS `
        --target-tags=$NETWORK_TAG `
        --source-ranges=$MY_IP `
        --rules=tcp:8787  # You can customize the allowed ports
}

# Start the Flask application
flask --app SlothAI run --with-threads --port 8080 --debug