#!/usr/bin/env bash
# Runs osv-scanner, retrying when the tool itself fails to complete the scan
# (e.g. it cannot reach api.osv.dev), so a transient outage is never reported
# as "vulnerabilities found" or, worse, silently as clean (issue personal-finance#32).
#
# osv-scanner's own documented exit codes
# (https://google.github.io/osv-scanner/output/), reproduced empirically
# 2026-09-05 against a real vulnerable lockfile (lodash@4.17.4) and a forced
# network failure (HTTPS_PROXY/HTTP_PROXY pointed at an unreachable host):
#   0   -> no vulnerabilities found
#   1   -> vulnerabilities found
#   127 -> the tool failed to complete the scan. IMPORTANT: on this failure
#          osv-scanner's own text report still printed
#          "Total 0 packages affected by 0 known vulnerabilities" - reading
#          the report text instead of the real exit code would have read as
#          clean, which is worse than the npm 503 case this issue started
#          with, since there the endpoint at least said it had failed.
#   128 -> no packages were found to scan. Not a transient failure - most
#          likely the scan path or a manifest pattern is wrong. Retrying
#          will not help, so this is reported and failed immediately, never
#          retried and never treated as a network-shaped "unknown".
#
# IMPORTANT: this must invoke the osv-scanner *binary* (installed with
# `go install .../osv-scanner@<pinned version>`), never
# `go run github.com/google/osv-scanner/v2/cmd/osv-scanner@<version>`. `go run`
# does not propagate the wrapped program's exit code - it normalizes every
# non-zero exit to 1, collapsing all three non-clean codes above (1, 127, 128)
# into one signal. Verified empirically 2026-09-05: the compiled v2.5.1 binary
# returns 0/1/127/128 for the four cases above, but `go run` of the identical
# version and inputs returned 1 in every non-clean case, including the
# network-failure one where osv-scanner's own text output claimed "0 known
# vulnerabilities" - `go run` would have made that unrecoverable at the
# exit-code level too, with no way left to tell it apart from a real finding.
#
# The command run on each attempt is overridable via OSV_SCANNER_CMD so this
# logic can be exercised by osv-scanner-gate.test.sh with a fake command,
# without needing network access or a real vulnerable dependency.
set -u

ATTEMPTS="${OSV_SCANNER_ATTEMPTS:-3}"
DELAY_SECONDS="${OSV_SCANNER_RETRY_DELAY:-10}"
OSV_SCANNER_CMD="${OSV_SCANNER_CMD:-osv-scanner scan source --no-call-analysis=go --config=osv-scanner.toml -r .}"

EXIT_CODE=0
for attempt in $(seq 1 "$ATTEMPTS"); do
  OUTPUT="$(eval "$OSV_SCANNER_CMD" 2>&1)"
  EXIT_CODE=$?

  case "$EXIT_CODE" in
    0)
      echo "$OUTPUT"
      echo "osv-scanner: clean."
      exit 0
      ;;
    1)
      echo "$OUTPUT"
      echo "::error::osv-scanner found a vulnerability against a version we ship."
      exit 1
      ;;
    128)
      echo "$OUTPUT"
      echo "::error::osv-scanner found no packages to scan (exit 128). This is not a registry outage - it means the scan path or a manifest changed shape. Retrying will not help; fix the scan config."
      exit 3
      ;;
    *)
      echo "osv-scanner tool error on attempt $attempt/$ATTEMPTS (exit $EXIT_CODE):"
      echo "$OUTPUT"
      if [ "$attempt" -lt "$ATTEMPTS" ]; then
        sleep "$DELAY_SECONDS"
      fi
      ;;
  esac
done

echo "::error::osv-scanner could not be performed after $ATTEMPTS attempt(s) (tool exited $EXIT_CODE, not the vulnerabilities-found code 1). This means the scan did not run - it is not a report of a clean dependency tree, even if osv-scanner's own text output above says otherwise."
exit 2
