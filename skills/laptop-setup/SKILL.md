---
name: laptop-setup
description: >
  Provision, audit, or verify a developer laptop from a YAML app registry.
  Use this skill whenever the user mentions setting up a new laptop, fresh
  machine, dev machine, daily tools, installing many apps, checking whether
  tools are installed, re-running post-install setup, or verifying iOS
  Simulators / Android emulators. The
  bundled script detects macOS, Windows, and Linux, checks architecture and
  package managers, supports profile-based selection, dry-runs, skips
  already-installed apps, and runs optional post-install and verification
  commands from configs/apps.yaml.
---

# Laptop Setup

Use this skill to help a user audit, install, and verify the daily-use tools
on a new or existing laptop. The bundled tool reads
[./configs/apps.yaml](./configs/apps.yaml), detects the current platform,
checks which apps are already installed, and runs the configured install,
post-install, or verification commands.

The tool can make real changes to the machine. Treat `--list`, `--check`,
`--profiles`, `--verify`, and `--dry-run` as the normal first steps; run
mutating commands only when the user has clearly asked for installation or
setup.

## Agent Workflow

1. Locate the skill directory and run `python3 <skill>/scripts/laptop_setup.py --info`.
2. Run `python3 <skill>/scripts/laptop_setup.py --profiles` when the user wants
   a subset such as `baseline`, `containers`, `java`, `mobile`, or `ai`.
3. Run `python3 <skill>/scripts/laptop_setup.py --list` to show current status,
   optionally with `--profile <profile>`.
4. If the user wants installation or setup, preview with `--dry-run` first.
5. Explain the commands that will run, especially commands using `sudo`,
   package managers, App Store installs, shell profile edits, VM setup, or
   login/authentication prompts.
6. Run the requested mutating command only after the user's intent is clear:
   `--install`, `--install --name "App"`, `--setup`, `--configure`, or
   `--configure --name "App"`.
7. Run `--verify` for configured toolchains such as Xcode, iOS Simulator,
   Android Studio, Android SDK, and emulators.

If the current agent cannot execute local shell commands, provide the exact
commands for the user to run and explain the expected output.

## Skill Layout

- [./scripts/laptop_setup.py](./scripts/laptop_setup.py) - command-line tool
- [./scripts/scan_machine.py](./scripts/scan_machine.py) - scan this machine and
  generate a customized `apps.yaml` draft from what is actually installed
- [./configs/apps.yaml](./configs/apps.yaml) - bundled application registry (default)

### Custom registries (`--apps-file`)

By default the script loads the bundled `configs/apps.yaml`. Pass
`--apps-file <path>` to load any other YAML file in the same flat schema.
This lets other skills or users ship their own tool list without modifying
the bundled registry. All other flags (`--list`, `--install`, `--setup`,
`--verify`, `--profile`, `--name`, `--dry-run`) work identically against
the custom file.

```bash
# Default: bundled registry
python3 <skill>/scripts/laptop_setup.py --list

# Custom registry shipped by another skill
python3 <skill>/scripts/laptop_setup.py --install \
  --apps-file <other-skill>/configs/apps.yaml \
  --profile <profile>

# Personal registry
python3 <skill>/scripts/laptop_setup.py --list --apps-file ~/my-tools.yaml
```

### Generating the registry from this machine (instead of hand-editing)

`configs/apps.yaml` is a draft that the user must customize. Rather than
editing it by hand, you can **scan the user's current machine** and produce a
starting point that reflects what is actually installed:

```bash
# Preview the drafted registry for THIS machine (no files written)
python3 <skill>/scripts/scan_machine.py --dry-run

# Append this machine's detected apps into configs/apps.yaml
# (existing entries are kept verbatim; nothing is removed or overwritten)
python3 <skill>/scripts/scan_machine.py

# Append to a custom path instead
python3 <skill>/scripts/scan_machine.py --output ~/my-tools.yaml
```

