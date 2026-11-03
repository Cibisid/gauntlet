#!/usr/bin/env bash
# End-to-end on a real Kubernetes cluster (kind in CI):
#   build image -> load into kind -> create secrets -> deploy -> run two canaries
#   through the proxy: a leaking candidate must roll back, a healthy one must promote.
# Requires: docker, kind, kubectl, and `pip install -e .` (for the gauntlet CLI).
set -euo pipefail

CLUSTER="${KIND_CLUSTER:-gauntlet}"
NS=gauntlet
WORK="$(mktemp -d)"
trap 'kill ${PF_PID:-0} 2>/dev/null || true; rm -rf "$WORK"' EXIT

docker build -t gauntlet:ci .
kind load docker-image gauntlet:ci --name "$CLUSTER"

ADMIN_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
CLIENT_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
ADMIN_HASH="$(GAUNTLET_KEY_TO_HASH="$ADMIN_KEY" gauntlet hash-key)"
CLIENT_HASH="$(GAUNTLET_KEY_TO_HASH="$CLIENT_KEY" gauntlet hash-key)"

kubectl apply -f deploy/k8s/base/namespace.yaml
kubectl -n "$NS" create secret generic gauntlet-keys \
  --from-literal=admin_key_hash="$ADMIN_HASH" \
  --from-literal=api_key_hashes="ci:$CLIENT_HASH" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -k deploy/k8s/overlays/kind
kubectl -n "$NS" rollout status deploy/mock-llm --timeout=180s
kubectl -n "$NS" rollout status deploy/gauntlet-proxy --timeout=180s

kubectl -n "$NS" port-forward svc/gauntlet-proxy 18080:8080 >/dev/null 2>&1 &
PF_PID=$!
for _ in $(seq 1 60); do curl -fsS http://127.0.0.1:18080/healthz >/dev/null 2>&1 && break; sleep 1; done

export GAUNTLET_ADMIN_KEY="$ADMIN_KEY" GAUNTLET_API_KEY="$CLIENT_KEY"
P=http://127.0.0.1:18080

# Faster rollout steps for CI: same releases, shorter schedule.
python - "$WORK" <<'PY'
import sys, yaml
work = sys.argv[1]
for src, dst in [("releases/trialbridge/examples/injectable_model_guarded.yaml", "leaky.yaml"),
                 ("releases/trialbridge/candidate.yaml", "healthy.yaml")]:
    doc = yaml.safe_load(open(src))
    doc["rollout"] = {"steps": [0.5, 1.0], "min_requests": 30}
    yaml.safe_dump(doc, open(f"{work}/{dst}", "w"), sort_keys=False)
PY

drive() {  # drive <suite> <count>
  python - "$P" "$1" "$2" <<'PY'
import json, os, sys, httpx
url, suite, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = [json.loads(l) for l in open("cases/trialbridge/synthetic_v1.jsonl")]
inputs = [r["inputs"] for r in rows if r["suite"] == suite]
h = {"Authorization": f"Bearer {os.environ['GAUNTLET_API_KEY']}"}
with httpx.Client(base_url=url, headers=h, timeout=30) as c:
    codes = [c.post("/v1/apps/trialbridge/invoke", json={"inputs": inputs[i % len(inputs)]}).status_code
             for i in range(n)]
print(f"drove {n} {suite} requests; status counts: { {k: codes.count(k) for k in set(codes)} }")
PY
}

gauntlet rollout deploy --proxy "$P" --release releases/trialbridge/baseline.yaml

echo "--- canary 1: model that leaks under injection (guardrail blocks it) -> expect rollback"
gauntlet rollout start --proxy "$P" --release "$WORK/leaky.yaml"
drive security 120
if gauntlet rollout watch --proxy "$P" --release "$WORK/leaky.yaml" --interval 1 --timeout 60; then
  echo "FAIL: leaking canary was promoted"; exit 1
fi

echo "--- canary 2: healthy reworded prompt -> expect promote"
gauntlet rollout start --proxy "$P" --release "$WORK/healthy.yaml"
( for _ in 1 2 3 4; do drive quality 150; done ) &
DRIVER=$!
gauntlet rollout watch --proxy "$P" --release "$WORK/healthy.yaml" --interval 2 --timeout 120
wait "$DRIVER"

curl -fsS "$P/metrics" | grep -E '^gauntlet_(rollbacks_total|release_weight)' || true
echo "k8s e2e passed"
