/* SPDX-License-Identifier: GPL-2.0-only
 *
 * The film stage in fixed point, streamed by rows: the camera variant of
 * mf_develop_frame (same stages, order and definitions, parity-tested).
 *
 * Camera constraints (SX510 HS, DIGIC 4+, ARM946E-S, armv5te, no FPU, CHDK
 * module): no float, no libm, no heap; the only runtime helpers used are the
 * integer divides CHDK exports to modules, and none of them per pixel.
 * tools/arm_check.sh enforces this on the compiled object.
 *
 * Formats: input linear Q15 (32768 = 1.0); exposure/glow in Q15 up to 16.0;
 * gains Q16; Cineon grid position Q16; tetrahedral weights Q12; display
 * 0..65535; glow interpolation weights Q10.
 */
#include "mf_core.h"

#include <string.h>

#define PRINT_W 720
#define PRINT_H 480
#define ONE_Q15 32768
#define CLIP_Q15 (16 * ONE_Q15)
#define LUMA_R 871                      /* fos_dev.c LUMA_I, /4096 */
#define LUMA_G 2929
#define LUMA_B 296
#define LOG2_KEY_Q16 (-208694)          /* log2(0.11) */
#define EV_MIN_Q16 (-2 * 65536)
#define EV_MAX_Q16 (229376)             /* 3.5 */
#define SLIDE_EV_Q16 65536
#define CIN_GAIN_Q16 64828              /* 1 - 0.0108 (Cineon black) */
#define CIN_BLACK_Q22 45298             /* 0.0108 * 2^22 */
#define CIN_P0_Q16 1404251              /* 32 * 685 / 1023 */
#define CIN_PB_Q16 185134               /* 32 * 300 * log10(2) / 1023, per stop */
#define VIG_Q16 3932                    /* 0.06 */

/* log2(1 + i/256) in Q16, i = 0..256 (generated) */
static const int32_t LOG2_T[257] = {
    0, 369, 736, 1102, 1466, 1829, 2190, 2551,
    2909, 3267, 3623, 3978, 4331, 4683, 5034, 5384,
    5732, 6079, 6425, 6769, 7112, 7454, 7795, 8134,
    8473, 8810, 9146, 9480, 9814, 10146, 10477, 10807,
    11136, 11464, 11791, 12116, 12440, 12764, 13086, 13407,
    13727, 14046, 14363, 14680, 14996, 15310, 15624, 15937,
    16248, 16559, 16868, 17177, 17484, 17791, 18096, 18401,
    18704, 19007, 19308, 19609, 19909, 20207, 20505, 20802,
    21098, 21393, 21687, 21980, 22272, 22564, 22854, 23144,
    23433, 23720, 24007, 24293, 24579, 24863, 25146, 25429,
    25711, 25992, 26272, 26551, 26830, 27108, 27384, 27660,
    27936, 28210, 28484, 28757, 29029, 29300, 29571, 29840,
    30109, 30378, 30645, 30912, 31178, 31443, 31707, 31971,
    32234, 32496, 32758, 33019, 33279, 33538, 33797, 34055,
    34312, 34569, 34825, 35080, 35334, 35588, 35841, 36094,
    36346, 36597, 36847, 37097, 37346, 37595, 37842, 38090,
    38336, 38582, 38827, 39072, 39316, 39559, 39802, 40044,
    40286, 40527, 40767, 41006, 41246, 41484, 41722, 41959,
    42196, 42432, 42667, 42902, 43137, 43370, 43603, 43836,
    44068, 44300, 44530, 44761, 44990, 45220, 45448, 45676,
    45904, 46131, 46357, 46583, 46809, 47034, 47258, 47482,
    47705, 47928, 48150, 48372, 48593, 48813, 49034, 49253,
    49472, 49691, 49909, 50127, 50344, 50560, 50776, 50992,
    51207, 51422, 51636, 51850, 52063, 52276, 52488, 52700,
    52911, 53122, 53332, 53542, 53751, 53960, 54169, 54377,
    54584, 54791, 54998, 55204, 55410, 55615, 55820, 56025,
    56229, 56432, 56635, 56838, 57040, 57242, 57443, 57644,
    57845, 58045, 58245, 58444, 58643, 58841, 59039, 59237,
    59434, 59631, 59827, 60023, 60219, 60414, 60609, 60803,
    60997, 61190, 61384, 61576, 61769, 61961, 62152, 62343,
    62534, 62725, 62915, 63104, 63294, 63483, 63671, 63859,
    64047, 64234, 64421, 64608, 64794, 64980, 65166, 65351,
    65536
};