`scan_machine.py` **discovers** tools/apps dynamically — there is no hardcoded
app list. It probes:

- **GUI apps** in the standard install folders (`/Applications` on macOS,
  `%ProgramFiles%` / `%LOCALAPPDATA%\Programs` on Windows).
- **Package managers**: `brew` formula/cask, `npm` global packages, `pip`
  packages.
- **Typical CLI install folders**: `/usr/local/bin`, `~/.local/bin`,
  `~/.cargo/bin`, `~/.npm-global/bin`, `/opt/homebrew/bin`.

Deliberate installs (GUI apps + package-manager tools) become **active entries**
with a best-effort generic install command (e.g. `brew install --cask <name>`).
Extra CLI binaries found in the install folders but not package-managed are
listed as a **commented inventory** at the end of the file.

It is **append-only and non-destructive**: only the detected tools whose `name`
is not already in the target file are added. Existing entries are never removed
or overwritten, so you can build a cross-platform snapshot safely:

1. Empty/delete `apps.yaml` once.
2. Run the scan on each of your machines in turn (Windows, macOS, Linux).
3. The file accumulates the **union** of every machine's detected tools.

The user removes entries themselves; the scan never deletes. After scanning,
review the draft before running `laptop_setup.py` — install commands are generic
guesses, so correct the ones you actually want to manage.

When the user says things like "set up my laptop", "make a registry for my
machine", or "update the apps list for what I have", prefer running
`scan_machine.py` first, then use the generated file with `laptop_setup.py`.

## Quick Start

```bash
# Show platform info
python3 <skill>/scripts/laptop_setup.py --info

# List apps & their status
python3 <skill>/scripts/laptop_setup.py --list
python3 <skill>/scripts/laptop_setup.py --profiles
python3 <skill>/scripts/laptop_setup.py --list --profile baseline

# Install everything that's missing (+ run post-install)
python3 <skill>/scripts/laptop_setup.py --install
python3 <skill>/scripts/laptop_setup.py --install --profile baseline --dry-run

# Install one specific app
python3 <skill>/scripts/laptop_setup.py --install --name "Visual Studio Code"

# Run post-install steps for already-installed apps
python3 <skill>/scripts/laptop_setup.py --setup
python3 <skill>/scripts/laptop_setup.py --setup --name "Android Studio"

# Run interactive configure steps (auth logins, etc.) for installed apps
python3 <skill>/scripts/laptop_setup.py --configure
python3 <skill>/scripts/laptop_setup.py --configure --name "GitHub CLI"

# Run configure steps non-interactively using a credentials file
python3 <skill>/scripts/laptop_setup.py --configure \
  --credentials-file ~/.config/laptop-setup/credentials.yaml
python3 <skill>/scripts/laptop_setup.py --install --profile baseline \
  --credentials-file ~/.config/laptop-setup/credentials.yaml \
  --non-interactive
python3 <skill>/scripts/laptop_setup.py --install --skip-configure

# Dry-run (show commands without executing)
python3 <skill>/scripts/laptop_setup.py --install --dry-run
python3 <skill>/scripts/laptop_setup.py --setup --dry-run
python3 <skill>/scripts/laptop_setup.py --install --name "Visual Studio Code" --dry-run

# Verify simulators, emulators & post-install state
python3 <skill>/scripts/laptop_setup.py --verify
python3 <skill>/scripts/laptop_setup.py --verify --name "Xcode"
```

Replace `<skill>` with the absolute path to this skill folder, for example
`~/.agents/skills/laptop-setup`, `~/.codex/skills/laptop-setup`, or a repo
path such as `kylinlab.tech.skills/skills/laptop-setup`.

## How It Works

1. **Detect platform** — macOS / Windows / Linux
2. **Detect architecture** — arm64, x64, x86, and CPU brand string
3. **Detect package managers** — brew, winget, choco, apt, dnf, snap …
4. **Load apps.yaml** — bundled `configs/apps.yaml` by default, or any
   file passed via `--apps-file <path>`
