from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from collections.abc import Mapping, Sequence


TAILSCALE_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class BindingError(ValueError):
    pass


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BindingError(f"{label} is missing")
    return value


def _tailscale_ip(value: str) -> str:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected address is not a Tailscale IPv4") from None
    if parsed.version != 4 or parsed not in TAILSCALE_IPV4_NETWORK:
        raise argparse.ArgumentTypeError("expected address is not a Tailscale IPv4")
    return value


def verify(config: object, expected_tailscale: str) -> None:
    root = _mapping(config, "Compose configuration")
    services = _mapping(root.get("services"), "services")
    sales_ui = _mapping(services.get("sales-ui"), "sales-ui")
    environment = _mapping(sales_ui.get("environment"), "sales-ui environment")
    if environment.get("UI_EXTRA_HOSTS") != expected_tailscale:
        raise BindingError("sales-ui host allowlist does not match the VM Tailscale address")

    ports = sales_ui.get("ports")
    if not isinstance(ports, Sequence) or isinstance(ports, (str, bytes)):
        raise BindingError("sales-ui ports are missing")
    expected = {
        ("127.0.0.1", "8791", 8791),
        (expected_tailscale, "8791", 8791),
    }
    actual: set[tuple[object, object, object]] = set()
    for port in ports:
        entry = _mapping(port, "sales-ui port")
        actual.add((entry.get("host_ip"), str(entry.get("published")), entry.get("target")))
    if len(ports) != 2 or actual != expected:
        raise BindingError("sales-ui bindings are not exactly loopback plus VM Tailscale")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify rendered sales-ui bindings")
    parser.add_argument("--expected-tailscale", required=True, type=_tailscale_ip)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        config = json.load(sys.stdin)
        verify(config, arguments.expected_tailscale)
    except (BindingError, json.JSONDecodeError):
        print("sales-ui bindings: rejected", file=sys.stderr)
        return 1
    print("sales-ui bindings: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
