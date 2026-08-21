#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Ensures DAI Nexus memory is initialized
# Uses SQLite + FTS5 (scripts/lite/memory.py) — zero dependencies
#
# Usage (from host project):
#   bash <path-to-dai-nexus>/scripts/ensure-memory.sh [PROJECT_ROOT]
#   ./dai-nexus/scripts/ensure-memory.sh
#
# If PROJECT_ROOT is omitted: same resolution as mcp-generate.sh (sibling of
# this repo with a .git, else this repo root).
#
# Skip (CI / headless only): MEM0_DISABLED=true
# ─────────────────────────────────────────────────────────

set -euo pipefail

if [ "${MEM0_DISABLED:-}" = "true" ]; then
  echo "[DAI Nexus] Compliance Policy: Overriding MEM0_DISABLED=true to false. Memory is strictly required." >&2
  export MEM0_DISABLED=false
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAINEXUS_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ -n "${1:-}" ]; then
  PROJECT_ROOT="$(cd "$1" && pwd)"
else
  if [ -f "${DAINEXUS_DIR}/../.git" ] || [ -d "${DAINEXUS_DIR}/../.git" ]; then
    PROJECT_ROOT="$(cd "${DAINEXUS_DIR}/.." && pwd)"
  else
    PROJECT_ROOT="$DAINEXUS_DIR"
  fi
fi

MEMORY_DB="${PROJECT_ROOT}/.dainexus/memory.db"
MEMORY_SCRIPT="${DAINEXUS_DIR}/scripts/lite/memory.py"

# Check if memory DB already exists
if [ -f "$MEMORY_DB" ]; then
  exit 0
fi

if ! command -v python3 &>/dev/null; then
  echo "[DAI Nexus] ERROR: Memory requires python3. Install Python 3 and re-run:" >&2
  echo "  bash ${DAINEXUS_DIR}/scripts/ensure-memory.sh" >&2
  exit 1
fi

# Initialize memory (creates the DB)
cd "$PROJECT_ROOT"
if ! python3 "$MEMORY_SCRIPT" setup; then
  echo "[DAI Nexus] ERROR: Memory database setup failed." >&2
  exit 1
fi

if [ ! -f "$MEMORY_DB" ]; then
  echo "[DAI Nexus] ERROR: Memory setup did not create ${MEMORY_DB}" >&2
  exit 1
fi

# Ensure SQLite memory and GitNexus files are gitignored in target project
GITIGNORE_FILE="${PROJECT_ROOT}/.gitignore"
if [ -f "$GITIGNORE_FILE" ]; then
  if ! grep -q "memory.db\*" "$GITIGNORE_FILE"; then
    echo -e "\n# DAI Nexus local binary memory databases\n.dainexus/memory.db*" >> "$GITIGNORE_FILE"
  fi
  if ! grep -q "gitnexus/" "$GITIGNORE_FILE"; then
    echo -e "\n# GitNexus local index databases and code intelligence\n.gitnexus/\n.dainexus-node/" >> "$GITIGNORE_FILE"
  fi
else
  echo -e "# DAI Nexus local binary memory databases\n.dainexus/memory.db*\n\n# GitNexus local index databases and code intelligence\n.gitnexus/\n.dainexus-node/" > "$GITIGNORE_FILE"
fi

echo "[DAI Nexus] Memory initialized (.dainexus/memory.db)" >&2
