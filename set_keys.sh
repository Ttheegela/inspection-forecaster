#!/bin/zsh
# Prompts for keys without echoing them and writes .env
cd "$(dirname "$0")"
read -s "m?Mistral API key: "; echo
read -s "k?Elasticsearch API key: "; echo
printf 'MISTRAL_API_KEY=%s\nES_URL=https://nyc-hacknight-ef0767.es.us-central1.gcp.elastic.cloud\nES_API_KEY=%s\n' "$m" "$k" > .env
chmod 600 .env
echo "Saved .env"
