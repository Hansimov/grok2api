from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse
import tomllib

from app.core.proxy_env import resolve_proxy_from_env, translate_loopback_proxy_url


REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DEFAULTS_FILE = REPO_ROOT / "config.defaults.toml"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_toml_dict(path: Path) -> dict[str, Any]:
    with path.open("rb") as file_obj:
        data = tomllib.load(file_obj)
    if not isinstance(data, dict):
        raise SystemExit(f"invalid TOML structure in {path}")
    return data


def load_cli_settings() -> dict[str, Any]:
    if not CLI_DEFAULTS_FILE.exists():
        raise SystemExit(f"missing CLI defaults file: {CLI_DEFAULTS_FILE}")

    settings = load_toml_dict(CLI_DEFAULTS_FILE).get("cli")
    if not isinstance(settings, dict):
        raise SystemExit("[cli] is missing in config.defaults.toml")

    local_settings_path = (
        REPO_ROOT / str(settings["defaults"]["state_dir"]) / "cli.toml"
    )
    if local_settings_path.exists():
        settings = deep_merge(settings, load_toml_dict(local_settings_path))

    defaults = settings.get("defaults")
    compose = settings.get("compose")
    container_environment = settings.get("container_environment")
    if not isinstance(defaults, dict):
        raise SystemExit("[cli.defaults] is missing in config.defaults.toml")
    if not isinstance(compose, dict):
        raise SystemExit("[cli.compose] is missing in config.defaults.toml")
    if not isinstance(container_environment, dict):
        raise SystemExit(
            "[cli.container_environment] is missing in config.defaults.toml"
        )

    return settings


CLI_SETTINGS = load_cli_settings()
STATE_DIR = REPO_ROOT / str(CLI_SETTINGS["defaults"]["state_dir"])
INSTANCES_DIR = STATE_DIR / "instances"
HOST_REPO_ROOT = Path(os.getenv("GROK2API_HOST_ROOT", str(REPO_ROOT)))
HOST_STATE_DIR = HOST_REPO_ROOT / str(CLI_SETTINGS["defaults"]["state_dir"])
HOST_INSTANCES_DIR = HOST_STATE_DIR / "instances"


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    defaults = CLI_SETTINGS["defaults"]
    default_proxy = str(defaults.get("proxy", "")).strip() or resolve_proxy_from_env(
        os.environ
    )
    parser = argparse.ArgumentParser(
        prog="grok2api",
        description="Manage Grok2API Docker instances from the host.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser_ = subparsers.add_parser("build", help="Build the Docker image")
    build_parser_.add_argument("--image", default=defaults["image"], help="Image tag")
    build_parser_.add_argument(
        "--no-cache", action="store_true", help="Build without Docker layer cache"
    )
    build_parser_.set_defaults(func=cmd_build)

    start_parser = subparsers.add_parser("start", help="Create or start an instance")
    add_instance_argument(start_parser)
    start_parser.add_argument(
        "--port",
        type=int,
        default=int(defaults["host_port"]),
        help="Host port to expose the API on",
    )
    start_parser.add_argument(
        "--proxy",
        default=default_proxy,
        help="Host-side outbound proxy URL for Grok requests",
    )
    start_parser.add_argument(
        "--workers",
        type=int,
        default=int(defaults["workers"]),
        help="Granian worker count",
    )
    start_parser.add_argument(
        "--storage-type",
        default=defaults["storage_type"],
        choices=["local", "redis", "mysql", "pgsql"],
        help="Storage backend used by the container",
    )
    start_parser.add_argument(
        "--storage-url",
        default=defaults["storage_url"],
        help="Connection URL for non-local storage",
    )
    start_parser.add_argument(
        "--app-key",
        default=None,
        help="Optional admin password written into the instance config",
    )
    start_parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key written into the instance config",
    )
    start_parser.add_argument(
        "--function-key",
        default=None,
        help="Optional function key written into the instance config",
    )
    start_parser.add_argument(
        "--app-url",
        default=None,
        help="Optional external app URL written into the instance config",
    )
    start_parser.add_argument(
        "--image", default=defaults["image"], help="Image tag to run"
    )
    start_parser.add_argument(
        "--rebuild", action="store_true", help="Build the image before starting"
    )
    start_parser.set_defaults(func=cmd_start)

    stop_parser = subparsers.add_parser("stop", help="Stop an instance")
    add_instance_argument(stop_parser)
    stop_parser.set_defaults(func=cmd_stop)

    restart_parser = subparsers.add_parser("restart", help="Restart an instance")
    add_instance_argument(restart_parser)
    restart_parser.set_defaults(func=cmd_restart)

    list_parser = subparsers.add_parser("list", help="List managed instances")
    list_parser.set_defaults(func=cmd_list)

    status_parser = subparsers.add_parser(
        "status", help="Show instance status and health"
    )
    status_parser.add_argument(
        "name", nargs="?", default=None, help="Optional instance name"
    )
    status_parser.set_defaults(func=cmd_status)

    logs_parser = subparsers.add_parser("logs", help="Show instance container logs")
    add_instance_argument(logs_parser)
    logs_parser.add_argument(
        "-f", "--follow", action="store_true", help="Follow log output"
    )
    logs_parser.add_argument(
        "--tail", default="100", help="Number of lines from the end of the logs"
    )
    logs_parser.add_argument(
        "--since", default=None, help="Show logs since a timestamp or duration"
    )
    logs_parser.set_defaults(func=cmd_logs)

    remove_parser = subparsers.add_parser(
        "remove", help="Delete an instance and its instance files"
    )
    add_instance_argument(remove_parser)
    remove_parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Remove containers but keep instance data and logs",
    )
    remove_parser.set_defaults(func=cmd_remove)

    return parser


