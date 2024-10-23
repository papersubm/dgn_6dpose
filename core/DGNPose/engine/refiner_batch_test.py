import os.path as osp
import random
import torch
from functools import partial
from einops import rearrange
from core.utils.zoom_utils import deepim_boxes, batch_crop_resize
from core.utils.camera_geometry import (
    bboxes_from_pose,
    centers_2d_from_pose,
    get_K_crop_resize,
)
from .refiner_engine_utils import (
    boxes_to_masks,
    _empty,
    get_input_dim,
    _normalize_image,
)


def batch_data_test(cfg, data, device="cuda", dtype=torch.float32):
    # batch test data and flatten
    tensor_kwargs = {"dtype": dtype, "device": device}
    to_float_args = {"dtype": dtype, "device": device, "non_blocking": True}
    to_long_args = {
        "dtype": torch.long,
        "device": device,
        "non_blocking": True,
    }

    net_cfg = cfg.MODEL.DEEPIM
    backbone_cfg = net_cfg.BACKBONE

    batch = {}
    num_imgs = len(data)
    batch["img"] = torch.stack([d["image"] for d in data]).to(**to_float_args)
    # construct flattened instance data =============================
    batch["obj_cls"] = torch.cat([d["instances"].obj_classes for d in data], dim=0).to(**to_long_args)
    batch["obj_bbox"] = torch.cat([d["instances"].obj_boxes.tensor for d in data], dim=0).to(**to_float_args)
    # NOTE: initial pose or the output pose estimate
    batch["obj_pose_est"] = torch.cat([d["instances"].obj_poses.tensor for d in data], dim=0).to(**to_float_args)

    # # (extent, points, sym_infos)
    batch["obj_extent"] = torch.cat([d["instances"].obj_extents for d in data], dim=0).to(**to_float_args)
    batch["obj_points"] = torch.cat([d["instances"].obj_points for d in data], dim=0).to(**to_float_args)

    num_insts_per_im = [len(d["instances"]) for d in data]
    n_obj = len(batch["obj_cls"])
    K_list = []
    sym_infos_list = []
    im_ids = []
    inst_ids = []
    for i_im in range(num_imgs):
        sym_infos_list.extend(data[i_im]["instances"].obj_sym_infos)
        for i_inst in range(num_insts_per_im[i_im]):
            im_ids.append(i_im)
            inst_ids.append(i_inst)
            K_list.append(data[i_im]["cam"].clone())

    batch["im_id"] = torch.tensor(im_ids, **tensor_kwargs)
    batch["inst_id"] = torch.tensor(inst_ids, **tensor_kwargs)
    batch["K"] = torch.stack(K_list, dim=0).to(**to_float_args)
    batch["sym_info"] = sym_infos_list

    # placeholders for zoomed data ----------------------------
    im_H, im_W = batch["img"].shape[-2:]
    h_in, w_in = backbone_cfg.INPUT_H, backbone_cfg.INPUT_W
    if backbone_cfg.INPUT_MASK:  # TODO: use box_ren
        batch["mask_obs"] = boxes_to_masks(batch["obj_bbox"], imH=im_H, imW=im_W, **tensor_kwargs)
        batch["zoom_mask_ren"] = _empty(n_obj, 1, h_in, w_in)

    if net_cfg.INPUT_REN_TYPE == "rgb":
        batch["zoom_img_ren"] = _empty(n_obj, 3, h_in, w_in)
    elif net_cfg.INPUT_REN_TYPE == "xyz":
        batch["zoom_xyz_ren"] = _empty(n_obj, 3, h_in, w_in)
    else:
        raise ValueError(f"Invalid input_ren_type: {net_cfg.INPUT_REN_TYPE}")

    input_dim = get_input_dim(cfg)
    if isinstance(input_dim, tuple):
        batch["zoom_x_obs"] = _empty(n_obj, input_dim[0], h_in, w_in)
        batch["zoom_x_ren"] = _empty(n_obj, input_dim[1], h_in, w_in)
    else:  # shared
        batch["zoom_x"] = _empty(n_obj, input_dim, h_in, w_in)

    if backbone_cfg.INPUT_DEPTH:
        batch["zoom_depth_ren"] = _empty(n_obj, 1, h_in, w_in)  # gl ren depth
    return batch