/* 2^(i/256) in Q30, i = 0..256 (generated) */
static const uint32_t EXP2_T[257] = {
    1073741824u, 1076653033u, 1079572136u, 1082499153u, 1085434106u, 1088377016u,
    1091327906u, 1094286796u, 1097253708u, 1100228665u, 1103211687u, 1106202798u,
    1109202018u, 1112209370u, 1115224875u, 1118248556u, 1121280436u, 1124320536u,
    1127368878u, 1130425485u, 1133490379u, 1136563583u, 1139645120u, 1142735011u,
    1145833280u, 1148939949u, 1152055042u, 1155178580u, 1158310587u, 1161451085u,
    1164600099u, 1167757650u, 1170923762u, 1174098458u, 1177281762u, 1180473697u,
    1183674286u, 1186883552u, 1190101520u, 1193328213u, 1196563654u, 1199807867u,
    1203060876u, 1206322705u, 1209593378u, 1212872918u, 1216161350u, 1219458698u,
    1222764986u, 1226080238u, 1229404479u, 1232737732u, 1236080024u, 1239431376u,
    1242791816u, 1246161366u, 1249540052u, 1252927899u, 1256324931u, 1259731174u,
    1263146652u, 1266571390u, 1270005413u, 1273448747u, 1276901417u, 1280363448u,
    1283834865u, 1287315695u, 1290805962u, 1294305692u, 1297814910u, 1301333643u,
    1304861917u, 1308399756u, 1311947188u, 1315504238u, 1319070932u, 1322647296u,
    1326233356u, 1329829140u, 1333434672u, 1337049980u, 1340675091u, 1344310030u,
    1347954824u, 1351609500u, 1355274085u, 1358948606u, 1362633090u, 1366327563u,
    1370032052u, 1373746586u, 1377471191u, 1381205894u, 1384950723u, 1388705706u,
    1392470869u, 1396246240u, 1400031848u, 1403827719u, 1407633882u, 1411450365u,
    1415277195u, 1419114401u, 1422962010u, 1426820052u, 1430688553u, 1434567544u,
    1438457051u, 1442357104u, 1446267730u, 1450188960u, 1454120821u, 1458063343u,
    1462016553u, 1465980482u, 1469955159u, 1473940611u, 1477936870u, 1481943963u,
    1485961921u, 1489990772u, 1494030547u, 1498081275u, 1502142985u, 1506215708u,
    1510299473u, 1514394310u, 1518500250u, 1522617322u, 1526745556u, 1530884983u,
    1535035634u, 1539197537u, 1543370725u, 1547555228u, 1551751076u, 1555958300u,
    1560176931u, 1564406999u, 1568648537u, 1572901575u, 1577166143u, 1581442275u,
    1585730000u, 1590029350u, 1594340357u, 1598663052u, 1602997467u, 1607343634u,
    1611701585u, 1616071351u, 1620452965u, 1624846459u, 1629251865u, 1633669214u,
    1638098541u, 1642539877u, 1646993254u, 1651458706u, 1655936265u, 1660425963u,
    1664927835u, 1669441912u, 1673968228u, 1678506817u, 1683057710u, 1687620943u,
    1692196547u, 1696784557u, 1701385007u, 1705997930u, 1710623359u, 1715261330u,
    1719911875u, 1724575029u, 1729250827u, 1733939301u, 1738640488u, 1743354420u,
    1748081133u, 1752820662u, 1757573041u, 1762338305u, 1767116489u, 1771907628u,
    1776711757u, 1781528911u, 1786359126u, 1791202437u, 1796058879u, 1800928489u,
    1805811301u, 1810707353u, 1815616678u, 1820539314u, 1825475297u, 1830424663u,
    1835387448u, 1840363688u, 1845353420u, 1850356681u, 1855373507u, 1860403934u,
    1865448001u, 1870505744u, 1875577199u, 1880662405u, 1885761398u, 1890874216u,
    1896000896u, 1901141476u, 1906295993u, 1911464486u, 1916646992u, 1921843549u,
    1927054196u, 1932278970u, 1937517909u, 1942771053u, 1948038440u, 1953320108u,
    1958616096u, 1963926443u, 1969251188u, 1974590370u, 1979944027u, 1985312200u,
    1990694927u, 1996092249u, 2001504204u, 2006930832u, 2012372174u, 2017828268u,
    2023299156u, 2028784876u, 2034285470u, 2039800978u, 2045331439u, 2050876895u,
    2056437387u, 2062012954u, 2067603638u, 2073209480u, 2078830522u, 2084466803u,
    2090118366u, 2095785251u, 2101467502u, 2107165158u, 2112878262u, 2118606857u,
    2124350982u, 2130110682u, 2135885998u, 2141676973u, 2147483648u
};

