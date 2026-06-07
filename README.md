# ansible-redfish-example

Ansible portfolio demonstrating out-of-band server management via the Redfish API. Polls BMC controllers (Dell iDRAC9/10, HPE iLO, Lenovo XCC), checks live firmware and BIOS state against version-controlled YAML baselines, and generates compliance reports. Includes a write path for BIOS setup password rotation via the Dell iDRAC Redfish action endpoint.

## What it does

```
BMC (iDRAC/iLO/XCC)
      │
      │  HTTPS / Redfish
      ▼
Control node (Ansible)
      │
      ├── redfish_facts role     →  polls firmware inventory + BIOS attributes
      ├── compliance_check role  →  diffs live state against YAML baseline
      │       └── filter_plugins/compliance.py  (Python compliance engine)
      ├── bios_firmware role     →  stages BIOS password change via Redfish action
      └── firmware_fetch role    →  raw URI polling with retry for flaky BMCs
            │
            ▼
      files/reports/
        <host>_compliance.json
        <host>_compliance.html
```

Ansible never SSHs to the servers. Every task is delegated to the control node, which speaks Redfish (HTTPS) directly to the BMC address.

## Prerequisites

- Python 3.11+
- ansible-core 2.15+
- community.general collection (`ansible-galaxy collection install -r requirements.yml`)
- Docker or the DMTF mockup server for local testing

## Running locally

### 1. Start the Dell iDRAC mockup server

```bash
# Clone the DMTF mockup server
git clone https://github.com/DMTF/Redfish-Mockup-Server.git

# Clone Dell's iDRAC mockup data
git clone https://github.com/dell/iDRAC-Redfish-Scripting.git
unzip "iDRAC-Redfish-Scripting/iDRAC Redfish Mockup Clients/R660xs_iDRAC9_7_20_10_05_mockup_client.zip" \
  -d idrac-mockup

# Generate a self-signed cert
openssl req -newkey rsa:2048 -nodes \
  -keyout mockup-server.key -x509 -days 365 \
  -out mockup-server.crt -subj "/CN=127.0.0.1"

# Start the server
python3 Redfish-Mockup-Server/redfishMockupServer.py \
  -D idrac-mockup/R660xs_iDRAC9_7_20_10_05_mockup_client \
  -p 8000 --host 127.0.0.1 \
  --ssl --cert mockup-server.crt --key mockup-server.key
```

Verify: `curl -sk https://127.0.0.1:8000/redfish/v1 | python3 -m json.tool | grep Vendor`

### 2. Configure credentials

```bash
ansible-vault create inventory/group_vars/all/vault.yml --vault-password-file .vault_pass
```

The vault file expects:
```yaml
vault_bmc_username: "root"
vault_bmc_password: "calvin"
```

### 3. Run the playbooks

```bash
# Verify BMC connectivity
ansible-playbook playbooks/00_preflight.yml --limit poc-dell-01

# Collect and display firmware + BIOS data
ansible-playbook playbooks/10_audit.yml --limit poc-dell-01

# Run compliance check against baseline — generates HTML + JSON reports
ansible-playbook playbooks/20_compliance.yml --limit poc-dell-01

# Stage a BIOS setup password change (--check for dry run)
# BIOS_OLD_PASSWORD and BIOS_NEW_PASSWORD must be set in the environment
export BIOS_OLD_PASSWORD=""
export BIOS_NEW_PASSWORD="YourNewPassword"
ansible-playbook playbooks/30_bios_password.yml --limit poc-dell-01 --check

# Fetch firmware inventory via raw Redfish URI with retry handling
ansible-playbook playbooks/40_firmware_fetch.yml --limit poc-dell-01
```

Reports are written to `files/reports/`.

## Project structure

```
├── ansible.cfg                      # project-local config
├── requirements.yml                 # Ansible collection dependencies
├── inventory/
│   ├── hosts.yml                    # BMC inventory — vendor-grouped
│   └── group_vars/
│       ├── all/
│       │   ├── vars.yml             # global Redfish settings + credential refs
│       │   └── vault.yml            # AES-256 encrypted BMC credentials
│       ├── dell_idrac.yml           # Dell-specific resource IDs
│       ├── hpe_ilo.yml
│       └── lenovo_xcc.yml
├── baselines/
│   └── dell_idrac9_r660xs.yml       # desired-state: firmware versions + BIOS attrs
├── filter_plugins/
│   └── compliance.py                # Python compliance engine
├── roles/
│   ├── redfish_facts/               # polls BMC, sets redfish_firmware_entries + redfish_bios_attrs
│   ├── compliance_check/            # diffs live state vs baseline, writes reports
│   ├── bios_firmware/               # Dell BIOS setup password via Redfish action
│   └── firmware_fetch/              # raw URI fetch with retry for flaky endpoints
├── playbooks/
│   ├── 00_preflight.yml
│   ├── 10_audit.yml
│   ├── 20_compliance.yml
│   ├── 30_bios_password.yml
│   └── 40_firmware_fetch.yml
└── .github/workflows/ci.yml         # yamllint + syntax check + live compliance run
```

## Inventory design

The inventory lists BMC controllers, not operating systems. Hosts are grouped by vendor so the correct OEM Redfish endpoints and baselines apply automatically via `group_vars`. Adding a new vendor means adding a group, a `group_vars/<vendor>.yml`, and a baseline file — the playbooks need no changes.

## Compliance baseline

`baselines/dell_idrac9_r660xs.yml` defines minimum firmware versions and required BIOS attribute values for a Dell PowerEdge R660xs. The compliance engine (`filter_plugins/compliance.py`) performs version-aware comparison — a server with a newer firmware version than the baseline minimum passes; an older version fails.

The mockup deliberately has `SecureBoot: Disabled` while the baseline requires `Enabled`. This produces a live compliance failure on every run, demonstrating the tool catching a real security misconfiguration.

## Secrets

Two tiers of secret management are used, reflecting different sensitivity levels:

**BMC read credentials** (`vault_bmc_username`, `vault_bmc_password`) are stored in an Ansible Vault file (`inventory/group_vars/all/vault.yml`). The vault file is committed encrypted (AES-256) — only the vault password is secret. The vault password is stored in `.vault_pass` locally and as the `VAULT_PASSWORD` GitHub Secret in CI. In production this would be replaced by a HashiCorp Vault or CyberArk lookup plugin.

**BIOS setup password** (`BIOS_OLD_PASSWORD`, `BIOS_NEW_PASSWORD`) is more sensitive — it's a write credential that changes server firmware configuration. It is never stored in the vault. Instead it is sourced from environment variables at runtime, populated from GitHub Secrets in CI or a secrets manager in production. This means the BIOS password is never written to disk or committed to the repository in any form.

```
Ansible Vault  →  BMC polling credentials (read)
GitHub Secrets →  BIOS setup password (write, higher sensitivity)
```

## CI

GitHub Actions runs on every pull request to `master`:

1. `lint-and-validate` — yamllint + ansible syntax check across all playbooks
2. `compliance` — spins up the DMTF mockup server with a real Dell iDRAC9 mockup, then runs:
   - `20_compliance.yml` — full compliance check (SecureBoot finding expected)
   - `30_bios_password.yml --check` — BIOS password dry run, with `BIOS_OLD_PASSWORD` and `BIOS_NEW_PASSWORD` sourced from GitHub Secrets

The `master` branch is protected by a ruleset: no direct pushes, PR required, signed commits enforced, `lint-and-validate` must pass before merge.
