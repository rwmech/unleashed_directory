# Card art for /kids

Drop PNGs in here and the slots on `/kids` fill themselves. Nothing else is
needed: the page names each file in `pages/kids.md` with a `!!` line, and
`pix_html()` renders **nothing at all** until the file exists. No broken
image, no reserved gap, no alt text standing in for a picture nobody drew.
So the page is correct today with this folder empty, and it is correct again
the moment a file lands.

Served from `/pix/<name>`, not `/static/`, because `gallery_html()` puts
everything in `static/` into the photo gallery on the manifesto, and blocky
card art has no business among photographs of real hardware.

## The spec

- **4:1, every slot, including the hero.** 640x160 is plenty; 1280x320 if
  you want the headroom. One ratio on purpose: two would mean drawing two
  shapes and letting `object-fit` crop whichever one landed in the wrong
  place, and a 4:1 banner cropped to 2:1 loses the sides of the picture on
  the screen with the least room to spare.
- Rendered at 110px tall in a three column card, 162px in a two column one,
  88px on a phone. It is a strip across the top of a card, not a poster.
- **PNG.** `.jpg`, `.webp` and `.gif` also work; PNG is right for flat
  blocky colour.
- Low resolution is the point. The CSS sets `image-rendering:pixelated`, so
  a 64x16 source scales up with hard square edges rather than being
  smoothed into mush. Draw small.
- Keep the palette in the site's range: `#d98f24`, `#ffd35c`, `#ffab52`,
  `#2e1c05` for the hero, `#4ce0e0` and `#12121a` for the rest.

## The one hard rule

**Generic voxel and blocky pixel art only.** Cubes, chunky low-resolution
textures, hard pixel edges, flat colour.

**Nothing owned by Mojang or Microsoft.** No creeper, no Steve or Alex, no
recognisable grass, dirt, cobble or diamond block texture, no logo or
wordmark, and the word itself never appears in a heading, a filename, an
alt text or the page title. The comparison is fine in running prose, which
is ordinary nominative use; the art is where it would stop being fine, and
this is the one page on the site aimed at children, which is the worst
possible place to attract a takedown.

An image model asked for "Minecraft style" will hand back actual
Mojang-looking blocks and it will look fine to anybody not checking. Check
every file before it goes in.

## Alt text

Written in `pages/kids.md` on the `!!` line, after the `|`. It carries what
the picture **means**, not what it looks like, because somebody who cannot
see it needs the point rather than an inventory of pixels. A slot with no
alt text renders nothing, deliberately.

    !! parts.png | A small circuit board and a usb cable, the whole shopping list
