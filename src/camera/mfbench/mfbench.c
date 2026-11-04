/* SPDX-License-Identifier: GPL-2.0-only
 * MFBENCH.FLT module glue: CHDK headers only (their int32_t differs from
 * <stdint.h>, so the measurements live in mfbench_cam.c).
 *
 * The measurements run in their own low-priority task, like CHDK's DNG byte
 * reverser: run inside the GUI/keyboard task, a 30 s computation starved the
 * camera's other tasks and the SX510 HS powered off (first camera run,
 * 2026-11-04). The module stays loaded until that task has finished. */
#include "stdlib.h"
#include "gui.h"
#include "gui_mbox.h"
#include "simple_module.h"
#include "module_def.h"
#include "task.h"

const char *mfb_camera_main(void);

static volatile int task_running;

static void bench_task(void)
{
    mfb_camera_main();
    task_running = 0;
    ExitTask();
}

static void closed(__attribute__((unused)) unsigned btn) { }

int _run()
{
    if (task_running) return 0;
    task_running = 1;
    CreateTask("MFBench", 0x1A, 0x4000, bench_task);   /* below spytask, as the DNG reverser */
    gui_mbox_init((int) "M-Film bench",
                  (int) "Running in background, 1-2 min.\nKeep the camera on.\nDone when A/MFBENCH.TXT ends with 'done'.",
                  MBOX_FUNC_RESTORE | MBOX_TEXT_CENTER, closed);
    return 0;
}

int _module_can_unload() { return task_running == 0; }

int _module_exit_alt() { return 0; }

libsimple_sym _librun = { { 0, 0, _module_can_unload, _module_exit_alt, _run } };

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
