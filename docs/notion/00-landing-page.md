# 🤖 LiraLab Robot Infrastructure

Every robot setup in the lab, with the same documentation structure, so that
knowing one rig helps you with the next one.

## Why this exists

Each robot comes with its own data collection and inference API. We are
building a shared interface around them so one pipeline can collect data from
all of them, and so datasets stay reusable across projects and across robots.

Reference: [TRI Raiden](https://tri-ml.github.io/raiden/)

## Setups

> Make this a database view with the properties below; the table here is the
> placeholder content.

| Robot | Owners | Desktop | Repo | Preflight | Status |
|---|---|---|---|---|---|
| [🦾 WidowX](./widowx.md) | Hugo, Gahyun | Alienware | [USC-Lira/bridge_data_robot](https://github.com/USC-Lira/bridge_data_robot) | ✅ draft | Collecting |
| 🦾 Trossen AI | Misha, Alekya, Mousumi | — | — | ⬜ | Teleop stack not ready |
| 🦾 XArm | Peiqi, Bo-Ruei | — | — | ⬜ | — |
| 🦾 DROID | Ryan, Steve | — | — | ⬜ | — |

Physical setup — curtains, lights, camera mounts: **Aric**

## Shared conventions

These are the things that must be identical across robots. Everything else is
per-rig detail.

### Folder layout

```
/datasets/<task_instruction>/<timestamp>/
```

Same absolute path on every robot desktop. `task_instruction` first so that all
data for a task is in one place regardless of which robot or which session
produced it; `timestamp` identifies the recording session.

### Per-session metadata

Set once, when collection starts, before the first trajectory:

- `teleoperator`
- `task_instruction`
- `robot` / `setup`
- `date_time`

### Per-trajectory

- Same observation and action key names across robots.
- Success/failure label on every trajectory — **failed trajectories are saved,
  not discarded**, with the correct label.

> ⚠️ The exact key schema is not settled yet. Agree it across all four teams
> before anyone writes their saver — it is much cheaper than reconciling four
> formats later. **[open]**

### Before every session

Run that robot's `preflight.py`. It verifies cabling, camera IDs, USB
connections and the rest of the rig's prerequisites, and exits non-zero if the
session would go wrong.

## Tooling (in progress)

| Tool | What | Status |
|---|---|---|
| `preflight.py` | per-robot pre-collection checks | WidowX drafted, others ⬜ |
| Data inspection UI | web UI to review trajectories, camera streams, state plots; relabel or delete | ⬜ |
| `upload_to_hub.py` | convert to LeRobot format, push to Hugging Face | ⬜ |
| Camera calibration | recover initial camera pose | future |

```bash
python upload_to_hub.py --dataset_path path/to/local/dataset --repo_id username/repo_id
```

## Physical setup standards

- Curtains and lights for consistent lighting.
- A set of **fixed** cameras per robot, plus optional extra cameras. The fixed
  ones are what make datasets reusable across projects, so their positions are
  marked and must not drift.
- Camera mounts with marked positions on every rig.

## Future work

- Shared evaluation structure
- Human-in-the-loop demonstration collection
- Camera pose recovery script
