# Installing on a cloud VM with Docker (AWS, Azure, Google Cloud)

The simplest way to run Agent Hangar in the cloud is one virtual machine with Docker. It runs the same stack as on a
laptop, and the guided installer works the same way. Use Kubernetes ([kubernetes.md](kubernetes.md)) when you need
several replicas, a managed database or autoscaling.

Every cloud command below comes from that provider's own documentation; the source is linked under each step.

**The flow, on any cloud:**

1. Create an **Ubuntu 24.04 LTS** VM. It needs a firewall that allows **only SSH, and only from your IP**.
2. Install **Docker Engine** with Docker's official apt repository.
3. Clone the repository and run the **installer**.
4. Give people an **HTTPS address**. Use a tunnel, which opens no inbound ports, or your own reverse proxy.

> Do not open port 8090 to the internet. The tunnel (or a reverse proxy on 443) is the only way in. Until you set it
> up, reach the portal through an SSH port-forward (step 4).

## Machine size

| | x86-64 | ARM64 (cheaper per vCPU) |
|---|---|---|
| **AWS** | `t3.xlarge` (4 vCPU, 16 GiB) | `m7g.xlarge` (Graviton3, 4 vCPU, 16 GiB) |
| **Azure** | `Standard_D4s_v5` (4 vCPU, 16 GiB) | `Standard_D4ps_v5` (Ampere Altra, 4 vCPU, 16 GiB) |
| **Google Cloud** | `e2-standard-4` (4 vCPU, 16 GB) | `c4a-standard-4` (Axion, 4 vCPU, 16 GB) |

