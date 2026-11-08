# Build the Wayland pointer helper. The binary is generated, never committed.
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
PKG_CONFIG ?= pkg-config

WAYLAND_CFLAGS := $(shell $(PKG_CONFIG) --cflags wayland-client 2>/dev/null)
WAYLAND_LIBS := $(shell $(PKG_CONFIG) --libs wayland-client 2>/dev/null)

BIN := bin/hypr-vinput
SRC := hypr-vinput.c wlr-virtual-pointer-code.c
HDR := wlr-virtual-pointer-unstable-v1-client-protocol.h

all: $(BIN)

$(BIN): $(SRC) $(HDR)
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(WAYLAND_CFLAGS) -o $@ $(SRC) $(WAYLAND_LIBS)

clean:
	rm -rf bin

.PHONY: all clean
