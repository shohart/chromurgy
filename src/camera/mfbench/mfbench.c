/* SPDX-License-Identifier: GPL-2.0-only
 * MFBENCH.FLT module glue: CHDK headers only (their int32_t differs from
 * <stdint.h>, so the measurements live in mfbench_cam.c). */
#include "stdlib.h"
#include "gui.h"
#include "gui_mbox.h"
#include "simple_module.h"
#include "module_def.h"

const char *mfb_camera_main(void);
static void finish(unsigned btn);

int basic_module_init()
{
    const char *msg = mfb_camera_main();
    gui_mbox_init((int) "M-Film bench", (int) msg, MBOX_FUNC_RESTORE | MBOX_TEXT_CENTER, finish);
    return 1;
}

#include "simple_module.c"

static void finish(__attribute__((unused)) unsigned btn) { running = 0; }

ModuleInfo _module_info = {
    MODULEINFO_V1_MAGICNUM,
    sizeof(ModuleInfo),
    SIMPLE_MODULE_VERSION,
    ANY_CHDK_BRANCH, 0, OPT_ARCHITECTURE,
    ANY_PLATFORM_ALLOWED,
    (int32_t) "M-Film bench",
    MTYPE_TOOL,
    &_librun.base,
    ANY_VERSION, ANY_VERSION, ANY_VERSION, ANY_VERSION,
    0,
};
