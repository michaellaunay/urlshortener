#!/bin/bash
# Recompile every message catalogue and check the result.
#
# The .mo files are versioned (the running application reads them and
# never compiles anything), so forgetting this step ships a page that
# is translated in the .po and English on screen. The test suite
# catches it by parsing the .mo binary — run it right after.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

cd "${ROOT}"

for language in $(ls urlshortener/locale | grep -v '\.pot$'); do
    if [ -f "urlshortener/locale/${language}/LC_MESSAGES/urlshortener.po" ]; then
        pybabel compile -D urlshortener -d urlshortener/locale -l "${language}"
    fi
done

echo
echo "Now verify:"
echo "  pytest -q tests/test_i18n.py"
