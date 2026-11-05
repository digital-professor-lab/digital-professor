#!/usr/bin/env bash
# Check out the exact Week 3 commit into .week3/ (ignored by git). Safe to run again.
# Needs network access to the team repository. No Docker, API key or model download.
set -euo pipefail

WEEK3_COMMIT="9f27fae12f9ef6c3a78ad908cdbd56a952fb2e13"   # branch Sean/-Retrieval-working, the Week 3 retrieval package
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$HERE/.week3"

if [ -d "$TARGET/.git" ] || [ -f "$TARGET/.git" ]; then
  CURRENT="$(git -C "$TARGET" rev-parse HEAD)"
  if [ "$CURRENT" = "$WEEK3_COMMIT" ]; then
    echo "Week 3 already at $WEEK3_COMMIT in $TARGET"
    exit 0
  fi
  echo "Moving $TARGET from $CURRENT to $WEEK3_COMMIT"
  git -C "$TARGET" fetch --depth 1 origin "$WEEK3_COMMIT"
  git -C "$TARGET" checkout --quiet --detach "$WEEK3_COMMIT"
else
  URL="$(git -C "$HERE" remote get-url origin 2>/dev/null || echo https://github.com/digital-professor-lab/digital-professor.git)"
  mkdir -p "$TARGET"
  git -C "$TARGET" init --quiet
  git -C "$TARGET" remote add origin "$URL"
  GIT_LFS_SKIP_SMUDGE=1 git -C "$TARGET" fetch --quiet --depth 1 origin "$WEEK3_COMMIT"
  git -C "$TARGET" checkout --quiet --detach "$WEEK3_COMMIT"
fi

ACTUAL="$(git -C "$TARGET" rev-parse HEAD)"
if [ "$ACTUAL" != "$WEEK3_COMMIT" ]; then
  echo "Expected $WEEK3_COMMIT but found $ACTUAL" >&2
  exit 1
fi
test -f "$TARGET/data/catalog/passages.jsonl"
echo "Week 3 ready at $ACTUAL in $TARGET"
