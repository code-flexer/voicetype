#!/bin/zsh
set -eu
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"
exec uv run --no-project --python 3.13 "${0:A:h}/install.py" uninstall "$@"
