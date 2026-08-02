# Windows Cleanup Guidance

How to clean up useless files and folders on Windows safely. Prefer built-in OS tools (Storage Sense, Cleanup recommendations, Disk Cleanup) and an allowlisted dry-run scan before removing anything.

## Inspect Free Space First

- Settings > System > Storage — shows drive usage and recommendations.
- File Explorer > This PC — shows capacity and free space per drive.
- PowerShell:

```powershell
Get-PSDrive -PSProvider FileSystem
```

## Built-in Tools To Use First

Prefer these for system-managed cleanup, including Recycle Bin and system temporary files:

- **Storage Sense** — Settings > System > Storage > Storage Sense. Can remove temporary files and Recycle Bin content automatically. Runs on the system drive by default; does not touch Downloads or cloud-provider content unless configured.
- **Cleanup recommendations** — Settings > System > Storage > Cleanup recommendations. Per-category review of large files, unused apps, and temporary files.
- **Disk Cleanup (`cleanmgr`)** — legacy tool for interactive cleanup. Supports `/sageset` and `/sagerun` profiles for repeatable cleanup:

```powershell
cleanmgr
cleanmgr /sageset:1
cleanmgr /sagerun:1
```

## Safe To Clean (Regenerable)

These are scanned by the bundled helper under the `safe` profile:

- `%TEMP%`, `%LOCALAPPDATA%\Temp` — current user's temporary folders.
- `%LOCALAPPDATA%\Microsoft\Windows\INetCache` — Internet Explorer/Edge legacy cache.
- `%LOCALAPPDATA%\Microsoft\Windows\Explorer` — thumbnail and icon cache.
- `%LOCALAPPDATA%\Microsoft\Windows\Caches` — shell cache.
- `%LOCALAPPDATA%\CrashDumps` — crash dumps.
- `%LOCALAPPDATA%\Microsoft\Windows\WER\ReportArchive` — Windows Error Reporting archive.
- `%LOCALAPPDATA%\Microsoft\Windows\WER\ReportQueue` — Windows Error Reporting queue.

## Developer Caches

Scanned under the `developer` profile (`--include-developer`). Expect IDE startup to be slower after cleanup:

- `%LOCALAPPDATA%\Microsoft\VisualStudio\*\ComponentModelCache` — Visual Studio component model cache.
- `%LOCALAPPDATA%\Microsoft\VisualStudio\*\Designer\ShadowCache` — designer shadow cache.

## Package Caches

Scanned under the `package-caches` profile (`--include-package-caches`). Prefer manager-specific commands first — see [public-cleanup-guidance.md](./public-cleanup-guidance.md) for npm, pip, pnpm, Yarn, and conda commands.

Helper-scanned locations:

- `%LOCALAPPDATA%\npm-cache`, `%LOCALAPPDATA%\pip\Cache`
- `%LOCALAPPDATA%\Yarn\Cache`, `%LOCALAPPDATA%\pnpm\store`
- `%USERPROFILE%\.npm`, `%USERPROFILE%\.cache\pip`, `%USERPROFILE%\.pnpm-store`

## Recycle Bin

Prefer Storage Sense, Cleanup recommendations, or Disk Cleanup for Recycle Bin and system cleanup instead of direct file deletion. Emptying the Recycle Bin permanently removes files the user may still expect to recover — ask explicitly first.

## Windows.old After Upgrade

If `Windows.old` appears after a recent upgrade, warn the user that deleting it removes the rollback option. Use Storage Sense or Disk Cleanup (which handles it safely) rather than manual deletion.

## Store App / Windows Update Temp

If low-space warnings continue because Temp fills with Store app packages, use Microsoft's documented Store cache reset and Windows Update troubleshooting paths rather than manual deletion.

## Do Not Delete

- `C:\Windows`, `WinSxS`, `Program Files` — system and program directories.
- User profile folders (`%USERPROFILE%`, Desktop, Documents, Downloads, Pictures, etc.).
- OneDrive offline data.
- Browser profiles.
- `Windows.old` (until rollback is no longer needed).

## Vendor References

- Microsoft Support, "Free up drive space in Windows": https://support.microsoft.com/en-us/windows/free-up-drive-space-in-windows-85529ccb-c365-490d-b548-831022bc9b32
- Microsoft Support, "Manage drive space with Storage Sense": https://support.microsoft.com/en-us/windows/manage-drive-space-with-storage-sense-654f6ada-7bfc-45e5-966b-e24aded96ad5
- Microsoft Learn, `cleanmgr`: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cleanmgr