enum { PHASE_SCAN, PHASE_GLOW, PHASE_RENDER };

struct mf_fx {
    mf_fx_look L;
    const uint16_t *table;
    uint64_t seed;
    int w, h, phase, next_row;
    int32_t snum, sden;                 /* print scale s = snum / sden */
    /* pass 1: scanner */
    int pw, ph, ncols;                  /* print size, sample columns (every 4th print px) */
    int py, sy0, sy1;                   /* current sample row and its frame rows */
    int64_t log_sum;
    int32_t nsamples;
    int32_t ev_q16;
    int32_t gain_q16[3];
    uint16_t *sx0, *sx1;                /* [ncols] frame columns of each sample */
    uint32_t *sacc;                     /* [ncols * 3] channel sums of the current sample row */
    /* pass 2: glow grid */
    int gw, gh;
    uint16_t *cell_x;                   /* [w] grid column of frame column x */
    uint16_t *cnt_x, *cnt_y;            /* [gw], [gh] frame px per grid column / row */
    int32_t *grid;                      /* [gw * gh] */
    int32_t *gtmp;                      /* [max(gw, gh)] */
    /* pass 3: per-column constants */
    uint16_t *gx, *gfx;                 /* [w] glow column and weight (Q10) */
    uint16_t *vig_x;                    /* [w] 0.06 tx^2 in Q16 */
};

static uint32_t clz32(uint32_t x)
{
#if defined(__GNUC__)
    return x ? (uint32_t) __builtin_clz(x) : 32;
#else
    uint32_t n = 0;
    while (!(x & 0x80000000u)) { x <<= 1; n++; }
    return n;
#endif
}

int32_t mf_fx_log2_q16(uint32_t x)
{
    if (!x) return INT32_MIN;
    uint32_t n = 31 - clz32(x);
    uint32_t m = x << (31 - n);                     /* 1.xxx with the top bit at 31 */
    uint32_t idx = (m >> 23) & 0xFF, rem = (m >> 7) & 0xFFFF;
    int32_t t0 = LOG2_T[idx], t1 = LOG2_T[idx + 1];
    return (int32_t) (n << 16) + t0 + (((t1 - t0) * (int32_t) rem) >> 16);
}

uint32_t mf_fx_exp2_q16(int32_t q)
{
    int32_t ip = q >> 16;                           /* floor */
    uint32_t fp = (uint32_t) q & 0xFFFF;
    uint32_t idx = fp >> 8, rem = fp & 0xFF;
    uint32_t e0 = EXP2_T[idx], e1 = EXP2_T[idx + 1];
    uint32_t m = e0 + (((e1 - e0) * rem) >> 8);                     /* Q30, 1..2 */
    int sh = 30 - 16 - ip;                          /* to Q16 */
    if (sh <= 0) return ip > 15 ? 0xFFFFFFFFu : m << -sh;
    if (sh >= 32) return 0;
    return (m + (1u << (sh - 1))) >> sh;
}

/* floor(a * b / c) for non-negative 32-bit a, b and positive c: 64/32 by shift-subtract */
static uint32_t muldiv(uint32_t a, uint32_t b, uint32_t c)
{
    uint64_t n = (uint64_t) a * b, q = 0, r = 0;
    for (int i = 63; i >= 0; i--)
    {
        r = (r << 1) | ((n >> 63) & 1);
        n <<= 1;
        q <<= 1;
        if (r >= c) { r -= c; q |= 1; }
    }
    return (uint32_t) q;
}

