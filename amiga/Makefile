AMIGA_CC ?= m68k-amigaos-gcc
CFLAGS = -std=c99 -m68000 -Os -fomit-frame-pointer -fno-strict-aliasing -Wall -Wextra -Werror
TARGET = ../src/main/python/emu68hatcher/data/local_packages/System/C/Hatcher-UAE-ScreenMode

.PHONY: all
all: $(TARGET)

$(TARGET): uae-screenmode.c
	mkdir -p $(dir $@)
	$(AMIGA_CC) $(CFLAGS) $< -o $@ -noixemul -s
