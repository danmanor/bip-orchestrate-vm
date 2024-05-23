#!/usr/bin/env python3
import argparse
import ipaddress
import os
import sys
from typing import Optional


def _optional(env_key: str, default: str) -> str:
    v = os.environ.get(env_key)
    return default if v is None or v == "" else v


def _optional_fallback(primary_key: str, fallback_key: str, default: str) -> str:
    v = os.environ.get(primary_key)
    if v is not None and v != "":
        return v
    v2 = os.environ.get(fallback_key)
    if v2 is not None and v2 != "":
        return v2
    return default


def _stack_order(ip_stack: str):
    ip_stack = ip_stack.lower()
    if ip_stack == "v4":
        return ["v4"]
    if ip_stack == "v6":
        return ["v6"]
    if ip_stack == "v4v6":
        return ["v4", "v6"]
    if ip_stack == "v6v4":
        return ["v6", "v4"]
    raise SystemExit("IP_STACK must be one of: v4, v6, v4v6, v6v4")


def _render_ipv4_block(cidr: str) -> str:
    n = ipaddress.IPv4Network(cidr, strict=False)
    # Convention used by the old template: .1 gateway, .2-.254 DHCP
    gw = str(ipaddress.IPv4Address(int(n.network_address) + 1))
    dhcp_start = str(ipaddress.IPv4Address(int(n.network_address) + 2))
    dhcp_end = str(ipaddress.IPv4Address(int(n.broadcast_address) - 1))
    return "\n".join(
        [
            f"  <ip family='ipv4' address='{gw}' prefix='{n.prefixlen}'>",
            "    <dhcp>",
            f"      <range start='{dhcp_start}' end='{dhcp_end}'/>",
            "    </dhcp>",
            "  </ip>",
        ]
    )


def _render_ipv6_block(cidr: str, dhcp_start_preferred: Optional[str]) -> str:
    n = ipaddress.IPv6Network(cidr, strict=False)
    # Use first usable addresses as gw and DHCP range. Keep range modest.
    gw = str(ipaddress.IPv6Address(int(n.network_address) + 1))
    dhcp_start = str(ipaddress.IPv6Address(int(n.network_address) + 2))
    if dhcp_start_preferred:
        try:
            p = ipaddress.IPv6Address(dhcp_start_preferred)
            if p in n:
                dhcp_start = str(p)
        except Exception:
            # ignore invalid preferred address
            pass
    # End at +0x1000 by default, but never exceed last address
    dhcp_end_int = min(int(ipaddress.IPv6Address(dhcp_start)) + 0x1000, int(n.network_address) + (n.num_addresses - 2))
    dhcp_end = str(ipaddress.IPv6Address(dhcp_end_int))
    return "\n".join(
        [
            f"  <ip family='ipv6' address='{gw}' prefix='{n.prefixlen}'>",
            "    <dhcp>",
            f"      <range start='{dhcp_start}' end='{dhcp_end}'/>",
            "    </dhcp>",
            "  </ip>",
        ]
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Render libvirt net XML for IPv4/IPv6/dual-stack")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    ip_stack = _optional("IP_STACK", "v4")
    order = _stack_order(ip_stack)

    net_name = _optional("NET_NAME", "test-net")
    net_uuid = _optional("NET_UUID", "a29bce40-ce15-43c8-9142-fd0a3cc37f9a")
    bridge = _optional("NET_BRIDGE_NAME", "tt0")
    mac = _optional("NET_MAC", "52:54:00:e0:8d:fe")
    base_domain = _optional("BASE_DOMAIN", "redhat.com")

    machine_v4 = _optional_fallback("MACHINE_NETWORK_V4", "MACHINE_NETWORK", "192.168.126.0/24")
    machine_v6 = _optional("MACHINE_NETWORK_V6", "fd00:0:0:126::/64")
    host_ip_v6 = _optional("HOST_IP_V6", "fd00:0:0:126::10")

    ip_blocks = []
    for fam in order:
        if fam == "v4":
            ip_blocks.append(_render_ipv4_block(machine_v4))
        else:
            ip_blocks.append(_render_ipv6_block(machine_v6, host_ip_v6))

    content = "\n".join(
        [
            "<network>",
            f"  <name>{net_name}</name>",
            f"  <uuid>{net_uuid}</uuid>",
            "  <forward mode='nat'/>",
            f"  <bridge name='{bridge}' stp='on' delay='0'/>",
            "  <mtu size='1500'/>",
            f"  <mac address='{mac}'/>",
            f"  <domain name='{base_domain}' localOnly='yes'/>",
            "  <dns enable='yes'/>",
            *ip_blocks,
            "</network>",
            "",
        ]
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


