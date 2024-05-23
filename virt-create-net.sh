#!/bin/bash
# Create a libvirt virtual network called 'test-net' configured
# to assign sno1.test-cluster.redhat.com/192.168.126.10 to
# DHCP requests from 52:54:00:ee:42:e1
# libvirt will also configure dnsmasq (listening on 192.168.126.1)
# to respond to DNS queries for several hosts under
# test-cluster.redhat.com with the 192.168.126.10 address.
# This dnsmasq is also configured to not forward unresolved requests
# within the test-cluster.redhat.com domain to upstream DNS servers.
# Finally, we configure NetworkManager to send any DNS queries
# on this machine for api.test-cluster.redhat.com to the libvirt
# configured dnsmasq on 192.168.126.1

# Warn terminal users about dns changes
if [ -t 1 ]; then
    function ask_yes_or_no() {
        read -p "$1 ([y]es or [N]o): "
        case $(echo "$REPLY" | tr '[A-Z]' '[a-z]') in
            y|yes) echo "yes" ;;
            *)     echo "no" ;;
        esac
    }

    echo "This script will make changes to the DNS configuration of your machine, read $0 to learn more"

    if [[ -f .dns_changes_confirmed || "yes" == $(ask_yes_or_no "Are you sure you want to continue?") ]]; then
        touch .dns_changes_confirmed
    else
        exit 1
    fi
fi

set -euo pipefail

if [ -z "${NET_NAME:-}" ]; then
    echo "Please set NET_NAME"
    exit 1
fi

if [ -z ${NET_XML+x} ]; then
    echo "Please set NET_XML"
    exit 1
fi

if [ -z "${NET_UUID:-}" ]; then
    echo "Please set NET_UUID"
    exit 1
fi

_xml_bridge_name() {
python3 - "$1" <<'PY'
import sys
import xml.etree.ElementTree as ET
path = sys.argv[1]
root = ET.parse(path).getroot()
bridge = root.find("bridge")
print("" if bridge is None else bridge.attrib.get("name", ""))
PY
}

_xml_uuid() {
python3 - "$1" <<'PY'
import sys
import xml.etree.ElementTree as ET
path = sys.argv[1]
root = ET.parse(path).getroot()
uuid = root.find("uuid")
print("" if uuid is None or uuid.text is None else uuid.text.strip())
PY
}

_virsh_net_dumpxml() {
    sudo virsh net-dumpxml "$1" 2>/dev/null || true
}

_virsh_bridge_name() {
python3 - <<'PY'
import sys
import xml.etree.ElementTree as ET
xml = sys.stdin.read()
if not xml.strip():
    print("")
    raise SystemExit(0)
root = ET.fromstring(xml)
bridge = root.find("bridge")
print("" if bridge is None else bridge.attrib.get("name", ""))
PY
}

_virsh_uuid() {
python3 - <<'PY'
import sys
import xml.etree.ElementTree as ET
xml = sys.stdin.read()
if not xml.strip():
    print("")
    raise SystemExit(0)
root = ET.fromstring(xml)
uuid = root.find("uuid")
print("" if uuid is None or uuid.text is None else uuid.text.strip())
PY
}

# If NET_BRIDGE_NAME is provided, validate it matches the XML we are about to define.
if [ -n "${NET_BRIDGE_NAME:-}" ]; then
    xml_bridge="$(_xml_bridge_name "${NET_XML}")"
    if [ -z "${xml_bridge}" ]; then
        echo "Error: could not determine <bridge name='...'> from ${NET_XML}"
        exit 1
    fi
    if [ "${xml_bridge}" != "${NET_BRIDGE_NAME}" ]; then
        echo "Error: NET_BRIDGE_NAME='${NET_BRIDGE_NAME}' but ${NET_XML} contains bridge '${xml_bridge}'"
        echo "Hint: this usually means you're defining a stale/incorrect net.xml from a different directory."
        exit 1
    fi
fi

# If a network with the same name exists but has a different UUID, replace it.
existing_uuid="$(_virsh_net_dumpxml "${NET_NAME}" | _virsh_uuid)"
if [ -n "${existing_uuid}" ] && [ "${existing_uuid}" != "${NET_UUID}" ]; then
    echo "Network '${NET_NAME}' already exists with UUID '${existing_uuid}' (expected '${NET_UUID}'), replacing it"
    sudo virsh net-destroy "${NET_NAME}" >/dev/null 2>&1 || true
    sudo virsh net-undefine "${NET_NAME}" >/dev/null 2>&1 || true
fi

# Only create network if it does not exist
if ! sudo virsh net-dumpxml $NET_NAME | grep -q "<uuid>$NET_UUID</uuid>"; then
    sudo virsh net-define "${NET_XML}"
    # Sanity-check what libvirt stored (helps catch "stale XML" or unexpected mutation).
    stored_xml="$(_virsh_net_dumpxml "${NET_NAME}")"
    stored_bridge="$(printf '%s' "${stored_xml}" | _virsh_bridge_name)"
    if [ -n "${NET_BRIDGE_NAME:-}" ] && [ -n "${stored_bridge}" ] && [ "${stored_bridge}" != "${NET_BRIDGE_NAME}" ]; then
        echo "Error: after net-define, libvirt stored bridge '${stored_bridge}' but NET_BRIDGE_NAME='${NET_BRIDGE_NAME}'"
        echo "This indicates the network definition does not match the intended XML."
        exit 1
    fi
    sudo virsh net-autostart $NET_NAME
    if ! sudo virsh net-start $NET_NAME; then
        echo "Error: failed to start libvirt network '${NET_NAME}' from ${NET_XML}"
        if [ -n "${NET_BRIDGE_NAME:-}" ]; then
            echo "Bridge requested: ${NET_BRIDGE_NAME}"
        else
            echo "Bridge in XML: $(_xml_bridge_name "${NET_XML}")"
        fi
        echo "Bridge in libvirt definition: ${stored_bridge:-unknown}"
        echo "Tip: if you see 'already in use by interface <X>', pick a unique NET_BRIDGE_NAME not used on the host."
        exit 1
    fi
fi

echo -e "[main]\ndns=dnsmasq" | sudo tee /etc/NetworkManager/conf.d/bip.conf
sudo systemctl reload NetworkManager.service
