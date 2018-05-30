import numpy as np
import xml.etree.ElementTree as ET
from MujocoManip.models.base import MujocoXML
from MujocoManip.miscellaneous import XMLError
from MujocoManip.models.world import MujocoWorldBase
from MujocoManip.models.model_util import *
from MujocoManip.miscellaneous.utils import *
from collections import OrderedDict
from MujocoManip.models.table_top_task import ObjectPositionSampler

class UniformRandomPegsSampler(ObjectPositionSampler):
    """
        Places all objects within the table uniformly random
    """
    def __init__(self, x_range=None, 
                    y_range=None,
                    z_range=None, 
                    ensure_object_boundary_in_range=True,
                    z_rotation=True):
        """
        Args:
            x_range(float * 2): override the x_range used to uniformly place objects
                    if None, default to x-range of table
            y_range(float * 2): override the y_range used to uniformly place objects
                    if None default to y-range of table
            x_range and y_range are both with respect to (0,0) = center of table.
            ensure_object_boundary_in_range:
                True: The center of object is at position:
                     [uniform(min x_range + radius, max x_range - radius)], [uniform(min x_range + radius, max x_range - radius)]
                False: 
                    [uniform(min x_range, max x_range)], [uniform(min x_range, max x_range)]
            z_rotation:
                Add random z-rotation
        """
        self.x_range = x_range
        self.y_range = y_range
        self.z_range = z_range
        self.ensure_object_boundary_in_range = ensure_object_boundary_in_range
        self.z_rotation = z_rotation

    def sample_x(self, object_horizontal_radius):
        x_range = self.x_range
        if x_range is None:
            x_range = [-self.table_size[0] / 2, self.table_size[0] / 2]
        minimum = min(x_range)
        maximum = max(x_range)
        if self.ensure_object_boundary_in_range:
            minimum += object_horizontal_radius
            maximum -= object_horizontal_radius
        return np.random.uniform(high=maximum, low=minimum)
        
    def sample_y(self, object_horizontal_radius):
        y_range = self.y_range

        if y_range is None:
            y_range = [-self.table_size[0] / 2, self.table_size[0] / 2]
        minimum = min(y_range)
        maximum = max(y_range)
        if self.ensure_object_boundary_in_range:
            minimum += object_horizontal_radius
            maximum -= object_horizontal_radius
        return np.random.uniform(high=maximum, low=minimum)

    def sample_z(self, object_horizontal_radius):
        z_range = self.z_range
        if z_range is None:
            z_range = [0, 1]
        minimum = min(z_range)
        maximum = max(z_range)
        if self.ensure_object_boundary_in_range:
            minimum += object_horizontal_radius
            maximum -= object_horizontal_radius
        return np.random.uniform(high=maximum, low=minimum)

    def sample_quat(self):
        if self.z_rotation:
            rot_angle = np.random.uniform(high=2 * np.pi,low=0)
            return [np.cos(rot_angle / 2), 0, 0, np.sin(rot_angle / 2)]
        else:
            return [1, 0, 0, 0]

    def sample(self):
        pos_arr = []
        quat_arr = []
        placed_objects = []
        for obj_mjcf in self.mujoco_objects:
            horizontal_radius = obj_mjcf.get_horizontal_radius()
            bottom_offset = obj_mjcf.get_bottom_offset()
            success = False
            for i in range(5000): # 1000 retries
                object_x = self.sample_x(horizontal_radius)
                object_y = self.sample_y(horizontal_radius)
                object_z = self.sample_z(0.01)
                # objects cannot overlap
                location_valid = True
                pos = self.table_top_offset - bottom_offset + np.array([object_x, object_y, object_z])

                for pos2, r in placed_objects:
                    if np.linalg.norm(pos - pos2, 2) <= r + horizontal_radius and abs(pos[2]-pos2[2])<0.021:
                        location_valid = False
                        break
                if location_valid: 
                    # location is valid, put the object down
                    placed_objects.append((pos, horizontal_radius))
                    # random z-rotation
                    
                    quat = self.sample_quat()
                    
                    quat_arr.append(quat)
                    pos_arr.append(pos)
                    success = True
                    break
                
                # bad luck, reroll
            if not success:
                raise RandomizationError('Cannot place all objects on the desk')

        return pos_arr, quat_arr

class PegsTask(MujocoWorldBase):

    """
        APC manipulation task can be specified 
        by three elements of the environment.
        @mujoco_arena, MJCF robot workspace (e.g., shelves)
        @mujoco_robot, MJCF robot model
        @mujoco_objects, a list of MJCF objects of interest
    """

    def __init__(self, mujoco_arena, mujoco_robot, mujoco_objects, initializer=None):
        super().__init__()

        self.object_metadata = []
        self.merge_arena(mujoco_arena)
        self.merge_robot(mujoco_robot)
        self.merge_objects(mujoco_objects)

        if initializer is None:
            initializer = UniformRandomPegsSampler()
        mjcfs = [x for _, x in self.mujoco_objects.items()]
        self.initializer = initializer
        self.initializer.setup(mjcfs, self.shelf_offset, self.shelf_size)

    def merge_robot(self, mujoco_robot):
        self.robot = mujoco_robot
        self.merge(mujoco_robot)

    def merge_arena(self, mujoco_arena):
        self.arena = mujoco_arena
        self.shelf_offset = mujoco_arena.table_top_abs
        self.shelf_size = mujoco_arena.full_size
        self.bin1_body = mujoco_arena.bin1_body
        self.peg1_body = mujoco_arena.peg1_body
        self.peg2_body = mujoco_arena.peg2_body
        self.merge(mujoco_arena)

    def merge_objects(self, mujoco_objects):
        self.n_objects = len(mujoco_objects)
        self.mujoco_objects = mujoco_objects
        self.objects = [] # xml manifestation
        self.max_horizontal_radius = 0
        for obj_name, obj_mjcf in mujoco_objects.items():
            self.merge_asset(obj_mjcf)
            # Load object
            obj = obj_mjcf.get_collision(name=obj_name, site=True)
            obj.append(joint(name=obj_name, type='free', damping='0.0005'))
            self.objects.append(obj)
            self.worldbody.append(obj)

            self.max_horizontal_radius = max(self.max_horizontal_radius,
                                             obj_mjcf.get_horizontal_radius())


    def sample_quat(self):
        if self.z_rotation:
            rot_angle = np.random.uniform(high=2 * np.pi,low=0)
            return [np.cos(rot_angle / 2), 0, 0, np.sin(rot_angle / 2)]
        else:
            return [1, 0, 0, 0]

    def place_objects(self):
        """
        Place objects randomly until no more collisions or max iterations hit.
        Args:
            position_sampler: generate random positions to put objects
        """
        pos_arr, quat_arr = self.initializer.sample()
        for i in range(len(self.objects)):
            self.objects[i].set('pos', array_to_string(pos_arr[i]))
            self.objects[i].set('quat', array_to_string(quat_arr[i]))