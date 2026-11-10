# 03. Grade Catalog

## Catalog design

The first implementation must ship with a curated starter set of Creative Color Grades.

These grades are not exact reproductions of copyrighted branded presets.
They are original presets inspired by well-known aesthetic families.

Each preset must define:

- stable ID
- display name
- short description
- category
- tags
- parameter values
- provenance notes

## Mandatory tag families

Every preset must support tags from the following families where appropriate:

- `VSCO`
- `Instagram Classics`

Other useful tags may include:

- `Matte`
- `Vintage`
- `Portrait`
- `Editorial`
- `Muted`
- `Pastel`
- `Cinematic`
- `Moody`
- `Warm`
- `Cool`
- `Earthy`
- `Faded`

## Initial recommended preset catalog

### A. Warm / Matte / Vintage

1. **Warm Muted Matte**  
   Tags: `VSCO`, `Matte`, `Warm`, `Muted`, `Portrait`  
   Character: lifted blacks, warm creamy highlights, muted saturation, earthy shadows.

2. **Faded Vintage Portrait**  
   Tags: `VSCO`, `Vintage`, `Portrait`, `Faded`  
   Character: soft contrast, lifted blacks, slight warm bias, gentle skin preservation.

3. **Golden Editorial Soft**  
   Tags: `VSCO`, `Editorial`, `Warm`, `Golden Hour`  
   Character: glowing warm highlights, low aggression contrast, elegant skin response.

4. **Earthy Soft Fade**  
   Tags: `VSCO`, `Earthy`, `Muted`, `Vintage`  
   Character: olive-brown shadows, lowered blue/green intensity, matte contrast.

### B. Early Social / Instagram-inspired

5. **Valencia-Inspired Soft Warmth**  
   Tags: `Instagram Classics`, `Warm`, `Faded`  
   Character: warm highlights, reduced contrast, nostalgic soft palette.

6. **Nashville-Inspired Pastel Fade**  
   Tags: `Instagram Classics`, `Pastel`, `Faded`, `Vintage`  
   Character: pastel magenta warmth, low density contrast, airy faded shadows.

7. **Rise-Inspired Cream Lift**  
   Tags: `Instagram Classics`, `Warm`, `Matte`, `Soft`  
   Character: lifted blacks, creamy brightness, nostalgic warmth.

8. **Toaster-Inspired Retro Punch**  
   Tags: `Instagram Classics`, `Vintage`, `Warm`, `Punchy`  
   Character: warm retro tone, slightly stronger contrast, nostalgic tint.

### C. Moody / Cinematic / Cool

9. **Moody Earth Portrait**  
   Tags: `VSCO`, `Moody`, `Earthy`, `Portrait`  
   Character: subdued palette, slightly darker mids, olive/cyan shadow shaping.

10. **Cool Cinematic Fade**  
    Tags: `Cinematic`, `Cool`, `Faded`  
    Character: cooler shadows, restrained saturation, soft highlight rolloff.

11. **Steel Blue Mood**  
    Tags: `Cinematic`, `Cool`, `Moody`  
    Character: cool gray-blue palette with low-color restraint.

### D. Bright / Airy / Editorial

12. **Pastel Air**  
    Tags: `VSCO`, `Pastel`, `Editorial`, `Soft`  
    Character: bright low-contrast look, reduced color density, soft lifted base.

13. **Soft Cream Editorial**  
    Tags: `Editorial`, `Warm`, `Portrait`, `Airy`  
    Character: cream-toned highlights, refined skin, low aggression blacks.

14. **Dusty Summer**  
    Tags: `VSCO`, `Vintage`, `Warm`, `Muted`  
    Character: dusty warm palette, lower greens, nostalgic summertime finish.

### E. B&W-oriented finishing grades

15. **Matte Monochrome Soft**  
    Tags: `Matte`, `Monochrome`, `Portrait`  
    Character: matte blacks, smooth highlight shoulders, soft classic B&W mood.

16. **Classic Silver Fade**  
    Tags: `Vintage`, `Monochrome`, `Faded`  
    Character: low-gloss monochrome with lifted blacks and gentle tonal rolloff.

## Catalog philosophy

This list is a starting catalog.

The implementation must support:

- system presets,
- user presets,
- hidden experimental presets,
- future expansion without schema changes.
