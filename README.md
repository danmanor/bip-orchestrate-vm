See https://github.com/openshift/enhancements/pull/565

Note that this repo is just a proof-of-concept. This repo is for debugging / experimenting with
single-node *bootstrap-in-place* installation. Clusters created by this repo are not officially supported.

bootstrap-in-place is currently unsupported (and doesn't even work) on any cloud providers, it's meant
for baremetal / virtual machines that can boot arbitrary ISO files. Even for those purposes, it might
be easier for you to just use the Red Hat OpenShift Assisted Installer - it's a much more friendly interface
to install Single Node OpenShift on baremetal with proper configurations, validations and bootstrap-in-place
support.

If you need a single-node cluster on a cloud provider - the recommended (but still currently not officially supported) way is 
by just using regular IPI installer and setting the `install-config.yaml` control plane replicas to 1 and the compute replicas 
to 0. This will create, during installation, a temporary extra bootstrap node which will get automatically
torn down by the installer when installation is done, leaving you with a single-node OpenShift installation.

# How to run - manual mode (recommended)

Since the manual mode does not have strong dependencies on any platform (i.e., platform-agnostic), it is therefore the recommended mode for this repo. However, automatic provisioning for `libvirt` and `vsphere` can be found in the [How to run - automatic makefile](https://github.com/eranco74/bootstrap-in-place-poc#how-to-run---automatic-makefile) section below.

- Create a workdir for the installer - `mkdir sno-workdir`
- Create an `install-config.yaml` in the sno-workdir. An example file can be found in `./install-config.yaml.template`. There are a small number of fields in the template that should be set by hand. Reasonable defaults are given below.
    * `IP_STACK` - one of `v4`, `v6`, `v4v6` (dual-stack primary v4), `v6v4` (dual-stack primary v6). **In dual-stack, the primary family is always listed first in `install-config.yaml`**.
    * `MACHINE_NETWORK_V4` - IPv4 machine network CIDR. Default `192.168.126.0/24`.
    * `MACHINE_NETWORK_V6` - IPv6 machine network CIDR. Default `fd00:0:0:126::/64`.
    * `CLUSTER_SVC_NETWORK_V4` - IPv4 service network CIDR. Default `172.30.0.0/16`.
    * `CLUSTER_SVC_NETWORK_V6` - IPv6 service network CIDR. Default `fd02:0:0:0::/112`.
    * `CLUSTER_NETWORK_V4` - IPv4 cluster network CIDR. Default `10.128.0.0/14`.
    * `CLUSTER_NETWORK_V6` - IPv6 cluster network CIDR. Default `fd01:0:0:0::/48`.
    * `CLUSTER_NAME` - the cluster name, the default is `test-cluster`.
    * `BASE_DOMAIN` - the cluster base domain, the default is `redhat.com`.
- Download the ISO to the workdir `./download_live_iso.sh sno-workdir/base.iso`
- Get an installer binary using `oc adm release extract --command=openshift-install --to ./bin ${RELEASE_IMAGE}`
- (optional) If custom manifests are defined, generate manifests with `./manifests.sh` and then copy custom manifests into generated folder. Invocation examples:
```bash
INSTALLATION_DISK=/dev/sda \
RELEASE_IMAGE=quay.io/openshift-release-dev/ocp-release:4.13.5-x86_64 \
INSTALLER_BIN=./bin/openshift-install \
INSTALLER_WORKDIR=./sno-workdir \
./manifests.sh
```
```bash
cp ./manifests/*.yaml $INSTALLER_WORKDIR/manifests/
```
- Generate an ignition file using the installer with `./generate.sh`. Invocation example:
```bash
INSTALLATION_DISK=/dev/sda \
RELEASE_IMAGE=quay.io/openshift-release-dev/ocp-release:4.13.5-x86_64 \
INSTALLER_BIN=./bin/openshift-install \
INSTALLER_WORKDIR=./sno-workdir \
./generate.sh
```
- Embed the ignition file inside the ISO using `./embed.sh`. Invocation example:
```bash
ISO_PATH=./sno-workdir/base.iso \
IGNITION_PATH=./sno-workdir/bootstrap-in-place-for-live-iso.ign \
OUTPUT_PATH=./sno-workdir/embedded.iso \
./embed.sh
```

You can now use `sno-workdir/embedded.iso` to install a single node cluster. The kubeconfig file can be found in `./sno-workdir/auth/kubeconfig`

# How to run - automatic makefile

Automatic mode using Makefiles, currently supports SNO deployments on two virtualization providers, namely `libvirt` and `vSphere`.

### `libvirt` provider
- Set PULL_SECRET environment variable to your pull secret
- `make start-iso` - Spins up a VM with the liveCD. This will automatically perform the following actions:
	- Extract the openshift installer from the release image.
	- Generate the install-config.yaml.
	- Execute the openshift-installer `create single-node-ignition-config` command to generate the bootstrap-in-place-for-live-iso.ign.
	- Add the complete-installation.service to bootstrap-in-place-for-live-iso.ign.
	- Download the RHCOS live ISO.
	- Embed the bootstrap-in-place Ignition to the ISO.
	- Create a libvirt network & VM.
	- Boot the VM with that ISO.
- You can now monitor the progress using `make ssh` and `journalctl -f -u bootkube.service` or `kubectl --kubeconfig ./sno-workdir/auth/kubeconfig get clusterversion`.

### `vSphere` provider
- Update vSphere values and credentials in the [Makefile.vsphere](Makefile.vsphere).
  * `VSPHERE_DATACENTER_NAME`
  * `VSPHERE_DATASTORE_NAME`
  * `VSPHERE_NETWORK_NAME`
  * `VSPHERE_USER`
  * `VSPHERE_PASSWORD`
  * `VSPHERE_SERVER`
  * `VSPHERE_VM_NAME`
- Set PULL_SECRET environment variable to your pull secret
- `make deploy-vsphere` - Spins up a VM with the liveCD in vSphere. This will automatically perform the following actions:
    - Create a workdir for the installer - `mkdir sno-workdir`.
    - Extract the openshift installer from the release image.
    - Generate the install-config.yaml.
    - Execute the openshift-installer `create single-node-ignition-config` command to generate the bootstrap-in-place-for-live-iso.ign.
    - Add the complete-installation.service to bootstrap-in-place-for-live-iso.ign.
    - Download the RHCOS live ISO.
    - Embed the bootstrap-in-place Ignition to the ISO.
    - Upload embedded ISO to vSphere datastore.
    - Create a VM in vSphere
    - Boot the VM with that ISO


# Install SNO with bootstrap in place using the `Agent Based Installer (ABI)` flow
- Set PULL_SECRET environment variable to your pull secret
- `make start-iso-abi` - Spins up a VM with the ABI ISO. This will automatically perform the following actions:
    - Extract the openshift installer from the release image.
    - Generate the install-config.yaml.
    - Execute the openshift-installer `agent create image` command to generate the agent.iso.
    - Create a libvirt network & VM.
    - Boot the VM with that ISO.
- You can now monitor the progress using `abi-wait-complete` or `make ssh` and `journalctl -f -u assisted-service.service` or `kubectl --kubeconfig ./sno-workdir/auth/kubeconfig get clusterversion`.

### Host IP configuration (ABI flow)

For the ABI flow, the host IP is configured via **AgentConfig `hosts[].networkConfig` (nmstate)** (static IP + DNS + default route). This avoids relying on DHCP reservations to force a specific host address.

- The generated `agent-config.yaml` is rendered by `render-agent-config.py` when `AGENT_CONFIG_RENDER=1` (default).
- `make start-iso-abi` still configures local DNS records (`api.*` / `apps.*`) on the libvirt network gateway so the hostnames resolve correctly.
- Interface naming differs by platform:
  - libvirt guests typically use **`ens3`** (default `HOST_IFNAME=ens3`)
  - bare metal often uses names like **`eno1`** (override via `HOST_IFNAME=eno1`)

## IP stack examples (ABI flow)

IPv4 only:

```bash
export IP_STACK=v4
export MACHINE_NETWORK_V4=192.168.126.0/24
export CLUSTER_NETWORK_V4=10.128.0.0/14
export CLUSTER_SVC_NETWORK_V4=172.30.0.0/16
export HOST_IP_V4=192.168.126.10
export HOST_IFNAME=ens3
make start-iso-abi
```

IPv6 only:

```bash
export IP_STACK=v6
export MACHINE_NETWORK_V6=fd00:0:0:126::/64
export HOST_IP_V6=fd00:0:0:126::10
export HOST_IFNAME=ens3
make start-iso-abi
```

Dual-stack, primary IPv4 (v4v6):

```bash
export IP_STACK=v4v6
export HOST_IFNAME=ens3
make start-iso-abi
```

Dual-stack, primary IPv6 (v6v4):

```bash
export IP_STACK=v6v4
export HOST_IP_V6=fd00:0:0:126::10
export HOST_IFNAME=ens3
make start-iso-abi
```

# Other notes

* Default release image is quay.io/openshift-release-dev/ocp-release:4.13.5-x86_64 you can override it using RELEASE_IMAGE env var.
* make will execute the generate.sh script with INSTALLATION_DISK=/dev/vda
* if you’re running the installation on a BM environment, it should be updated.
