_base_ = "./ss_v1_dibr_mlBCE_FreezeBN_woCenter_woDepth_refinePM10_ape.py"
OUTPUT_DIR = "output/DGNPose/ssLM/ss_v1_dibr_mlBCE_FreezeBN_woCenter_woDepth_refinePM10/cat"
DATASETS = dict(
    TRAIN=("lm_real_cat_train",), TRAIN2=("lm_pbr_cat_train",), TRAIN2_RATIO=0.0, TEST=("lm_real_cat_test",)
)
MODEL = dict(
    WEIGHTS="output/DGNPose/lm_pbr/resnest50d_a6_AugCosyAAEGray_BG05_mlBCE_lm_pbr_100e/cat/model_final_wo_optim-f38cfafd.pth"
)
