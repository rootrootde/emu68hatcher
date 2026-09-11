#include <exec/types.h>
#include <graphics/displayinfo.h>
#include <graphics/gfxbase.h>
#include <proto/exec.h>
#include <proto/graphics.h>
#include <stdio.h>
#include <string.h>

#define SAVED_PREFS "SYS:Prefs/Env-Archive/Sys/ScreenMode.prefs"
#define UAE_PREFS SAVED_PREFS ".UAE"
#define ACTIVE_PREFS "ENV:Sys/ScreenMode.prefs"
#define PREFS_LIMIT 4096

struct GfxBase *GfxBase;

struct Prefs {
    UBYTE data[PREFS_LIMIT];
    ULONG size;
    UBYTE *scrm;
};

struct Mode {
    ULONG id;
    UWORD width, height, depth;
};

static ULONG read32(const UBYTE *p)
{
    return ((ULONG)p[0] << 24) | ((ULONG)p[1] << 16) | ((ULONG)p[2] << 8) | p[3];
}

static UWORD read16(const UBYTE *p)
{
    return ((UWORD)p[0] << 8) | p[1];
}

static void write16(UBYTE *p, UWORD value)
{
    p[0] = (UBYTE)(value >> 8);
    p[1] = (UBYTE)value;
}

static void write32(UBYTE *p, ULONG value)
{
    write16(p, (UWORD)(value >> 16));
    write16(p + 2, (UWORD)value);
}

static int load_prefs(const char *path, struct Prefs *prefs)
{
    ULONG end, offset, size;
    FILE *file = fopen(path, "rb");
    int valid;
    if (!file)
        return 0;
    prefs->size = fread(prefs->data, 1, sizeof(prefs->data), file);
    valid = !ferror(file) && fgetc(file) == EOF;
    fclose(file);
    if (!valid || prefs->size < 12 || memcmp(prefs->data, "FORM", 4) ||
        memcmp(prefs->data + 8, "PREF", 4))
        return 0;
    size = read32(prefs->data + 4);
    if (size < 4 || size > prefs->size - 8)
        return 0;
    end = size + 8;
    for (offset = 12; offset + 8 <= end; offset += size + (size & 1)) {
        const UBYTE *header = prefs->data + offset;
        size = read32(header + 4);
        offset += 8;
        if (size > end - offset || (size & 1) > end - offset - size)
            return 0;
        if (!memcmp(header, "SCRM", 4)) {
            if (size < 28)
                return 0;
            prefs->scrm = prefs->data + offset;
            return 1;
        }
    }
    return 0;
}

static int query_mode(ULONG id, struct DisplayInfo *display, struct DimensionInfo *dims)
{
    /* the SDK's const register argument miscompiles NULL handles with GCC 15. */
    DisplayInfoHandle handle = FindDisplayInfo(id);
    if (!handle)
        return 0;
    memset(display, 0, sizeof(*display));
    memset(dims, 0, sizeof(*dims));
    return GetDisplayInfoData(handle, (UBYTE *)display, sizeof(*display), DTAG_DISP, id) &&
           GetDisplayInfoData(handle, (UBYTE *)dims, sizeof(*dims), DTAG_DIMS, id) &&
           !display->NotAvailable && (display->PropertyFlags & DIPF_IS_WB);
}

static int valid_saved_mode(const struct Prefs *prefs)
{
    struct DisplayInfo display;
    struct DimensionInfo dims;
    UWORD width = read16(prefs->scrm + 20), height = read16(prefs->scrm + 22);
    UWORD depth = read16(prefs->scrm + 24);
    if (!query_mode(read32(prefs->scrm + 16), &display, &dims))
        return 0;
    return depth && depth <= dims.MaxDepth &&
           (width == 0xffff || (width >= dims.MinRasterWidth && width <= dims.MaxRasterWidth)) &&
           (height == 0xffff || (height >= dims.MinRasterHeight && height <= dims.MaxRasterHeight));
}

