#!/usr/bin/env bash
# Installs every Claude skill this project depends on.
# Safe to re-run; already-installed skills are skipped by the CLI.
set -euo pipefail

SKILLS=(
  # core pipeline
  "googleworkspace/cli@gws-sheets"
  "affaan-m/ecc@data-scraper-agent"
  "affaan-m/ecc@deep-research"
  "affaan-m/ecc@python-patterns"

  # reddit
  "lignertys/reddit-research-skills@reddapi"
  "lignertys/reddit-research-skills@reddit-leads"
  "lignertys/reddit-research-skills@reddit-search-api"

  # discovery
  "hoodini/ai-agents-skills@github-trending"

  # c++
  "affaan-m/ecc@cpp-coding-standards"
  "affaan-m/ecc@cpp-testing"

  # ml + cost control
  "affaan-m/ecc@mle-workflow"
  "affaan-m/ecc@cost-aware-llm-pipeline"
  "affaan-m/ecc@browser-qa"
)

failed=()

for pkg in "${SKILLS[@]}"; do
  printf '==> %s\n' "$pkg"
  npx -y skills add "$pkg" -g -y || failed+=("$pkg")
done

echo
if [ ${#failed[@]} -eq 0 ]; then
  echo "All ${#SKILLS[@]} skills installed."
else
  echo "Failed: ${failed[*]}"
  exit 1
fi

cat <<'EOF'

Next:
  1. Restart Claude Code so the skills load.
  2. ollama pull nomic-embed-text
     ollama pull qwen3.5:4b-instruct-q4_K_M
     ollama pull gpt-oss:20b
  3. brew install cmake
EOF
