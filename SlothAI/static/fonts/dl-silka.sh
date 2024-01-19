#!/bin/bash

# Define an array of URLs
urls=(
    "https://postgresml.org/dashboard/static/fonts/silka-bold-webfont.eot"
    "https://postgresml.org/dashboard/static/fonts/silka-bold-webfont.eot?#iefix"
    "https://postgresml.org/dashboard/static/fonts/silka-bold-webfont.woff2"
    "https://postgresml.org/dashboard/static/fonts/silka-bold-webfont.woff"
    "https://postgresml.org/dashboard/static/fonts/silka-bold-webfont.ttf"
    "https://postgresml.org/dashboard/static/fonts/silka-extralight-webfont.eot"
    "https://postgresml.org/dashboard/static/fonts/silka-extralight-webfont.eot?#iefix"
    "https://postgresml.org/dashboard/static/fonts/silka-extralight-webfont.woff2"
    "https://postgresml.org/dashboard/static/fonts/silka-extralight-webfont.woff"
    "https://postgresml.org/dashboard/static/fonts/silka-extralight-webfont.ttf"
    "https://postgresml.org/dashboard/static/fonts/silka-light-webfont.eot"
    "https://postgresml.org/dashboard/static/fonts/silka-light-webfont.eot?#iefix"
    "https://postgresml.org/dashboard/static/fonts/silka-light-webfont.woff2"
    "https://postgresml.org/dashboard/static/fonts/silka-light-webfont.woff"
    "https://postgresml.org/dashboard/static/fonts/silka-light-webfont.ttf"
    "https://postgresml.org/dashboard/static/fonts/silka-medium-webfont.eot"
    "https://postgresml.org/dashboard/static/fonts/silka-medium-webfont.eot?#iefix"
    "https://postgresml.org/dashboard/static/fonts/silka-medium-webfont.woff2"
    "https://postgresml.org/dashboard/static/fonts/silka-medium-webfont.woff"
    "https://postgresml.org/dashboard/static/fonts/silka-medium-webfont.ttf"
    "https://postgresml.org/dashboard/static/fonts/silka-regular-webfont.eot"
    "https://postgresml.org/dashboard/static/fonts/silka-regular-webfont.eot?#iefix"
    "https://postgresml.org/dashboard/static/fonts/silka-regular-webfont.woff2"
    "https://postgresml.org/dashboard/static/fonts/silka-regular-webfont.woff"
    "https://postgresml.org/dashboard/static/fonts/silka-regular-webfont.ttf"
    "https://postgresml.org/dashboard/static/fonts/silka-semibold-webfont.eot"
    "https://postgresml.org/dashboard/static/fonts/silka-semibold-webfont.eot?#iefix"
    "https://postgresml.org/dashboard/static/fonts/silka-semibold-webfont.woff2"
    "https://postgresml.org/dashboard/static/fonts/silka-semibold-webfont.woff"
    "https://postgresml.org/dashboard/static/fonts/silka-semibold-webfont.ttf"
    "https://postgresml.org/dashboard/static/fonts/silka-thin-webfont.eot"
    "https://postgresml.org/dashboard/static/fonts/silka-thin-webfont.eot?#iefix"
    "https://postgresml.org/dashboard/static/fonts/silka-thin-webfont.woff2"
    "https://postgresml.org/dashboard/static/fonts/silka-thin-webfont.woff"
    "https://postgresml.org/dashboard/static/fonts/silka-thin-webfont.ttf"
)

# Loop through each URL and use curl to download the file
for url in "${urls[@]}"; do
    filename=$(basename "$url")
    curl -o "$filename" "$url"
done

