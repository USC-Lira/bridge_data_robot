#!/usr/bin/env python3

if __name__ == '__main__':
    from widowx_envs.widowx_env import StateReachingWidowX
    # LIRA: no cameras. Moving the arm needs none, and the default camera list
    # (/cam0/image_raw) does not exist on our rig: CameraRecorder would wait for
    # its camera_info forever and go_sleep would never return.
    env = StateReachingWidowX(env_params={'camera_topics': []})
    env.move_to_neutral()
    env._controller.bot.arm.go_to_sleep_pose()