5. **Filter selection** — all apps by default, or apps tagged by `--profile`
6. **Check each app** — via PATH command lookup, shell checks, or well-known file paths
7. **Install missing** — using the right command for the detected platform
8. **Run post-install** — execute `post_install_<os>` commands for newly installed (or `--setup`) apps
9. **Run configure** — execute `configure_<os>` steps for newly installed
   apps (or `--configure`). Each step picks `non_interactive` when
   credentials are available, otherwise falls back to `interactive` unless
   `--non-interactive` is set
10. **Print a summary** — after any install/setup/configure run, a unified
    table shows per-app install / post-install / configure status, plus a
    "Manual follow-ups needed" section listing missing credentials or
    failed steps. A machine-readable copy is written to
    `~/.laptop-setup/last-run.json` (mode 600)
11. **Verify** — run `verify_<os>` checks to list simulators, emulators, SDK state (`--verify`)

## Platform Support

| Platform | Package Manager | GUI App Check | Notes |
|----------|----------------|---------------|-------|
| macOS    | Homebrew (`brew`) | `/Applications/*.app` | Auto-installs Homebrew if missing |
| Windows  | winget | `%PROGRAMFILES%` paths | Asks user to install App Installer if winget missing |
| Linux    | apt / dnf / snap | `which` command | Detects distro package manager automatically |

## Registered Apps

| App | Platforms | Install Method | Post-Install |
|-----|-----------|---------------|--------------|
| Docker Desktop | macOS, Windows | brew cask / winget | Manual first launch may finish backend setup |
| Node.js, Python, Git, GitHub CLI, ripgrep, jq | macOS, Windows, Linux | brew / winget / apt,dnf | Baseline developer CLI tools |
| ClaudeCode, Codex, Copilot CLI | macOS, Windows, Linux | brew / winget / npm / apt,dnf | Auth/login after install |
| Wireshark | macOS, Windows, Linux | brew cask / winget / apt,dnf | — |
| UTM | macOS | brew cask | — |
| Android Studio | macOS, Windows, Linux | brew cask / winget / snap | SDK tools, emulator, Android 15 image, default AVD |
| Visual Studio Code | macOS, Windows, Linux | brew cask / winget / snap | — |
| Xcode | macOS | xcode-select (CLI tools) | Full Xcode via mas, iOS Simulator runtime |
| Visual Studio Professional | Windows | winget | — |
| Google Chrome | macOS, Windows, Linux | brew cask / winget / wget+dpkg | — |

## Configuration

Edit [./configs/apps.yaml](./configs/apps.yaml) to add or remove apps.
Each entry uses flat keys:

```yaml
- name: MyApp
  description: Short description
  profiles: [baseline, web]
  platforms: [macos, windows, linux]
  check_command: myapp              # generic PATH check
  check_shell: "myapp --version >/dev/null 2>&1"  # optional shell check
  check_path: "~/.myapp/config"      # optional generic path check
  check_macos_path: "/Applications/MyApp.app"   # macOS-specific check
  install_macos: "brew install --cask myapp"
  install_windows: "winget install -e --id Vendor.MyApp"
  install_linux_apt: "sudo apt install -y myapp"
  post_install_macos:               # optional post-install steps
    - "echo 'hello' >> ~/.zshrc"
    - "myapp init --rootful"
  verify_macos:                      # optional verification checks
    - label: "MyApp version"
      command: "myapp --version"
    - label: "MyApp data"
      command: "ls ~/myapp-data/"
  configure_macos:                   # optional configure steps
    - name: "Authenticate"
      check: "myapp whoami >/dev/null 2>&1"   # skip if exit 0
      interactive: "myapp login"               # prompts the user
      non_interactive: 'printf "%s" "$MYAPP_TOKEN" | myapp login --with-token'
      requires: [MYAPP_TOKEN]
      sensitive: true                          # mask command output
```

### Configure steps (post-install configuration)