def batch_updater_test(
    cfg,
    batch,
    renderer,
    poses_est=None,
    ren_models=None,
    device="cuda",
    dtype=torch.float32,
):
    """
    iter=0: poses_est=None, obj_pose_est is from data loader
    """
    if ren_models is None:
        # TODO: maybe config renderer type
        return batch_updater_test_egl(
            cfg,
            batch,
            renderer=renderer,
            poses_est=poses_est,
            device=device,
            dtype=dtype,
        )
    # using DIBR ------------------------------------------------------------------------------
    tensor_kwargs = {"dtype": dtype, "device": device}
    input_cfg = cfg.INPUT
    net_cfg = cfg.MODEL.DEEPIM
    backbone_cfg = net_cfg.BACKBONE
    im_H, im_W = batch["img"].shape[-2:]
    h_in, w_in = backbone_cfg.INPUT_H, backbone_cfg.INPUT_W

    # NOTE: [0, 255] in config, DIBR renders rgb in [0, 1]
    pixel_mean = torch.tensor(cfg.MODEL.PIXEL_MEAN, **tensor_kwargs).view(3, 1, 1) / 255.0
    pixel_std = torch.tensor(cfg.MODEL.PIXEL_STD, **tensor_kwargs).view(3, 1, 1) / 255.0

    n_obj = batch["obj_cls"].shape[0]
    if poses_est is not None:
        batch["obj_pose_est"] = poses_est

    # get crop bboxes and resize ratios based on obj_pose_est and obj_bbox -----------------------------
    ren_boxes = bboxes_from_pose(
        batch["obj_points"],
        K=batch["K"],
        pose=batch["obj_pose_est"],
        z_min=0.1,
    )
    ren_centers_2d = centers_2d_from_pose(K=batch["K"], pose=batch["obj_pose_est"], z_min=0.1)
    crop_bboxes, resize_ratios = deepim_boxes(
        ren_boxes,
        ren_centers_2d,
        obs_boxes=batch["obj_bbox"],
        lamb=input_cfg.ZOOM_ENLARGE_SCALE,
        imHW=(im_H, im_W),
        outHW=(h_in, w_in),
    )
    batch["zoom_K"] = get_K_crop_resize(batch["K"], crop_bboxes[:, :2], resize_ratios)
    # for rendering data
    batch["K_DIBR"] = batch["K"].clone()

    # get zoomed obs data ---------------------------------------------------
    im_rois = torch.cat([batch["im_id"].view(-1, 1), crop_bboxes], dim=1)  # to crop and resize image_obs
    inst_rois = torch.cat([torch.arange(n_obj, **tensor_kwargs).view(-1, 1), crop_bboxes], dim=1)
    zoom_img_obs = batch_crop_resize(batch["img"], im_rois, out_H=h_in, out_W=w_in)
    if backbone_cfg.INPUT_DEPTH:
        # TODO
        # zoom_depth_obs = deepim_crop_resize(batch['depth_obs'], im_rois, out_H=h_in, out_W=w_in)
        raise NotImplementedError()
    if backbone_cfg.INPUT_MASK:  # crop and resize mask_obs
        zoom_mask_obs = batch_crop_resize(batch["mask_obs"], inst_rois, out_H=h_in, out_W=w_in)

    # yapf: disable
    # get zoomed ren data (directly render the zoomed data with zoomed K) ---------------
    cur_models = [ren_models[int(_l)] for _l in batch["obj_cls"]]
    ren_func = {
        "batch": partial(renderer.render_batch, antialias=True),
        "batch_single": partial(renderer.render_batch_single, antialias=True),
        "batch_tex": partial(renderer.render_batch_tex, max_mip_level=9, uv_type="vertex"),
        "batch_single_tex": partial(renderer.render_batch_single_tex, max_mip_level=9, uv_type="vertex"),
    }[cfg.DIBR.RENDER_TYPE]
    ren_ret = ren_func(
        batch["obj_pose_est"][:, :3, :3],  # Rs
        batch["obj_pose_est"][:, :3, 3],  # ts
        cur_models,
        # Ks=batch["zoom_K"],
        # width=w_in,
        # height=h_in,
        Ks=batch["K_DIBR"],
        width=im_W,
        height=im_H,
        mode=["color", "depth", "mask", "xyz"],
    )

    if net_cfg.INPUT_REN_TYPE == "rgb":
        img_ren = rearrange(ren_ret["color"][..., [2,1,0]], "b h w c -> b c h w")  # bgr;[0,1]
        zoom_img_ren = batch_crop_resize(img_ren, inst_rois, out_H=h_in, out_W=w_in)
        batch["zoom_img_ren"].copy_(zoom_img_ren, non_blocking=True)
        batch["zoom_img_ren"] = _normalize_image(batch["zoom_img_ren"], pixel_mean, pixel_std)  # normalize images
    elif net_cfg.INPUT_REN_TYPE == "xyz":
        xyz_ren = rearrange(ren_ret["xyz"], "b h w c -> b c h w")
        zoom_xyz_ren = batch_crop_resize(xyz_ren, inst_rois, out_H=h_in, out_W=w_in)
        batch["zoom_xyz_ren"].copy_(zoom_xyz_ren, non_blocking=True)
        batch["zoom_xyz_ren"] = batch["zoom_xyz_ren"] / batch["obj_extent"].view(-1, 3, 1, 1) + 0.5
    else:
        raise ValueError(f"Invalid input_ren_type: {net_cfg.INPUT_REN_TYPE}.")

    if backbone_cfg.INPUT_MASK:
        mask_ren = rearrange(ren_ret["mask"].to(torch.float32), "b h w -> b 1 h w")
        zoom_mask_ren = batch_crop_resize(mask_ren, inst_rois, out_H=h_in, out_W=w_in)
        batch["zoom_mask_ren"].copy_(zoom_mask_ren, non_blocking=True)

    if backbone_cfg.INPUT_DEPTH:
        depth_ren = rearrange(ren_ret["depth"], "b h w -> b 1 h w")
        zoom_depth_ren = batch_crop_resize(depth_ren, inst_rois, out_H=h_in, out_W=w_in)
        batch["zoom_depth_ren"].copy_(zoom_depth_ren, non_blocking=True)

    # yapf: enable

    # collect zoomed ren/obs data =======================================
    if backbone_cfg.SHARED:  # im_ren, im_obs
        # ren data
        if net_cfg.INPUT_REN_TYPE == "rgb":
            batch["zoom_x"][:, 0:3] = batch["zoom_img_ren"]
        elif net_cfg.INPUT_REN_TYPE == "xyz":
            batch["zoom_x"][:, 0:3] = batch["zoom_xyz_ren"]
        else:
            raise ValueError(f"Invalid input_ren_type: {net_cfg.INPUT_REN_TYPE}")
        # obs data
        if net_cfg.INPUT_OBS_TYPE == "rgb":
            batch["zoom_x"][:, 3:6] = zoom_img_obs
        elif net_cfg.INPUT_OBS_TYPE == "xyz":
            raise NotImplementedError("Notimplemented for input obs xyz")
        else:
            raise ValueError(f"Invalid input_obs_type: {net_cfg.INPUT_OBS_TYPE}")
        if backbone_cfg.INPUT_MASK:  # im_ren, im_obs, mask_ren, mask_obs
            batch["zoom_x"][:, 6:7] = batch["zoom_mask_ren"]
            batch["zoom_x"][:, 7:8] = zoom_mask_obs
            if backbone_cfg.INPUT_DEPTH:  # im_ren, im_obs, mask_ren, mask_obs, depth_ren, depth_obs
                # TODO
                # batch["zoom_x"][:, 8:9] = batch['zoom_depth_ren']
                # batch["zoom_x"][:, 9:10] = zoom_depth_obs
                raise NotImplementedError()
        else:  # not input mask
            if backbone_cfg.INPUT_DEPTH:  # im_ren, im_obs, depth_ren, depth_obs
                # TODO
                # batch['zoom_x'][:, 6:7] = batch['zoom_depth_ren']
                # batch['zoom_x'][:, 7:8] = zoom_depth_obs
                raise NotImplementedError()
    else:  # unshared inputs --------------------------------
        # ren data
        if net_cfg.INPUT_REN_TYPE == "rgb":
            batch["zoom_x_ren"][:, :3] = batch["zoom_img_ren"]  # im_ren
        elif net_cfg.INPUT_REN_TYPE == "xyz":
            batch["zoom_x_ren"][:, :3] = batch["zoom_xyz_ren"]
        else:
            raise ValueError(f"Invalid input_ren_type: {net_cfg.INPUT_REN_TYPE}")
        # obs data
        if net_cfg.INPUT_OBS_TYPE == "rgb":
            batch["zoom_x_obs"][:, :3] = zoom_img_obs  # im_obs
        elif net_cfg.INPUT_OBS_TYPE == "xyz":
            raise NotImplementedError("Notimplemented for input obs xyz")
        else:
            raise ValueError(f"Invalid input_obs_type: {net_cfg.INPUT_OBS_TYPE}")
        if backbone_cfg.INPUT_MASK:
            batch["zoom_x_ren"][:, 3:4] = batch["zoom_mask_ren"]  # im_ren, mask_ren
            batch["zoom_x_obs"][:, 3:4] = zoom_mask_obs  # im_obs, mask_obs
            if backbone_cfg.INPUT_DEPTH:  # TODO
                # batch['zoom_x_ren'][:, 4:5] = batch['zoom_depth_ren']  # im_ren, mask_ren, depth_ren
                # batch['zoom_x_obs'][:, 4:5] = zoom_depth_obs  # im_obs, mask_obs, depth_obs
                raise NotImplementedError()
        else:  # not input mask
            if backbone_cfg.INPUT_DEPTH:
                # batch['zoom_x_ren'][:, 3:4] = batch['zoom_depth_ren']  # im_ren, depth_ren
                # batch['zoom_x_obs'][:, 3:4] = zoom_depth_obs  # im_obs, depth_obs
                raise NotImplementedError()  # TODO
    # done batch update test (DIBR) ------------------------------------------


