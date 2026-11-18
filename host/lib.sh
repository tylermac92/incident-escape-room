# Shared by the host scripts; sourced from the repository root, not run.
PROJECT=incident-escape-room
LABEL=com.incident-escape-room.managed=true
PROJECT_FILTER="label=com.docker.compose.project=$PROJECT"
# The same pinned base as sim/ and controller/Dockerfile.
PYTHON_IMAGE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# Run a stdlib checker from isolation/ in a throwaway container with no network,
# so the host needs only Docker. Its input is stdin; extra arguments go to the script.
run_checker() {
    script=$1
    shift
    docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
        --user 65534:65534 --label "$LABEL" "$PYTHON_IMAGE" \
        python -c "$(cat "isolation/src/isolation/$script")" "$@"
}
