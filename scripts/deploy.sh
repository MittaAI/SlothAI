#!/bin/bash

# Function to display help message
show_help() {
  echo "Usage: deploy.sh [OPTIONS]"
  echo "Deploy your application."
  echo "Options:"
  echo "  -h, --help        Display this help message."
  echo "  -s, --staging     Deploy to the staging environment."
  echo "  -p, --production  Deploy to the production environment."
}

# Default environment
environment=""

filename=default
while (( $# > 0 ))
do
    opt="$1"
    shift

    case $opt in
    -h|--help)
        show_help
        exit 0
        ;;
    -s|--staging)
        environment="staging"
        shift
        ;;
    -p|--production)
        environment="production"
        shift
        ;;
    --*)
        echo "Invalid option: '$opt'" >&2
        exit 1
        ;;
    *)
        # end of long options
        break;
        ;;
   esac

done

script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Deploy based on the selected environment
if [ -n "$environment" ]; then
  echo "Deploying to $environment environment..."
  if [ "$environment" == "staging" ]; then
    gcloud app deploy "$script_dir/../app.yaml" --no-promote --version staging
  elif [ "$environment" == "production" ]; then
    gcloud app deploy "$script_dir/../app.yaml" --version production
  fi
  exit 0
else
  echo "ERROR: Deployment environment not set. Set a deployment environment by using one of the flags below."
  show_help
fi