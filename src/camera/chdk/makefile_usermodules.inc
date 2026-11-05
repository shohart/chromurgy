# SPDX-License-Identifier: GPL-2.0-only
# Hooked into CHDK release-1_6 modules/Makefile by tools/build_chdk16.sh: links
# the camera's developer (src/camera/dev) and the fixed-point film core into
# lua.flt, next to the M-Film Lua functions (src/camera/chdk/mfilm_lua.c).
MF_ROOT ?= $(error MF_ROOT not set)
MF_CORE = $(MF_ROOT)/src/shared/film_core
MF_DEV = $(MF_ROOT)/src/camera/dev
MF_INC = -I$(MF_CORE)/include -I$(MF_DEV)

MF_OBJS = $Omfdev_cam.o $Omfd_develop.o $Omfd_dng.o $Omfd_jpeg.o $Omfd_view.o $Omfd_files.o $Omf_fx.o $Omf_seed.o $Omf_sha256.o
$Olua.flt: $(MF_OBJS)

# mfdev_cam.c: CHDK libc headers + GCC stdint (Thumb like the module)
$Omfdev_cam.o: $(MF_DEV)/mfdev_cam.c $(MF_DEV)/mfd.h
	@echo $< '->' $@
	$(CC) $(CFLAGS) $(MF_INC) -c -o $@ $<
# the developer and the film core as ARM code (-marm): Thumb-1 would need libgcc
# helpers CHDK does not export (64-bit multiply/shift, clz); ARMv5TE interworks
$Omfd_%.o: $(MF_DEV)/mfd_%.c $(MF_DEV)/mfd.h
	@echo $< '->' $@
	$(CC) $(CFLAGS) -marm $(MF_INC) -c -o $@ $<
$Omf_%.o: $(MF_CORE)/src/mf_%.c
	@echo $< '->' $@
	$(CC) $(CFLAGS) -marm $(MF_INC) -DMF_CORE_SOURCE_HASH=\"camera\" -c -o $@ $<
