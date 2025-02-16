_base_ = ["./ss_dibr_mlBCE_FreezeBN_woCenter_refinePM10_10e_train810_benchvise.py"]

# refiner_cfg_path = "configs/_base_/DGNPose_refiner_base.py"
OUTPUT_DIR = "output/DGNPose/ssHB/ss_dibr_mlBCE_FreezeBN_woCenter_refinePM10_10e_train810/driller"

DATASETS = dict(
    TRAIN=("hb_bdp_driller_train810",),  # real data
    TRAIN2=("lm_pbr_driller_train",),  # synthetic data
    TEST=("hb_bdp_driller_test100",),
)

RENDERER = dict(DIFF_RENDERER="DIBR")  # DIBR | DIBR

MODEL = dict(
    # synthetically trained model
    WEIGHTS="output/DGNPose/lm_pbr/resnest50d_a6_AugCosyAAEGray_BG05_mlBCE_lm_pbr_100e/driller/model_final_wo_optim-4cfc7d64.pth",
)
