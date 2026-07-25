#!/usr/bin/env bash

set -euo pipefail

export PYNETFT_CURL_PREFIX="${PYNETFT_CURL_PREFIX:-${RUNNER_TEMP:-/tmp}/pynetft-curl}"
exec bash "$(dirname "${BASH_SOURCE[0]}")/build_static_curl.sh"
