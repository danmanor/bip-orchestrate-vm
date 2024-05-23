#!/usr/bin/env python3
import argparse
import ipaddress
import os
import sys


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


def _gateway_for_cidr(cidr: str) -> str:
    n = ipaddress.ip_network(cidr, strict=False)
    # Convention used by libvirt net config in this repo: first usable address is gateway (.1)
    return str(ipaddress.ip_address(int(n.network_address) + 1))


def _prefixlen_for_cidr(cidr: str) -> int:
    return ipaddress.ip_network(cidr, strict=False).prefixlen


def main() -> int:
    ap = argparse.ArgumentParser(description="Render agent-config.yaml (rendezvous IP follows primary family)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--name", default="sno-cluster")
    args = ap.parse_args()

    ip_stack = _optional("IP_STACK", "v4")
    primary = _stack_order(ip_stack)[0]

    host_ip_v4 = _optional_fallback("HOST_IP_V4", "HOST_IP", "192.168.126.10")
    host_ip_v6 = _optional("HOST_IP_V6", "fd00:0:0:126::10")
    rendezvous_ip = host_ip_v4 if primary == "v4" else host_ip_v6

    machine_v4 = _optional_fallback("MACHINE_NETWORK_V4", "MACHINE_NETWORK", "192.168.126.0/24")
    machine_v6 = _optional("MACHINE_NETWORK_V6", "fd00:0:0:126::/64")

    gw_v4 = _optional("GATEWAY_V4", _gateway_for_cidr(machine_v4))
    gw_v6 = _optional("GATEWAY_V6", _gateway_for_cidr(machine_v6))
    dns_v4 = _optional("DNS_SERVER_V4", gw_v4)
    dns_v6 = _optional("DNS_SERVER_V6", gw_v6)

    host_name = _optional("HOST_NAME", "master-0")
    host_mac = _optional("HOST_MAC", "52:54:00:ee:42:e1")
    host_ifname = _optional("HOST_IFNAME", "enp1s0")

    want_v4 = ip_stack.lower() in ("v4", "v4v6", "v6v4")
    want_v6 = ip_stack.lower() in ("v6", "v4v6", "v6v4")
    v4_prefix = _prefixlen_for_cidr(machine_v4)
    v6_prefix = _prefixlen_for_cidr(machine_v6)

    dns_servers = []
    if want_v4:
        dns_servers.append(dns_v4)
    if want_v6:
        dns_servers.append(dns_v6)
    dns_block = "\n".join([f"              - {s}" for s in dns_servers]) if dns_servers else "              - 8.8.8.8"

    routes_lines = []
    if want_v4:
        routes_lines.extend(
            [
                "            - destination: 0.0.0.0/0",
                f"              next-hop-address: {gw_v4}",
                f"              next-hop-interface: {host_ifname}",
                "              table-id: 254",
            ]
        )
    if want_v6:
        routes_lines.extend(
            [
                "            - destination: ::/0",
                f"              next-hop-address: {gw_v6}",
                f"              next-hop-interface: {host_ifname}",
                "              table-id: 254",
            ]
        )

    iface_lines = [
        f"        - name: {host_ifname}",
        "          type: ethernet",
        "          state: up",
        f"          mac-address: {host_mac}",
    ]
    if want_v4:
        iface_lines.extend(
            [
                "          ipv4:",
                "            enabled: true",
                "            address:",
                f"              - ip: {host_ip_v4}",
                f"                prefix-length: {v4_prefix}",
                "            dhcp: false",
            ]
        )
    else:
        iface_lines.extend(["          ipv4:", "            enabled: false"])
    if want_v6:
        iface_lines.extend(
            [
                "          ipv6:",
                "            enabled: true",
                "            address:",
                f"              - ip: {host_ip_v6}",
                f"                prefix-length: {v6_prefix}",
                "            dhcp: false",
            ]
        )
    else:
        iface_lines.extend(["          ipv6:", "            enabled: false"])

    content = "\n".join(
        [
            "apiVersion: v1alpha1",
            "kind: AgentConfig",
            "metadata:",
            f"  name: {args.name}",
            f"rendezvousIP: {rendezvous_ip}",
            "hosts:",
            f"  - hostname: {host_name}",
            "    interfaces:",
            f"      - name: {host_ifname}",
            f"        macAddress: {host_mac}",
            "    networkConfig:",
            "      interfaces:",
            *iface_lines,
            "      dns-resolver:",
            "        config:",
            "          server:",
            *dns_block.splitlines(),
            "      routes:",
            "        config:",
            *routes_lines,
            "",
        ]
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