static int64_t sdiv64(int64_t n, uint32_t d)
{
    uint64_t u = n < 0 ? (uint64_t) -n : (uint64_t) n, q = 0, r = 0;
    for (int i = 63; i >= 0; i--)
    {
        r = (r << 1) | ((u >> 63) & 1);
        u <<= 1;
        q <<= 1;
        if (r >= d) { r -= d; q |= 1; }
    }
    return n < 0 ? -(int64_t) q : (int64_t) q;
}

static size_t align8(size_t n) { return (n + 7) & ~(size_t) 7; }

static void scale_of(int w, int h, int32_t *snum, int32_t *sden)
{
    if ((int64_t) w * PRINT_H >= (int64_t) h * PRINT_W) { *snum = w; *sden = PRINT_W; }
    else { *snum = h; *sden = PRINT_H; }
}

static void grid_size(int w, int h, int32_t snum, int32_t sden, int *gw, int *gh)
{
    /* ceil(w / cell), cell = 4 s */
    *gw = (int) (((uint32_t) w * (uint32_t) sden + 4u * (uint32_t) snum - 1) / (4u * (uint32_t) snum));
    *gh = (int) (((uint32_t) h * (uint32_t) sden + 4u * (uint32_t) snum - 1) / (4u * (uint32_t) snum));
    if (*gw < 2) *gw = 2;
    if (*gh < 2) *gh = 2;
}

static int print_cols(int w, int32_t snum, int32_t sden)
{
    return (int) ((2u * (uint32_t) w * (uint32_t) sden + (uint32_t) snum) / (2u * (uint32_t) snum));
}

size_t mf_fx_ctx_size(int w, int h)
{
    if (w < 2 || h < 2 || w > 8192 || h > 8192) return 0;
    int32_t snum, sden;
    scale_of(w, h, &snum, &sden);
    int gw, gh, pw = print_cols(w, snum, sden);
    grid_size(w, h, snum, sden, &gw, &gh);
    int ncols = (pw + 3) / 4;
    size_t n = align8(sizeof(struct mf_fx));
    n += align8(sizeof(uint16_t) * (size_t) ncols) * 2 + align8(sizeof(uint32_t) * 3 * (size_t) ncols);
    n += align8(sizeof(uint16_t) * (size_t) w) * 4;                         /* cell_x, gx, gfx, vig_x */
    n += align8(sizeof(uint16_t) * (size_t) gw) + align8(sizeof(uint16_t) * (size_t) gh);
    n += align8(sizeof(int32_t) * (size_t) gw * gh) + align8(sizeof(int32_t) * (size_t) (gw > gh ? gw : gh));
    return n;
}

static void *take(uint8_t **p, size_t bytes)
{
    void *r = *p;
    *p += align8(bytes);
    return r;
}

/* glow read position for frame coordinate x: cell j and weight of j+1 (Q10),
 * u = (x + 0.5) / cell - 0.5 as glow_pos() */
static void glow_pos(int x, int32_t snum, int32_t sden, int n, uint16_t *j, uint16_t *f)
{
    int32_t num = (2 * x + 1) * sden - 4 * snum;                       /* u = num / (8 snum) */
    uint32_t den = 8u * (uint32_t) snum;
    if (num <= 0) { *j = 0; *f = 0; return; }
    uint32_t k = (uint32_t) num / den;
    if ((int) k >= n - 1) { *j = (uint16_t) (n - 2); *f = 1024; return; }
    *j = (uint16_t) k;
    *f = (uint16_t) (((uint32_t) num - k * den) * 1024u / den);
}

static void sample_rows(const mf_fx *fx, int py, int *y0, int *y1)
{
    *y0 = (int) muldiv((uint32_t) py, (uint32_t) fx->snum, (uint32_t) fx->sden);
    *y1 = (int) muldiv((uint32_t) py + 1, (uint32_t) fx->snum, (uint32_t) fx->sden);
    if (*y1 <= *y0) *y1 = *y0 + 1;
    if (*y1 > fx->h) *y1 = fx->h;
}

