from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ALLOWED_COMMANDS = {"check", "monitor", "ask", "explain-file", "migration"}
ALLOWED_RUNTIME_PROFILES = {"local", "staging", "production"}
SENSITIVE_ARG_FLAGS = {
    "--db-dsn",
    "--dsn",
    "--password",
    "--pass",
    "--token",
    "--secret",
    "--api-key",
    "--apikey",
}
CONNECTION_STRING_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://")
FAIL_ON_FINDINGS_STATUSES = {"warn", "critical", "error"}
DEFAULT_RELEASE_REPOSITORY = "ralfnascimento/pgmind"
RELEASE_ASSET_NAME = "pgmind-linux-x86_64"
RELEASE_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RELEASE_TAG_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class InputValidationError(ValueError):
    pass


class ReleaseResolutionError(RuntimeError):
    pass


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _emit_mask(value: str) -> None:
    is_github_actions = os.getenv("GITHUB_ACTIONS", "").strip().lower() == "true"
    if value and is_github_actions:
        print(f"::add-mask::{value}")


def _set_output(name: str, value: str) -> None:
    output_file = os.getenv("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def _resolve_output_paths() -> tuple[str, str]:
    summary_path = ""
    artifacts_path = ""
    monitor_latest = Path("artifacts") / "monitor" / "latest.json"
    if monitor_latest.exists():
        summary_path = str(monitor_latest)
    artifacts_root = Path("artifacts")
    if artifacts_root.exists():
        artifacts_path = str(artifacts_root)
    return summary_path, artifacts_path


def _read_default_release_tag() -> str:
    path = Path(__file__).with_name("release_tag.txt")
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    raise ReleaseResolutionError(
        "release_tag.txt is missing in action image; unable to resolve release tag"
    )


def _release_request(
    url: str,
    token: str,
    *,
    release_repository: str,
    release_tag: str,
) -> dict:
    _validate_github_api_url(url, allow_uploads=False)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "pgmind-action-entrypoint",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        status = exc.code
        auth_state = "provided" if token else "missing"
        context = (
            f"repository='{release_repository}', tag='{release_tag}', auth='{auth_state}'"
        )
        if status == 404:
            raise ReleaseResolutionError(
                "release lookup failed "
                f"({context}); tag not found or inaccessible. "
                "Provide github_token for private repositories."
            ) from exc
        raise ReleaseResolutionError(
            f"failed to query release metadata ({context}): HTTP {status}"
        ) from exc
    except urllib.error.URLError as exc:
        auth_state = "provided" if token else "missing"
        context = (
            f"repository='{release_repository}', tag='{release_tag}', auth='{auth_state}'"
        )
        raise ReleaseResolutionError(
            f"failed to query release metadata ({context}): {exc.reason}"
        ) from exc


def _download_release_asset(download_url: str, destination: Path, token: str) -> None:
    _validate_github_api_url(download_url, allow_uploads=True)
    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": "pgmind-action-entrypoint",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(download_url, headers=headers)
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=60) as response:
            destination.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        raise ReleaseResolutionError(f"failed to download release asset: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseResolutionError(f"failed to download release asset: {exc.reason}") from exc


def _resolve_release_binary(env: dict[str, str]) -> str:
    release_tag = env.get("INPUT_RELEASE_TAG", "").strip() or _read_default_release_tag()
    release_repository = (
        env.get("INPUT_RELEASE_REPOSITORY", "").strip()
        or env.get("GITHUB_ACTION_REPOSITORY", "").strip()
        or DEFAULT_RELEASE_REPOSITORY
    )
    _validate_release_resolution_inputs(release_repository, release_tag)
    github_token = env.get("INPUT_GITHUB_TOKEN", "").strip() or env.get("GITHUB_TOKEN", "").strip()

    metadata_url = f"https://api.github.com/repos/{release_repository}/releases/tags/{release_tag}"
    metadata = _release_request(
        metadata_url,
        github_token,
        release_repository=release_repository,
        release_tag=release_tag,
    )
    asset = next(
        (item for item in metadata.get("assets", []) if item.get("name") == RELEASE_ASSET_NAME),
        None,
    )
    if asset is None:
        raise ReleaseResolutionError(
            "release asset lookup failed "
            f"(repository='{release_repository}', tag='{release_tag}'): "
            f"asset '{RELEASE_ASSET_NAME}' was not found"
        )

    download_url = str(asset.get("url", "")).strip()
    if not download_url:
        raise ReleaseResolutionError(
            f"release asset '{RELEASE_ASSET_NAME}' does not expose an API download URL"
        )

    cache_dir = Path("/tmp/pgmind-action")
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_repo = release_repository.replace("/", "_")
    binary_path = cache_dir / f"{safe_repo}-{release_tag}-{RELEASE_ASSET_NAME}"
    if not binary_path.exists():
        _download_release_asset(download_url, binary_path, github_token)
        binary_path.chmod(0o755)

    expected_digest = str(asset.get("digest", "")).strip().lower()
    if expected_digest.startswith("sha256:"):
        expected = expected_digest.split(":", 1)[1]
        calculated = hashlib.sha256(binary_path.read_bytes()).hexdigest()
        if expected != calculated:
            raise ReleaseResolutionError(
                "release asset digest mismatch; refusing to execute downloaded binary"
            )

    return str(binary_path)


def _validate_release_resolution_inputs(release_repository: str, release_tag: str) -> None:
    if not RELEASE_REPOSITORY_PATTERN.match(release_repository):
        raise ReleaseResolutionError("release repository format is invalid; expected 'owner/repo'")
    if not RELEASE_TAG_PATTERN.match(release_tag):
        raise ReleaseResolutionError("release tag format is invalid")


def _validate_github_api_url(url: str, *, allow_uploads: bool) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ReleaseResolutionError("release lookup URL must use https")
    host = (parsed.hostname or "").lower()
    allowed_hosts = {"api.github.com", "uploads.github.com"} if allow_uploads else {"api.github.com"}
    if host not in allowed_hosts:
        raise ReleaseResolutionError(
            f"release lookup URL host '{host or 'unknown'}' is not allowed"
        )


def _validate_runtime_profile(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_RUNTIME_PROFILES:
        raise InputValidationError(
            "input 'runtime_profile' must be one of: local, staging, production"
        )
    return normalized


def _validate_boolean_input(name: str, value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise InputValidationError(f"input '{name}' must be true or false")
    return normalized


def _validate_and_parse_args(raw_args: str) -> list[str]:
    try:
        parsed = shlex.split(raw_args)
    except ValueError as exc:
        raise InputValidationError("input 'args' has invalid shell quoting") from exc

    for value in parsed:
        lowered = value.lower()
        if any(lowered == flag or lowered.startswith(f"{flag}=") for flag in SENSITIVE_ARG_FLAGS):
            raise InputValidationError(
                "sensitive CLI flags are not allowed in 'args'; use secure action inputs"
            )
        if CONNECTION_STRING_PATTERN.search(value):
            raise InputValidationError(
                "connection strings are not allowed in 'args'; use the secure 'db_dsn' input"
            )
    return parsed


def _evaluate_fail_on_findings(command: str, summary_path: str) -> tuple[bool, str | None]:
    if command != "monitor":
        return False, None
    if not summary_path:
        return False, "monitor summary was not produced; cannot evaluate findings"

    try:
        payload = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"failed to parse monitor summary: {exc}"

    status = str(payload.get("result", {}).get("status", "")).strip().lower()
    return status in FAIL_ON_FINDINGS_STATUSES, None


def main() -> int:
    if len(sys.argv) < 2:
        print("error: input 'command' is required", file=sys.stderr)
        _set_output("exit_code", "2")
        return 2

    command = sys.argv[1].strip()
    if command not in ALLOWED_COMMANDS:
        print(
            "error: unsupported command. Allowed: check, monitor, ask, explain-file, migration",
            file=sys.stderr,
        )
        _set_output("exit_code", "2")
        return 2

    env = os.environ.copy()
    try:
        args_raw = sys.argv[2] if len(sys.argv) > 2 else ""
        parsed_args = _validate_and_parse_args(args_raw)
        runtime_profile = _validate_runtime_profile(env.get("INPUT_RUNTIME_PROFILE", "local"))
        llm_enabled = _validate_boolean_input("llm_enabled", env.get("INPUT_LLM_ENABLED", "false"))
        fail_on_findings = _truthy(
            _validate_boolean_input("fail_on_findings", env.get("INPUT_FAIL_ON_FINDINGS", "false"))
        )
    except InputValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _set_output("exit_code", "2")
        return 2

    env["PGMIND_RUNTIME_PROFILE"] = runtime_profile
    env["PGMIND_LLM_ENABLED"] = llm_enabled
    db_dsn = env.get("INPUT_DB_DSN", "").strip()
    if db_dsn:
        _emit_mask(db_dsn)
        env["PGMIND_DB_DSN"] = db_dsn

    try:
        pgmind_cmd = _resolve_release_binary(env)
    except ReleaseResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _set_output("exit_code", "2")
        return 2

    cmd = [pgmind_cmd, command, *parsed_args]
    completed = subprocess.run(cmd, env=env, check=False)
    summary_path, artifacts_path = _resolve_output_paths()

    final_exit_code = completed.returncode
    if completed.returncode == 0 and fail_on_findings:
        should_fail, reason = _evaluate_fail_on_findings(command, summary_path)
        if reason:
            print(f"error: {reason}", file=sys.stderr)
            final_exit_code = 2
        elif should_fail:
            print("error: findings detected and fail_on_findings=true", file=sys.stderr)
            final_exit_code = 1

    exit_code = str(final_exit_code)
    _set_output("exit_code", exit_code)
    _set_output("summary_path", summary_path)
    _set_output("artifacts_path", artifacts_path)
    return final_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
