#!/bin/zsh
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"

voicetype_fail() {
    print -u2 -- "VoiceType: $*"
    return 1
}

voicetype_check_platform() {
    if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
        voicetype_fail "Apple Silicon Macs are required."
        return 1
    fi
    local macos_version
    macos_version="$(sw_vers -productVersion)"
    if (( ${macos_version%%.*} < 15 )); then
        voicetype_fail "macOS 15 or later is required."
        return 1
    fi
    if (( EUID == 0 )); then
        voicetype_fail "Run Install.command as your normal macOS user, without sudo."
        return 1
    fi
}

voicetype_has_hammerspoon() {
    [[ -d /Applications/Hammerspoon.app || -d "$HOME/Applications/Hammerspoon.app" ]]
}

voicetype_has_speexdsp() {
    if [[ -n "${VOICETYPE_SPEEXDSP_LIBRARY:-}" ]]; then
        local library_path="${VOICETYPE_SPEEXDSP_LIBRARY/#\~/$HOME}"
        [[ -f "$library_path" ]]
    else
        [[ -f /opt/homebrew/opt/speexdsp/lib/libspeexdsp.dylib ||
           -f /usr/local/opt/speexdsp/lib/libspeexdsp.dylib ]]
    fi
}

voicetype_ensure_homebrew() {
    if command -v brew >/dev/null; then
        return 0
    fi
    print -- "Installing Homebrew from its official installer. Internet access is required."
    print -- "Homebrew may ask for your macOS administrator password and install Apple developer tools."
    local brew_script
    brew_script="$(curl -fsSL --retry 3 --connect-timeout 15 --max-time 300 \
        https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || {
        voicetype_fail "Could not download the Homebrew installer. Check your connection and run Install.command again."
        return 1
    }
    /bin/bash -c "$brew_script" || {
        voicetype_fail "Homebrew installation did not finish. Run Install.command again after resolving the error above."
        return 1
    }
    rehash
    command -v brew >/dev/null || {
        voicetype_fail "Homebrew is not available after installation."
        return 1
    }
}

voicetype_ensure_prerequisites() {
    if [[ -n "${VOICETYPE_SPEEXDSP_LIBRARY:-}" ]] && ! voicetype_has_speexdsp; then
        voicetype_fail "VOICETYPE_SPEEXDSP_LIBRARY does not point to a file."
        return 1
    fi
    local -a missing_formulae=()
    local tool_name needs_hammerspoon=0
    for tool_name in uv sox; do
        if ! command -v "$tool_name" >/dev/null; then
            missing_formulae+=("$tool_name")
        fi
    done
    if ! voicetype_has_speexdsp; then
        missing_formulae+=(speexdsp)
    fi
    if ! voicetype_has_hammerspoon; then
        needs_hammerspoon=1
    fi
    if (( ${#missing_formulae[@]} == 0 && needs_hammerspoon == 0 )); then
        return 0
    fi
    voicetype_ensure_homebrew || return 1
    if (( ${#missing_formulae[@]} > 0 )); then
        print -- "Installing missing VoiceType dependencies: ${missing_formulae[*]}"
        brew install --formula "${missing_formulae[@]}" || {
            voicetype_fail "Dependency installation failed. Run Install.command again after resolving the error above."
            return 1
        }
    fi
    if (( needs_hammerspoon )); then
        print -- "Installing Hammerspoon for VoiceType keyboard shortcuts."
        brew install --cask hammerspoon || {
            voicetype_fail "Hammerspoon installation failed. Run Install.command again after resolving the error above."
            return 1
        }
    fi
    rehash
    for tool_name in uv sox; do
        command -v "$tool_name" >/dev/null || {
            voicetype_fail "$tool_name is unavailable after installation."
            return 1
        }
    done
    voicetype_has_speexdsp && voicetype_has_hammerspoon || {
        voicetype_fail "An installed dependency is unavailable. Review the Homebrew output above."
        return 1
    }
}

if [[ "${ZSH_EVAL_CONTEXT}" == toplevel ]]; then
    voicetype_check_platform
    voicetype_ensure_prerequisites
    print -- "Installing VoiceType. Python packages and the speech model may be downloaded."
    print -- "At first use, allow macOS audio permissions and Hammerspoon Accessibility access when prompted."
    exec uv run --no-project --python 3.13 "${0:A:h}/install.py" install "$@"
fi