static ULONG distance(UWORD a, UWORD b)
{
    return a > b ? a - b : b - a;
}

static int choose_mode(const struct Prefs *prefs, struct Mode *best)
{
    ULONG id = (ULONG)INVALID_ID, best_score = ~0UL;
    UWORD wanted_width = read16(prefs->scrm + 20);
    UWORD wanted_height = read16(prefs->scrm + 22);
    UWORD wanted_depth = read16(prefs->scrm + 24);
    if (!wanted_width || !wanted_height || !wanted_depth || wanted_depth > 32 ||
        wanted_width == 0xffff || wanted_height == 0xffff)
        return 0;
    best->id = (ULONG)INVALID_ID;
    while ((id = NextDisplayInfo(id)) != (ULONG)INVALID_ID) {
        struct DisplayInfo display;
        struct DimensionInfo dims;
        struct NameInfo name = {0};
        LONG width, height;
        UWORD depth;
        ULONG score;
        /* P96's UAE modes need not carry DIPF_IS_FOREIGN. */
        if (!query_mode(id, &display, &dims) ||
            !GetDisplayInfoData(FindDisplayInfo(id), (UBYTE *)&name, sizeof(name), DTAG_NAME, id) ||
            strncmp((char *)name.Name, "UAE:", 4))
            continue;
        width = (LONG)dims.Nominal.MaxX - dims.Nominal.MinX + 1;
        height = (LONG)dims.Nominal.MaxY - dims.Nominal.MinY + 1;
        if (width < 320 || height < 200 || width > 65535 || height > 65535 ||
            !dims.MaxDepth)
            continue;
        depth = wanted_depth < dims.MaxDepth ? wanted_depth : dims.MaxDepth;
        /* prefer the requested size, then the closest supported colour depth. */
        score = (distance((UWORD)width, wanted_width) +
                 distance((UWORD)height, wanted_height)) * 256 +
                distance(depth, wanted_depth);
        if (score < best_score) {
            best_score = score;
            best->id = id;
            best->width = (UWORD)width;
            best->height = (UWORD)height;
            best->depth = depth;
        }
    }
    return best->id != (ULONG)INVALID_ID;
}

static int write_active(const struct Prefs *prefs)
{
    FILE *file = fopen(ACTIVE_PREFS, "wb");
    int ok;
    if (!file)
        return 0;
    ok = fwrite(prefs->data, 1, prefs->size, file) == prefs->size;
    if (fclose(file))
        ok = 0;
    return ok;
}

int main(void)
{
    static struct Prefs wanted, saved;
    struct Mode mode;
    int result = 10;
    if (!load_prefs(UAE_PREFS, &wanted)) {
        puts("Hatcher: cannot read UAE screen preferences");
        return 10;
    }
    GfxBase = (struct GfxBase *)OpenLibrary((CONST_STRPTR)"graphics.library", 39);
    if (!GfxBase)
        return 10;
    /* VideoCore IDs can collide with unrelated UAE modes. */
    if (load_prefs(SAVED_PREFS, &saved) &&
        read32(saved.scrm + 16) != read32(wanted.scrm + 16) && valid_saved_mode(&saved)) {
        result = write_active(&saved) ? 0 : 10;
    } else if (choose_mode(&wanted, &mode)) {
        write32(wanted.scrm + 16, mode.id);
        write16(wanted.scrm + 20, mode.width);
        write16(wanted.scrm + 22, mode.height);
        write16(wanted.scrm + 24, mode.depth);
        /* only ENV changes; the saved VideoCore prefs still belong to PiStorm. */
        if (write_active(&wanted)) {
            printf("Hatcher: UAE screen %ux%u, depth %u (0x%08lx)\n",
                   mode.width, mode.height, mode.depth, (unsigned long)mode.id);
            result = 0;
        }
    } else {
        puts("Hatcher: no usable UAE screen mode found");
    }
    if (result)
        puts("Hatcher: could not set UAE screen preferences");
    CloseLibrary((struct Library *)GfxBase);
    return result;
}
