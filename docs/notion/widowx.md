# 🦾 WidowX

Trossen WidowX 250 6-DOF arm on the Alienware desktop, teleoperated with a Meta
Quest 2.

**Owners:** Hugo, Gahyun
**Repo:** [USC-Lira/bridge_data_robot](https://github.com/USC-Lira/bridge_data_robot) (fork of [rail-berkeley/bridge_data_robot](https://github.com/rail-berkeley/bridge_data_robot))
**Checkout on the desktop:** `~/bridge_data_robot`

> ⚠️ **Return the arm to the sleep position and power it off when you are
> done.** Hold the arm while shutting down — it drops when torque disengages.

## At a glance

| | |
|---|---|
| Arm | WidowX 250 6-DOF (`ROBONETV2_ARM=wx250s`) |
| Desktop | Alienware · login: *see lab password manager* |
| Cameras | Intel RealSense D415 (serial `217222067236`, set as `REALSENSE_SERIAL` in `docker-compose.yml`), colour + depth, published under the historical `/D435/...` topic names. It replaced a D435 (`146322077603`). Logitech 1080P Pro Stream ×2 and a wrist cam are supported but not in the current config. |
| Teleop | Meta Quest 2 + RAIL Oculus Teleoperation app, over USB/adb |
| Environment | ROS Noetic in docker (`robonet` service) |
| Data out | `/datasets` on the host ↔ `/home/robonet/trainingdata` (`$DATA`) in the container. Older sessions: `$HOME/widowx_data` |

## 1. Physical setup

1. **Power** — the arm's power brick is plugged in.
2. **Arm data** — mini-USB → USB from the arm to the desktop. This is what
   becomes `/dev/ttyDXL`.
3. **Cameras** — the RealSense D435 over USB (use a USB 3 port). If you move a
   camera to a different port, re-run preflight (it regenerates the chart).
4. **Quest 2** (teleop only) — USB-C → USB to the desktop. Leave it plugged in
   during teleop; it both charges and carries the control data.
   1. Turn the headset on.
   2. Put it on; approve the **Allow USB** prompt with the controller.
   3. On the desktop, `adb devices` must list it as `device`. If it says
      `unauthorized`, repeat step ii.
   4. If the headset restarted or ran out of battery, open the **RAIL Oculus
      Teleoperation** app and redraw the guardian boundaries when prompted.

> 📷 *Attach: photo of the correctly cabled rig.*

## 2. Preflight

Run before every session, from the host, in the repo root:

```bash
cd ~/bridge_data_robot
python3 widowx_envs/widowx_envs/preflight/preflight.py \
    --conf widowx_envs/experiments/bridge_data_v2/conf_jesse.py
```

It checks cabling, USB enumeration, the camera connector chart, the Quest's adb
state, docker, the dataset directory, and — once the container is up — the ROS
side: arm driver, camera topics, live frames, and that the conf file you passed
declares only topics that are actually publishing.

- If all host checks pass and the container is not running, preflight
  **starts it** (`docker compose up -d`, building the image only if it is
  missing or the Dockerfile changed), opens a new terminal window with its
  output, waits for the arm and cameras, then runs the container checks.
- It fixes what it can by itself (USB chart, adb, the headset's USB
  permissions) and **pauses** for what needs you: plugging in the headset,
  clicking "Allow" inside it.
- Exit code `0` = clear to collect, `1` = fix the failures first.
- Every failure prints the command that fixes it.
- `--no-start` only checks; `--non-interactive` never pauses or asks.

Details and how to add checks: [`docs/preflight.md`](https://github.com/USC-Lira/bridge_data_robot/blob/main/docs/preflight.md)

> 🚧 Preflight has not yet been run against the real rig — if it reports
> something you know is fine, fix the check and open a PR.

## 3. Data collection

### The short way: one command

```bash
cd ~/bridge_data_robot
python3 datacollection.py widowx_envs/experiments/bridge_data_v2/conf_jesse.py
```

It runs preflight with that conf (which starts the container if needed). If
preflight ends without a FAIL, it asks whether to start collecting, then asks
you to confirm the **RAIL Oculus Teleoperation app is open** in the headset and
the **headset is facing you**, and starts `run_data_collection.py` with the
same conf. `Ctrl+C` stops collection; `python3 stop_container.py` stops the
container. The two windows below are what it does for you.

### Window 1 — preflight starts the robot

```bash
cd ~/bridge_data_robot
python3 widowx_envs/widowx_envs/preflight/preflight.py \
    --conf widowx_envs/experiments/bridge_data_v2/conf_jesse.py
```

Preflight regenerates `usb_connector_chart.yml`, checks the rig, starts the
robonet container in the background (Ubuntu + ROS + arm driver + cameras), and
opens a **"robonet (container output)"** window with its log. Closing that
window only closes the view; the container keeps running. To get the log back:
`docker compose logs -f robonet`.

> ⚠️ The two Logitech webcams have the same name, so blue/yellow are assigned
> by enumeration order. If preflight warns that a topic **now points at a
> different USB port**, check the images before collecting — blue and yellow
> may have swapped. The previous chart is kept in `usb_connector_chart.yml.bak`.

> 📷 *Attach: screenshot of healthy roslaunch output.*

To sanity-check the sensors by hand:

```bash
docker compose exec robonet bash
rostopic list
rostopic echo /D435/color/image_raw --noarr
```

### Window 2 — collect

```bash
cd ~/bridge_data_robot
docker compose exec robonet bash
python widowx_envs/widowx_envs/run_data_collection.py \
    widowx_envs/experiments/bridge_data_v2/conf_jesse.py
```

Use your own config file — there are examples in
`widowx_envs/experiments/bridge_data_v2/`. **Copy one to
`conf_<yourname>.py`; do not edit `conf.py`.**

#### The config file

A conf only states what differs between projects; everything else comes from
`widowx_envs/widowx_envs/simple_conf.py`:

```python
from widowx_envs.simple_conf import make_config

config = make_config(
    cameras=["D435"],            # D435 (the RealSense), blue, yellow, wrist
    depth=True,                  # also record RealSense depth
    action_mode="3trans3rot",    # see below
    metadata={"task": "put the cup in the bowl", "operator": "Hugo"},  # both required
    neutral_before_each=True,    # optional: arm to neutral before every trajectory (default True)
    # num_trajectories=50,       # optional: default is no limit, end the session from the headset
    # max_seconds_per_trajectory=100,
    # env={...}, agent={...}, collection={...}   # override any other setting
)
```

**`action_mode`** (required) decides which parts of the arm follow your hand:

| `action_mode` | Follows the hand | Locked |
|---|---|---|
| `3trans3rot` | x, y, z, roll, pitch, yaw, gripper | – |
| `3trans1rot` | x, y, z, yaw, gripper | roll, pitch at the default orientation |
| `3trans` | x, y, z, gripper | roll, pitch, yaw at the default orientation |
| `custom` | your choice, with `control={...}` | your choice |

With `custom`, give **every** axis (`x y z roll pitch yaw gripper`) one of:
`"teleop"` (follows your hand / the trigger), `"hold"` (stays where it was when
the trajectory started), or a number (meters for x/y/z, degrees from the
default orientation for roll/pitch/yaw, 0 closed .. 1 open for the gripper).

```python
action_mode="custom",
control={"x": "teleop", "y": "teleop", "z": 0.12,
         "roll": "hold", "pitch": "hold", "yaw": "teleop", "gripper": "teleop"},
```

Fixed numbers are reached **before** recording: after going to neutral, the
arm moves there slowly (about 5 cm/s and 30°/s, at least 2 s) and only then
waits for the grip button, so starting a trajectory never jumps. It does the
same after **B** (neutral). Preflight checks beforehand that the arm can reach
that pose (`container.control_start`), so an out-of-reach value fails there.
Make sure the path from neutral to that pose is clear. A fixed **gripper**
value is applied when recording starts.

Whatever is locked, every dataset records the same 7-number actions
(xyz + roll/pitch/yaw deltas + gripper); locked axes are recorded as "no
change". Preflight (`host.conf_settings`) checks the conf before anything
starts: a preset combined with `control`, a missing axis, an unknown camera,
an empty task or operator, or a typo in an override all fail there with the
exact problem.

Then:

- Make sure the headset is **facing you**, and keep the controller inside its
  field of view.

**VR controls** (right controller; `python3 datacollection.py --controls`
prints this card):

| Control | Before recording | While recording | After a trajectory |
|---|---|---|---|
| **Grip** (middle finger) | press to **start** recording | **hold** to move the arm: it follows your hand, position and rotation. Release to stop; move your hand, press again to continue from there | |
| **Trigger** (index finger) | | closes the gripper; how far you pull = how closed | |
| **B** | moves the arm to its **neutral** pose | **ends** the trajectory | |
| **A** | | | **save** it |
| **Right joystick** (press) | **end the session** (then **A** to confirm, grip to keep collecting) | | **discard** it |

A trajectory also ends by itself after the conf's `T` steps. Move smoothly:
a sudden jump prints `delta transform too large!` and pauses in the terminal;
type `c` and Enter to continue.

### Where the data lands

Inside the container under `$DATA` (`/home/robonet/trainingdata`), which is
`/datasets` on the host. Sessions recorded before the move are still in
`$HOME/widowx_data`; they were not copied over.

> 🚧 The lab-wide target layout is `/datasets/<task_instruction>/<timestamp>`.
> The WidowX saver does not write that yet — tracked as an open item.

## 4. Powering off

1. Stop collection in **window 2** first.
2. Stop the container:
   ```bash
   python3 stop_container.py
   ```
   It moves the arm to its sleep pose, asks you to confirm, then stops the
   container. ⚠️ **Hold the arm** anyway: the motors turn off when it stops.
3. Power the arm off.
4. Put the Quest on its charger.

## 5. Inference

With the `robonet` container running (started by preflight, window 1):

```bash
# server
docker compose exec robonet bash -lic "widowx_env_service --server"

# verify — ⚠️ the robot will move
python widowx_envs/widowx_envs/widowx_env_service.py --client
```

Client, in your own conda env, with [edgeml](https://github.com/youliangtan/edgeml) installed plus:

```bash
cd ~/bridge_data_robot/widowx_envs && pip install -e .
conda activate YOUR_ENV
python your_inference_script.py
```

Example to crib from: `$HOME/bridge_data_v2/experiments/eval.py`.

### Octo

```bash
# check the camera view first
conda activate octo2
python3 ~/octo/examples/show_camera.py --im_size 256 --show_image True

# eval
cd ~/octo
python3 examples/04_eval_finetuned_on_robot_jesse.py \
  --checkpoint_weights_path=~/.cache/huggingface/hub/models--rail-berkeley--octo-base-1.5/snapshots/ee3c10e8edd6ce2e8b1e8744d3c6fba4097bed48/ \
  --checkpoint_step=300000 --im_size=256 --show_image
```

> `im_size` is hacky at the moment — 256 is what works.

## 6. Data processing

```bash
# raw -> numpy
python3 bridge_data_v2/data_processing/bridgedata_raw_to_numpy.py \
    --input_path=... --depth=1 --output_path=... --overwrite=True

# [optional] attach language to each parent folder
python3 bridge_data_v2/data_processing/bridgedata_add_lang_descriptions.py \
    <root_dir> "<lang description>"

# [optional] drop im0 if you recorded an extra camera you do not want
python3 bridge_data_v2/data_processing/bridgedata_remove_unnecessary_im0.py <dir>

# -> TFRecords / RLDS
cd ~/dlimp/rlds_converters/bridge_dataset
conda activate octo2
tfds build --manual_dir MAIN_FOLDER
mv ~/tensorflow_datasets/bridge_dataset TARGET_LOCATION
```

### Fine-tuning Octo

```bash
python examples/02_finetune_on_lira_data.py \
  --pretrained_path ~/.cache/huggingface/hub/models--rail-berkeley--octo-base-1.5/snapshots/ee3c10e8edd6ce2e8b1e8744d3c6fba4097bed48 \
  --data_dir ~/jesse_datasets/ \
  --save_dir ~/jesse_octo_checkpoints/bridge_42_trajs_octo_base-1.5 \
  --wandb_run_name TEST --batch_size 16
```

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `module 'numpy' has no attribute 'typeDict'` | old scipy vs new numpy | `pip install --upgrade scipy` **inside the container** |
| `Device not found. Run 'adb devices'` at collection start | Quest not connected/authorised | Connect it, accept the in-headset USB prompt. Expected before the headset is attached. |
| `adb devices` shows `no permissions` | No udev rule for the Quest (USB vendor `2833`), so the user cannot open it | Add `/etc/udev/rules.d/51-oculus.rules` (preflight's `host.vr_headset` prints the exact commands), replug, `adb kill-server` |
| VR controller does nothing | RAIL Oculus Teleoperation app not running, or guardian not drawn | Open the app in the headset, redraw boundaries |
| `No RealSense devices were found!` | D435 not enumerated, wrong serial in `widowx_rs.launch`, or the D435 is **also** listed in `usb_connector_chart.yml` so two drivers fight over it | Replug (USB 3), check the serial, remove the D435 line from the chart |
| `PermissionError: [Errno 13]` from docker | user not in the `docker` group | `sudo groupadd docker; sudo usermod -aG docker $USER`, then **reboot** |
| Collection hangs with no error at startup | `CameraRecorder` waiting forever on a `camera_info` topic that does not exist | `rostopic list \| grep camera_info`; set `info_name` explicitly on the `IMTopic` |
| Data recorded from the wrong camera | empty/duplicate entry in `usb_connector_chart.yml` | Plug in all cameras and run preflight (it regenerates the chart) |
| Permission error when saving, after teleoperating | `/datasets` not writable by the container user (uid 1000) | Run preflight: `host.dataset_dir.writable` prints the exact fix |
| Arm driver fails to start | mini-USB unplugged, arm unpowered, or missing udev rule | check cable + power; `ls /dev/ttyDXL` |

## 8. Known gaps

- Saver still writes the old folder layout, not `/datasets/<task>/<timestamp>`.
- No session metadata prompt (teleoperator, task instruction) at collection start.
- Failed trajectories are discarded rather than saved with a label.
- Camera positions are not yet marked/fixed, so datasets are not reliably
  reusable across sessions.
- Preflight unverified on hardware.

## 9. Reference

- [USC-Lira/bridge_data_robot](https://github.com/USC-Lira/bridge_data_robot) — this fork
- [rail-berkeley/bridge_data_robot](https://github.com/rail-berkeley/bridge_data_robot) — upstream
- [rail-berkeley/bridge_data_v2](https://github.com/rail-berkeley/bridge_data_v2) — data processing + eval
- [octo-models/octo](https://github.com/octo-models/octo)
- [Hardware setup doc](https://docs.google.com/document/d/1si-6cTElTWTgflwcZRPfgHU7-UwfCUkEztkH3ge5CGc/edit)
- In-repo: [`docs/preflight.md`](https://github.com/USC-Lira/bridge_data_robot/blob/main/docs/preflight.md), [`docs/repo-workflow.md`](https://github.com/USC-Lira/bridge_data_robot/blob/main/docs/repo-workflow.md)

> 📷 *Attach: example camera observation from the current setup.*