int mf_fx_begin(void *mem, size_t len, const mf_fx_look *look, const uint16_t *table, uint64_t grain_seed,
                mf_fx **out)
{
    if (!mem || !look || !table || !out) return MF_E_INVALID_ARG;
    const int w = look->width, h = look->height;
    size_t need = mf_fx_ctx_size(w, h);
    if (!need || len < need || ((uintptr_t) mem & 7)) return MF_E_INVALID_ARG;
    memset(mem, 0, need);
    uint8_t *p = mem;
    mf_fx *fx = take(&p, sizeof *fx);
    fx->L = *look;
    fx->table = table;
    fx->seed = grain_seed;
    fx->w = w;
    fx->h = h;
    scale_of(w, h, &fx->snum, &fx->sden);
    fx->pw = print_cols(w, fx->snum, fx->sden);
    fx->ph = print_cols(h, fx->snum, fx->sden);
    fx->ncols = (fx->pw + 3) / 4;
    grid_size(w, h, fx->snum, fx->sden, &fx->gw, &fx->gh);
    fx->sx0 = take(&p, sizeof(uint16_t) * (size_t) fx->ncols);
    fx->sx1 = take(&p, sizeof(uint16_t) * (size_t) fx->ncols);
    fx->sacc = take(&p, sizeof(uint32_t) * 3 * (size_t) fx->ncols);
    fx->cell_x = take(&p, sizeof(uint16_t) * (size_t) w);
    fx->gx = take(&p, sizeof(uint16_t) * (size_t) w);
    fx->gfx = take(&p, sizeof(uint16_t) * (size_t) w);
    fx->vig_x = take(&p, sizeof(uint16_t) * (size_t) w);
    fx->cnt_x = take(&p, sizeof(uint16_t) * (size_t) fx->gw);
    fx->cnt_y = take(&p, sizeof(uint16_t) * (size_t) fx->gh);
    fx->grid = take(&p, sizeof(int32_t) * (size_t) fx->gw * fx->gh);
    fx->gtmp = take(&p, sizeof(int32_t) * (size_t) (fx->gw > fx->gh ? fx->gw : fx->gh));

    for (int i = 0; i < fx->ncols; i++)
    {
        uint32_t px = 4u * (uint32_t) i;
        uint32_t x0 = muldiv(px, (uint32_t) fx->snum, (uint32_t) fx->sden);
        uint32_t x1 = muldiv(px + 1, (uint32_t) fx->snum, (uint32_t) fx->sden);
        if (x1 <= x0) x1 = x0 + 1;
        if (x1 > (uint32_t) w) x1 = (uint32_t) w;
        fx->sx0[i] = (uint16_t) x0;
        fx->sx1[i] = (uint16_t) x1;
    }
    const uint32_t cden = 4u * (uint32_t) fx->snum;
    for (int x = 0; x < w; x++)
    {
        uint32_t c = muldiv((uint32_t) x, (uint32_t) fx->sden, cden);
        if ((int) c >= fx->gw) c = (uint32_t) fx->gw - 1;
        fx->cell_x[x] = (uint16_t) c;
        fx->cnt_x[c]++;
        glow_pos(x, fx->snum, fx->sden, fx->gw, &fx->gx[x], &fx->gfx[x]);
        /* tx = 2x/(w-1) - 1; 0.06 tx^2 in Q16 */
        int32_t tx = (int32_t) muldiv((uint32_t) (2 * x), 32768, (uint32_t) (w - 1)) - 32768;   /* Q15 */
        fx->vig_x[x] = (uint16_t) (((int64_t) tx * tx * VIG_Q16) >> 30);
    }
    for (int y = 0; y < h; y++)
    {
        uint32_t c = muldiv((uint32_t) y, (uint32_t) fx->sden, cden);
        if ((int) c >= fx->gh) c = (uint32_t) fx->gh - 1;
        fx->cnt_y[c]++;
    }
    fx->py = 0;
    sample_rows(fx, 0, &fx->sy0, &fx->sy1);
    fx->phase = PHASE_SCAN;
    fx->next_row = 0;
    *out = fx;
    return MF_OK;
}

/* ---------------------------------------------------------------- pass 1 */

