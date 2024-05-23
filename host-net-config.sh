#!/bin/bash

set -euo pipefail

tmpfile=$(mktemp)
_cleanup(){
    rm -f $tmpfile
}
trap _cleanup exit

CONFIGURE_DHCP="${CONFIGURE_DHCP:-1}"

_stack_order() {
    # prints families in desired order: ipv4 ipv6 / ipv6 ipv4 / ...
    case "${IP_STACK:-v4}" in
        v4) echo "ipv4" ;;
        v6) echo "ipv6" ;;
        v4v6) echo "ipv4 ipv6" ;;
        v6v4) echo "ipv6 ipv4" ;;
        *) echo "IP_STACK must be one of: v4, v6, v4v6, v6v4" >&2; exit 2 ;;
    esac
}

_want_v4() { [[ "${IP_STACK:-v4}" == "v4" || "${IP_STACK:-v4}" == "v4v6" || "${IP_STACK:-v4}" == "v6v4" ]]; }
_want_v6() { [[ "${IP_STACK:-v4}" == "v6" || "${IP_STACK:-v4}" == "v4v6" || "${IP_STACK:-v4}" == "v6v4" ]]; }

_dnsmasq_set_addresses() {
    # _dnsmasq_set_addresses domain_name ip1 [ip2 ...]
    local domain="$1"; shift
    sudo mkdir -p /etc/NetworkManager/dnsmasq.d
    if [ -f /etc/NetworkManager/dnsmasq.d/bip.conf ]; then
        grep -vE "^address=/${domain}/" /etc/NetworkManager/dnsmasq.d/bip.conf > "$tmpfile" || true
    else
        : > "$tmpfile"
    fi
    for ip in "$@"; do
        echo "address=/${domain}/${ip}" >> "$tmpfile"
    done
    sudo tee /etc/NetworkManager/dnsmasq.d/bip.conf < "$tmpfile" >/dev/null
}

_family_index() {
    # _family_index ipv4|ipv6 -> 0-based index of <ip family='...'> in libvirt network XML
    local fam="$1"
    # In dual-stack, the order in net.xml is controlled by IP_STACK (primary first).
    # We intentionally compute it from virsh output to avoid assumptions.
    local idx
    idx="$(sudo virsh net-dumpxml "$NET_NAME" | awk -F"'" '/<ip family=/{print $2}' | nl -ba | awk -v f="$fam" '$2==f {print $1-1; exit}')"
    if [ -z "$idx" ]; then
        echo "Could not find <ip family='$fam'> in libvirt network $NET_NAME" >&2
        exit 1
    fi
    echo "$idx"
}

_net_update_dhcp_host() {
    # _net_update_dhcp_host ipv4|ipv6 ip_addr
    local fam="$1"
    local ip="$2"
    if [ "$fam" = "ipv6" ]; then
        # libvirt/dnsmasq does not accept "mac=" for IPv6 static host definitions.
        # Without a predictable DUID, we can't safely reserve a fixed IPv6 by host identity here.
        # For single-node libvirt usage, we instead make the IPv6 DHCP range start at HOST_IP_V6
        # (see render-net-xml.py), so the first lease is deterministic.
        return 0
    fi
    local idx
    idx="$(_family_index "$fam")"
    local xml
    xml="<host mac=\"${HOST_MAC}\" name=\"${HOST_NAME}\" ip=\"${ip}\"/>"

    # If the host entry already exists under this MAC, "modify" works; otherwise fall back to add-last.
    if sudo virsh net-update "$NET_NAME" modify ip-dhcp-host "$xml" --live --parent-index "$idx" >/dev/null 2>&1; then
        return 0
    fi
    sudo virsh net-update "$NET_NAME" add-last ip-dhcp-host "$xml" --live --parent-index "$idx" >/dev/null
}

# Defaults for older callers
: "${HOST_IP_V4:=${HOST_IP:-192.168.126.10}}"
: "${HOST_IP_V6:=${HOST_IP_V6:-fd00:0:0:126::10}}"

# Optionally update libvirt DHCP configuration for requested families.
# For ABI, we prefer static host configuration via AgentConfig nmstate, so callers can disable DHCP edits.
if [ "${CONFIGURE_DHCP}" = "1" ]; then
    if _want_v4; then
        _net_update_dhcp_host ipv4 "${HOST_IP_V4}"
    fi
    if _want_v6; then
        _net_update_dhcp_host ipv6 "${HOST_IP_V6}"
    fi
fi

# Update dnsmasq configuration
dns_ips=()
if _want_v4; then dns_ips+=("${HOST_IP_V4}"); fi
if _want_v6; then dns_ips+=("${HOST_IP_V6}"); fi
_dnsmasq_set_addresses "api.${CLUSTER_NAME}.${BASE_DOMAIN}" "${dns_ips[@]}"
_dnsmasq_set_addresses "apps.${CLUSTER_NAME}.${BASE_DOMAIN}" "${dns_ips[@]}"
sudo systemctl reload NetworkManager.service
