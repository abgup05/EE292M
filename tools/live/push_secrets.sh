#!/bin/sh
# Copy the two values the live site needs from this container's environment (given by the
# compose file's env_file, never printed) into the Vercel project's environment variables,
# using the login the Vercel CLI already saved on this machine. Run by `make site-secrets`.
#
#   MODE=check   say what is present (names and yes/no only) and stop
#   MODE=push    set the variables for the production environment
#   REDEPLOY=1   after a push, redeploy production so the running site reads them
#
# Nothing here prints a value, a token or the contents of a credential file.
set -eu

PROJECT="${VERCEL_PROJECT:-ee292m-visualization}"
AUTH="$HOME/.local/share/com.vercel.cli"
NAMES="ANTHROPIC_API_KEY SEC_USER_AGENT"
MODE="${MODE:-check}"

present() { eval "v=\${$1:-}"; if [ -n "$v" ]; then echo yes; else echo no; fi; }

echo "Values in the environment file:"
for name in $NAMES; do echo "  $name: $(present "$name")"; done

if [ ! -f "$AUTH/auth.json" ]; then
  echo "No saved Vercel login was found on this machine (auth.json is missing)."
  echo "Log in once with the Vercel CLI, or set the variables in the Vercel dashboard."
  exit 2
fi
# Key names only, so a rotating login can be told from a plain token.
echo "Saved Vercel login: found; its fields: $(tr -d '\n' < "$AUTH/auth.json" | grep -o '"[A-Za-z_]*"[[:space:]]*:' | tr -d '": ' | tr '\n' ' ')"

# A login with an expiry is refreshed by the CLI when it has run out. The saved login is mounted
# at the CLI's own path, writable, so a refreshed login is saved where the machine's own CLI
# reads it and nobody is signed out.
expires=$(tr -d '\n' < "$AUTH/auth.json" | grep -o '"expiresAt"[[:space:]]*:[[:space:]]*[0-9]*' | grep -o '[0-9]*$' || true)
if [ -n "$expires" ]; then
  now=$(date +%s)
  if [ "$expires" -gt 9999999999 ]; then expires=$((expires / 1000)); fi
  left=$(( (expires - now) / 60 ))
  if [ "$left" -gt 5 ]; then echo "Saved Vercel login: good for another $left minutes."
  else echo "Saved Vercel login: ran out $(( -left )) minutes ago; the CLI will try to refresh it."; fi
fi

if [ "$MODE" = "check" ]; then exit 0; fi

mkdir -p /tmp/work
npm install --global --silent vercel@latest > /dev/null 2>&1
echo "Vercel CLI $(vercel --version 2> /dev/null | tail -1)"
if vercel whoami > /tmp/who.log 2>&1; then echo "Signed in to Vercel."
else echo "The saved Vercel login could not be refreshed; sign in again with the Vercel CLI:"; grep -v -i 'token' /tmp/who.log | tail -3; exit 2; fi
cd /tmp/work
vercel link --yes --project "$PROJECT" > /tmp/link.log 2>&1 || { echo "Could not link the project $PROJECT:"; tail -3 /tmp/link.log; exit 3; }
echo "Linked to the project $PROJECT."

for name in $NAMES; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then echo "  $name: empty in the environment file, left as it is on Vercel"; continue; fi
  vercel env rm "$name" production --yes > /dev/null 2>&1 || true
  if printf '%s' "$value" | vercel env add "$name" production --sensitive > /tmp/add.log 2>&1; then
    echo "  $name: set for production"
  else
    echo "  $name: could not be set:"; tail -2 /tmp/add.log; exit 4
  fi
done

echo "Variables now on the project (names only):"
vercel env ls production 2> /dev/null | awk 'NR>1 && $1 ~ /^[A-Z_]+$/ {print "  " $1}'

if [ "${REDEPLOY:-}" = "1" ]; then
  url=$(vercel ls --prod --yes 2> /dev/null | grep -o 'https://[^ ]*' | head -1)
  test -n "$url" || { echo "Could not find the production deployment to redeploy."; exit 5; }
  vercel redeploy "$url" --target production > /tmp/redeploy.log 2>&1 && echo "Redeployed production." || { echo "Redeploy failed:"; tail -3 /tmp/redeploy.log; exit 6; }
fi
