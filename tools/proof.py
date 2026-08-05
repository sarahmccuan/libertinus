"""Render a proof sheet of shaped test strings.

Shapes each line of a proof file with HarfBuzz and rasterises the result, so
you can look at what the font actually does rather than what you hope it does.
Also writes a text dump of the glyph sequence and positions, which diffs
cleanly between runs.

    python tools/proof.py -i build/LibertinusSerif-Regular.otf \
        -p tools/proofs/greek-macrons.txt -o build/proof

Proof file syntax: one test string per line, UTF-8. Lines starting with '##'
are section headings, lines starting with '#' are comments, blank lines are
ignored. A '\t#' at the end of a line is a per-cell note.
"""

import argparse
import os
import unicodedata

import uharfbuzz as hb
from fontTools.misc.transform import Transform
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

BG = (255, 255, 255)
INK = (0, 0, 0)
LABEL = (110, 110, 110)
HEADING = (0, 0, 0)
GUIDE = (215, 225, 240)
FLAG = (200, 40, 40)


class Section:
    def __init__(self, title):
        self.title = title
        self.cases = []


class Case:
    def __init__(self, text, note):
        self.text = text
        self.note = note


def read_proof(path, normalize):
    sections = [Section(None)]
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            if line.startswith("##"):
                sections.append(Section(line[2:].strip()))
                continue
            if line.startswith("#"):
                continue
            note = None
            if "\t#" in line:
                line, note = line.split("\t#", 1)
                note = note.strip()
            text = line.strip()
            if not text:
                continue
            if normalize != "none":
                text = unicodedata.normalize(normalize.upper(), text)
            sections[-1].cases.append(Case(text, note))
    return [s for s in sections if s.cases]


def codepoint_label(text):
    return " ".join("%04X" % ord(c) for c in text)


def shape(hbfont, text, script, language, features):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.direction = "ltr"
    buf.script = script
    buf.language = language
    hb.shape(hbfont, buf, features)
    return buf.glyph_infos, buf.glyph_positions


class Renderer:
    def __init__(self, path, size, script, language, features):
        self.ttf = TTFont(path)
        self.glyphset = self.ttf.getGlyphSet()
        self.order = self.ttf.getGlyphOrder()
        self.upem = self.ttf["head"].unitsPerEm
        self.ascender = self.ttf["hhea"].ascent
        self.descender = self.ttf["hhea"].descent
        self.size = size
        self.scale = size / self.upem
        self.script = script
        self.language = language
        self.features = features

        blob = hb.Blob.from_file_path(path)
        self.hbfont = hb.Font(hb.Face(blob))
        self.hbfont.scale = (self.upem, self.upem)

        self.markglyphs = {}
        if "GDEF" in self.ttf and self.ttf["GDEF"].table.GlyphClassDef:
            self.markglyphs = self.ttf["GDEF"].table.GlyphClassDef.classDefs

    def shape(self, text):
        return shape(self.hbfont, text, self.script, self.language, self.features)

    def trace(self, text):
        """hb-shape style dump: glyph@offset+advance, one line."""
        infos, positions = self.shape(text)
        parts = []
        for info, pos in zip(infos, positions):
            name = self.order[info.codepoint]
            part = name
            if pos.x_offset or pos.y_offset:
                part += "@%d,%d" % (pos.x_offset, pos.y_offset)
            part += "+%d" % pos.x_advance
            parts.append(part)
        return "[" + "|".join(parts) + "]"

    def has_notdef(self, text):
        infos, _ = self.shape(text)
        return any(i.codepoint == 0 for i in infos)

    def unattached(self, text):
        """Marks that GPOS left sitting at the origin.

        A mark that comes out of shaping with no offset at all was not
        attached to anything -- almost always a missing anchor rather than an
        anchor in the wrong place. This is the check that is easy to miss by
        eye, because the mark still draws, just in the wrong spot.
        """
        infos, positions = self.shape(text)
        loose = []
        for i, (info, pos) in enumerate(zip(infos, positions)):
            if i == 0:
                continue
            name = self.order[info.codepoint]
            if self.markglyphs.get(name) == 3 and not (pos.x_offset or pos.y_offset):
                loose.append(name)
        return loose

    def image(self, text, pad=8):
        """Rasterise one shaped string. Returns (coverage bitmap, baseline y)."""
        infos, positions = self.shape(text)
        pen = FreeTypePen(self.glyphset)
        x = y = 0
        for info, pos in zip(infos, positions):
            name = self.order[info.codepoint]
            tpen = TransformPen(pen, Transform().translate(x + pos.x_offset,
                                                           y + pos.y_offset))
            self.glyphset[name].draw(tpen)
            x += pos.x_advance
            y += pos.y_advance

        bbox = pen.bbox if pen.bbox else (0, 0, x, 0)
        # Vertical extent is fixed to the font's own metrics so that every cell
        # in the sheet shares a baseline; horizontal extent follows the ink so
        # that narrow samples do not get lost in whitespace. Marks can
        # overshoot the hhea ascender, so take whichever is taller.
        x0 = min(bbox[0], 0)
        x1 = max(bbox[2], x)
        top = max(self.ascender, bbox[3]) + 40
        bottom = min(self.descender, bbox[1]) - 40

        width = max(1, int(round((x1 - x0) * self.scale)) + 2 * pad)
        height = max(1, int(round((top - bottom) * self.scale)) + 2 * pad)
        transform = (Transform()
                     .translate(pad, pad)
                     .scale(self.scale)
                     .translate(-x0, -bottom))
        img = pen.image(width=width, height=height, transform=transform)
        baseline = height - pad - int(round(-bottom * self.scale))
        # FreeTypePen returns LA, with the coverage in the alpha channel.
        return img.getchannel("A"), baseline


