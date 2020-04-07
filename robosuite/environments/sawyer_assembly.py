from collections import OrderedDict
import random
import numpy as np
from copy import deepcopy

from robosuite.utils.mjcf_utils import range_to_uniform_grid
from robosuite.utils.transform_utils import convert_quat
import robosuite.utils.env_utils as EU
from robosuite.environments.sawyer import SawyerEnv

from robosuite.models.arenas import LegoArena
from robosuite.models.objects import Hole3dObject, GridObject
from robosuite.models.robots import Sawyer
from robosuite.models.tasks import TableTopTask, UniformRandomSampler
from robosuite.controllers import load_controller_config
import os


class SawyerAssembly(SawyerEnv):
    """
    This class corresponds to the 3-part assembly task for the Sawyer robot arm.
    """

    def __init__(
        self,
        controller_config=None,
        gripper_type="TwoFingerGripper",
        table_full_size=(0.8, 0.8, 0.8),
        table_friction=(1., 5e-3, 1e-4),
        use_camera_obs=True,
        use_object_obs=True,
        reward_shaping=False,
        placement_initializer=None,
        gripper_visualization=False,
        use_indicator_object=False,
        indicator_num=1,
        has_renderer=False,
        has_offscreen_renderer=True,
        render_collision_mesh=False,
        render_visual_mesh=True,
        control_freq=10,
        horizon=1000,
        ignore_done=False,
        camera_name="frontview",
        camera_height=256,
        camera_width=256,
        camera_depth=False,
        camera_real_depth=False,
        camera_segmentation=False,
        eval_mode=False,
        perturb_evals=False,
    ):
        """
        Args:
            controller_config (dict): If set, contains relevant controller parameters for creating a custom controller.
                Else, uses the default controller for this specific task

            gripper_type (str): type of gripper, used to instantiate
                gripper models from gripper factory.

            table_full_size (3-tuple): x, y, and z dimensions of the table.

            table_friction (3-tuple): the three mujoco friction parameters for
                the table.

            use_camera_obs (bool): if True, every observation includes a
                rendered image.

            use_object_obs (bool): if True, include object (cube) information in
                the observation.

            reward_shaping (bool): if True, use dense rewards.

            placement_initializer (ObjectPositionSampler instance): if provided, will
                be used to place objects on every reset, else a UniformRandomSampler
                is used by default.

            gripper_visualization (bool): True if using gripper visualization.
                Useful for teleoperation.

            use_indicator_object (bool): if True, sets up an indicator object that
                is useful for debugging.

            indicator_num (int): number of indicator objects to add to the environment.
                Only used if @use_indicator_object is True.

            has_renderer (bool): If true, render the simulation state in
                a viewer instead of headless mode.

            has_offscreen_renderer (bool): True if using off-screen rendering.

            render_collision_mesh (bool): True if rendering collision meshes
                in camera. False otherwise.

            render_visual_mesh (bool): True if rendering visual meshes
                in camera. False otherwise.

            control_freq (float): how many control signals to receive
                in every second. This sets the amount of simulation time
                that passes between every action input.

            horizon (int): Every episode lasts for exactly @horizon timesteps.

            ignore_done (bool): True if never terminating the environment (ignore @horizon).

            camera_name (str): name of camera to be rendered. Must be
                set if @use_camera_obs is True.

            camera_height (int): height of camera frame.

            camera_width (int): width of camera frame.

            camera_depth (bool): True if rendering RGB-D, and RGB otherwise.

            camera_real_depth (bool): True if convert depth to real depth in meters

            camera_segmentation (bool): True if also return semantic segmentation of the camera view
        """

        # Load the default controller if none is specified
        if controller_config is None:
            controller_path = os.path.join(os.path.dirname(__file__), '..', 'controllers/config/default_sawyer.json')
            controller_config = load_controller_config(custom_fpath=controller_path)

        # Assert that the controller config is a dict file
        assert type(controller_config) == dict, \
            "Inputted controller config must be a dict! Instead, got type: {}".format(type(controller_config))

        # settings for table top
        self.table_full_size = table_full_size
        self.table_friction = table_friction

        # whether to use ground-truth object states
        self.use_object_obs = use_object_obs

        # reward configuration
        self.reward_shaping = reward_shaping

        # object placement initializer
        if placement_initializer is not None:
            self.placement_initializer = placement_initializer
        else:
            self.placement_initializer = UniformRandomSampler(
                x_range=[-0.3, 0.2],
                y_range=[-0.3, 0.2],
                ensure_object_boundary_in_range=False,
                z_rotation=None,
            )

        super().__init__(
            controller_config=controller_config,
            gripper_type=gripper_type,
            gripper_visualization=gripper_visualization,
            use_indicator_object=use_indicator_object,
            indicator_num=indicator_num,
            has_renderer=has_renderer,
            has_offscreen_renderer=has_offscreen_renderer,
            render_collision_mesh=render_collision_mesh,
            render_visual_mesh=render_visual_mesh,
            control_freq=control_freq,
            horizon=horizon,
            ignore_done=ignore_done,
            use_camera_obs=use_camera_obs,
            camera_name=camera_name,
            camera_height=camera_height,
            camera_width=camera_width,
            camera_depth=camera_depth,
            camera_real_depth=camera_real_depth,
            camera_segmentation=camera_segmentation,
            eval_mode=eval_mode,
            perturb_evals=perturb_evals,
        )

    def _get_placement_initializer_for_eval_mode(self):
        """
        Sets a placement initializer that is used to initialize the
        environment into a fixed set of known task instances.
        This is for reproducibility in policy evaluation.
        """

        assert(self.eval_mode)

        # set up placement grid by getting bounds per dimension and then
        # using meshgrid to get all combinations
        x_bounds, y_bounds, z_rot_bounds = self._grid_bounds_for_eval_mode()
        x_grid = range_to_uniform_grid(a=x_bounds[0], b=x_bounds[1], n=x_bounds[2])
        y_grid = range_to_uniform_grid(a=y_bounds[0], b=y_bounds[1], n=y_bounds[2])
        z_rotation = range_to_uniform_grid(a=z_rot_bounds[0], b=z_rot_bounds[1], n=z_rot_bounds[2])
        grid = np.meshgrid(x_grid, y_grid, z_rotation)
        x_grid = grid[0].ravel()
        y_grid = grid[1].ravel()
        z_rotation = grid[2].ravel()
        grid_length = x_grid.shape[0]

        round_robin_period = grid_length
        if self.perturb_evals:
            # sample 100 rounds of perturbations and then sampler will repeat
            round_robin_period *= 100

            # perturbation size should be half the grid spacing
            x_pos_perturb_size = ((x_bounds[1] - x_bounds[0]) / x_bounds[2]) / 2.
            y_pos_perturb_size = ((y_bounds[1] - y_bounds[0]) / y_bounds[2]) / 2.
            z_rot_perturb_size = ((z_rot_bounds[1] - z_rot_bounds[0]) / z_rot_bounds[2]) / 2.

        # assign grid locations for the full round robin schedule
        final_x_grid = np.zeros(round_robin_period)
        final_y_grid = np.zeros(round_robin_period)
        final_z_grid = np.zeros(round_robin_period)
        for t in range(round_robin_period):
            g_ind = t % grid_length
            x, y, z = x_grid[g_ind], y_grid[g_ind], z_rotation[g_ind]
            if self.perturb_evals:
                x += np.random.uniform(low=-x_pos_perturb_size, high=x_pos_perturb_size)
                y += np.random.uniform(low=-y_pos_perturb_size, high=y_pos_perturb_size)
                z += np.random.uniform(low=-z_rot_perturb_size, high=z_rot_perturb_size)
            final_x_grid[t], final_y_grid[t], final_z_grid[t] = x, y, z

        self.placement_initializer = RoundRobinSampler(
            x_range=final_x_grid,
            y_range=final_y_grid,
            ensure_object_boundary_in_range=False,
            z_rotation=final_z_grid
        )

    def _grid_bounds_for_eval_mode(self):
        """
        Helper function to get grid bounds of x positions, y positions, 
        and z-rotations for reproducible evaluations, and number of points
        per dimension.
        """

        # (low, high, number of grid points for this dimension)
        x_bounds = (-0.3, 0.2, 3)
        y_bounds = (-0.3, 0.2, 3)
        # z_rot_bounds = (1., 1., 1)
        z_rot_bounds = (0., 2. * np.pi, 3)
        return x_bounds, y_bounds, z_rot_bounds

    def lego_sample(self):
        """
        Returns a randomly sampled block,hole
        """
        blocks = [[1,1,1],[1,0,1],[1,1,0],[1,0,0]]
        hole_side = [[0,0,0],[0,0.95,0],[0,0,1],[0,1,1]]
        hole = [[[0,0,0],[0,0,0],[0,0,0]]]

        # Pick out two sides of block1
        pick = random.randint(0,len(blocks)-1)
        side1 = blocks[pick]
        hole1 = hole_side[pick]
        pick = random.randint(0,len(blocks)-1)
        side2 = blocks[pick]
        hole2 = hole_side[pick]

        block1 = [[[1,1,1],[1,1,1],[1,1,1]],
                [[0,0,0],[0.9,.9,.9],[0,0,0]],
                [[0,0,0],[.9,.9,.9],[0,0,0]],
                    ]
        block1[0][0] = side1
        block1[0][2] = side2
        hole[0][0] = hole1
        hole[0][2] = hole2

        # Generate hole
        grid_x = 8
        grid_z = 1
        grid = np.ones((grid_z,grid_x,grid_x))

        offset_x = random.randint(1,grid_x-4)
        offset_y = random.randint(1,grid_x-3)

        for z in range(len(hole)):
            for y in range(len(hole[0])):
                for x in range(len(hole[0][0])):
                    grid[z][offset_y+y][offset_x+x] = hole[z][y][x]
        grid = np.rot90(grid,random.randint(0,3),(1,2))
        # Generate Pieces

        block2 = [ [[1,1,1],[0,0,0],[1,1,1]],
                [[1,1,1],[0,0,0],[1,1,1]],
                [[1,1,1],[1,1,1],[1,1,1]],
                [[0,0,0],[0,1,0],[0,0,0]]
                    ]
        return block1, block2,grid

    def _load_model(self):
        """
        Loads an xml model, puts it in self.model
        """
        super()._load_model()
        self.mujoco_robot.set_base_xpos([0, 0, 0])

        # load model for table top workspace
        self.mujoco_arena = LegoArena(
            table_full_size=self.table_full_size, table_friction=self.table_friction
        )
        if self.use_indicator_object:
            self.mujoco_arena.add_pos_indicator(self.indicator_num)

        # The sawyer robot has a pedestal, we want to align it with the table
        self.mujoco_arena.set_origin([0.16 + self.table_full_size[0] / 2, 0, 0])

        # initialize objects of interest
        h1,h2,pg = self.lego_sample()

        h1 = Hole3dObject(size= 0.017, pattern = h1)
        h2 = Hole3dObject(size= 0.017, pattern = h2)
        self.grid = GridObject(size=0.0175, pattern=pg, offset=0.25)
        self.mujoco_arena.table_body.append(self.grid.get_collision(name='grid',site=True))
        self.mujoco_objects = OrderedDict([("block1", h1),("block2", h2)])

        # reset initial joint positions (gets reset in sim during super() call in _reset_internal)
        self.init_qpos = np.array([-0.5538, -0.8208, 0.4155, 1.8409, -0.4955, 0.6482, 1.9628])
        self.init_qpos += np.random.randn(self.init_qpos.shape[0]) * 0.02

        # task includes arena, robot, and objects of interest
        self.model = TableTopTask(
            self.mujoco_arena,
            self.mujoco_robot,
            self.mujoco_objects,
            initializer=self.placement_initializer,
        )
        self.model.place_objects()

    def _get_reference(self):
        """
        Sets up references to important components. A reference is typically an
        index or a list of indices that point to the corresponding elements
        in a flatten array, which is how MuJoCo stores physical simulation data.
        """
        super()._get_reference()
        self.block_body_id = self.sim.model.body_name2id("block1")
        self.l_finger_geom_ids = [
            self.sim.model.geom_name2id(x) for x in self.gripper.left_finger_geoms
        ]
        self.r_finger_geom_ids = [
            self.sim.model.geom_name2id(x) for x in self.gripper.right_finger_geoms
        ]

    def _reset_internal(self):
        """
        Resets simulation internal configurations.
        """
        super()._reset_internal()

    def reward(self, action=None):
        """
        Reward function for the task.

        The dense reward has three components.

            Reaching: in [0, 1], to encourage the arm to reach the cube
            Grasping: in {0, 0.25}, non-zero if arm is grasping the cube
            Lifting: in {0, 1}, non-zero if arm has lifted the cube

        The sparse reward only consists of the lifting component.

        Args:
            action (np array): unused for this task

        Returns:
            reward (float): the reward
        """
        reward = 0.
        if self._check_success():
            reward = 1.

        return reward

    def _get_observation(self):
        """
        Returns an OrderedDict containing observations [(name_string, np.array), ...].

        Important keys:
            robot-state: contains robot-centric information.
            object-state: requires @self.use_object_obs to be True.
                contains object-centric information.
            image: requires @self.use_camera_obs to be True.
                contains a rendered frame from the simulation.
            depth: requires @self.use_camera_obs and @self.camera_depth to be True.
                contains a rendered depth map from the simulation
        """
        di = super()._get_observation()

        # low-level object information
        if self.use_object_obs:
            # position and rotation of object
            block_pos = np.array(self.sim.data.body_xpos[self.block_body_id])
            block_quat = convert_quat(
                np.array(self.sim.data.body_xquat[self.block_body_id]), to="xyzw"
            )
            di["block_pos"] = block_pos
            di["block_quat"] = block_quat

            gripper_site_pos = np.array(self.sim.data.site_xpos[self.eef_site_id])
            di["gripper_to_block"] = gripper_site_pos - block_pos

            di["object-state"] = np.concatenate(
                [block_pos, block_quat, di["gripper_to_block"]]
            )

        return di

    def _check_contact(self):
        """
        Returns True if gripper is in contact with an object.
        """
        collision = False
        for contact in self.sim.data.contact[: self.sim.data.ncon]:
            if (
                self.sim.model.geom_id2name(contact.geom1)
                in self.gripper.contact_geoms()
                or self.sim.model.geom_id2name(contact.geom2)
                in self.gripper.contact_geoms()
            ):
                collision = True
                break
        return collision

    def _check_success(self):
        """
        Returns True if task has been completed.
        """
        return False
        # cnt = 0
        # result = True
        # for i in range(len(self.block)):
        #     for j in range(len(self.block[0])):
        #         if(self.block[i][j]):
        #             if(not self.grid.in_grid(self.sim.data.geom_xpos[self.sim.model.geom_name2id("block1-"+str(cnt))]-[0.16 + self.table_full_size[0] / 2, 0, 0.4])):
        #                 result = False
        #             cnt +=1
        # return result

    def _gripper_visualization(self):
        """
        Do any needed visualization here. Overrides superclass implementations.
        """
        pass

