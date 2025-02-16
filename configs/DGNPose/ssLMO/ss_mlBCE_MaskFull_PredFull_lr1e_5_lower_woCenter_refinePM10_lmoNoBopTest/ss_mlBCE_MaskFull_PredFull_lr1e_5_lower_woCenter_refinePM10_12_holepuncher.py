_base_ = ["ss_mlBCE_MaskFull_PredFull_lr1e_5_lower_woCenter_refinePM10_01_ape.py"]

OUTPUT_DIR = (
    "output/DGNPose/ssLMO/ss_mlBCE_MaskFull_PredFull_lr1e_5_lower_woCenter_refinePM10_lmoNoBopTest/holepuncher"
)

DATASETS = dict(
    TRAIN=("lmo_NoBopTest_holepuncher_train",),
    TRAIN2=("lmo_pbr_holepuncher_train",),  # real data  # synthetic data
)

MODEL = dict(
    # synthetically trained model
    WEIGHTS="output/DGNPose/lmoPbrSO/resnest50d_online_AugCosyAAEGray_mlBCE_DoubleMask_lmo_pbr_100e/holepuncher/model_final_wo_optim-c98281c9.pth"
)
