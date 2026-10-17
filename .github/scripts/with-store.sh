#!/usr/bin/env bash
# Holt den Datenspeicher (Branch "data") nach ./store, führt "python -m radar <args>" aus
# und speichert die Ergebnisse zurück. Der Branch wird dabei als ein einziger Commit
# gehalten (amend + force push), damit das Repository nicht anwächst.
set -uo pipefail
REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"

rm -rf store
if git ls-remote --exit-code --heads "$REPO_URL" data >/dev/null 2>&1; then
  git clone --quiet --depth 1 --branch data "$REPO_URL" store
else
  echo "Branch 'data' existiert noch nicht – wird angelegt."
  mkdir store && git -C store init -q -b data && git -C store remote add origin "$REPO_URL"
fi

python -m radar "$@"
rc=$?

cd store
git config user.name "aktien-radar-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
if ! git diff --cached --quiet; then
  msg="Daten $(date -u +%Y-%m-%dT%H:%M:%SZ) ($*)"
  if git rev-parse -q --verify HEAD >/dev/null; then
    git commit -q --amend -m "$msg"
  else
    git commit -q -m "$msg"
  fi
  for i in 1 2 3; do
    git push -q --force origin data && break
    echo "Push fehlgeschlagen, neuer Versuch ($i)…"; sleep 5
  done
fi
exit $rc
