import numpy as np
import time
import rospy
import pickle as pkl

from multicam_server.topic_utils import IMTopic
from widowx_envs.widowx_env import WidowXEnv


env_params = {
    'camera_topics': [IMTopic('/blue/image_raw')
                      ],
    'gripper_attached': 'custom',
    'skip_move_to_neutral': True,
    'move_to_rand_start_freq': -1,
    'fix_zangle': 0.1,
    'move_duration': 0.2,
    'adaptive_wait': True,
    'action_clipping': None
}


def replay(env, policy_dict):
    actions = np.stack([d['actions'] for d in policy_dict], axis=0)

    last_tstep = time.time()
    rospy.sleep(0.1)

    obs_imgs = []
    for action in actions:
        env.step(action)
        # t = time.time()
        # while True:
        #     if t - last_tstep > env_params['move_duration']:
        #         print(f'loop {t - last_tstep}s')
        #         obs = env.step(action)
        #         obs_imgs.append(obs['images'])
        #         last_tstep = t
        #         break
    
    env._controller.open_gripper(True)
    env.move_to_neutral()
    # clip = mpy.ImageSequenceClip(obs_imgs, fps=10)
    # clip.write_videofile('video_replay' + '.mp4')


if __name__ == '__main__':
    dir = '/home/robonet/trainingdata/robonetv2/bridge_data_v2/2024-05-21_17-36-21/raw/traj_group0/traj32'
    policy_dict = pkl.load(open(dir + '/policy_out.pkl', "rb"))

    env = WidowXEnv(env_params)
    env.start()
    env.move_to_neutral()


    replay(env, policy_dict)

    replay(env, policy_dict)

    print('Finished!')
    