# TODO

Open work on the WidowX stack that is agreed but not done yet. Add an entry
when you defer something; delete it in the PR that finishes it.

## Move collected data to `/datasets`

**Today:** everything is saved under the host's `~/widowx_data`
(`/home/liralab-widowx/widowx_data`), whether or not `/datasets` exists:

1. `run_data_collection.py` saves to
   `$DATA/<project_key>/<subpath>/<save_dir_prefix>`
   ([run_data_collection.py:85](../widowx_envs/widowx_envs/run_data_collection.py#L85)).
2. In the container `$DATA=/home/robonet/trainingdata` (`ENV DATA` in
   `widowx_envs/Dockerfile`).
3. `docker-compose.yml` mounts `$HOME/widowx_data:/home/robonet/trainingdata`.

**Target:** the lab-wide layout from the infrastructure doc,
`/datasets/<task_instruction>/<timestamp>`, the same on every robot.

### Step 1: change where data is saved (small)

- [ ] Create `/datasets` on the Alienware, writable by the container user
      (uid 1000):
      `sudo mkdir -p /datasets && sudo chown -R 1000:1000 /datasets`
- [ ] In `docker-compose.yml`, change the mount to
      `- /datasets:/home/robonet/trainingdata`.
- [ ] Point preflight at it: `legacy_dataset_root: /datasets` in the preflight
      config (`widowx_envs/widowx_envs/preflight/config.py` and
      `preflight.example.yaml`), so `host.dataset_dir.writable` and
      `free_space` check the folder that is actually used.
- [ ] Decide what happens to the existing sessions in `~/widowx_data`: move
      them into `/datasets`, or leave them and note where they are.
- [ ] Update the data-transfer notes in the data collection guide, which
      say files end up in `$HOME/widowx_data`.

The folder layout under `$DATA` is unchanged by this step, still
`<project_key>/<subpath>/...`.

### Step 2: the unified layout (bigger, needs a group decision)

- [ ] Save as `/datasets/<task_instruction>/<timestamp>` instead of
      `<project_key>/<subpath>/<prefix>`. This changes the save path logic in
      `run_data_collection.py`, and is the "unified trajectory saver" from the
      infrastructure doc.
- [ ] Settle first whether that saver is one shared package used by every
      robot repo, rather than a WidowX-only change (see "Where new shared code
      goes" in [repo-workflow.md](repo-workflow.md)).

### Preflight in the meantime

- [ ] `host.dataset_dir.unified_root` warns on every run that `/datasets` does
      not exist, although nothing uses it yet. Turn it into a PASS-level note
      ("not used yet: data goes to ~/widowx_data") until step 1 lands, then
      make it a real check, and drop the separate `legacy_dataset_root` once
      there is only one data folder.

## Make the docker build reproducible

The Noetic end-of-life break (rosdep skipping Noetic, so `dynamixel_sdk` was
never installed) went unnoticed because the Interbotix install script hides
its own failures. Remaining risks of the same kind:

- [ ] The Interbotix script clones `interbotix_ros_core` and
      `interbotix_ros_toolboxes` at their latest commit (only
      `interbotix_ros_manipulators` is checked out to `noetic`). Pin all three
      to known-good commits.
- [ ] The ROS apt key added in `widowx_envs/Dockerfile`
      (`C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654`) was rotated in 2025. A
      build without cache may fail at the ROS apt steps with `EXPKEYSIG`;
      switch to the `ros-apt-source` package from the ROS install docs.
- [ ] The Interbotix script has no `set -e`, so any failure inside it is
      invisible. Consider running it with `bash -e`, or replacing it with the
      few steps we actually need.
