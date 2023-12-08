#!/bin/bash

# Get your public IP address
MY_IP=$(curl -s https://ipinfo.io/ip)

# Replace periods with hyphens to create a valid name
FIREWALL_RULE_NAME="allow-sloth-$(echo $MY_IP | tr '.' '-')"

# Replace "sloth" with your actual network tag
NETWORK_TAG="sloth"

# Create a firewall rule allowing incoming traffic from your IP address if it doesn't exist
if ! gcloud compute firewall-rules describe "$FIREWALL_RULE_NAME" &>/dev/null; then
    gcloud compute firewall-rules create $FIREWALL_RULE_NAME \
        --action=ALLOW \
        --direction=INGRESS \
        --target-tags=$NETWORK_TAG \
        --source-ranges=$MY_IP \
        --rules=tcp:8787  # You can customize the allowed ports
fi

flask --app SlothAI run --port 8080 --debug
