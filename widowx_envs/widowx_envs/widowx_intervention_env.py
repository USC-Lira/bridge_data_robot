from widowx_env import VR_WidowX
import rospy

class InterventionWidowX(VR_WidowX):
    def __init__(self, env_params=None, **kwargs):
        super(InterventionWidowX, self).__init__(env_params, **kwargs)
    
    def reset(self, itraj=None):
        self.task_stage = 0
        obs = super(VR_WidowX, self).reset(itraj=itraj)
        start_key = 'handle'
        
        print('Place the object between gripper fingers and Press A to close it. Then press {} button to start recording.'.format(start_key))
        buttons = self.get_vr_buttons()
        while not buttons[start_key]:
            buttons = self.get_vr_buttons()
            rospy.sleep(0.01)
            if 'A' in buttons and buttons['A']:
                self._controller.close_gripper()
                rospy.sleep(1)
                print("Object in hand. Waiting for {} button press to start recording.".format(start_key))
        return self.current_obs()
