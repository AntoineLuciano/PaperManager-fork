#!/usr/bin/env bash
# Run the backend test suite against a throwaway Neo4j, never against a real library.
#
#   backend/scripts/run_tests.sh                 # whole suite except @integration tests
#   backend/scripts/run_tests.sh tests/test_x.py -k name   # any pytest arguments
#
# Starts neo4j:5.15 and the backend image on a private Docker network, runs pytest in
# a one-off container with only test settings (the project's .env is not mounted),
# then removes both. Build the backend image first if needed: docker compose build backend
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${PM_TEST_IMAGE:-papermanager-backend:latest}"
RUN_ID="pmtest-$$"
NET="$RUN_ID-net"
DB="$RUN_ID-neo4j"
PASSWORD="testpassword"

cleanup() {
  docker rm -f "$DB" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" -e NEO4J_AUTH="neo4j/$PASSWORD" neo4j:5.15 >/dev/null

echo "Waiting for the test Neo4j…"
for _ in $(seq 1 60); do
  if docker exec "$DB" cypher-shell -u neo4j -p "$PASSWORD" "RETURN 1" >/dev/null 2>&1; then break; fi
  sleep 2
done
docker exec "$DB" cypher-shell -u neo4j -p "$PASSWORD" "RETURN 1" >/dev/null

# Default: everything except tests that call real external services (Drive, Anthropic, ...).
ARGS=("$@")
[ ${#ARGS[@]} -eq 0 ] && ARGS=(-q -m "not integration")

docker run --rm --network "$NET" \
  -v "$ROOT/backend:/app" -v "$ROOT/prompts:/prompts:ro" -v "$ROOT/frontend:/frontend:ro" \
  -w /app \
  -e NEO4J_URI="bolt://$DB:7687" -e NEO4J_USER=neo4j -e NEO4J_PASSWORD="$PASSWORD" \
  -e PM_TESTS_ALLOW_DB=1 \
  -e TRUSTED_HOSTS=localhost,127.0.0.1,test,testserver \
  -e JWT_SECRET_KEY=test-secret -e DEFAULT_USER_NAME=testuser -e DEFAULT_USER_PASSWORD=test-password \
  -e CONCEPT_MAP_AUTO=false \
  "$IMAGE" python -m pytest -p no:cacheprovider "${ARGS[@]}"
