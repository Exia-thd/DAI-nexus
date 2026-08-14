#!/usr/bin/env bash
# Install idempotent parent-repository hooks that keep a DAI Nexus submodule current.

set -euo pipefail

PROJECT_ROOT="${1:-$(pwd)}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"

if ! git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "DAI Nexus hook install denied: target is not a Git working tree: $PROJECT_ROOT" >&2
    exit 2
fi
if [[ ! -f "$PROJECT_ROOT/.gitmodules" ]]; then
    echo "DAI Nexus hook install skipped: no .gitmodules in $PROJECT_ROOT" >&2
    exit 2
fi

if [[ -d "$PROJECT_ROOT/.husky" ]]; then
    HOOKS_DIR="$PROJECT_ROOT/.husky"
else
    HOOKS_DIR="$(git -C "$PROJECT_ROOT" rev-parse --git-path hooks)"
    if [[ "$HOOKS_DIR" != /* ]]; then
        HOOKS_DIR="$PROJECT_ROOT/$HOOKS_DIR"
    fi
fi
mkdir -p "$HOOKS_DIR"

install_hook() {
    local event="$1"
    local hook_file="$HOOKS_DIR/$event"
    local marker="# DAI Nexus managed submodule auto-update"

    if [[ -f "$hook_file" ]] && grep -qF "$marker" "$hook_file"; then
        echo "DAI Nexus $event hook already installed: $hook_file"
        return
    fi
    if [[ ! -f "$hook_file" ]]; then
        printf '%s\n' '#!/usr/bin/env sh' > "$hook_file"
    fi

    cat >> "$hook_file" <<'HOOK_BLOCK'

# DAI Nexus managed submodule auto-update
DAINEXUS_PARENT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
if [ -f "$DAINEXUS_PARENT_ROOT/.gitmodules" ]; then
    DAINEXUS_SUBMODULE_PATH=$(
        git -C "$DAINEXUS_PARENT_ROOT" config --file .gitmodules --name-only --get-regexp '^submodule\..*\.path$' 2>/dev/null |
        while IFS= read -r DAINEXUS_PATH_KEY; do
            DAINEXUS_PATH_VALUE=$(git -C "$DAINEXUS_PARENT_ROOT" config --file .gitmodules --get "$DAINEXUS_PATH_KEY" 2>/dev/null || true)
            if printf '%s' "$DAINEXUS_PATH_VALUE" | grep -qi dai-nexus; then
                printf '%s\n' "$DAINEXUS_PATH_VALUE"
                break
            fi
        done
    )
    if [ -z "$DAINEXUS_SUBMODULE_PATH" ]; then
        DAINEXUS_SUBMODULE_PATH=$(
            git -C "$DAINEXUS_PARENT_ROOT" config --file .gitmodules --name-only --get-regexp '^submodule\..*\.url$' 2>/dev/null |
            while IFS= read -r DAINEXUS_URL_KEY; do
                DAINEXUS_URL_VALUE=$(git -C "$DAINEXUS_PARENT_ROOT" config --file .gitmodules --get "$DAINEXUS_URL_KEY" 2>/dev/null || true)
                if printf '%s' "$DAINEXUS_URL_VALUE" | grep -qi dai-nexus; then
                    DAINEXUS_PATH_KEY=${DAINEXUS_URL_KEY%.url}.path
                    git -C "$DAINEXUS_PARENT_ROOT" config --file .gitmodules --get "$DAINEXUS_PATH_KEY" 2>/dev/null || true
                    break
                fi
            done
        )
    fi
    if [ -z "$DAINEXUS_SUBMODULE_PATH" ]; then
        DAINEXUS_SUBMODULE_PATH=dai-nexus
    fi
    DAINEXUS_UPDATER="$DAINEXUS_PARENT_ROOT/$DAINEXUS_SUBMODULE_PATH/scripts/lite/submodule-auto-update.sh"
    if [ -x "$DAINEXUS_UPDATER" ]; then
        bash "$DAINEXUS_UPDATER" --pull
    fi
fi
# End DAI Nexus managed submodule auto-update
HOOK_BLOCK
    chmod +x "$hook_file"
    echo "Installed DAI Nexus $event hook: $hook_file"
}

install_hook post-merge
install_hook post-checkout
