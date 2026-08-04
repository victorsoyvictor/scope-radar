# The display board

The radar in the article runs on a **WT32-SC01 Plus**, made by Wireless Tag.

## Specification

| | |
|---|---|
| Module | ESP32-S3-WROVER-N16R2 |
| Flash | 16 MB |
| PSRAM | 2 MB |
| Panel | 3.5" IPS, 480×320 |
| Display controller | ST7796 |
| Touch | FT6336U capacitive, 2-point |
| Display interface | 8-bit Intel 8080 parallel bus, driven by the S3's LCD_CAM peripheral with DMA |
| Extras | speaker, RS485, microSD, debug header, GPIO expansion on both sides |

The parallel bus is the part that matters for a radar. Most cheap ESP32 display
boards wire the panel over SPI; the 8080 bus gives several times the bandwidth,
which is what lets the firmware wipe and redraw the whole scope four times a
second instead of resorting to partial updates.

The 2 MB of PSRAM is the real constraint. A full 480×320 framebuffer at two bytes
per pixel is 300 KB, or 600 KB double-buffered, which doesn't fit alongside an
aircraft store and JSON responses. The ESP32 build works around it by having LVGL
render in strips into a pair of 480×20 line buffers.

## Buying one

Watch out for one thing: **"WT32-SC01" and "WT32-SC01 Plus" are different boards**,
and several marketplace listings mix them up. Some listings titled *Plus* go on to
describe an ESP32-WROVER-B with 4 MB flash and 8 MB PSRAM — that's the older
non-Plus board, which uses SPI and a resistive-era design. The genuine Plus says
**ESP32-S3-WROVER-N16R2, 16 MB flash, 2 MB PSRAM**. If a listing doesn't say
ESP32-S3, it isn't the Plus.

Expect roughly **AUD 45–60** / **EUR 30 ex VAT** / **USD 30–40**.

### Australia

- **Pakronics** (Melbourne) — carries local stock and offers pickup, which is
  the quickest option if you're in Melbourne.
- **Core Electronics** (Newcastle, NSW) — same-day dispatch on orders before 2 PM.
- **Dialedin** — free standard shipping over AUD 129.

### Elsewhere

- Antratek (NL) — around EUR 29.90 ex VAT.
- Tindie, Elecrow, RobotShop, and the usual marketplaces.

Prices and stock shift, so treat these as a starting point rather than a quote.

## Firmware

The article's own firmware wasn't public at the time of writing — the author said
in the comments he was working on releasing it. If you want to build the hardware
version now, [MatixYo's Plane Radar](https://github.com/MatixYo/plane-radar) is
MIT-licensed and ships prebuilt binaries, so you can flash it without compiling
anything. It targets an ESP32-C3 Super Mini with a 1.28" round display rather
than this board.