# --------------------------------------------------------------------------------------------
def batch_updater_test_egl(cfg, batch, renderer, poses_est=None, device="cuda", dtype=torch.float32):
    """
    iter=0: poses_est=None, obj_pose_est is from data loader
    """
    tensor_kwargs = {"dtype": dtype, "device": device}
    input_cfg = cfg.INPUT
    net_cfg = cfg.MODEL.DEEPIM
    backbone_cfg = net_cfg.BACKBONE
    im_H, im_W = batch["img"].shape[-2:]
    h_in, w_in = backbone_cfg.INPUT_H, backbone_cfg.INPUT_W

    # for renderer
    image_tensor = torch.cuda.FloatTensor(h_in, w_in, 4, device=device).detach()  # image
    seg_tensor = torch.cuda.FloatTensor(h_in, w_in, 4, device=device).detach()  # mask
    pc_cam_tensor = torch.cuda.FloatTensor(h_in, w_in, 4, device=device).detach()  # depth
    pc_obj_tensor = torch.cuda.FloatTensor(h_in, w_in, 4, device=device).detach()  # xyz
    pixel_mean = torch.tensor(cfg.MODEL.PIXEL_MEAN, **tensor_kwargs).view(3, 1, 1)
    pixel_std = torch.tensor(cfg.MODEL.PIXEL_STD, **tensor_kwargs).view(3, 1, 1)

    n_obj = batch["obj_cls"].shape[0]
    if poses_est is not None:
        batch["obj_pose_est"] = poses_est
    # get crop bboxes and resize ratios based on obj_pose_est and obj_bbox
    ren_boxes = bboxes_from_pose(
        batch["obj_points"],
        K=batch["K"],
        pose=batch["obj_pose_est"],
        z_min=0.1,
    )
    ren_centers_2d = centers_2d_from_pose(K=batch["K"], pose=batch["obj_pose_est"], z_min=0.1)
    crop_bboxes, resize_ratios = deepim_boxes(
        ren_boxes,
        ren_centers_2d,
        obs_boxes=batch["obj_bbox"],
        lamb=input_cfg.ZOOM_ENLARGE_SCALE,
        imHW=(im_H, im_W),
        outHW=(h_in, w_in),
    )
    batch["zoom_K"] = get_K_crop_resize(batch["K"], crop_bboxes[:, :2], resize_ratios)  # for rendering zoomed data
    # get zoomed obs data ---------------------------------------------------
    im_rois = torch.cat([batch["im_id"].view(-1, 1), crop_bboxes], dim=1)  # crop and resize image_obs
    inst_rois = torch.cat([torch.arange(n_obj, **tensor_kwargs).view(-1, 1), crop_bboxes], dim=1)
    zoom_img_obs = batch_crop_resize(batch["img"], im_rois, out_H=h_in, out_W=w_in)
    if backbone_cfg.INPUT_DEPTH:
        # zoom_depth_obs = deepim_crop_resize(batch['depth_obs'], im_rois, out_H=h_in, out_W=w_in)
        raise NotImplementedError()
    if backbone_cfg.INPUT_MASK:  # crop and resize mask_obs
        zoom_mask_obs = batch_crop_resize(batch["mask_obs"], inst_rois, out_H=h_in, out_W=w_in)

    # yapf: disable
    # get zoomed ren data (directly render the zoomed data with zoomed K) ---------------
    for _i in range(n_obj):
        renderer.render(
            [int(batch["obj_cls"][_i])],
            [batch["obj_pose_est"][_i].detach().cpu().numpy()],  # src pose
            K=batch["zoom_K"][_i].detach().cpu().numpy(),
            image_tensor=image_tensor, seg_tensor=seg_tensor, pc_cam_tensor=pc_cam_tensor,
            pc_obj_tensor=pc_obj_tensor)
        if net_cfg.INPUT_REN_TYPE == "rgb":
            batch["zoom_img_ren"][_i].copy_(rearrange(image_tensor[..., :3], "h w c -> c h w"), non_blocking=True)  # 255
        elif net_cfg.INPUT_REN_TYPE == "xyz":
            batch["zoom_xyz_ren"][_i].copy_(rearrange(pc_obj_tensor[..., :3], "h w c -> c h w"), non_blocking=True)
        else:
            raise ValueError(f"Invalid input_ren_type: {net_cfg.INPUT_REN_TYPE}")
        if backbone_cfg.INPUT_MASK:
            batch["zoom_mask_ren"][_i, 0].copy_(
                (seg_tensor[:, :, 0] > 0).to(torch.float32), non_blocking=True)

        if backbone_cfg.INPUT_DEPTH:
            batch["zoom_depth_ren"][_i, 0].copy_(pc_cam_tensor[:, :, 2], non_blocking=True)
    if net_cfg.INPUT_REN_TYPE == "rgb":
        batch["zoom_img_ren"] = _normalize_image(batch["zoom_img_ren"], pixel_mean, pixel_std)  # normalize images
    elif net_cfg.INPUT_REN_TYPE == "xyz":
        batch["zoom_xyz_ren"] = batch["zoom_xyz_ren"] / batch["obj_extent"].view(-1, 3, 1, 1) + 0.5
    else:
        raise ValueError(f"Invalid input_ren_type: {net_cfg.INPUT_REN_TYPE}")
    # yapf: enable

    # collect zoomed ren/obs data -----------------------------
    if backbone_cfg.SHARED:  # im_ren, im_obs
        # ren data
        if net_cfg.INPUT_REN_TYPE == "rgb":
            batch["zoom_x"][:, 0:3] = batch["zoom_img_ren"]
        elif net_cfg.INPUT_REN_TYPE == "xyz":
            batch["zoom_x"][:, 0:3] = batch["zoom_xyz_ren"]
        else:
            raise ValueError(f"Invalid input_ren_type: {net_cfg.INPUT_REN_TYPE}")
        # obs data
        if net_cfg.INPUT_OBS_TYPE == "rgb":
            batch["zoom_x"][:, 3:6] = zoom_img_obs
        elif net_cfg.INPUT_OBS_TYPE == "xyz":
            # TODO
            raise NotImplementedError("Not implemented for obs xyz data!")
        else:
            raise ValueError(f"Invalid input_obs_type: {net_cfg.INPUT_OBS_TYPE}")

        if backbone_cfg.INPUT_MASK:  # im_ren, im_obs, mask_ren, mask_obs
            batch["zoom_x"][:, 6:7] = batch["zoom_mask_ren"]
            batch["zoom_x"][:, 7:8] = zoom_mask_obs
            if backbone_cfg.INPUT_DEPTH:  # im_ren, im_obs, mask_ren, mask_obs, depth_ren, depth_obs
                # batch["zoom_x"][:, 8:9] = batch['zoom_depth_ren']
                # batch["zoom_x"][:, 9:10] = zoom_depth_obs
                raise NotImplementedError()
        else:  # not input mask
            if backbone_cfg.INPUT_DEPTH:  # im_ren, im_obs, depth_ren, depth_obs
                # batch['zoom_x'][:, 6:7] = batch['zoom_depth_ren']
                # batch['zoom_x'][:, 7:8] = zoom_depth_obs
                raise NotImplementedError()
    else:  # unshared inputs --------------------
        # ren data
        if net_cfg.INPUT_REN_TYPE == "rgb":
            batch["zoom_x_ren"][:, :3] = batch["zoom_img_ren"]  # im_ren
        elif net_cfg.INPUT_REN_TYPE == "xyz":
            batch["zoom_x_ren"][:, :3] = batch["zoom_xyz_ren"]
        else:
            raise ValueError(f"Invalid input_ren_type: {net_cfg.INPUT_REN_TYPE}")
        # obs data
        if net_cfg.INPUT_OBS_TYPE == "rgb":
            batch["zoom_x_obs"][:, :3] = zoom_img_obs  # im_obs
        elif net_cfg.INPUT_OBS_TYPE == "xyz":
            # TODO
            raise NotImplementedError("Not implemented for obs xyz data!")
        else:
            raise ValueError(f"Invalid input_obs_type: {net_cfg.INPUT_OBS_TYPE}")
        if backbone_cfg.INPUT_MASK:
            batch["zoom_x_ren"][:, 3:4] = batch["zoom_mask_ren"]  # im_ren, mask_ren
            batch["zoom_x_obs"][:, 3:4] = zoom_mask_obs  # im_obs, mask_obs
            if backbone_cfg.INPUT_DEPTH:
                # batch['zoom_x_ren'][:, 4:5] = batch['zoom_depth_ren']  # im_ren, mask_ren, depth_ren
                # batch['zoom_x_obs'][:, 4:5] = zoom_depth_obs  # im_obs, mask_obs, depth_obs
                raise NotImplementedError()
        else:  # not input mask
            if backbone_cfg.INPUT_DEPTH:  #
                # batch['zoom_x_ren'][:, 3:4] = batch['zoom_depth_ren']  # im_ren, depth_ren
                # batch['zoom_x_obs'][:, 3:4] = zoom_depth_obs  # im_obs, depth_obs
                raise NotImplementedError()
    # done batch update test (egl) ------------------------------------------
