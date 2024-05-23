#!/usr/bin/env python3
import argparse
import json
import os
import sys


def _require(env_key: str) -> str:
    v = os.environ.get(env_key)
    if v is None or v == "":
        raise SystemExit(f"Missing required env var: {env_key}")
    return v


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


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _indent_block(s: str, spaces: int) -> str:
    prefix = " " * spaces
    s = s.rstrip("\n")
    if not s:
        return prefix
    return "\n".join(prefix + line for line in s.splitlines())


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Render install-config.yaml for SNO ABI/BiP")
    ap.add_argument("--pull-secret-file", required=True)
    ap.add_argument("--ssh-key-file", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    ip_stack = _optional("IP_STACK", "v4")
    order = _stack_order(ip_stack)

    cluster_name = _require("CLUSTER_NAME")
    base_domain = _require("BASE_DOMAIN")
    installation_disk = _require("INSTALLATION_DISK")

    # Backward-compatible v4 env keys (existing Makefile variables)
    machine_v4 = _optional_fallback("MACHINE_NETWORK_V4", "MACHINE_NETWORK", "192.168.126.0/24")
    cluster_v4 = _optional_fallback("CLUSTER_NETWORK_V4", "CLUSTER_NETWORK", "10.128.0.0/14")
    svc_v4 = _optional_fallback("CLUSTER_SVC_NETWORK_V4", "CLUSTER_SVC_NETWORK", "172.30.0.0/16")
    hostprefix_v4 = int(_optional_fallback("CLUSTER_NETWORK_HOSTPREFIX_V4", "CLUSTER_NETWORK_HOSTPREFIX", "23"))

    # New v6 env keys
    machine_v6 = _optional("MACHINE_NETWORK_V6", "fd00:0:0:126::/64")
    cluster_v6 = _optional("CLUSTER_NETWORK_V6", "fd01:0:0:0::/48")
    svc_v6 = _optional("CLUSTER_SVC_NETWORK_V6", "fd02:0:0:0::/112")
    hostprefix_v6 = int(_optional("CLUSTER_NETWORK_HOSTPREFIX_V6", "64"))

    pull_secret_raw = _read_file(args.pull_secret_file).strip()
    # Validate it is JSON and normalize to compact string; install-config wants a string.
    try:
        pull_secret_compact = json.dumps(json.loads(pull_secret_raw), separators=(",", ":"))
    except Exception as e:
        raise SystemExit(f"Invalid JSON in pull-secret file {args.pull_secret_file}: {e}")

    ssh_key = _read_file(args.ssh_key_file).strip()

    def machine_cidrs():
        out = []
        for fam in order:
            out.append(machine_v4 if fam == "v4" else machine_v6)
        return out

    def service_cidrs():
        out = []
        for fam in order:
            out.append(svc_v4 if fam == "v4" else svc_v6)
        return out

    def cluster_entries():
        out = []
        for fam in order:
            if fam == "v4":
                out.append((cluster_v4, hostprefix_v4))
            else:
                out.append((cluster_v6, hostprefix_v6))
        return out

    lines = []
    lines.append("apiVersion: v1")
    lines.append(f"baseDomain: {base_domain}")
    lines.append("compute:")
    lines.append("- architecture: amd64")
    lines.append("  hyperthreading: Enabled")
    lines.append("  name: worker")
    lines.append("  platform: {}")
    lines.append("  replicas: 0")
    lines.append("controlPlane:")
    lines.append("  architecture: amd64")
    lines.append("  hyperthreading: Enabled")
    lines.append("  name: master")
    lines.append("  platform: {}")
    lines.append("  replicas: 1")
    lines.append("metadata:")
    lines.append("  creationTimestamp: null")
    lines.append(f"  name: {cluster_name}")
    lines.append("networking:")
    lines.append("  clusterNetwork:")
    for cidr, hp in cluster_entries():
        lines.append(f"  - cidr: {cidr}")
        lines.append(f"    hostPrefix: {hp}")
    lines.append("  machineNetwork:")
    for cidr in machine_cidrs():
        lines.append(f"  - cidr: {cidr}")
    lines.append("  networkType: OVNKubernetes")
    lines.append("  serviceNetwork:")
    for cidr in service_cidrs():
        lines.append(f"  - {cidr}")
    lines.append("platform:")
    lines.append("  none: {}")
    lines.append("BootstrapInPlace:")
    lines.append(f"  InstallationDisk: {installation_disk}")
    lines.append("publish: External")
    lines.append("pullSecret: |")
    lines.append(_indent_block(pull_secret_compact, 8))
    lines.append("sshKey: |")
    lines.append(_indent_block(ssh_key, 8))
    lines.append("")

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