def paste_ink(sheet, gray, box, color=INK):
    """Composite a coverage bitmap as coloured ink."""
    layer = Image.new("RGB", gray.size, color)
    sheet.paste(layer, box, gray)


def clip_text(draw, text, font, width):
    """Trim a label to fit the cell, with an ellipsis."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def build_sheet(renderer, sections, columns, cell_w, cell_h, guides, label_font,
                heading_font):
    pad = 14
    label_h = 34
    head_h = 30

    rows = []  # (kind, payload)
    for section in sections:
        if section.title:
            rows.append(("head", section.title))
        for i in range(0, len(section.cases), columns):
            rows.append(("cases", section.cases[i:i + columns]))

    height = pad
    for kind, _ in rows:
        height += head_h if kind == "head" else cell_h + label_h
    height += pad
    width = pad * 2 + columns * cell_w

    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    y = pad
    for kind, payload in rows:
        if kind == "head":
            draw.text((pad, y + 6), payload, font=heading_font, fill=HEADING)
            draw.line([(pad, y + head_h - 4), (width - pad, y + head_h - 4)],
                      fill=GUIDE)
            y += head_h
            continue

        for col, case in enumerate(payload):
            cx = pad + col * cell_w
            img, baseline = renderer.image(case.text)
            notdef = renderer.has_notdef(case.text)
            loose = renderer.unattached(case.text)
            bad = notdef or loose

            # Samples wider than the cell are scaled down rather than cropped,
            # so a long word stays legible instead of losing its tail.
            avail = cell_w - 12
            if img.width > avail:
                ratio = avail / img.width
                img = img.resize((avail, max(1, int(img.height * ratio))),
                                 Image.LANCZOS)
                baseline = int(baseline * ratio)

            # Keep every sample on the same baseline within a row.
            bl_y = y + int(cell_h * 0.72)
            if guides:
                draw.line([(cx + 6, bl_y), (cx + cell_w - 6, bl_y)], fill=GUIDE)

            ox = cx + max(0, (cell_w - img.width) // 2)
            paste_ink(sheet, img, (ox, bl_y - baseline), FLAG if bad else INK)

            label = codepoint_label(case.text)
            if notdef:
                label += "  .notdef"
            elif loose:
                label += "  loose: " + ",".join(loose)
            draw.text((cx + 6, y + cell_h + 2),
                      clip_text(draw, label, label_font, cell_w - 12),
                      font=label_font, fill=FLAG if bad else LABEL)
            if case.note:
                draw.text((cx + 6, y + cell_h + 16),
                          clip_text(draw, case.note, label_font, cell_w - 12),
                          font=label_font, fill=LABEL)
        y += cell_h + label_h

    return sheet


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--input", required=True, help="font to proof")
    ap.add_argument("-p", "--proof", required=True, help="proof text file")
    ap.add_argument("-o", "--output", default="build/proof", help="output dir")
    ap.add_argument("-s", "--size", type=int, default=96, help="sample size in px")
    ap.add_argument("-c", "--columns", type=int, default=6)
    ap.add_argument("--cell-width", type=int, default=190)
    ap.add_argument("--cell-height", type=int, default=170)
    ap.add_argument("--script", default="Grek")
    ap.add_argument("--language", default="")
    ap.add_argument("--feature", action="append", default=[],
                    help="OpenType feature, e.g. -kern (repeatable)")
    ap.add_argument("--normalize", choices=("none", "nfc", "nfd"), default="none",
                    help="normalise proof strings before shaping")
    ap.add_argument("--no-guides", dest="guides", action="store_false")
    args = ap.parse_args()

    features = {}
    for spec in args.feature:
        if spec.startswith("-"):
            features[spec[1:]] = False
        else:
            features[spec.lstrip("+")] = True

    renderer = Renderer(args.input, args.size, args.script, args.language,
                        features or None)
    sections = read_proof(args.proof, args.normalize)

    label_font = ImageFont.load_default(13)
    heading_font = ImageFont.load_default(16)

    os.makedirs(args.output, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.proof))[0]

    sheet = build_sheet(renderer, sections, args.columns, args.cell_width,
                        args.cell_height, args.guides, label_font, heading_font)
    png = os.path.join(args.output, stem + ".png")
    sheet.save(png)

    problems = []
    txt = os.path.join(args.output, stem + ".txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("# %s\n" % os.path.basename(args.input))
        for section in sections:
            if section.title:
                f.write("\n## %s\n" % section.title)
            for case in section.cases:
                label = codepoint_label(case.text)
                flag = ""
                if renderer.has_notdef(case.text):
                    flag = "  <- .notdef"
                else:
                    loose = renderer.unattached(case.text)
                    if loose:
                        flag = "  <- unattached: " + " ".join(loose)
                if flag:
                    problems.append(label)
                f.write("%-34s %s%s\n" % (label, renderer.trace(case.text), flag))

    total = sum(len(s.cases) for s in sections)
    print("%d samples -> %s" % (total, png))
    print("shaping     -> %s" % txt)
    if problems:
        print("%d of %d samples have unattached marks or missing glyphs"
              % (len(problems), total))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
