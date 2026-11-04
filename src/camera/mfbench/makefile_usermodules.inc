# SPDX-License-Identifier: GPL-2.0-only
# Hooked into CHDK's modules/Makefile (its "-include makefile_usermodules.inc")
# by tools/build_chdk.sh: adds MFBENCH.FLT, built from the shared film core.
MF_ROOT ?= $(error MF_ROOT not set)
MF_CORE = $(MF_ROOT)/src/shared/film_core
MF_BENCH = $(MF_ROOT)/src/camera/mfbench
MF_INC = -I$(MF_CORE)/include -I$(MF_BENCH)

FLTS += $Omfbench.flt
$Omfbench.flt: $Omfbench.o $Omfbench_cam.o $Omfbench_run.o $Omf_fx.o $Omf_sha256.o $Omf_seed.o

# mfbench.c: CHDK headers only; the rest: GCC's stdint.h + CHDK's libc headers
$Omfbench.o: $(MF_BENCH)/mfbench.c
	@echo $< '->' $@
	$(CC) $(CFLAGS) -c -o $@ $<
$Omfbench_cam.o: $(MF_BENCH)/mfbench_cam.c $(MF_BENCH)/mfbench.h
	@echo $< '->' $@
	$(CC) $(CFLAGS) $(MF_INC) -c -o $@ $<
# CHDK builds modules as Thumb; the film core is built as ARM code (-marm, as
# tools/arm_check.sh checks it): Thumb-1 would need libgcc helpers CHDK does
# not export (64-bit multiply/shift, clz) and is slower. ARMv5TE interworks.
$Omfbench_run.o: $(MF_BENCH)/mfbench_run.c $(MF_BENCH)/mfbench.h
	@echo $< '->' $@
	$(CC) $(CFLAGS) -marm $(MF_INC) -c -o $@ $<
$Omf_%.o: $(MF_CORE)/src/mf_%.c
	@echo $< '->' $@
	$(CC) $(CFLAGS) -marm $(MF_INC) -DMF_CORE_SOURCE_HASH=\"camera\" -c -o $@ $<
