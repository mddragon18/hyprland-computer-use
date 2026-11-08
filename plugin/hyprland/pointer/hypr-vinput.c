/*
 * hypr-vinput — inject pointer events through zwlr_virtual_pointer_v1.
 *
 * A Wayland-native replacement for XTEST/uinput: no root, no /dev/uinput, no
 * XWayland. Built locally from source (see the Makefile beside this file).
 *
 *   hypr-vinput probe                    (connect + check protocol, no input)
 *   hypr-vinput warp <x> <y> [<x_extent> <y_extent>]
 *   hypr-vinput click <button> [<hold_ms>]
 *   hypr-vinput press <button> | release <button>
 *   hypr-vinput hitat <x> <y> <x_extent> <y_extent> [<button>]
 *   hypr-vinput drag <x1> <y1> <x2> <y2> <x_extent> <y_extent> [<button>]
 *   hypr-vinput scrollat <x> <y> <x_extent> <y_extent> <amount>
 *   hypr-vinput scroll <amount>          (positive scrolls down)
 *
 * <button> is left|right|middle or a raw evdev button code.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>

#include "wlr-virtual-pointer-unstable-v1-client-protocol.h"

/* wl_fixed_t is 24.8 fixed point (not 16.16). */
#define FIXED(d) ((int32_t)((double)(d) * 256.0))

static struct zwlr_virtual_pointer_manager_v1 *mgr = NULL;

static void registry_global(void *data, struct wl_registry *registry, uint32_t name,
                            const char *interface, uint32_t version) {
    (void)data;
    if (strcmp(interface, zwlr_virtual_pointer_manager_v1_interface.name) == 0) {
        mgr = wl_registry_bind(registry, name, &zwlr_virtual_pointer_manager_v1_interface,
                               version < 1u ? 1u : version);
    }
}

static void registry_global_remove(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_global_remove,
};

static uint32_t now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}

static uint32_t parse_button(const char *s) {
    if (!strcmp(s, "left")) return 0x110;
    if (!strcmp(s, "right")) return 0x111;
    if (!strcmp(s, "middle")) return 0x112;
    return (uint32_t)strtoul(s, NULL, 0);
}

/* Absolute motion alone does not hand pointer focus to the surface, so Hyprland
 * only re-focuses on relative motion. A 1 px jitter each way makes the following
 * button/axis event land on the window under the pointer. */