static void finish_sample_row(mf_fx *fx)
{
    for (int i = 0; i < fx->ncols; i++)
    {
        uint32_t npx = (uint32_t) (fx->sx1[i] - fx->sx0[i]) * (uint32_t) (fx->sy1 - fx->sy0);
        const uint32_t *m = fx->sacc + 3 * i;
        /* v = floor(luma * 4096), luma = sum(m_c * LUMA_c) / 4096 / npx / 32768 */
        uint64_t l = (uint64_t) m[0] * LUMA_R + (uint64_t) m[1] * LUMA_G + (uint64_t) m[2] * LUMA_B;
        uint32_t v = (uint32_t) (sdiv64((int64_t) (l >> 15), npx));
        if (v > 4096) v = 4096;
        /* log2(v / 4096 + 1e-4), argument in Q24 */
        fx->log_sum += mf_fx_log2_q16((v << 12) + 1678) - (24 << 16);
        fx->nsamples++;
    }
    memset(fx->sacc, 0, sizeof(uint32_t) * 3 * (size_t) fx->ncols);
}

static void finish_scan(mf_fx *fx)
{
    int32_t ev;
    if (fx->L.slide) ev = SLIDE_EV_Q16;
    else if (!fx->nsamples) ev = 0;
    else
    {
        int64_t mean = sdiv64(fx->log_sum, (uint32_t) fx->nsamples);
        ev = LOG2_KEY_Q16 - (int32_t) mean;
        if (ev < EV_MIN_Q16) ev = EV_MIN_Q16;
        if (ev > EV_MAX_Q16) ev = EV_MAX_Q16;
    }
    fx->ev_q16 = ev;
    uint32_t k = mf_fx_exp2_q16(ev + fx->L.ev_q16);
    for (int c = 0; c < 3; c++) fx->gain_q16[c] = (int32_t) (((uint64_t) k * (uint32_t) fx->L.bal_q16[c]) >> 16);
    fx->phase = PHASE_GLOW;
    fx->next_row = 0;
}

int mf_fx_scan_rows(mf_fx *fx, const uint16_t *rgb, size_t stride, int y0, int n)
{
    if (!fx || !rgb || fx->phase != PHASE_SCAN || y0 != fx->next_row || n < 1 || y0 + n > fx->h)
        return MF_E_INVALID_ARG;
    for (int r = 0; r < n; r++)
    {
        const int y = y0 + r;
        const uint16_t *row = rgb + (size_t) r * stride;
        if (!fx->L.slide && fx->py < fx->ph && y >= fx->sy0 && y < fx->sy1)
        {
            for (int i = 0; i < fx->ncols; i++)
            {
                uint32_t *m = fx->sacc + 3 * i;
                for (int x = fx->sx0[i]; x < fx->sx1[i]; x++)
                    for (int c = 0; c < 3; c++)
                    {
                        uint32_t v = row[3 * x + c];
                        m[c] += v > ONE_Q15 ? ONE_Q15 : v;
                    }
            }
            if (y == fx->sy1 - 1)
            {
                finish_sample_row(fx);
                fx->py += 4;
                if (fx->py < fx->ph) sample_rows(fx, fx->py, &fx->sy0, &fx->sy1);
            }
        }
    }
    fx->next_row = y0 + n;
    if (fx->next_row == fx->h) finish_scan(fx);
    return MF_OK;
}

int32_t mf_fx_scanner_ev_q16(const mf_fx *fx) { return fx ? fx->ev_q16 : 0; }

/* ---------------------------------------------------------------- pass 2 */

static inline uint32_t expose(const mf_fx *fx, uint32_t v, int c)
{
    if (v > ONE_Q15) v = ONE_Q15;
    uint32_t e = (uint32_t) (((uint64_t) v * (uint32_t) fx->gain_q16[c]) >> 16);
    return e > CLIP_Q15 ? CLIP_Q15 : e;
}

static void finish_glow(mf_fx *fx)
{
    const int gw = fx->gw, gh = fx->gh;
    int32_t *g = fx->grid, *t = fx->gtmp;
    for (int y = 0; y < gh; y++)
        for (int x = 0; x < gw; x++)
        {
            uint32_t cnt = (uint32_t) fx->cnt_x[x] * fx->cnt_y[y];
            int32_t *v = g + y * gw + x;
            if (cnt) *v = (int32_t) (((uint32_t) *v + cnt / 2) / cnt);
        }
    for (int pass = 0; pass < 2; pass++)            /* [1 2 1] / 4, twice each way, edges clamped */
    {
        for (int y = 0; y < gh; y++)
        {
            int32_t *r = g + y * gw;
            for (int x = 0; x < gw; x++)
                t[x] = (r[x > 0 ? x - 1 : 0] + 2 * r[x] + r[x < gw - 1 ? x + 1 : gw - 1] + 2) >> 2;
            memcpy(r, t, sizeof(int32_t) * (size_t) gw);
        }
        for (int x = 0; x < gw; x++)
        {
            for (int y = 0; y < gh; y++)
                t[y] = (g[(y > 0 ? y - 1 : 0) * gw + x] + 2 * g[y * gw + x]
                        + g[(y < gh - 1 ? y + 1 : gh - 1) * gw + x] + 2) >> 2;
            for (int y = 0; y < gh; y++) g[y * gw + x] = t[y];
        }
    }
    fx->phase = PHASE_RENDER;
}

