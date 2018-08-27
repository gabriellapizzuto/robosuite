"""
    Gripper with 11 dof controlling three fingers
    and its open/close variant
"""
import numpy as np
from RoboticsSuite.models.grippers.gripper import Gripper
import RoboticsSuite.utils as U


class RobotiqThreeFingerGripperBase(Gripper):
    """
    Gripper with 11 dof controlling three fingers
    """

    def __init__(self):
        super().__init__(U.xml_path_completion("grippers/robotiq_gripper_s.xml"))

    def format_action(self, action):
        return action

    @property
    def init_qpos(self):
        return np.zeros(11)

    @property
    def joints(self):
        return [
            "palm_finger_1_joint",
            "finger_1_joint_1",
            "finger_1_joint_2",
            "finger_1_joint_3",
            "palm_finger_2_joint",
            "finger_2_joint_1",
            "finger_2_joint_2",
            "finger_2_joint_3",
            "finger_middle_joint_1",
            "finger_middle_joint_2",
            "finger_middle_joint_3",
        ]

    @property
    def dof(self):
        return 11

    def contact_geoms(self):
        return [
            "f1_l0",
            "f1_l1",
            "f1_l2",
            "f1_l3",
            "f2_l0",
            "f2_l1",
            "f2_l2",
            "f2_l3",
            "f3_l0",
            "f3_l1",
            "f3_l2",
            "f3_l3",
        ]

    @property
    def visualization_sites(self):
        return ["grip_site", "grip_site_cylinder"]


class RobotiqThreeFingerGripper(RobotiqThreeFingerGripperBase):
    """
    One dof variant of RobotiqThreeFingerGripperBase
    """

    def format_action(self, action):
        """
        Args:
            action: 1 => open, -1 => closed
        """
        return -1 * np.ones(11) * action