- 16 GB covers the base stack plus memory (Neo4j) and Data Studio. For the base stack alone, 8 GB is enough (see
  [install.md](install.md#1-requirements)).
- Give the disk 64 GB: images, agent containers, the database and backups.
- The published images are multi-architecture since 0.14.1, so ARM machines work without changes.

References:
- AWS: [general purpose instance types](https://aws.amazon.com/ec2/instance-types/general-purpose/),
  [M7g](https://aws.amazon.com/ec2/instance-types/m7g/).
- Azure: [Dsv5 series](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dsv5-series),
  [Dpsv5 series](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dpsv5-series).
- Google Cloud: [general-purpose machine family](https://docs.cloud.google.com/compute/docs/general-purpose-machines).

---

## 1. Create the VM

### AWS (Amazon EC2)

You need the AWS CLI installed and configured
([install](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)).

**1. Key pair.** The private key can only be downloaded now.

```bash
aws ec2 create-key-pair --key-name agent-hangar --query 'KeyMaterial' --output text > agent-hangar.pem
chmod 400 agent-hangar.pem
```

[Source: key pairs in the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-services-ec2-keypairs.html)

**2. Security group.** Only SSH, only from your IP.

```bash
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG_ID=$(aws ec2 create-security-group --group-name agent-hangar --description "Agent Hangar" \
          --vpc-id "$VPC_ID" --query GroupId --output text)
MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$MY_IP/32"
```

[Source: security groups in the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-services-ec2-sg.html)

**3. Instance.** Canonical publishes the current Ubuntu AMI as a Systems Manager public parameter, so there is no AMI
ID to look up. For ARM, use `.../current/arm64/...` with `--instance-type m7g.xlarge`.

```bash
aws ec2 run-instances \
  --image-id resolve:ssm:/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --instance-type t3.xlarge --count 1 \
  --key-name agent-hangar --security-group-ids "$SG_ID" \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":64,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=agent-hangar}]'
```

Sources:
- [run-instances in the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-services-ec2-instances.html)
- [`resolve:ssm` public parameters](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/finding-an-ami-parameter-store.html)
- [Ubuntu parameter paths (Canonical)](https://ubuntu.com/aws/docs/aws-how-to/instances/find-ubuntu-images/)
- [block device mapping](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/block-device-mapping-concepts.html)

**4. Connect.** The user on Ubuntu AMIs is `ubuntu`.

```bash
IP=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=agent-hangar" "Name=instance-state-name,Values=running" \
       --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
ssh -i agent-hangar.pem ubuntu@"$IP"
```

[Source: connect to a Linux instance](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-to-linux-instance.html)

To connect without opening port 22 at all, AWS offers
[Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html): "no need to open
inbound ports, maintain bastion hosts, or manage SSH keys".

### Azure (Virtual Machines)

You need the Azure CLI ([install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)), signed in with
`az login`. Azure Cloud Shell already has it.

**1. Resource group and a network security group.** Only SSH, only from your IP. Creating the NSG first avoids the
default rule that `az vm create` would add, which allows port 22 from any source.

```bash
az group create --name rg-agent-hangar --location eastus
az network nsg create --resource-group rg-agent-hangar --name nsg-agent-hangar
MY_IP=$(curl -s https://checkip.amazonaws.com)
az network nsg rule create --resource-group rg-agent-hangar --nsg-name nsg-agent-hangar --name SSH \
  --access Allow --protocol Tcp --direction Inbound --priority 100 \
  --source-address-prefix "$MY_IP/32" --source-port-range "*" \
  --destination-address-prefix "*" --destination-port-range 22
```

Sources:
- [quickstart: create a Linux VM with the Azure CLI](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/quick-create-cli)
- [network security groups for Linux VMs](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/tutorial-virtual-network)

**2. VM.** Ubuntu 24.04 is `Canonical:ubuntu-24_04-lts:server:latest`. For ARM, use
`Canonical:ubuntu-24_04-lts:server-arm64:latest` with `--size Standard_D4ps_v5`.

```bash
az vm create \
  --resource-group rg-agent-hangar --name agent-hangar \
  --image Canonical:ubuntu-24_04-lts:server:latest \
  --size Standard_D4s_v5 --os-disk-size-gb 64 \
  --admin-username azureuser --generate-ssh-keys \
  --public-ip-sku Standard --nsg nsg-agent-hangar
```

Sources:
- [az vm create reference](https://learn.microsoft.com/en-us/cli/azure/vm)
- [finding images with the CLI](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/cli-ps-findimage)
- [Ubuntu image URNs (Canonical)](https://ubuntu.com/azure/docs/azure-how-to/instances/find-ubuntu-images/)

**3. Connect.**

```bash
IP=$(az vm show --show-details --resource-group rg-agent-hangar --name agent-hangar --query publicIps --output tsv)
ssh azureuser@"$IP"
```

To reach the VM with no public SSH port, use
[Azure Bastion](https://learn.microsoft.com/en-us/azure/bastion/bastion-overview): "your virtual machines don't need
a public IP address, agent, or special client software".

### Google Cloud (Compute Engine)

You need the gcloud CLI ([install](https://docs.cloud.google.com/sdk/docs/install)), set up with `gcloud init`.
Cloud Shell already has it.

**1. Firewall: SSH only through IAP.** No SSH from the internet.

```bash
gcloud compute firewall-rules create allow-ssh-ingress-from-iap \
  --direction=INGRESS --action=allow --rules=tcp:22 \
  --source-ranges=35.235.240.0/20 --target-tags=agent-hangar
```

Sources:
- [IAP TCP forwarding](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding)
- In the `default` network, the pre-populated rule `default-allow-ssh` allows port 22 from `0.0.0.0/0`. If your
  project uses that network, restrict or remove that rule. See
  [VPC firewall rules](https://docs.cloud.google.com/firewall/docs/firewalls).

**2. VM.** The image family is `ubuntu-2404-lts-amd64` in the project `ubuntu-os-cloud`. For ARM, use the family
`ubuntu-2404-lts-arm64` with an Arm machine type such as `c4a-standard-4`; check that type's zones and disk types on
the machine family page.

```bash
gcloud compute instances create agent-hangar \
  --zone=us-central1-a --machine-type=e2-standard-4 \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=64GB --tags=agent-hangar
```

Sources:
- [operating system details (image families)](https://docs.cloud.google.com/compute/docs/images/os-details)
- [gcloud compute instances create](https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/create)

**3. Connect.**

```bash
gcloud compute ssh agent-hangar --zone=us-central1-a --tunnel-through-iap
```

[Source: gcloud compute ssh](https://docs.cloud.google.com/sdk/gcloud/reference/compute/ssh)

---

## 2. Install Docker Engine (on the VM)

These are Docker's official steps for Ubuntu. Ubuntu 24.04 is supported on both x86-64 and arm64.

```bash
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

[Source: install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

Then run Docker without `sudo`, and have it start at boot:

```bash
sudo usermod -aG docker $USER
newgrp docker
sudo systemctl enable docker.service containerd.service
```

[Source: Linux post-installation steps](https://docs.docker.com/engine/install/linux-postinstall/). As Docker's
docs warn, the `docker` group grants root-level privileges, so add only the admin who runs the hangar.

## 3. Install Agent Hangar (on the VM)

```bash
sudo apt install -y git python3-venv
git clone https://github.com/valteresj2/agent-hangar && cd agent-hangar
./scripts/install.sh
```

The wizard is the same as on any machine ([install.md](install.md#3-what-the-wizard-asks)). Two answers matter on a
cloud VM:

- **Images:** `published`. They are pulled from ghcr.io; nothing is built on the VM.
- **Address:** choose a tunnel. Each one gives HTTPS without opening any inbound port:

| Tunnel | What you need |
|---|---|
| **Cloudflare Tunnel** | A Cloudflare account and a domain. "connect your resources to Cloudflare without a publicly routable IP address" ([docs](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)). |
| **Tailscale Funnel** | An auth key, with HTTPS and Funnel enabled in the tailnet ([docs](https://tailscale.com/kb/1223/funnel)). |
| **ngrok** | An authtoken and a fixed domain (the free one works). |

**Your own domain instead of a tunnel:**
1. Choose *local* in the wizard.
2. Put a reverse proxy with TLS in front of `localhost:8090`.
3. Set `PUBLIC_BASE_URL=https://your-domain` in `.env`.
4. Allow only port 443 in the cloud firewall.

For unattended installs (VM images, cloud-init), use `./scripts/install.sh --answers setup.yaml` with
[`setup.example.yaml`](../setup.example.yaml) as the model.

## 4. Open it

- **With a tunnel:** open the HTTPS address the wizard printed.
- **Before the tunnel (or for admin only):** forward the port over SSH and open `http://localhost:8090` on your
  computer:

```bash
ssh -i agent-hangar.pem -L 8090:localhost:8090 ubuntu@"$IP"                           # AWS
ssh -L 8090:localhost:8090 azureuser@"$IP"                                             # Azure
gcloud compute ssh agent-hangar --zone=us-central1-a --tunnel-through-iap -- -L 8090:localhost:8090   # Google Cloud
```

Then run `hangar doctor` on the VM. It checks Docker, the central, the LLM, memory, the public address and TLS.

## Day 2

- **Upgrade:** `hangar upgrade --version <x.y.z>` takes a backup first. See [backup.md](backup.md).
- **Backups:** `hangar backup` writes to `.hangar/backups/`. Copy them off the VM (S3, Blob Storage, Cloud Storage),
  or also take disk snapshots in your cloud.
- **Costs:** a stopped VM is not billed for compute; its disk still is.

## Remove everything

```bash
aws ec2 terminate-instances --instance-ids <instance-id>                            # AWS (then delete the SG and key pair)
az group delete --name rg-agent-hangar                                              # Azure: the whole resource group
gcloud compute instances delete agent-hangar --zone=us-central1-a                   # Google Cloud
gcloud compute firewall-rules delete allow-ssh-ingress-from-iap
```

Sources:
- [terminate EC2 instances](https://docs.aws.amazon.com/cli/latest/userguide/cli-services-ec2-instances.html#terminating-instances)
- [az group delete (Azure)](https://learn.microsoft.com/en-us/cli/azure/group)

Terminating or deleting is permanent: back up `.hangar/backups/` first.