int mf_fx_glow_rows(mf_fx *fx, const uint16_t *rgb, size_t stride, int y0, int n)
{
    if (!fx || !rgb || fx->phase != PHASE_GLOW || y0 != fx->next_row || n < 1 || y0 + n > fx->h)
        return MF_E_INVALID_ARG;
    const uint32_t cden = 4u * (uint32_t) fx->snum;
    const int32_t thr = fx->L.hal_thr_q15;
    const int on = fx->L.hal_q16[0] | fx->L.hal_q16[1] | fx->L.hal_q16[2];
    for (int r = 0; on && r < n; r++)
    {
        const int y = y0 + r;
        const uint16_t *row = rgb + (size_t) r * stride;
        uint32_t cy = muldiv((uint32_t) y, (uint32_t) fx->sden, cden);
        if ((int) cy >= fx->gh) cy = (uint32_t) fx->gh - 1;
        int32_t *grow = fx->grid + cy * (uint32_t) fx->gw;
        for (int x = 0; x < fx->w; x++)
        {
            const uint16_t *px = row + 3 * x;
            uint32_t l = (expose(fx, px[0], 0) * LUMA_R + expose(fx, px[1], 1) * LUMA_G
                          + expose(fx, px[2], 2) * LUMA_B) >> 12;
            if ((int32_t) l > thr) grow[fx->cell_x[x]] += (int32_t) l - thr;
        }
    }
    fx->next_row = y0 + n;
    if (fx->next_row == fx->h) finish_glow(fx);
    return MF_OK;
}

/* ---------------------------------------------------------------- pass 3 */

/* Cineon code position on the 33-grid (0..32 in Q16) of a linear Q15 value */
static inline int32_t cineon_pos(int32_t lin)
{
    if (lin < 0) lin = 0;
    uint32_t x = (uint32_t) (((uint64_t) (uint32_t) lin * CIN_GAIN_Q16) >> 9) + CIN_BLACK_Q22;
    int32_t l2 = mf_fx_log2_q16(x) - (22 << 16);
    int32_t p = CIN_P0_Q16 + (int32_t) (((int64_t) l2 * CIN_PB_Q16) >> 16);
    return p < 0 ? 0 : p > (32 << 16) ? (32 << 16) : p;
}

static void table_apply(const uint16_t *t, const int32_t lin[3], uint32_t out[3])
{
    int32_t f[3], i[3];
    for (int c = 0; c < 3; c++)
    {
        int32_t p = cineon_pos(lin[c]);
        i[c] = p >> 16;
        if (i[c] > MF_GRID - 2) i[c] = MF_GRID - 2;
        f[c] = (p - (i[c] << 16)) >> 4;             /* Q12 */
    }
    const int32_t fr = f[0], fg = f[1], fb = f[2];
    const int R = 1, G = MF_GRID, B = MF_GRID * MF_GRID;
    const int base = (i[2] * MF_GRID + i[1]) * MF_GRID + i[0];
    int o1, o2;
    int32_t w0, w1, w2, w3;
    if (fr >= fg)
    {
        if (fg >= fb)      { o1 = R; o2 = R + G; w0 = 4096 - fr; w1 = fr - fg; w2 = fg - fb; w3 = fb; }
        else if (fr >= fb) { o1 = R; o2 = R + B; w0 = 4096 - fr; w1 = fr - fb; w2 = fb - fg; w3 = fg; }
        else               { o1 = B; o2 = R + B; w0 = 4096 - fb; w1 = fb - fr; w2 = fr - fg; w3 = fg; }
    }
    else
    {
        if (fb >= fg)      { o1 = B; o2 = G + B; w0 = 4096 - fb; w1 = fb - fg; w2 = fg - fr; w3 = fr; }
        else if (fb >= fr) { o1 = G; o2 = G + B; w0 = 4096 - fg; w1 = fg - fb; w2 = fb - fr; w3 = fr; }
        else               { o1 = G; o2 = R + G; w0 = 4096 - fg; w1 = fg - fr; w2 = fr - fb; w3 = fb; }
    }
    const uint16_t *a = t + 3 * base, *b = t + 3 * (base + o1), *c = t + 3 * (base + o2),
                   *d = t + 3 * (base + R + G + B);
    for (int k = 0; k < 3; k++)
        out[k] = ((uint32_t) w0 * a[k] + (uint32_t) w1 * b[k] + (uint32_t) w2 * c[k] + (uint32_t) w3 * d[k]
                  + 2048) >> 12;
}

