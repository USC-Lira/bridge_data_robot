"""
This script shows how we evaluated a finetuned Octo model on a real WidowX robot. While the exact specifics may not
be applicable to your use case, this script serves as a didactic example of how to use Octo in a real-world setting.

If you wish, you may reproduce these results by [reproducing the robot setup](https://rail-berkeley.github.io/bridgedata/)
and installing [the robot controller](https://github.com/rail-berkeley/bridge_data_robot)
"""

from datetime import datetime
from functools import partial
import os
import time

from absl import app, flags, logging
import click
import cv2
import imageio
import numpy as np
import keyboard
np.set_printoptions(suppress=True)

logging.set_verbosity(logging.WARNING)

FLAGS = flags.FLAGS

flags.DEFINE_string(
    "checkpoint_weights_path", None, "Path to checkpoint", required=True
)
flags.DEFINE_integer("checkpoint_step", None, "Checkpoint step")

# custom to bridge_data_robot
flags.DEFINE_string("ip", "localhost", "IP address of the robot")
flags.DEFINE_integer("port", 5556, "Port of the robot")
flags.DEFINE_spaceseplist("goal_eep", [0.3, 0.0, 0.15], "Goal position")
flags.DEFINE_spaceseplist("initial_eep", [0.3, 0.0, 0.15], "Initial position")
flags.DEFINE_bool("blocking", False, "Use the blocking controller")


flags.DEFINE_integer("im_size", None, "Image size", required=True)
flags.DEFINE_string("video_save_path", None, "Path to save video")
flags.DEFINE_integer("num_timesteps", 120, "num timesteps")
flags.DEFINE_integer("horizon", 1, "Observation history length")
flags.DEFINE_integer("pred_horizon", 1, "Length of action sequence from model")
flags.DEFINE_integer("exec_horizon", 1, "Length of action sequence to execute")


# show image flag
flags.DEFINE_bool("show_image", False, "Show image")

##############################################################################

STEP_DURATION_MESSAGE = """
Bridge data was collected with non-blocking control and a step duration of 0.2s.
However, we relabel the actions to make it look like the data was collected with
blocking control and we evaluate with blocking control.
We also use a step duration of 0.4s to reduce the jerkiness of the policy.
Be sure to change the step duration back to 0.2 if evaluating with non-blocking control.
"""
STEP_DURATION = 0.2
STICKY_GRIPPER_NUM_STEPS = 1
WORKSPACE_BOUNDS = [[0.1, -0.15, -0.01, -1.57, 0], [0.45, 0.25, 0.25, 1.57, 0]]
CAMERA_TOPICS = [{"name": "/blue/image_raw"}]
ENV_PARAMS = {
    "camera_topics": CAMERA_TOPICS,
    "override_workspace_boundaries": WORKSPACE_BOUNDS,
    "move_duration": STEP_DURATION,
}


##############################################################################


def main(_):
    # goal sampling loop
    while True:
        input("Press [Enter] to start.")

        # do rollout
        last_tstep = time.time()
        images = []
        goals = []
        t = 0
        while t < FLAGS.num_timesteps:
            if time.time() > last_tstep + STEP_DURATION:
                last_tstep = time.time()

                # save images
                images.append(obs["image_primary"][-1])

                if FLAGS.show_image:
                    bgr_img = cv2.cvtColor(obs["image_primary"][-1], cv2.COLOR_RGB2BGR)
                    cv2.imshow("img_view", bgr_img)
                    cv2.waitKey(20)

                # get action
                forward_pass_time = time.time()
                print("forward pass time: ", time.time() - forward_pass_time)

                # perform environment step
                start_time = time.time()
                print("step time: ", time.time() - start_time)

                t += 1

                if keyboard.is_pressed('q'):  
                    print("done collecting human demo")
                    break

        # save video
        if FLAGS.video_save_path is not None:
            os.makedirs(FLAGS.video_save_path, exist_ok=True)
            curr_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            save_path = os.path.join(
                FLAGS.video_save_path,
                f"{curr_time}.mp4",
            )
            video = np.concatenate([np.stack(goals), np.stack(images)], axis=1)
            imageio.mimsave(save_path, video, fps=1.0 / STEP_DURATION * 3)


if __name__ == "__main__":
    # app.run(main)


    from multicam_server.topic_utils import IMTopic
    import rospy
    from sensor_msgs.msg import CameraInfo
    from multicam_server.camera_recorder import CameraRecorder
    from sshkeyboard import listen_keyboard

    def press(key):
        print(f"'{key}' pressed")

    def release(key):
        print(f"'{key}' released")

    rospy.init_node("camera_rec_test")
    imtopic = IMTopic('/blue/image_raw')
    rec = CameraRecorder(imtopic)

    listen_keyboard(
        on_press=press,
        on_release=release,
    )

    r = rospy.Rate(5)  # 10hz
    start_time = rospy.get_time()

    for t in range(20):
        print('t{} before get image {}'.format(t, rospy.get_time() - start_time))
        t0 = rospy.get_time()
        tstamp, im = rec.get_image()
        # print('get image took', rospy.get_time() - t0)

        im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        print(im.shape)

        t1 = rospy.get_time()
        folder = ""
        cv2.imwrite(f"{folder}/test_image_{t}.jpg", im)
        # print('save took ', rospy.get_time() - t1)

        r.sleep()

        # if keyboard.is_pressed("q"):
        #     print("pressed q")
            
