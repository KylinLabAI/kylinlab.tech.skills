# External Skills

This folder is reserved for downloading and storing external skills. External skills are not vendored under `skills/`. Install them with `npx skills add` and keep the canonical source link close to the command. (Local repo skills under `skills/` use `skills/skill-manager` instead.)

## Recommended Skills

| Skill | Source | Why Install It |
|---|---|---|
| `find-skills` | [GitHub](https://github.com/vercel-labs/skills/tree/main/skills/find-skills) | Discover public skills and install more targeted workflows |
| `frontend-design` | [GitHub](https://github.com/anthropics/skills/tree/main/skills/frontend-design) | Build polished, modern frontend UI with strong visual design defaults |
| `skill-creator` | [GitHub](https://github.com/anthropics/skills/tree/main/skills/skill-creator) | Guide for creating effective, well-structured skills |

## Install Commands

```bash
# find-skills - discover and install additional skills
npx skills add https://github.com/vercel-labs/skills/tree/main/skills/find-skills -g -y

# frontend-design - polished frontend UI design
npx skills add https://github.com/anthropics/skills --skill frontend-design -g -y

# skill-creator - author effective skills
npx skills add https://github.com/anthropics/skills --skill skill-creator -g -y
```

## Discover Skills

Browse and search the public skill catalog at [skills.sh](https://www.skills.sh/) to find additional skills, then install them with `npx skills add` (see Install Commands above).

## Maintenance Notes

- Add new external skills to this file.
- Prefer the canonical install command from the Skills Directory or source repo.
- Do not add external skill folders under `skills/` unless the suite deliberately vendored them; vendored skills must also update README inventory and CODEOWNERS.

## Note

All files in this folder are ignored by git except for this README.md file.
