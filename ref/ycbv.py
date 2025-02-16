# encoding: utf-8
"""This file includes necessary params, info."""
import os
import mmcv
import os.path as osp

import numpy as np

# ---------------------------------------------------------------- #
# ROOT PATH INFO
# ---------------------------------------------------------------- #
cur_dir = osp.abspath(osp.dirname(__file__))
root_dir = osp.normpath(osp.join(cur_dir, ".."))
# directory storing experiment data (result, model checkpoints, etc).
output_dir = osp.join(root_dir, "output")

data_root = osp.join(root_dir, "datasets")
bop_root = osp.join(data_root, "BOP_DATASETS/")

# ---------------------------------------------------------------- #
# YCBV DATASET
# ---------------------------------------------------------------- #
dataset_root = osp.join(bop_root, "ycbv")

train_real_dir = osp.join(dataset_root, "train_real")
train_render_dir = osp.join(dataset_root, "train_synt")
train_pbr_dir = osp.join(dataset_root, "train_pbr")

test_dir = osp.join(dataset_root, "test")

test_scenes = [i for i in range(48, 59 + 1)]
train_real_scenes = [i for i in range(0, 91 + 1) if i not in test_scenes]
train_synt_scenes = [i for i in range(0, 79 + 1)]
train_pbr_scenes = [i for i in range(0, 49 + 1)]

model_dir = osp.join(dataset_root, "models")
fine_model_dir = osp.join(dataset_root, "models_fine")
model_eval_dir = osp.join(dataset_root, "models_eval")
model_scaled_simple_dir = osp.join(dataset_root, "models_rescaled")  # m, .obj
vertex_scale = 0.001

# object info
id2obj = {
    1: "002_master_chef_can",  # [1.3360, -0.5000, 3.5105]
    2: "003_cracker_box",  # [0.5575, 1.7005, 4.8050]
    3: "004_sugar_box",  # [-0.9520, 1.4670, 4.3645]
    4: "005_tomato_soup_can",  # [-0.0240, -1.5270, 8.4035]
    5: "006_mustard_bottle",  # [1.2995, 2.4870, -11.8290]
    6: "007_tuna_fish_can",  # [-0.1565, 0.1150, 4.2625]
    7: "008_pudding_box",  # [1.1645, -4.2015, 3.1190]
    8: "009_gelatin_box",  # [1.4460, -0.5915, 3.6085]
    9: "010_potted_meat_can",  # [2.4195, 0.3075, 8.0715]
    10: "011_banana",  # [-18.6730, 12.1915, -1.4635]
    11: "019_pitcher_base",  # [5.3370, 5.8855, 25.6115]
    12: "021_bleach_cleanser",  # [4.9290, -2.4800, -13.2920]
    13: "024_bowl",  # [-0.2270, 0.7950, -2.9675]
    14: "025_mug",  # [-8.4675, -0.6995, -1.6145]
    15: "035_power_drill",  # [9.0710, 20.9360, -2.1190]
    16: "036_wood_block",  # [1.4265, -2.5305, 17.1890]
    17: "037_scissors",  # [7.0535, -28.1320, 0.0420]
    18: "040_large_marker",  # [0.0460, -2.1040, 0.3500]
    19: "051_large_clamp",  # [10.5180, -1.9640, -0.4745]
    20: "052_extra_large_clamp",  # [-0.3950, -10.4130, 0.1620]
    21: "061_foam_brick",  # [-0.0805, 0.0805, -8.2435]
}
objects = sorted(id2obj.values())

obj_num = len(id2obj)
obj2id = {_name: _id for _id, _name in id2obj.items()}

model_paths = [osp.join(model_dir, "obj_{:06d}.ply").format(_id) for _id in id2obj]  # TODO: check this
texture_paths = [osp.join(model_dir, "obj_{:06d}.png".format(_id)) for _id in id2obj]
model_colors = [((i + 1) * 10, (i + 1) * 10, (i + 1) * 10) for i in range(obj_num)]  # for renderer

# yapf: disable
diameters = np.array([172.063, 269.573, 198.377, 120.543, 196.463,
                      89.797,  142.543, 114.053, 129.540, 197.796,
                      259.534, 259.566, 161.922, 124.990, 226.170,
                      237.299, 203.973, 121.365, 174.746, 217.094,
                      102.903]) / 1000.0
# yapf: enable
# Camera info
width = 640
height = 480
zNear = 0.25
zFar = 6.0
center = (height / 2, width / 2)
# default: 0000~0059 and synt
camera_matrix = uw_camera_matrix = np.array([[1066.778, 0.0, 312.9869], [0.0, 1067.487, 241.3109], [0.0, 0.0, 1.0]])
# 0060~0091
cmu_camera_matrix = np.array([[1077.836, 0.0, 323.7872], [0.0, 1078.189, 279.6921], [0.0, 0.0, 1.0]])

depth_factor = 10000.0


def get_models_info():
    """key is str(obj_id)"""
    models_info_path = osp.join(model_dir, "models_info.json")
    assert osp.exists(models_info_path), models_info_path
    models_info = mmcv.load(models_info_path)  # key is str(obj_id)
    return models_info


def get_fps_points():
    """key is str(obj_id) generated by
    core/DGNPose_modeling/tools/ycbv/ycbv_1_compute_fps.py."""
    fps_points_path = osp.join(model_dir, "fps_points.pkl")
    assert osp.exists(fps_points_path), fps_points_path
    fps_dict = mmcv.load(fps_points_path)
    return fps_dict


def get_keypoints_3d():
    """key is str(obj_id) generated by
    core/roi_pvnet/tools/ycbv/ycbv_1_compute_keypoints_3d.py."""
    keypoints_3d_path = osp.join(model_dir, "keypoints_3d.pkl")
    assert osp.exists(keypoints_3d_path), keypoints_3d_path
    kpts_dict = mmcv.load(keypoints_3d_path)
    return kpts_dict
