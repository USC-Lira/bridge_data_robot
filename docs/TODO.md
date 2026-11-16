# TODO

Open work on the WidowX stack that is agreed but not done yet. Add an entry
when you defer something; delete it in the PR that finishes it.

## Move collected data to `/datasets`

**Done (step 1):** new data is saved under `/datasets` on the host
(`docker-compose.yml` mounts `${DATASET_ROOT:-/datasets}` as `$DATA`, and
preflight passes its `dataset_root` as `DATASET_ROOT` and creates the folder).
Sessions recorded before that stay in `~/widowx_data`; nothing was moved.
Inside `/datasets` the layout is still the old one,
`<project_key>/<subpath>/<save_dir_prefix>`
([run_data_collection.py:85](../widowx_envs/widowx_envs/run_data_collection.py#L85)).

**Target:** the lab-wide layout from the infrastructure doc,
`/datasets/<task_instruction>/<timestamp>`, the same on every robot.

- [ ] Decide whether the old sessions in `~/widowx_data` should be moved into
      `/datasets` later, or archived where they are.

### Step 2: the unified layout (bigger, needs a group decision)

- [ ] Save as `/datasets/<task_instruction>/<timestamp>` instead of
      `<project_key>/<subpath>/<prefix>`. This changes the save path logic in
      `run_data_collection.py`, and is the "unified trajectory saver" from the
      infrastructure doc.
- [ ] Settle first whether that saver is one shared package used by every
      robot repo, rather than a WidowX-only change (see "Where new shared code
      goes" in [repo-workflow.md](repo-workflow.md)).

## Make the docker build reproducible

The Noetic end-of-life break (rosdep skipping Noetic, so `dynamixel_sdk` was
never installed) went unnoticed because the Interbotix install script hides
its own failures. Remaining risks of the same kind:

- [ ] The Interbotix script clones `interbotix_ros_core` and
      `interbotix_ros_toolboxes` at their latest commit (only
      `interbotix_ros_manipulators` is checked out to `noetic`). Pin all three
      to known-good commits.
- [ ] The ROS apt key added in `widowx_envs/Dockerfile`
      (`C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654`) expired in June 2025 and
      was re-issued with the same fingerprint and a 2030 expiry. Whether
      `apt-key adv` gets the new copy depends on the keyserver, so a build
      without cache may fail with `EXPKEYSIG`. Switch to the `ros-apt-source`
      package (1.3.0 has a `focal` build), and drop the Interbotix script's own
      `apt-key` source, which would conflict with it.
- [ ] Pin every package in `widowx_envs/requirements.txt` to the versions that
      work today (`pip freeze` inside a working container). Almost nothing is
      pinned, so each rebuild installs the newest versions, and packages that
      quietly drop Python 3.8 (the container's version) break the import of
      `widowx_envs.widowx_env`. So far: `moviepy` (pinned to 1.0.3) and `scipy`
      (1.10.x, because the venv also sees Ubuntu's old system scipy).
- [ ] The Interbotix script has no `set -e`, so any failure inside it is
      invisible. Consider running it with `bash -e`, or replacing it with the
      few steps we actually need.

## RealSense naming and identity

The Alienware's RealSense is now a **D415** (`217222067236`), which replaced
the D435 (`146322077603`). Its serial is set in one place, `REALSENSE_SERIAL`
in `docker-compose.yml`.

- [ ] Its topics are still `/D435/...`, and preflight's catalog calls it `D435`,
      because `conf_*.py` files and existing datasets use that name. Decide
      whether to rename it to something model-neutral (e.g. `/realsense/...`),
      and update the conf files at the same time.
- [ ] Add a preflight check that compares the serial the RealSense driver
      reports with the expected one, so a camera swap fails with "found D415
      217222067236, expected ..." instead of the driver retrying forever.
- [ ] Remove `ENV REALSENSE_SERIAL` from `widowx_envs/Dockerfile` at the next
      planned rebuild; `docker-compose.yml` overrides it anyway.
- [ ] Possible follow-up: support **two RealSense cameras**. Today only one is
      wired up: `widowx_rs.launch` starts one driver group (`camera1`, one
      serial), `run.sh`/`docker-compose.yml` pass one `REALSENSE_SERIAL`, and
      preflight's catalog has one RealSense (it warns when it sees more). Needs
      a second driver group (`camera2`, `serial_no_camera2`), a
      `REALSENSE_SERIAL_2`, a second catalog entry, and preflight expecting two.
      Put them on different USB 3 controllers (colour + depth on two cameras is
      a lot of bandwidth), and name them by position (`realsense_front`,
      `realsense_side`) rather than by model.

## Session metadata

Short-form confs (`simple_conf.make_config`) carry the metadata inline:
`task` and `operator` are required, and preflight (`host.conf_settings`) and
the container check fail while they are empty. Each session folder also gets
`action_mode`, the resolved `control`, the cameras and the action format.

- [ ] Decide as a team whether more fields should be required (scene/objects,
      ...), and add them to `REQUIRED_METADATA` in `simple_conf.py`.
- [ ] Have preflight add what it already knows (RealSense model and serial from
      `docker-compose.yml`, robot model from its config), so sessions record
      which camera was used even though the topics say `/D435`.

## VR headset

- [ ] `datacollection.py` asks the operator to confirm that the RAIL Oculus
      Teleoperation app is open. Check it over adb instead (e.g. the
      foreground app from `adb shell dumpsys activity activities`). Needs the
      app's package name, read from the headset first (`adb shell pm list
      packages | grep -i rail`). Whether the headset faces the operator still
      has to be asked.

- [ ] The container has its own adb key (lost when the container is
      recreated). If the container starts the adb server before the host does,
      the headset asks for "Allow" again. Preflight starts it on the host first,
      which avoids this in the normal flow; mounting the host's `~/.android`
      into the container in `docker-compose.yml` would rule it out.
