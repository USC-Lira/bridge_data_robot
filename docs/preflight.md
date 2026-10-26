# `preflight.py` — pre-collection checks for the WidowX

> Status: **implemented, not yet run against the robot.** Everything here was
> written and tested off-hardware (parsers and the runner are exercised; the
> host and ROS checks have never seen the Alienware desktop). First task for
> whoever is next at the rig: run it and fix what it gets wrong.

## Why

From the infrastructure doc:

> Before running the data collection script, each robot should have its own
> verifier script that checks some pre-requisites, like setting up camera ids,
> check usb connections, etc. Something like `preflight.py` for each robot
> codebase.

The specific pain this targets on the WidowX: almost every failure mode on this
rig shows up *late* — after you have put the headset on, after you have
teleoperated a trajectory, or worse, not at all (data silently recorded from
the wrong camera). Preflight moves those failures to before the session starts.

## Where it runs

This is the one structural decision everything else follows from. The checks
split across a boundary:

| | lives on | needs |
|---|---|---|
| cabling, USB enumeration, connector chart, Quest/adb, docker, dataset dirs | **host** | system `python3`, no ROS, no venv |
| arm driver, camera topics, live frames, import health | **container** | ROS noetic + `~/myenv` |

So `preflight.py` runs in both places and knows which it is in. From the host,
`--scope all` runs the host checks directly and then re-invokes itself inside
the `robonet` container over `docker compose exec`, parsing the container's
JSON report back out and merging the two into one verdict.

The consequence for the code: **nothing imported at host scope may touch rospy,
numpy, or anything outside the stdlib.** `checks_container` is imported lazily,
only once we know we are in-container.

## Layout

```
widowx_envs/widowx_envs/preflight/
├── preflight.py          # CLI entrypoint + the host→container handoff
├── core.py               # Status/CheckResult, @check registry, runner, reporting
├── config.py             # PreflightConfig/CameraSpec: what a correct rig looks like
├── checks_host.py        # @check(..., scope="host")
└── checks_container.py   # @check(..., scope="container")   [imports rospy]
```

It lives inside the `widowx_envs` package rather than at the repo root because
`docker-compose.yml` already bind-mounts `./widowx_envs` to
`/home/robonet/widowx_envs`. The container therefore sees your edits with no
rebuild and no new mount.

## The check protocol

A check is a function that takes a `Context` and returns a `CheckResult`, or a
list of them when it fans out (one row per camera, per chart entry, …):

```python
@check("host.arm_serial_port", scope="host")
def arm_serial_port(ctx: Context) -> CheckResult:
    """The WidowX U2D2 serial link is enumerated and accessible."""
    ...
    return CheckResult(name, Status.FAIL, summary, remedy="...")
```

Four rules, which are what make the output usable at 11pm the night before a
deadline:

1. **Every `FAIL`/`WARN` carries a `remedy`** — the literal command or physical
   action that fixes it. A check that tells you something is broken without
   telling you what to do is only half a check.
2. **`FAIL` blocks, `WARN` does not.** `FAIL` means the session will go wrong.
   `WARN` means it probably still works but you should know (e.g. `/datasets`
   not created yet; a camera publishing at an unexpected resolution).
3. **Declare `requires=[...]`.** If the docker daemon is unreachable there is
   no point testing the nvidia runtime; dependents are `SKIP`ped rather than
   producing a cascade of noise. `--only` pulls prerequisites in automatically.
4. **Checks never raise.** The runner catches exceptions and converts them to a
   `FAIL` on that check alone, so one broken check cannot hide the other
   fifteen.

## Checks currently implemented

### Host

| name | catches |
|---|---|
| `host.repo_root` | running from the wrong directory |
| `host.docker_cli` | docker / compose v2 plugin missing |
| `host.docker_permissions` | the `usermod -aG docker` problem from the README |
| `host.nvidia_runtime` | `runtime: nvidia` in compose will fail |
| `host.arm_serial_port` | `/dev/ttyDXL` absent (cable/power/udev) or not writable |
| `host.v4l2_devices` | a camera is not enumerated at all |
| `host.usb_connector_chart` | see below — the big one |
| `host.vr_headset` | no adb device, or `unauthorized` instead of `device` |
| `host.dataset_dir` | `$HOME/widowx_data` missing, wrong owner, or nearly full |
| `host.robonet_container` | window 1 was never started |

### Container