`configure_<os>` describes one or more configuration steps that run after
install. Each step can support either or both of:

- `interactive` — a shell command run in the user's TTY (free to prompt
  for input). Used when no credentials are provided.
- `non_interactive` — a shell command that reads required values from the
  subprocess environment (for example, `$MYAPP_TOKEN`). Used when a
  credentials file is provided and all `requires` keys resolve.

Per-step keys:

| Key | Purpose |
|-----|---------|
| `name` | Human-readable label shown in the summary |
| `check` | Optional shell test; if it exits 0 the step is skipped (idempotent) |
| `interactive` | Command for the human-driven flow |
| `non_interactive` | Command for headless flow; reads env vars from credentials |
| `requires` | List of credential keys the non-interactive command needs |
| `sensitive` | When `true`, the command is masked in console output |

### Credentials file

Pass `--credentials-file <path>` to provide values for `requires` keys.
Credentials are loaded into the subprocess environment; they are **not**
substituted into command text, so they never leak into echoed output.

```yaml
# ~/.config/laptop-setup/credentials.yaml  (chmod 600 recommended)
GH_TOKEN: ghp_xxx                  # global key, available to all apps
NPM_TOKEN: npm_xxx
"GitHub CLI":                       # optional per-app override
  GH_TOKEN: ghp_per_app_token
```

Lookup order for each required key: app-scoped → global → environment
variable. Missing keys cause the step to fall back to the interactive
command, unless `--non-interactive` is set (in which case the step is
reported as `missing-creds` in the summary).

### Run summary

Every `--install`, `--setup`, and `--configure` run ends with a unified
summary table covering install / post-install / configure status per app,
plus a "Manual follow-ups needed" section for missing credentials or
failed steps. A JSON copy is written to `~/.laptop-setup/last-run.json`
(mode 600 on POSIX).

### Key naming convention

| Key pattern | Purpose |
|-------------|---------|
| `profiles` | Optional profile tags for `--profile`, for example `baseline`, `java`, `containers` |
| `bootstrap` | Optional boolean; bootstrap apps install before non-bootstrap apps |
| `check_command` | Cross-platform CLI command lookup |
| `check_commands` | Cross-platform CLI command list; any found command detects the app |
| `check_shell` | Cross-platform shell check; exit 0 detects the app |
| `check_path` / `check_paths` | Cross-platform file/directory existence checks |
| `check_<os>_path` | Platform-specific file/directory existence |
| `check_<os>_paths` | Platform-specific file/directory existence list |
| `check_<os>_command` | Platform-specific command name |
| `check_<os>_shell` | Platform-specific shell check; exit 0 detects the app |
| `install_<os>` | Install command for that OS |
| `install_linux_<pm>` | Linux package-manager-specific (apt/dnf/snap) |
| `install_linux_custom` | Linux fallback command |
| `install_<os>_note` | Post-install informational note |
| `post_install_<os>` | List of shell commands to run after install |
| `configure_<os>` | List of `{name, check, interactive, non_interactive, requires, sensitive}` configure steps |
| `verify_<os>` | List of `{label, command}` checks for `--verify` |

## Profiles

Profiles come from `profiles` tags in `apps.yaml`. They are optional filters:
the default `--list` and `--install` behavior still considers every registered
app. Use `--profile <name>` to narrow a command, and repeat it to combine
profiles.

```bash
python3 <skill>/scripts/laptop_setup.py --profiles
python3 <skill>/scripts/laptop_setup.py --list --profile containers
python3 <skill>/scripts/laptop_setup.py --install --profile java --dry-run
python3 <skill>/scripts/laptop_setup.py --install --profile baseline --profile ai --dry-run
```

## Post-Install Steps

Some apps need extra setup beyond a simple package install.
Define `post_install_macos`, `post_install_windows`, or `post_install_linux`
as a list of shell commands in `apps.yaml`.