def add_instance_argument(parser: argparse.ArgumentParser) -> None:
    defaults = CLI_SETTINGS["defaults"]
    parser.add_argument(
        "name",
        nargs="?",
        default=defaults["instance_name"],
        help="Instance name",
    )


def cmd_build(args: argparse.Namespace) -> int:
    ensure_docker_available()
    cache_dir = STATE_DIR / "build-cache" / "service"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if docker_buildx_supports_local_cache():
        buildx_command = [
            "docker",
            "buildx",
            "build",
            "--load",
            "--cache-from",
            f"type=local,src={cache_dir}",
            "--cache-to",
            f"type=local,dest={cache_dir},mode=max",
            "-t",
            args.image,
        ]
        if args.no_cache:
            buildx_command.append("--no-cache")
        buildx_command.append(str(REPO_ROOT))
        try:
            run(buildx_command)
            print(f"Built image {args.image}")
            return 0
        except SystemExit:
            pass

    command = ["docker", "build", "-t", args.image]

    if args.no_cache:
        command.append("--no-cache")
    command.append(str(REPO_ROOT))
    run(command)
    print(f"Built image {args.image}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    ensure_docker_available()
    name = normalize_instance_name(args.name)

    if args.storage_type != "local" and not args.storage_url:
        raise SystemExit("--storage-url is required when --storage-type is not local")

    if args.rebuild:
        cmd_build(argparse.Namespace(image=args.image, no_cache=False))

    instance = prepare_instance(
        name=name,
        host_port=args.port,
        proxy_url=args.proxy,
        workers=args.workers,
        storage_type=args.storage_type,
        storage_url=args.storage_url,
        image=args.image,
        app_key=args.app_key,
        api_key=args.api_key,
        function_key=args.function_key,
        app_url=args.app_url,
    )

    compose(instance, "up", "-d", "--force-recreate")
    print(
        f"Started instance {name} on http://127.0.0.1:{instance['host_port']} "
        f"with proxy {instance['container_proxy_url'] or '(disabled)'}"
    )
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    instance = load_instance(normalize_instance_name(args.name))
    compose(instance, "stop")
    print(f"Stopped instance {instance['name']}")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    instance = load_instance(normalize_instance_name(args.name))
    compose(instance, "restart")
    print(f"Restarted instance {instance['name']}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    instances = list_instances()
    if not instances:
        print("No managed instances.")
        return 0

    rows = []
    for instance in instances:
        status = inspect_container_status(instance["container_name"])
        rows.append(
            (
                instance["name"],
                status,
                str(instance["host_port"]),
                instance["container_name"],
                instance["container_proxy_url"] or "-",
            )
        )

    if not rows:
        print("No managed instances.")
        return 0

    headers = ("NAME", "STATUS", "PORT", "CONTAINER", "PROXY")
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    print(format_row(headers, widths))
    print(format_row(tuple("-" * width for width in widths), widths))
    for row in rows:
        print(format_row(row, widths))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    instances = list_instances(args.name)
    if not instances:
        print("No managed instances.")
        return 0

    rows = []
    for instance in instances:
        container_status = inspect_container_status(instance["container_name"])
        health = (
            check_instance_health(instance) if container_status == "running" else "-"
        )
        rows.append(
            (
                instance["name"],
                container_status,
                health,
                str(instance["host_port"]),
                instance["container_name"],
                instance["container_proxy_url"] or "-",
            )
        )

    headers = ("NAME", "STATUS", "HEALTH", "PORT", "CONTAINER", "PROXY")
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    print(format_row(headers, widths))
    print(format_row(tuple("-" * width for width in widths), widths))
    for row in rows:
        print(format_row(row, widths))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    instance = load_instance(normalize_instance_name(args.name))
    command = ["docker", "logs", "--tail", str(args.tail)]
    if args.follow:
        command.append("--follow")
    if args.since:
        command.extend(["--since", args.since])
    command.append(instance["container_name"])
    run(command)
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    instance = load_instance(normalize_instance_name(args.name))
    compose(instance, "down", "--remove-orphans")

    if not args.keep_files:
        shutil.rmtree(Path(instance["instance_dir"]), ignore_errors=True)

    print(f"Removed instance {instance['name']}")
    return 0


def prepare_instance(
    *,
    name: str,
    host_port: int,
    proxy_url: str,
    workers: int,
    storage_type: str,
    storage_url: str,
    image: str,
    app_key: str | None,
    api_key: str | None,
    function_key: str | None,
    app_url: str | None,
) -> dict[str, Any]:
    defaults = CLI_SETTINGS["defaults"]
    instance_dir = INSTANCES_DIR / name
    host_instance_dir = HOST_INSTANCES_DIR / name
    data_dir = instance_dir / "data"
    host_data_dir = host_instance_dir / "data"
    logs_dir = instance_dir / "logs"
    host_logs_dir = host_instance_dir / "logs"
    compose_path = instance_dir / "compose.yml"
    metadata_path = instance_dir / "instance.json"
    project_name = f"grok2api-{name}"
    container_name = project_name

    instance_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    host_proxy_url = normalize_proxy_url(proxy_url) if proxy_url else ""
    container_proxy_url = (
        translate_proxy_for_container(host_proxy_url) if host_proxy_url else ""
    )

    write_instance_config(
        data_dir=data_dir,
        host_port=host_port,
        container_proxy_url=container_proxy_url or None,
        app_key=app_key,
        api_key=api_key,
        function_key=function_key,
        app_url=app_url,
    )
    ensure_token_file(data_dir)

    instance = {
        "name": name,
        "project_name": project_name,
        "container_name": container_name,
        "instance_dir": str(instance_dir),
        "host_instance_dir": str(host_instance_dir),
        "compose_file": str(compose_path),
        "data_dir": str(data_dir),
        "host_data_dir": str(host_data_dir),
        "logs_dir": str(logs_dir),
        "host_logs_dir": str(host_logs_dir),
        "host_port": host_port,
        "container_port": int(defaults["container_port"]),
        "host_proxy_url": host_proxy_url,
        "container_proxy_url": container_proxy_url,
        "workers": workers,
        "storage_type": storage_type,
        "storage_url": storage_url,
        "image": image,
    }

    compose_path.write_text(render_compose(instance), encoding="utf-8")
    metadata_path.write_text(
        json.dumps(instance, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return instance


def list_instances(name: str | None = None) -> list[dict[str, Any]]:
    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    if name:
        metadata_path = INSTANCES_DIR / normalize_instance_name(name) / "instance.json"
        if not metadata_path.exists():
            return []
        return [json.loads(metadata_path.read_text(encoding="utf-8"))]

    instances: list[dict[str, Any]] = []
    for entry in sorted(p for p in INSTANCES_DIR.iterdir() if p.is_dir()):
        meta_path = entry / "instance.json"
        if meta_path.exists():
            instances.append(json.loads(meta_path.read_text(encoding="utf-8")))
    return instances


def write_instance_config(
    *,
    data_dir: Path,
    host_port: int,
    container_proxy_url: str | None,
    app_key: str | None,
    api_key: str | None,
    function_key: str | None,
    app_url: str | None,
) -> None:
    config_path = data_dir / "config.toml"
    defaults_path = REPO_ROOT / "config.defaults.toml"
    defaults = tomllib.loads(defaults_path.read_text(encoding="utf-8"))
    defaults.pop("cli", None)

    if config_path.exists():
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            config = deepcopy(defaults)
    else:
        config = defaults

    config.setdefault("app", {})
    config.setdefault("proxy", {})
    if container_proxy_url is not None:
        config["proxy"]["base_proxy_url"] = container_proxy_url
        config["proxy"]["asset_proxy_url"] = container_proxy_url

    if app_url is not None:
        config["app"]["app_url"] = app_url
    elif not config["app"].get("app_url"):
        config["app"]["app_url"] = f"http://127.0.0.1:{host_port}"

    if app_key is not None:
        config["app"]["app_key"] = app_key
    if api_key is not None:
        config["app"]["api_key"] = api_key
    if function_key is not None:
        config["app"]["function_key"] = function_key

    config_path.write_text(dump_toml(config), encoding="utf-8")


def ensure_token_file(data_dir: Path) -> None:
    token_path = data_dir / "token.json"
    if not token_path.exists():
        token_path.write_text("{}\n", encoding="utf-8")


def dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {format_toml_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def render_compose(instance: dict[str, Any]) -> str:
    compose_settings = CLI_SETTINGS["compose"]
    container_environment = deepcopy(CLI_SETTINGS["container_environment"])
    container_environment["SERVER_PORT"] = str(instance["container_port"])
    container_environment["SERVER_WORKERS"] = str(instance["workers"])
    container_environment["SERVER_STORAGE_TYPE"] = instance["storage_type"]
    container_environment["SERVER_STORAGE_URL"] = instance["storage_url"]
    data_volume = f"{instance['host_data_dir']}:/app/data"
    logs_volume = f"{instance['host_logs_dir']}:/app/logs"

    lines = [
        "services:",
        "  grok2api:",
        f"    container_name: {instance['container_name']}",
        f"    image: {instance['image']}",
        "    ports:",
        f"      - \"{instance['host_port']}:{instance['container_port']}\"",
    ]

    extra_hosts = compose_settings.get("extra_hosts", [])
    if extra_hosts:
        lines.append("    extra_hosts:")
        for extra_host in extra_hosts:
            lines.append(f"      - {quote_yaml(str(extra_host))}")

    lines.append("    environment:")
    for key, value in container_environment.items():
        lines.append(f"      {key}: {quote_yaml(str(value))}")

    lines.extend(
        [
            "    volumes:",
            f"      - {quote_yaml(data_volume)}",
            f"      - {quote_yaml(logs_volume)}",
            f"    restart: {compose_settings['restart']}",
        ]
    )
    return "\n".join(lines) + "\n"


def quote_yaml(value: str) -> str:
    return json.dumps(value)


def check_instance_health(instance: dict[str, Any]) -> str:
    url = f"http://host.docker.internal:{instance['host_port']}/health"
    for _ in range(3):
        try:
            with urllib_request.urlopen(url, timeout=3) as response:
                if response.status != 200:
                    return f"http-{response.status}"
                payload = json.loads(response.read().decode("utf-8"))
                return str(payload.get("status", "ok"))
        except urllib_error.HTTPError as exc:
            return f"http-{exc.code}"
        except Exception:
            time.sleep(1)
    return "unreachable"


def compose(instance: dict[str, Any], *args: str) -> None:
    command = compose_base_command()
    command.extend(
        [
            "-p",
            instance["project_name"],
            "-f",
            instance["compose_file"],
            *args,
        ]
    )
    run(command)


def compose_base_command() -> list[str]:
    if shutil.which("docker") is None:
        raise SystemExit("docker is not installed or not in PATH")

    probe = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if probe.returncode == 0:
        return ["docker", "compose"]

    if shutil.which("docker-compose") is not None:
        return ["docker-compose"]

    raise SystemExit("docker compose is not available")


def docker_buildx_available() -> bool:
    probe = subprocess.run(
        ["docker", "buildx", "version"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    return probe.returncode == 0


def docker_buildx_supports_local_cache() -> bool:
    if not docker_buildx_available():
        return False

    probe = subprocess.run(
        ["docker", "buildx", "inspect"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if probe.returncode != 0:
        return False

    for line in probe.stdout.splitlines():
        if line.startswith("Driver:"):
            return line.split(":", 1)[1].strip() != "docker"
    return False


def ensure_docker_available() -> None:
    if shutil.which("docker") is None:
        raise SystemExit("docker is not installed or not in PATH")
    run(["docker", "info"], capture_output=True)


def normalize_instance_name(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise SystemExit("instance name cannot be empty")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if any(ch not in allowed for ch in normalized):
        raise SystemExit(
            "instance name may only contain lowercase letters, digits, and dashes"
        )
    return normalized


def normalize_proxy_url(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        raise SystemExit("proxy URL must include scheme, host, and port")
    return value


def translate_proxy_for_container(proxy_url: str) -> str:
    return translate_loopback_proxy_url(proxy_url)


def inspect_container_status(container_name: str) -> str:
    if shutil.which("docker") is None:
        return "docker-missing"

    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Status}}", container_name],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        return "not-found"
    return result.stdout.strip() or "unknown"


def load_instance(name: str) -> dict[str, Any]:
    metadata_path = INSTANCES_DIR / name / "instance.json"
    if not metadata_path.exists():
        raise SystemExit(f"instance {name} does not exist")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def format_row(values: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(value.ljust(widths[index]) for index, value in enumerate(values))


def run(
    command: list[str], *, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=capture_output,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        if capture_output:
            message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        else:
            message = str(exc)
        raise SystemExit(message) from exc


if __name__ == "__main__":
    raise SystemExit(main())
