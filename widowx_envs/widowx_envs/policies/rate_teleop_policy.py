"""LIRA: teleop policy for rate devices (keyboard, ...).

While a key (or axis) is held the target pose moves at the device's speed;
when nothing is held it stays where it is. The new target then goes through
the same per-axis control as VR (VRTeleopPolicy.apply_control: locked axes,
"hold", fixed values) and is turned into the same 7-number action, so the
dataset format does not depend on the input device.
"""

import numpy as np

import widowx_envs.utils.transformation_utils as tr
from widowx_envs.policies.vr_teleop_policy import VRTeleopPolicy


class RateTeleopPolicy(VRTeleopPolicy):

    def reset(self):
        super(RateTeleopPolicy, self).reset()
        self.device.reset_trajectory()

    def act(self, t=None, i_tr=None, images=None, task_id=None):
        linear, angular, gripper = self.device.rate_input()
        dt = self.env._hp.move_duration

        target, _ = self.env.get_target_state()
        rot, xyz = tr.TransToRp(target)
        xyz = np.asarray(xyz, dtype=float) + np.asarray(linear, dtype=float) * dt
        euler = np.asarray(self._euler_from_default(rot), dtype=float) + np.asarray(angular, dtype=float) * dt
        new_rot = tr.eulerAnglesToRotationMatrix(euler).dot(self.env._controller.default_rot)
        new_target = tr.RpToTrans(new_rot, xyz)

        new_target, gripper = self.apply_control(new_target, gripper)
        delta = new_target.dot(tr.TransInv(target))
        actions = tr.transform2action_local(delta, gripper, self.env._controller.get_cartesian_pose()[:3])
        if self.env._hp.action_mode == '3trans1rot':
            actions = np.concatenate([actions[:3], np.array([actions[5]]), np.array([gripper])])
        if self.env._hp.action_mode == '3trans':
            actions = np.concatenate([actions[:3], np.array([gripper])])

        output = {'actions': actions, 'new_robot_transform': new_target, 'delta_robot_transform': delta,
                  'policy_type': 'RateTeleopPolicy'}
        self.internal_counter += 1
        if self._hp.policy_T and self.internal_counter >= self._hp.policy_T:
            output['done'] = True
        return output
