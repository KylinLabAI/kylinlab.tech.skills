# Public Cleanup Guidance

Cross-platform reference for package-manager cleanup commands and general policy. OS-specific cleanup guidance (built-in tools, safe locations, vendor links) lives in the per-platform docs:

- [macOS](./macos-cleanup.md)
- [Windows](./windows-cleanup.md)
- [Linux](./linux-cleanup.md)

## Docker

Docker Docs, "Prune unused Docker objects": Docker does not remove unused objects unless explicitly asked; `docker system prune` removes stopped containers, unused networks, dangling images, and build cache. Volumes require the separate `--volumes` flag and should be treated as data-risky. Source: https://docs.docker.com/engine/manage-resources/pruning/

## Package Managers

Prefer package-manager commands because they understand their own cache layout. These commands apply across platforms.

### Homebrew (macOS)

Homebrew manpage: `brew cleanup` removes stale locks, outdated downloads, and old installed versions. `--dry-run` previews; `--prune` changes cache age scope; `--scrub` is broader. Source: https://docs.brew.sh/Manpage

```bash
brew cleanup --dry-run
brew cleanup
```

### npm

npm Docs, `npm cache`: `npm cache verify` verifies cache integrity and garbage-collects unneeded entries. npm's cache grows as packages are installed; full `clean` requires `--force` and is mainly for reclaiming disk space. Source: https://docs.npmjs.com/cli/v7/commands/npm-cache/

```bash
npm cache verify
npm cache clean --force
```

### pip

pip Docs, `pip cache`: `python -m pip cache info` reports cache state, and `python -m pip cache purge` removes all pip cache items. Source: https://pip.pypa.io/en/stable/cli/pip_cache/

```bash
python -m pip cache info
python -m pip cache purge
```

### pnpm

pnpm Docs, `pnpm store prune`: removes unreferenced packages from the store, may require future redownloads, and should not be run while the store server is active. Source: https://pnpm.io/cli/store

```bash
pnpm store prune
```

### Yarn

Yarn Docs, `yarn cache clean`: removes shared cache files; `--mirror` and `--all` broaden the scope. Source: https://yarnpkg.com/cli/cache/clean

```bash
yarn cache clean
```

### conda

conda Docs, `conda clean`: removes index cache, lock files, unused cache packages, tarballs, and logs. Use `--dry-run` before `--yes`; avoid `--force-pkgs-dirs` unless the user understands it can break symlinked environments. Source: https://docs.conda.io/projects/conda/en/stable/commands/clean.html

```bash
conda clean --all --dry-run
conda clean --all --yes
```

## Practical Policy

- Start with discovery: free-space report, largest known categories, and dry-run cleanup estimate.
- Delete regenerated artifacts first: temp files, logs, caches, package downloads, build outputs.
- Ask before deleting reversible-but-user-visible stores: Trash, Recycle Bin, Downloads, local backups, old installers, Docker objects, virtual machines, simulators, or app archives.
- Never delete system directories manually to solve low disk space. Use OS tools or vendor commands.