int mf_fx_render_rows(mf_fx *fx, const uint16_t *rgb, size_t stride, int y0, int n, uint16_t *out,
                      size_t out_stride)
{
    if (!fx || !rgb || !out || fx->phase != PHASE_RENDER || y0 < 0 || n < 1 || y0 + n > fx->h)
        return MF_E_INVALID_ARG;
    const int w = fx->w, gw = fx->gw;
    const int glow = fx->L.hal_q16[0] | fx->L.hal_q16[1] | fx->L.hal_q16[2];
    const int32_t amp = fx->L.grain_amp_q16;
    for (int r = 0; r < n; r++)
    {
        const int y = y0 + r;
        const uint16_t *row = rgb + (size_t) r * stride;
        uint16_t *orow = out + (size_t) r * out_stride;
        int32_t ty = (int32_t) muldiv((uint32_t) (2 * y), 32768, (uint32_t) (fx->h - 1)) - 32768;
        int32_t vig_y = (int32_t) (((int64_t) ty * ty * VIG_Q16) >> 30);
        uint16_t gy, gfy;
        glow_pos(y, fx->snum, fx->sden, fx->gh, &gy, &gfy);
        const int32_t *g0 = fx->grid + gy * gw, *g1 = g0 + gw;
        for (int x = 0; x < w; x++)
        {
            const uint16_t *px = row + 3 * x;
            int32_t vig = 65536 - fx->vig_x[x] - vig_y;
            int32_t lin[3];
            for (int c = 0; c < 3; c++)
                lin[c] = (int32_t) (((int64_t) expose(fx, px[c], c) * vig) >> 16);
            if (glow)
            {
                const int j = fx->gx[x];
                const int32_t fxw = fx->gfx[x];
                int32_t top = (g0[j] * (1024 - fxw) + g0[j + 1] * fxw) >> 10;
                int32_t bot = (g1[j] * (1024 - fxw) + g1[j + 1] * fxw) >> 10;
                int32_t gv = (int32_t) (((int64_t) top * (1024 - gfy) + (int64_t) bot * gfy) >> 10);
                for (int c = 0; c < 3; c++) lin[c] += (int32_t) (((int64_t) gv * fx->L.hal_q16[c]) >> 16);
            }
            uint32_t o[3];
            table_apply(fx->table, lin, o);
            if (amp > 0)
            {
                uint32_t l = (o[0] * 54 + o[1] * 183 + o[2] * 19) >> 8;
                if (l > 65535) l = 65535;
                int32_t wgt = (int32_t) (((uint64_t) ((l * (65535 - l)) >> 16) * (uint32_t) amp) >> 16);
                int32_t shared = mf_noise(fx->seed, (uint32_t) x, (uint32_t) y, 0);
                for (int c = 0; c < 3; c++)
                {
                    int32_t nz = fx->L.mono ? shared
                                 : (shared * 3 + mf_noise(fx->seed, (uint32_t) x, (uint32_t) y, 1u + (uint32_t) c) * 2) >> 2;
                    int32_t v = (int32_t) o[c] + (int32_t) (((int64_t) nz * wgt) >> 15);
                    orow[3 * x + c] = (uint16_t) (v < 0 ? 0 : v > 65535 ? 65535 : v);
                }
            }
            else
                for (int c = 0; c < 3; c++) orow[3 * x + c] = (uint16_t) (o[c] > 65535 ? 65535 : o[c]);
        }
    }
    return MF_OK;
}