Post-install commands are intentionally explicit in the registry because they
may edit shell profiles, initialize VMs, accept licenses, or start interactive
authentication flows. Review them with `--setup --dry-run` before execution.

- **On fresh install** (`--install`): post-install runs automatically after the app is installed.
- **On existing installs** (`--setup`): runs post-install for apps that are already present.
- **Dry-run** (`--dry-run`): prints the commands without executing.

### Xcode & iOS Simulator (macOS)

The Xcode post-install steps set up the full development toolchain:

1. Install `mas` (Mac App Store CLI) if not present
2. Install full **Xcode** from the App Store (if only CLI tools exist)
3. Point `xcode-select` to the Xcode.app developer directory
4. Accept the Xcode license non-interactively
5. Run first-launch component installation
6. Download the **iOS Simulator** runtime (`xcodebuild -downloadPlatform iOS`)

If `mas install` fails (App Store sign-in required), install Xcode manually and re-run `--setup --name Xcode`.

### Android Studio & Emulator (macOS)

The Android Studio post-install steps configure a complete Android development environment:

1. Install **SDK command-line tools** via `android-commandlinetools` brew cask
2. Accept all SDK licenses non-interactively
3. Install **platform-tools**, **emulator**, **build-tools 35**, **Android 15 (API 35)** platform, and **arm64 system image**
4. Create a default **Pixel 6 AVD** (`default_pixel`) for the emulator
5. Add `ANDROID_HOME` and SDK tool paths to `~/.zshrc`

After setup, `emulator -avd default_pixel` launches the Android emulator.

## Verification

Use `--verify` to inspect the state of simulators, emulators, and other
post-install artifacts without making any changes.

Define `verify_macos`, `verify_windows`, or `verify_linux` in `apps.yaml`
as a list of `{label, command}` pairs. Each command is executed and its
output displayed with a pass/fail indicator.

```bash
# Verify all apps that define checks
python3 <skill>/scripts/laptop_setup.py --verify

# Verify a specific app
python3 <skill>/scripts/laptop_setup.py --verify --name "Xcode"
python3 <skill>/scripts/laptop_setup.py --verify --name "Android Studio"
```

### What gets verified

| App | Checks |
|-----|--------|
| **Xcode** | Xcode version, active developer dir, iOS Simulator runtimes, iOS Simulator devices |
| **Android Studio** | App installed, ANDROID_HOME, SDK packages, cmdline-tools, system images, AVDs (emulators), emulator binary |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Homebrew not found" | Script auto-installs it; if it fails, run the Homebrew install manually |
| Homebrew installs but new shells cannot find `brew` | Ensure `~/.zprofile` contains the `brew shellenv` line shown by `brew shellenv` |
| "winget not found" | Install "App Installer" from the Microsoft Store |
| Xcode shows "Missing" after xcode-select | `xcode-select --install` only installs CLI tools; get full Xcode from App Store |
| Linux app not found | Ensure `apt`, `dnf`, or `snap` is available; check `--info` output |
| Script hangs on install | Some installs require sudo password; enter it when prompted |
| Post-install step fails | Re-run with `--setup --name "AppName"` to retry; check `--setup --dry-run` to review commands |
| Xcode: "mas install" fails | Sign in to the App Store manually first, then re-run `--setup --name Xcode` |
| Android: sdkmanager not found | Ensure `brew install --cask android-commandlinetools` succeeded; check `$(brew --prefix)/share/android-commandlinetools/` |
| Android: AVD won't start | Run `emulator -avd default_pixel -verbose` to see detailed errors; ensure hardware acceleration is enabled |

## Rules

- Always run `--list` or `--check` first to review before installing
- Use `--dry-run` before mutating install or setup commands unless the user has
  already confirmed they want execution now
- The script never installs apps that are already detected
- Platform-incompatible apps are silently skipped (shown as N/A)
- All install commands run in the current terminal session — sudo prompts pass through
- Post-install steps run sequentially; a failure stops remaining steps for that app
