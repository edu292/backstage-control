#!/usr/bin/env bash

set -euo pipefail

MINIMUM_SIZE=1400
STATICFILES_DIR="./staticfiles"

MANIFEST_FILE="$STATICFILES_DIR/staticfiles.json"
HASH_REGEX='\.[a-fA-F0-9]{8,}\.'

declare -A EXTENSIONS_TO_COMPRESS_SET
declare -A EXTENSIONS_TO_MINIFY_SET

EXTENSIONS_TO_COMPRESS_SET=([css]=1 [js]=1 [svg]=1 [ico]=1)
EXTENSIONS_TO_MINIFY_SET=([css]=1 [js]=1)

shopt -s globstar

for file in "$STATICFILES_DIR"/**/*.*; do
    if [[ ! -f "$file" ]]; then
      continue
    fi

    if [[ "$file" == "$MANIFEST_FILE" ]]; then
      continue
    fi

    if ! [[ "$file" =~ $HASH_REGEX ]]; then
      rm "$file"
      continue
    fi

    file_size=$(wc -c < "$file")
    if [[ "$file_size" -lt "$MINIMUM_SIZE" ]]; then
      continue
    fi

    extension="${file##*.}"

    if [[ -z "${EXTENSIONS_TO_COMPRESS_SET[$extension]:-}" ]]; then
      continue
    fi

    if [[ -n "${EXTENSIONS_TO_MINIFY_SET[$extension]:-}" ]]; then
      echo "  -> Minifying (esbuild)..."
      ./esbuild "$file" --minify "--outfile=$file" --allow-overwrite --log-level=error
    fi

    brotli --best "$file"

    gzip --best --keep "$file"

done
shopt -u globstar