static void settle(struct zwlr_virtual_pointer_v1 *ptr, unsigned x, unsigned y,
                   unsigned ex, unsigned ey) {
    zwlr_virtual_pointer_v1_motion_absolute(ptr, now_ms(), x, y, ex, ey);
    zwlr_virtual_pointer_v1_frame(ptr);
    zwlr_virtual_pointer_v1_motion(ptr, now_ms(), FIXED(1), 0);
    zwlr_virtual_pointer_v1_frame(ptr);
    usleep(20000);
    zwlr_virtual_pointer_v1_motion(ptr, now_ms(), FIXED(-1), 0);
    zwlr_virtual_pointer_v1_frame(ptr);
    usleep(20000);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr,
                "usage: hypr-vinput warp|click|press|release|hitat|drag|scrollat|scroll ...\n");
        return 2;
    }

    struct wl_display *dpy = wl_display_connect(NULL);
    if (!dpy) {
        fprintf(stderr, "hypr-vinput: cannot connect to wayland compositor\n");
        return 1;
    }
    struct wl_registry *registry = wl_display_get_registry(dpy);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    wl_display_roundtrip(dpy);

    if (!mgr) {
        fprintf(stderr, "hypr-vinput: compositor does not advertise %s\n",
                zwlr_virtual_pointer_manager_v1_interface.name);
        return 3;
    }

    struct zwlr_virtual_pointer_v1 *ptr =
        zwlr_virtual_pointer_manager_v1_create_virtual_pointer(mgr, NULL);

    const char *cmd = argv[1];
    uint32_t t = now_ms();

    if (!strcmp(cmd, "probe")) {
        printf("ok %s\n", zwlr_virtual_pointer_manager_v1_interface.name);
    } else if (!strcmp(cmd, "warp") && argc >= 4) {
        unsigned x = strtoul(argv[2], NULL, 0), y = strtoul(argv[3], NULL, 0);
        unsigned ex = argc >= 6 ? strtoul(argv[4], NULL, 0) : 2560;
        unsigned ey = argc >= 6 ? strtoul(argv[5], NULL, 0) : 1440;
        zwlr_virtual_pointer_v1_motion_absolute(ptr, t, x, y, ex, ey);
        zwlr_virtual_pointer_v1_frame(ptr);
    } else if (!strcmp(cmd, "click") && argc >= 3) {
        uint32_t button = parse_button(argv[2]);
        unsigned hold_ms = argc >= 4 ? (unsigned)strtoul(argv[3], NULL, 0) : 40u;
        zwlr_virtual_pointer_v1_button(ptr, t, button, 1);
        zwlr_virtual_pointer_v1_frame(ptr);
        usleep(hold_ms * 1000u);
        zwlr_virtual_pointer_v1_button(ptr, now_ms(), button, 0);
        zwlr_virtual_pointer_v1_frame(ptr);
    } else if ((!strcmp(cmd, "press") || !strcmp(cmd, "release")) && argc >= 3) {
        uint32_t button = parse_button(argv[2]);
        zwlr_virtual_pointer_v1_button(ptr, t, button, cmd[0] == 'p' ? 1 : 0);
        zwlr_virtual_pointer_v1_frame(ptr);
    } else if (!strcmp(cmd, "hitat") && argc >= 6) {
        unsigned x = strtoul(argv[2], NULL, 0), y = strtoul(argv[3], NULL, 0);
        unsigned ex = strtoul(argv[4], NULL, 0), ey = strtoul(argv[5], NULL, 0);
        uint32_t button = argc >= 7 ? parse_button(argv[6]) : 0x110;
        settle(ptr, x, y, ex, ey);
        zwlr_virtual_pointer_v1_button(ptr, now_ms(), button, 1);
        zwlr_virtual_pointer_v1_frame(ptr);
        usleep(40000);
        zwlr_virtual_pointer_v1_button(ptr, now_ms(), button, 0);
        zwlr_virtual_pointer_v1_frame(ptr);
    } else if (!strcmp(cmd, "drag") && argc >= 8) {
        unsigned x = strtoul(argv[2], NULL, 0), y = strtoul(argv[3], NULL, 0);
        unsigned tx = strtoul(argv[4], NULL, 0), ty = strtoul(argv[5], NULL, 0);
        unsigned ex = strtoul(argv[6], NULL, 0), ey = strtoul(argv[7], NULL, 0);
        uint32_t button = argc >= 9 ? parse_button(argv[8]) : 0x110;
        settle(ptr, x, y, ex, ey);
        zwlr_virtual_pointer_v1_button(ptr, now_ms(), button, 1);
        zwlr_virtual_pointer_v1_frame(ptr);
        /* Move in steps: one teleport is often dropped by text selection and
         * drag-and-drop clients that expect motion in between. */
        for (int i = 1; i <= 8; i++) {
            long ix = (long)x + ((long)tx - (long)x) * i / 8;
            long iy = (long)y + ((long)ty - (long)y) * i / 8;
            zwlr_virtual_pointer_v1_motion_absolute(ptr, now_ms(), (unsigned)ix,
                                                    (unsigned)iy, ex, ey);
            zwlr_virtual_pointer_v1_frame(ptr);
            usleep(12000);
        }
        usleep(40000);
        zwlr_virtual_pointer_v1_button(ptr, now_ms(), button, 0);
        zwlr_virtual_pointer_v1_frame(ptr);
    } else if (!strcmp(cmd, "scrollat") && argc >= 7) {
        unsigned x = strtoul(argv[2], NULL, 0), y = strtoul(argv[3], NULL, 0);
        unsigned ex = strtoul(argv[4], NULL, 0), ey = strtoul(argv[5], NULL, 0);
        double amount = strtod(argv[6], NULL);
        settle(ptr, x, y, ex, ey);
        /* wl_pointer: VERTICAL = 0. A wheel notch is 10.0 axis units and the
         * source is WHEEL (0); axis_stop is only meaningful for finger and
         * continuous sources. */
        zwlr_virtual_pointer_v1_axis_source(ptr, 0 /* WHEEL */);
        zwlr_virtual_pointer_v1_axis(ptr, now_ms(), 0 /* VERTICAL */, FIXED(amount * 10.0));
        zwlr_virtual_pointer_v1_axis_discrete(ptr, now_ms(), 0, FIXED(amount * 10.0), (int32_t)amount);
        zwlr_virtual_pointer_v1_frame(ptr);
    } else if (!strcmp(cmd, "scroll") && argc >= 3) {
        double amount = strtod(argv[2], NULL);
        zwlr_virtual_pointer_v1_axis_source(ptr, 0 /* WHEEL */);
        zwlr_virtual_pointer_v1_axis(ptr, t, 0 /* VERTICAL */, FIXED(amount * 10.0));
        zwlr_virtual_pointer_v1_axis_discrete(ptr, t, 0, FIXED(amount * 10.0), (int32_t)amount);
        zwlr_virtual_pointer_v1_frame(ptr);
    } else {
        fprintf(stderr, "hypr-vinput: unsupported command '%s'\n", cmd);
        zwlr_virtual_pointer_v1_destroy(ptr);
        wl_display_disconnect(dpy);
        return 4;
    }

    if (wl_display_roundtrip(dpy) < 0) {
        fprintf(stderr, "hypr-vinput: compositor rejected the event batch\n");
        zwlr_virtual_pointer_v1_destroy(ptr);
        wl_display_disconnect(dpy);
        return 5;
    }
    /* Axis events are delivered to the focused surface asynchronously; give the
     * compositor a second roundtrip before the virtual device disappears. */
    usleep(60000);
    wl_display_roundtrip(dpy);
    zwlr_virtual_pointer_v1_destroy(ptr);
    wl_display_disconnect(dpy);
    return 0;
}
