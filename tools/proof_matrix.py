"""Render one proof file across every face at once, faces side by side.

tools/proof.py answers "what does this face do?". This answers "do the faces
agree?", which is the question that matters once a value stops being measured
by hand and starts being derived per face -- a clearance that looks right in
Regular can collide in Bold Italic, and the only way to see that is to put them
next to each other on the same row.

    python tools/proof_matrix.py -p tools/proofs/greek-all.txt \
        -o build/proof/matrix.png

Rows are proof samples, columns are faces. A cell is flagged red when the face
leaves a mark unattached or has no glyph at all, so a hole shows up as a stripe
down one column rather than something you have to notice by eye.

Faces with no Greek at all are skipped -- Keyboard, Mono and Initials. Math is
included: it carries the full polytonic block and gets the same anchoring as the
text faces.

For mark collisions rather than missing anchors, see tools/check_overlap.py.
Nothing here can see two marks that merely touch.
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFont

from proof import (BG, FLAG, GUIDE, HEADING, INK, LABEL, Renderer,
                   clip_text, codepoint_label, paste_ink, read_proof)

# A face with no alpha has no Greek to say anything about.
PROBE = "alpha"


def load_font(size, bold=False):
    for name in (("segoeuib.ttf", "seguisb.ttf") if bold else ("segoeui.ttf",)):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def face_label(path):
    return os.path.basename(path).replace("Libertinus", "").replace(".otf", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-f", "--fonts", default="build/*.otf",
                    help="glob of faces to compare")
    ap.add_argument("-p", "--proof", required=True)
    ap.add_argument("-o", "--output", default="build/proof/matrix.png")
    ap.add_argument("-s", "--size", type=int, default=46)
    ap.add_argument("--cell-width", type=int, default=112)
    ap.add_argument("--cell-height", type=int, default=78)
    ap.add_argument("--gutter", type=int, default=210)
    ap.add_argument("--script", default="Grek")
    ap.add_argument("--language", default="")
    ap.add_argument("--repeat-header", type=int, default=18,
                    help="re-print the face names every N rows")
    ap.add_argument("--normalize", default="none",
                    choices=["none", "nfc", "nfd"])
    args = ap.parse_args()

    paths = sorted(glob.glob(args.fonts))
    faces = []
    for p in paths:
        try:
            r = Renderer(p, args.size, args.script, args.language, None)
        except Exception as e:
            print("  skipped %s (%s)" % (os.path.basename(p), e))
            continue
        if PROBE not in r.order:
            continue
        faces.append((face_label(p), r))
    if not faces:
        raise SystemExit("no faces with Greek matched %s" % args.fonts)

    sections = read_proof(args.proof, args.normalize)
    label_font = load_font(13)
    note_font = load_font(12)
    head_font = load_font(15, bold=True)
    col_font = load_font(12, bold=True)

    pad = 16
    head_h = 34
    colhead_h = 26

    # lay the rows out first so the canvas can be sized exactly
    rows = []
    for s in sections:
        if s.title:
            rows.append(("head", s.title))
        for case in s.cases:
            rows.append(("case", case))

    height = pad + colhead_h
    since = 0
    for kind, _ in rows:
        if kind == "head":
            height += head_h
            since = 0
            continue
        if args.repeat_header and since and since % args.repeat_header == 0:
            height += colhead_h
        height += args.cell_height
        since += 1
    height += pad

    width = pad * 2 + args.gutter + len(faces) * args.cell_width

    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    def column_header(y):
        for i, (name, _) in enumerate(faces):
            cx = pad + args.gutter + i * args.cell_width
            draw.text((cx + 4, y + 6),
                      clip_text(draw, name, col_font, args.cell_width - 8),
                      font=col_font, fill=HEADING)
        draw.line([(pad, y + colhead_h - 3), (width - pad, y + colhead_h - 3)],
                  fill=GUIDE)

    y = pad
    column_header(y)
    y += colhead_h

    since = 0
    flagged = 0
    for kind, payload in rows:
        if kind == "head":
            draw.text((pad, y + 8), payload, font=head_font, fill=HEADING)
            draw.line([(pad, y + head_h - 5), (width - pad, y + head_h - 5)],
                      fill=GUIDE)
            y += head_h
            since = 0
            continue

        if args.repeat_header and since and since % args.repeat_header == 0:
            column_header(y)
            y += colhead_h

        case = payload
        draw.text((pad, y + 8), codepoint_label(case.text), font=label_font,
                  fill=LABEL)
        if case.note:
            draw.text((pad, y + 26),
                      clip_text(draw, case.note, note_font, args.gutter - 10),
                      font=note_font, fill=LABEL)

        bl_y = y + int(args.cell_height * 0.74)
        for i, (_, r) in enumerate(faces):
            cx = pad + args.gutter + i * args.cell_width
            # Deliberately not wrapped in try/except: a face that cannot render
            # a sample is the single most important thing this sheet can tell
            # you, and swallowing it would draw an empty cell that reads as
            # "nothing to see here".
            img, baseline = r.image(case.text)
            bad = r.has_notdef(case.text) or r.unattached(case.text)
            if bad:
                flagged += 1

            avail = args.cell_width - 10
            if img.width > avail:
                ratio = avail / img.width
                img = img.resize((avail, max(1, int(img.height * ratio))),
                                 Image.LANCZOS)
                baseline = int(baseline * ratio)

            ox = cx + (args.cell_width - img.width) // 2
            oy = bl_y - baseline
            paste_ink(sheet, img, (ox, oy), FLAG if bad else INK)

        draw.line([(pad, y + args.cell_height - 1),
                   (width - pad, y + args.cell_height - 1)], fill=(242, 242, 242))
        y += args.cell_height
        since += 1

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".",
                exist_ok=True)
    sheet.save(args.output)
    total = sum(1 for k, _ in rows if k == "case") * len(faces)
    print("%d samples x %d faces = %d cells, %d flagged"
          % (sum(1 for k, _ in rows if k == "case"), len(faces), total, flagged))
    print("%d x %d -> %s" % (width, height, args.output))


if __name__ == "__main__":
    main()