| name | catches |
|---|---|
| `container.env` | `$DATA`/`$EXP`/`$ROBONETV2_ARM` unset (usually `bash -c` instead of `bash -lic`) |
| `container.python_env` | import failures, incl. the `numpy has no attribute 'typeDict'` scipy issue |
| `container.data_dir` | `$DATA` unwritable from inside |
| `container.ros_master` | roslaunch not up |
| `container.arm_node` | `/wx250s/joint_states` absent or silent |
| `container.camera_topics` | missing image **or `camera_info`** topic; silent topic; wrong resolution; frozen camera |
| `container.collection_config` | the conf file you are about to use declares a topic that is not live |

Two of those deserve explanation.

**`camera_info`.** `CameraRecorder.__init__` does a `rospy.wait_for_message` on
a `camera_info` topic it *guesses* from the image topic name, with no timeout.
If the guess is wrong, data collection hangs forever with no error. Preflight
checks the info topic explicitly, using the same guess.

**Frozen cameras.** `CameraRecorder` only errors after 100 identical frames,
i.e. mid-trajectory. Preflight grabs two frames and compares hashes up front.

### `host.usb_connector_chart` — the one that matters most

`start_streamers.py` turns the chart's **keys into ROS topic names** and matches
its **values against `v4l2-ctl --list-devices` by plain substring**:

```python
def get_dev(output_string, usb_id):
    for i, line in enumerate(lines):
        if usb_id in line:                      # <-- substring test
            return re.search('video(\d+)', lines[i + 1]).group(1)
```

`generate_usb_config.sh` writes an empty value for every camera that was not
plugged in when it ran:

```yaml
blue: ''
yellow: ''
wrist: 'usb-0000:00:14.0-2'
```

`'' in line` is **always true**, so `blue` matches the first device in the list.
It does not crash. It does not warn. It publishes some other camera's frames on
`/blue/image_raw`, and you find out weeks later when the dataset looks wrong.

So the chart check is fan-out, and hard-fails on: empty values, duplicate
values, values matching zero devices, and values matching more than one. It
also warns when a RealSense appears in the chart, since `widowx_rs.launch`
already starts `realsense2_camera` for it and two drivers contending for one
`/dev/video*` node is a plausible cause of the `No RealSense devices were
found!` warning in the manual. *(That last one is a hypothesis from reading the
code, not something I have reproduced — verify at the rig.)*

## Configuration

Expectations live in `config.py` (`PreflightConfig`, `CameraSpec`), not in the
check bodies, so re-cabling the rig is a config edit. Defaults describe the
current station: D435 colour + depth, no webcams, matching `conf_jesse.py`.
Override with `--config preflight.yaml`; see `preflight.example.yaml`.

**Keep `cameras:` in sync with whichever `conf_*.py` you collect with** — or
better, just pass `--conf`, which validates the real thing.

## Usage

```bash
cd ~/bridge_data_robot

# full check against the config you are about to collect with
python3 widowx_envs/widowx_envs/preflight/preflight.py \
    --conf widowx_envs/experiments/bridge_data_v2/conf_jesse.py

# host only — before starting the robonet container
python3 widowx_envs/widowx_envs/preflight/preflight.py --scope host

# one check while you debug it
python3 widowx_envs/widowx_envs/preflight/preflight.py --only host.usb_connector_chart -v

# machine-readable, for a session log
python3 widowx_envs/widowx_envs/preflight/preflight.py --json preflight_report.json

python3 widowx_envs/widowx_envs/preflight/preflight.py --list
```

Exit codes: `0` clear (possibly with warnings), `1` at least one blocking
failure, `2` preflight could not run.

## Adding a check

```python
@check("host.my_thing", scope="host", requires=["host.repo_root"])
def my_thing(ctx: Context) -> CheckResult:
    """One-line description — this shows up in --list."""
    rc, out, err = ctx.run(["some", "command"])      # never raises; 127 if missing
    if rc != 0:
        return _fail("host.my_thing", "what is wrong", remedy="the exact fix command")
    return _ok("host.my_thing", "what was found")
```

Put host-scope state you want to reuse in `ctx.cache` (the parsed chart and the
v4l2 output already live there).

## Known gaps / next up

- **Never run on hardware.** Highest priority.
- No check that the arm is physically at the sleep/rest position before start.
- No workspace-bounds or floor-height check (`record_floor_height` exists in the
  conf but is off).
- No check on Quest battery level — it dies mid-session and that is a known
  annoyance.
- The unified `/datasets/<task>/<timestamp>` layout is only warned about, not
  enforced, because the saver still writes the old layout. Once the saver is
  updated this should become a `FAIL`.
- Session metadata (teleoperator, task instruction) is checked for *presence*
  only; prompting for it belongs in the collection wrapper, not here.
