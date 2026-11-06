# SPDX-License-Identifier: GPL-2.0-only
"""Starter parameters of the Camera Looks and optical effects, transcribed (script-generated, not by hand)
from contracts/v0.5/camera-look-parameters.proposed.yaml and optical-parameters.proposed.yaml.
PROVISIONAL (version 0.1): original artistic approximations, not measured recreations of any camera or
filter. Tune visually; any change here changes render ids (creative.VERSION must be bumped too)."""
LOOKS = {
 "leica_m8_ccd": {
  "contrast_gain": 1.16,
  "toe_strength": 0.1,
  "highlight_shoulder": 0.17,
  "global_chroma_gain": 1.07,
  "shadow_warm_cool": -0.02,
  "highlight_warm_cool": 0.01,
  "green_hue_bias": 0.03,
  "microcontrast_amount": 0.12
 },
 "leica_m9_ccd": {
  "contrast_gain": 1.12,
  "toe_strength": 0.11,
  "highlight_shoulder": 0.18,
  "global_chroma_gain": 1.1,
  "shadow_warm_cool": 0.0,
  "highlight_warm_cool": 0.02,
  "green_hue_bias": 0.08,
  "microcontrast_amount": 0.09
 },
 "fujifilm_s5_pro": {
  "contrast_gain": 0.94,
  "toe_strength": 0.09,
  "highlight_shoulder": 0.32,
  "global_chroma_gain": 0.94,
  "shadow_warm_cool": 0.01,
  "highlight_warm_cool": 0.02,
  "green_hue_bias": -0.04,
  "microcontrast_amount": 0.01
 },
 "nikon_d200_ccd": {
  "contrast_gain": 1.14,
  "toe_strength": 0.08,
  "highlight_shoulder": 0.13,
  "global_chroma_gain": 1.11,
  "shadow_warm_cool": -0.01,
  "highlight_warm_cool": 0.0,
  "green_hue_bias": 0.04,
  "microcontrast_amount": 0.08
 },
 "pentax_645d_ccd": {
  "contrast_gain": 1.04,
  "toe_strength": 0.07,
  "highlight_shoulder": 0.23,
  "global_chroma_gain": 1.0,
  "shadow_warm_cool": 0.0,
  "highlight_warm_cool": 0.01,
  "green_hue_bias": 0.03,
  "microcontrast_amount": 0.06
 },
 "ricoh_gr_iii_positive": {
  "contrast_gain": 1.21,
  "toe_strength": 0.13,
  "highlight_shoulder": 0.14,
  "global_chroma_gain": 1.13,
  "shadow_warm_cool": -0.01,
  "highlight_warm_cool": 0.01,
  "green_hue_bias": 0.02,
  "microcontrast_amount": 0.11
 },
 "sigma_dp2_merrill_foveon": {
  "contrast_gain": 1.08,
  "toe_strength": 0.07,
  "highlight_shoulder": 0.14,
  "global_chroma_gain": 1.02,
  "shadow_warm_cool": 0.0,
  "highlight_warm_cool": 0.0,
  "green_hue_bias": -0.01,
  "microcontrast_amount": 0.2
 },
 "fujifilm_xpro3_classic_negative": {
  "contrast_gain": 1.23,
  "toe_strength": 0.14,
  "highlight_shoulder": 0.12,
  "global_chroma_gain": 0.9,
  "shadow_warm_cool": 0.0,
  "highlight_warm_cool": 0.0,
  "green_hue_bias": -0.07,
  "microcontrast_amount": 0.1
 },
 "neutral": {
  "contrast_gain": 1.0,
  "toe_strength": 0.0,
  "highlight_shoulder": 0.0,
  "global_chroma_gain": 1.0,
  "shadow_warm_cool": 0.0,
  "highlight_warm_cool": 0.0,
  "green_hue_bias": 0.0,
  "microcontrast_amount": 0.0
 }
}
EFFECTS = {
 "soft_sun_glow": {
  "threshold": 1.0,
  "knee": 0.28,
  "radius_fraction": 0.012,
  "warm_shift": 0.1,
  "veil": 0.08
 },
 "ricoh_hdf_diffusion": {
  "threshold": 0.75,
  "knee": 0.35,
  "radius_fraction": 0.006,
  "broad_radius_fraction": 0.02,
  "veil": 0.045
 },
 "black_pro_mist_like": {
  "threshold": 0.85,
  "knee": 0.3,
  "radius_fraction": 0.015,
  "veil": 0.035
 },
 "vintage_veiling_flare": {
  "threshold": 0.9,
  "knee": 0.4,
  "radius_fraction": 0.05,
  "veil": 0.13
 },
 "film_halation_extra": {
  "threshold": 1.15,
  "knee": 0.2,
  "radius_fraction": 0.003,
  "red_gain": 0.12
 },
 "orton_glow": {
  "threshold": 0.5,
  "knee": 0.4,
  "radius_fraction": 0.03,
  "mix": 0.28
 },
 "none": {}
}
