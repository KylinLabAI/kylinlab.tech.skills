# Skill Manual: laptop-setup

## What Problem It Solves

Developer laptop setup is repetitive and easy to drift across machines. Users need a profile-aware way to install and verify tools.

## Objective

This skill audits, installs, configures, and verifies developer tools from a YAML app registry.

## Workflow / Design

1. Detect platform and available package managers.
2. Read the app registry and selected profile.
3. Show missing tools or dry-run commands.
4. Install or configure selected apps.
5. Run verification checks and summarize results.

## The App Registry (`configs/apps.yaml`)

This skill is driven by a YAML registry at
[`configs/apps.yaml`](../skills/laptop-setup/configs/apps.yaml). In most cases
**you don't edit it by hand** — you run the scan step below and it generates a
registry that matches what's actually installed on your machine. You only open
the file if you want to fine-tune it (for example, remove a tool you'd rather
not manage):

- **Keep only what you use.** Delete apps you don't need.
- **Add your own tools** — internal CLIs, private package feeds, GUI apps, etc.
- **Map profiles to real roles** (e.g. `backend`, `mobile`, `data`) so a
  profile selects a sensible toolset.
- **Never inline secrets.** Provide tokens/API keys via `--credentials-file`,
  not in the YAML.

Each app entry is a flat list of fields. The most common ones:

| Field | Meaning |
|---|---|
| `name` | Display name |
| `description` | Short description shown in reports |
| `profiles` | Profile tags that select this app (e.g. `[baseline, web]`) |
| `platforms` | Target OS list: `[macos, windows, linux]` |
| `check_command` / `check_<os>_path` | How to detect an existing install |
| `install_<os>` / `install_linux_<pm>` | Install command per platform / package manager |
| `configure_<os>` | Optional auth/config step run after install |
| `verify_<os>` | Optional `{label, command}` checks for `--verify` |
| `bootstrap` | If `true`, install before non-bootstrap apps |

### Generate the registry by scanning your machine (recommended)

Instead of writing this file by hand, you can let the skill **scan your
current machine** and produce a draft that reflects what is actually
installed. There is **no hardcoded app list** — the helper *discovers* your
tools dynamically from the standard install folders and package managers, then
**adds** them to `apps.yaml`:

```bash
# Preview the draft for THIS machine (nothing is written)
python3 skills/laptop-setup/scripts/scan_machine.py --dry-run

# Add this machine's apps into configs/apps.yaml (existing entries kept, never overwritten)
python3 skills/laptop-setup/scripts/scan_machine.py

# Add to your own path instead
python3 skills/laptop-setup/scripts/scan_machine.py --output ~/my-tools.yaml
```

What it probes:

- **GUI apps** in the standard install folders (`/Applications` on macOS,
  `%ProgramFiles%` / `%LOCALAPPDATA%\Programs` on Windows).
- **Package managers**: Homebrew formula/cask, `npm` global packages, `pip`
  packages.
- **Typical CLI install folders**: `/usr/local/bin`, `~/.local/bin`,
  `~/.cargo/bin`, `~/.npm-global/bin`, `/opt/homebrew/bin`.

Deliberate installs (GUI apps + package-manager tools) become active entries
with a best-effort generic install command. Other CLI binaries found in those
folders but not package-managed are listed as a **commented inventory** at the
end of the file, so you can see everything without it polluting the active
registry.

The scan is **append-only and non-destructive**: it never removes or overwrites
an existing entry, so you can build a cross-platform snapshot. A common flow:

1. Empty (or delete) `apps.yaml` once.
2. Run the scan on each of your machines in turn — Windows, macOS, Linux.
3. The file accumulates the **union** of every machine's detected tools.

You remove entries yourself if you want; the scan won't delete anything.
Install commands are generic guesses — review the ones you actually want to
manage.

After it runs, you normally don't need to touch the file — the generated
registry already matches what's on your machine. You only open it if you want to
remove a tool you'd rather not manage.

### What a registry entry looks like (for your understanding only)

You don't need to understand the technical fields or edit this file yourself —
the scan step fills it in for you. This is just one real example so you know
what an entry looks like:

```yaml
- name: Docker Desktop
  description: Container runtime and GUI for building/running containers
  profiles: [baseline, backend, devops]
  platforms: [macos, windows, linux]
  check_macos_command: docker
  check_macos_path: "/Applications/Docker.app"
  check_windows_command: docker
  install_macos: "brew install --cask docker"
  install_windows: "winget install -e --id Docker.DockerDesktop"
  install_linux_apt: "sudo apt install -y docker.io"
```

That's one tool. Your generated registry will contain one block like this for
every app the scan finds on your machine.

## When To Use It

Use this skill when setting up a new laptop, auditing installed tools, installing profile-based toolsets, or verifying developer environment readiness.

Do not use it to manage project dependencies inside a single repository.

## How To Use This Skill

Ask for a list, dry-run, install, configure, or verify operation.

Example requests:

```text
List baseline profile apps and show which are missing.
```

```text
Install the ai profile with a dry-run first.
```

## Example Usage

The user asks to install a profile. The agent lists planned commands, asks for confirmation when appropriate, installs missing tools, and runs verification checks.

## Related Skill File

See [SKILL.md](../skills/laptop-setup/SKILL.md) for the agent-facing execution rules.
