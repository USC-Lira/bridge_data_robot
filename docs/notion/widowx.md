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
| Cameras | Intel RealSense D435 (serial `146322077603`), colour + depth. Logitech 1080P Pro Stream ×2 and a wrist cam are supported but not in the current config. |
| Teleop | Meta Quest 2 + RAIL Oculus Teleoperation app, over USB/adb |
| Environment | ROS Noetic in docker (`robonet` service) |
| Data out | `$HOME/widowx_data` on the host ↔ `/home/robonet/trainingdata` in the container |

## 1. Physical setup

1. **Power** — the arm's power brick is plugged in.
2. **Arm data** — mini-USB → USB from the arm to the desktop. This is what
   becomes `/dev/ttyDXL`.
3. **Cameras** — the RealSense D435 over USB (use a USB 3 port). If you move a
   camera to a different port you **must** re-run `./generate_usb_config.sh`.
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

- Exit code `0` = clear to collect, `1` = fix the failures first.
- Every failure prints the command that fixes it.
- Before the container is running, use `--scope host`.

Details and how to add checks: [`docs/preflight.md`](https://github.com/USC-Lira/bridge_data_robot/blob/main/docs/preflight.md)

> 🚧 Preflight has not yet been run against the real rig — if it reports
> something you know is fine, fix the check and open a PR.

## 3. Data collection

Two terminal windows. Window 1 runs the robot; window 2 runs collection.

### Window 1 — start the robot container

```bash
cd ~/bridge_data_robot

# only when a camera is new or moved USB ports
./generate_usb_config.sh

USB_CONNECTOR_CHART=$(pwd)/usb_connector_chart.yml docker compose up --build robonet
```

This builds and runs Ubuntu + ROS + all dependencies, and starts the arm driver
and camera nodes. **Leave it running.**

> ⚠️ If you have several cameras connected, check `./usb_connector_chart.yml`
> before continuing — each camera must have its own non-empty USB path. An
> empty entry silently binds that topic to the **wrong camera**, and the
> recorded data looks fine until you inspect it. `preflight.py` fails on this.

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

Then:

- Make sure the headset is **facing you**.
- Keep the controller inside the headset's field of view.
- To move the arm: hold the button under your middle finger and move your hand.
- **A** = save trajectory. **Right joystick** = discard trajectory.

### Where the data lands

Inside the container under `$DATA` (`/home/robonet/trainingdata`), which is
`$HOME/widowx_data` on the host.

> 🚧 The lab-wide target layout is `/datasets/<task_instruction>/<timestamp>`.
> The WidowX saver does not write that yet — tracked as an open item.

## 4. Powering off

1. Kill **window 2** first.
2. Then kill **window 1**.
3. ⚠️ **Hold the arm while window 1 shuts down** so it does not collapse onto
   the table.
4. Power the arm off.
5. Put the Quest on its charger.

## 5. Inference

With the `robonet` container running (window 1):

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
| VR controller does nothing | RAIL Oculus Teleoperation app not running, or guardian not drawn | Open the app in the headset, redraw boundaries |
| `No RealSense devices were found!` | D435 not enumerated, wrong serial in `widowx_rs.launch`, or the D435 is **also** listed in `usb_connector_chart.yml` so two drivers fight over it | Replug (USB 3), check the serial, remove the D435 line from the chart |
| `PermissionError: [Errno 13]` from docker | user not in the `docker` group | `sudo groupadd docker; sudo usermod -aG docker $USER`, then **reboot** |
| Collection hangs with no error at startup | `CameraRecorder` waiting forever on a `camera_info` topic that does not exist | `rostopic list \| grep camera_info`; set `info_name` explicitly on the `IMTopic` |
| Data recorded from the wrong camera | empty/duplicate entry in `usb_connector_chart.yml` | `./generate_usb_config.sh` with all cameras plugged in; run preflight |
| Permission error when saving, after teleoperating | `$HOME/widowx_data` owned by the wrong uid | `sudo chown -R 1000:1002 $HOME/widowx_data` |
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
