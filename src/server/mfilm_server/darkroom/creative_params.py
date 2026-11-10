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
 "hasselblad_500cm": {
  "contrast_gain": 1.06,
  "toe_strength": 0.08,
  "highlight_shoulder": 0.22,
  "global_chroma_gain": 1.04,
  "shadow_warm_cool": 0.01,
  "highlight_warm_cool": 0.02,
  "green_hue_bias": 0.02,
  "microcontrast_amount": 0.09
 },
 "leica_m6_rangefinder": {
  "contrast_gain": 1.15,
  "toe_strength": 0.12,
  "highlight_shoulder": 0.16,
  "global_chroma_gain": 1.06,
  "shadow_warm_cool": -0.01,
  "highlight_warm_cool": 0.02,
  "green_hue_bias": 0.04,
  "microcontrast_amount": 0.14
 },
 "contax_t2_sonnar": {
  "contrast_gain": 1.20,
  "toe_strength": 0.14,
  "highlight_shoulder": 0.12,
  "global_chroma_gain": 1.14,
  "shadow_warm_cool": -0.03,
  "highlight_warm_cool": 0.01,
  "green_hue_bias": -0.02,
  "microcontrast_amount": 0.13
 },
 "mamiya_7_ii": {
  "contrast_gain": 1.03,
  "toe_strength": 0.06,
  "highlight_shoulder": 0.25,
  "global_chroma_gain": 1.01,
  "shadow_warm_cool": 0.0,
  "highlight_warm_cool": 0.0,
  "green_hue_bias": 0.01,
  "microcontrast_amount": 0.11
 },
 "olympus_om1_zuiko": {
  "contrast_gain": 1.05,
  "toe_strength": 0.05,
  "highlight_shoulder": 0.20,
  "global_chroma_gain": 1.05,
  "shadow_warm_cool": 0.01,
  "highlight_warm_cool": 0.03,
  "green_hue_bias": 0.05,
  "microcontrast_amount": 0.07
 },
 "rolleiflex_28f_tlr": {
  "contrast_gain": 1.02,
  "toe_strength": 0.06,
  "highlight_shoulder": 0.28,
  "global_chroma_gain": 0.98,
  "shadow_warm_cool": 0.02,
  "highlight_warm_cool": 0.03,
  "green_hue_bias": 0.03,
  "microcontrast_amount": 0.06
 },
 "polaroid_sx70_instant": {
  "contrast_gain": 1.18,
  "toe_strength": 0.15,
  "highlight_shoulder": 0.30,
  "global_chroma_gain": 1.08,
  "shadow_warm_cool": -0.02,
  "highlight_warm_cool": 0.04,
  "green_hue_bias": -0.06,
  "microcontrast_amount": 0.04
 },
 "lomo_lca": {
  "contrast_gain": 1.25,
  "toe_strength": 0.16,
  "highlight_shoulder": 0.10,
  "global_chroma_gain": 1.18,
  "shadow_warm_cool": -0.02,
  "highlight_warm_cool": 0.03,
  "green_hue_bias": 0.06,
  "microcontrast_amount": 0.12
 },
 "pentax_67": {
  "contrast_gain": 1.08,
  "toe_strength": 0.09,
  "highlight_shoulder": 0.24,
  "global_chroma_gain": 1.03,
  "shadow_warm_cool": 0.0,
  "highlight_warm_cool": 0.02,
  "green_hue_bias": 0.01,
  "microcontrast_amount": 0.10
 },
 "fujifilm_x100vi": {
  "contrast_gain": 1.08,
  "toe_strength": 0.08,
  "highlight_shoulder": 0.26,
  "global_chroma_gain": 1.02,
  "shadow_warm_cool": 0.0,
  "highlight_warm_cool": 0.01,
  "green_hue_bias": -0.01,
  "microcontrast_amount": 0.15
 },
 "zenit_e_ttl": {
  "contrast_gain": 0.98,
  "toe_strength": 0.05,
  "highlight_shoulder": 0.22,
  "global_chroma_gain": 1.05,
  "shadow_warm_cool": 0.02,
  "highlight_warm_cool": 0.03,
  "green_hue_bias": 0.04,
  "microcontrast_amount": 0.06
 },
 "pentax_k1000": {
  "contrast_gain": 1.10,
  "toe_strength": 0.10,
  "highlight_shoulder": 0.18,
  "global_chroma_gain": 1.04,
  "shadow_warm_cool": -0.01,
  "highlight_warm_cool": 0.01,
  "green_hue_bias": 0.02,
  "microcontrast_amount": 0.12
 },
 "zorki_4": {
  "contrast_gain": 1.04,
  "toe_strength": 0.07,
  "highlight_shoulder": 0.25,
  "global_chroma_gain": 0.99,
  "shadow_warm_cool": 0.01,
  "highlight_warm_cool": 0.03,
  "green_hue_bias": 0.02,
  "microcontrast_amount": 0.08
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
  "threshold": 0.65,
  "knee": 0.3,
  "radius_fraction": 0.015,
  "warm_shift": 0.15,
  "veil": 0.12
 },
 "ricoh_hdf_diffusion": {
  "threshold": 0.5,
  "knee": 0.35,
  "radius_fraction": 0.008,
  "broad_radius_fraction": 0.025,
  "veil": 0.08
 },
 "black_pro_mist_like": {
  "threshold": 0.55,
  "knee": 0.3,
  "radius_fraction": 0.018,
  "veil": 0.06
 },
 "vintage_veiling_flare": {
  "threshold": 0.6,
  "knee": 0.4,
  "radius_fraction": 0.05,
  "veil": 0.18
 },
 "film_halation_extra": {
  "threshold": 0.6,
  "knee": 0.25,
  "radius_fraction": 0.005,
  "red_gain": 0.2
 },
 "orton_glow": {
  "threshold": 0.45,
  "knee": 0.4,
  "radius_fraction": 0.03,
  "mix": 0.4
 },
 "none": {}
}
from .optical_registry import extend as _extend  # noqa: E402
_extend(EFFECTS)
