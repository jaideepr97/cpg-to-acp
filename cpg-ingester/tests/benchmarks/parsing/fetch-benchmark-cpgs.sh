#!/usr/bin/env bash
# Fetch real CPGs listed in real-cpgs.manifest.yaml into the gitignored
# working/benchmarks/parsing/real/ directory (RHAIENG-6461).
#
# POLICY: real CPGs are NEVER committed. They are downloaded here for local
# realism testing only. See real-cpgs.manifest.yaml for the full policy.
#
# Behaviour:
#   * idempotent + safe to re-run (skips files already present + hash-valid)
#   * verifies sha256 when the manifest pins one; when the manifest says "TBD"
#     it downloads, prints the observed sha256, and records it (so you can pin
#     it in the manifest), continuing with a warning
#   * on 404 / blocked / scripted-fetch failure, prints a manual-fallback
#     message with the URL and target path, and continues to the next entry
#
# Usage:
#   ./fetch-benchmark-cpgs.sh
#
# Override the interpreter (used only to parse the YAML) with BENCH_PYTHON.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CPG_INGESTER_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
REPO_ROOT="$(cd "${CPG_INGESTER_DIR}/.." && pwd)"
MANIFEST="${SCRIPT_DIR}/real-cpgs.manifest.yaml"
DEST_DIR="${REPO_ROOT}/working/benchmarks/parsing/real"
PY="${BENCH_PYTHON:-${CPG_INGESTER_DIR}/.venv/bin/python}"

if [[ ! -f "${MANIFEST}" ]]; then
  echo "ERROR: manifest not found: ${MANIFEST}" >&2
  exit 1
fi
if [[ ! -x "${PY}" ]]; then
  echo "ERROR: python not found at ${PY} (set BENCH_PYTHON)." >&2
  exit 1
fi

mkdir -p "${DEST_DIR}"
echo "Downloading real CPGs into: ${DEST_DIR}"
echo "(These are NEVER committed — the dir is gitignored.)"
echo

# Emit one tab-separated line per entry: name<TAB>url<TAB>sha256<TAB>archetype
ENTRIES="$("${PY}" - "${MANIFEST}" <<'PYEOF'
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f) or {}
for e in data.get("cpgs", []):
    print("\t".join([
        str(e.get("name", "")).strip(),
        str(e.get("source_url", "")).strip(),
        str(e.get("sha256", "TBD")).strip(),
        str(e.get("archetype_tag", "")).strip(),
    ]))
PYEOF
)"

sha256_of() {  # portable sha256
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

manual_fallback() {
  local url="$1" dest="$2"
  echo "  !! Could not fetch via script. MANUAL FALLBACK:" >&2
  echo "     1. Open in a browser: ${url}" >&2
  echo "     2. Save the PDF to:   ${dest}" >&2
  echo "     3. Re-run this script to verify/record its sha256." >&2
}

total=0; ok=0; skipped=0; failed=0
while IFS=$'\t' read -r name url want_sha archetype; do
  [[ -z "${name}" ]] && continue
  total=$((total+1))
  dest="${DEST_DIR}/${name}.pdf"
  echo "[${archetype}] ${name}"

  # Skip if already present and (when pinned) hash matches.
  if [[ -f "${dest}" ]]; then
    if [[ "${want_sha}" != "TBD" && -n "${want_sha}" ]]; then
      have="$(sha256_of "${dest}")"
      if [[ "${have}" == "${want_sha}" ]]; then
        echo "  = already present, sha256 OK — skipping"
        skipped=$((skipped+1)); continue
      else
        echo "  ! present but sha256 MISMATCH (want ${want_sha}, have ${have}); re-downloading" >&2
      fi
    else
      echo "  = already present (manifest sha256=TBD); observed sha256:"
      echo "      $(sha256_of "${dest}")"
      skipped=$((skipped+1)); continue
    fi
  fi

  tmp="${dest}.part"
  if ! curl -fsSL --retry 2 --connect-timeout 20 -A "cpg-to-acp-benchmark/1.0" \
        -o "${tmp}" "${url}"; then
    rm -f "${tmp}"
    echo "  x download failed (404 / blocked / network)" >&2
    manual_fallback "${url}" "${dest}"
    failed=$((failed+1)); continue
  fi

  # Reject obvious non-PDF (e.g. an HTML block/interstitial page).
  if ! head -c 5 "${tmp}" | grep -q "%PDF"; then
    echo "  x downloaded content is not a PDF (likely an HTML block page)" >&2
    rm -f "${tmp}"
    manual_fallback "${url}" "${dest}"
    failed=$((failed+1)); continue
  fi

  mv "${tmp}" "${dest}"
  have="$(sha256_of "${dest}")"
  if [[ "${want_sha}" == "TBD" || -z "${want_sha}" ]]; then
    echo "  + downloaded; sha256 not yet pinned (manifest says TBD)."
    echo "    Observed sha256 (pin this in the manifest to guard against drift):"
    echo "      ${have}"
  elif [[ "${have}" == "${want_sha}" ]]; then
    echo "  + downloaded; sha256 verified OK"
  else
    echo "  ! downloaded but sha256 MISMATCH (want ${want_sha}, have ${have})" >&2
    echo "    Content may have drifted — review before using." >&2
  fi
  ok=$((ok+1))
done <<< "${ENTRIES}"

echo
echo "Summary: ${total} entries — ${ok} downloaded, ${skipped} skipped, ${failed} failed."
if [[ "${failed}" -gt 0 ]]; then
  echo "Some fetches failed; see manual-fallback notes above."
fi
echo "Now run: ./run-benchmark.sh --real   (or --all)"
