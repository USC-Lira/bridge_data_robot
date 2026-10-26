# Working with this repository

How the WidowX pair works in `USC-Lira/bridge_data_robot`. This is a proposal —
the decisions marked **[decide]** need a yes/no from the team before they are
real.

## What this repo is

`USC-Lira/bridge_data_robot` is our fork of
[`rail-berkeley/bridge_data_robot`](https://github.com/rail-berkeley/bridge_data_robot).
It is the control stack for the WidowX: a ROS noetic + Interbotix workspace
baked into the `robonet-base` docker image, plus the `widowx_envs` Python
package for teleop and data collection.

Current state as of this writing:

- 5 commits, all straight to `main`, no branches, no PRs.
- No `upstream` remote configured, so we cannot currently tell our changes
  apart from Berkeley's.
- Some editor swap files and a 2 MB `video_replay.mp4` are tracked.

None of that is a crisis, but it gets expensive once four people are editing
the same four robots' repos. Hence the rest of this document.

## Ground rules

### 1. Add a read-only `upstream` remote

```bash
git remote add upstream https://github.com/rail-berkeley/bridge_data_robot.git
git remote set-url --push upstream DISABLED   # make pushing to Berkeley impossible
git fetch upstream
```

We do not have to merge from upstream on any schedule. The point is being able
to run `git diff upstream/main -- <file>` and immediately see what is ours.

### 2. Prefer additive files over edits to vendored code

The cheapest change is a new file. `widowx_envs/widowx_envs/preflight/` is a
new directory; merging upstream will never conflict with it.

When you *must* edit a file that came from Berkeley, keep the diff minimal and
mark it so the next person knows it is deliberate:

```python
# LIRA: default to the D435 instead of the blue Logitech (our rig has no blue cam)
```

`grep -rn "LIRA:"` then gives the full list of our divergences from upstream.

**[decide]** Worth doing retroactively for the existing changes in
`widowx_rs.launch`, `run.sh` and `docker-compose.yml`? It is maybe 20 minutes
of `git diff upstream/main` and would make the next upstream merge much less
scary.

### 3. Branch and PR, do not push to `main`

```
feat/<short-description>     new capability      feat/preflight-checks
fix/<short-description>      bug fix             fix/camera-info-timeout
docs/<short-description>     documentation       docs/notion-widowx
```

One PR, one reviewer — for WidowX work that is Hugo or Gahyun. Reviews here are
cheap and mostly serve to spread knowledge of the rig, not to gate quality.

**[decide]** Protect `main` on GitHub (require a PR)? Recommended, but it does
mean you cannot hotfix from the robot desktop at midnight without opening a PR.
A reasonable middle ground: protect `main`, and allow direct pushes for commits
touching only `experiments/` conf files.

### 4. Do not commit data or binaries

Datasets, checkpoints, videos and PDFs do not belong in git. `.gitignore`
already covers `usb_connector_chart.yml` and the usual Python noise.

Cleanup items, as their own PR:

```bash
git rm --cached widowx_envs/.Dockerfile.sw[non] \
                widowx_envs/widowx_envs/base/.robot_base_env.py.swp
# and add  *.sw[op]  *.swn  to .gitignore
```

`widowx_envs/video_replay.mp4` (2 MB) — **[decide]** is it referenced by
anything, or can it go?

The two LiraLab PDFs and `instructions.txt` sitting in the working tree right
now should stay untracked (or move into Notion, which is where they belong).

### 5. Rig-specific values belong in config, not in code

The D435 serial `146322077603`, the `/datasets` root, the arm model — these
differ per station and will differ per robot as the lab grows. They live in
`preflight/config.py` and `preflight.example.yaml`.

Same principle for collection: **never edit `conf.py`**. Copy it to
`conf_<yourname_or_project>.py` and edit that. There are already five of these
and that is fine — they are cheap and they document what each project actually
collected with.

### 6. Where new shared code goes

| what | where |
|---|---|
| pre-collection checks | `widowx_envs/widowx_envs/preflight/` |
| experiment configs | `widowx_envs/experiments/bridge_data_v2/conf_*.py` |
| docs for this repo | `docs/` (and mirrored into Notion) |
| one-off analysis scripts | not here — your own repo |

The cross-robot pieces from the infrastructure doc (unified trajectory saver,
the inspection web UI, `upload_to_hub.py`) should **not** be forked into each
robot's repo. They want to be one shared package that each robot repo depends
on. **[decide]** — this is a question for the whole group, not just WidowX, and
it is worth settling before four teams write four savers.

### 7. Commit messages

Enough to find the change later: `preflight: fail on empty usb chart entries`
beats `updates` or `a bunch of changes`.

### 8. Before you push

There is no CI. Minimum bar:

```bash
python3 -m compileall -q widowx_envs/widowx_envs
python3 widowx_envs/widowx_envs/preflight/preflight.py --list
```

**[decide]** Add a GitHub Action that runs those two on PRs? ~15 lines, catches
syntax errors before they reach the robot desktop, and the host-scope code is
stdlib-only so it needs no ROS to lint.

## Robot-desktop specifics

The Alienware is a shared machine. A few things follow from that:

- **The checkout at `~/bridge_data_robot` is shared.** Check what branch it is
  on before you start — someone else may have left it on theirs.
- **`usb_connector_chart.yml` is gitignored and machine-specific.** Never commit
  it; regenerate it with `./generate_usb_config.sh` when cameras move ports.
- **The container mounts `./widowx_envs` live**, so Python edits take effect
  without a rebuild. Only `Dockerfile`/`requirements.txt` changes need
  `docker compose up --build`.
- **Leave the arm in the sleep position and powered off.** Window 2 first, then
  window 1, holding the arm.

## Working on the shared infrastructure effort

For the pieces from the infrastructure doc that are not WidowX-specific:

1. Agree the interface across robots *first* (trajectory key names, folder
   layout, metadata fields). A shared schema agreed in a 30-minute conversation
   is worth more than four good independent implementations.
2. Then implement per robot behind that interface.

Concretely for WidowX, in order:

- [x] `preflight.py` — *implemented, needs a pass on real hardware*
- [ ] session metadata prompt (teleoperator + task instruction) at collection start
- [ ] unified saving layout `/datasets/<task_instruction>/<timestamp>`
- [ ] failed-trajectory saving with correct labels
- [ ] Notion page (draft in `docs/notion/`)
