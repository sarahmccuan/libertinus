"""Report marks whose ink runs into the glyph beneath them.

Bounding boxes are not good enough for this. A psili's box overlaps a capital
long before its ink does, and a dialytika's box clears one long after -- the
question is only ever whether the black touches, so this rasterises each glyph
at its shaped position and counts pixels.

    python tools/check_overlap.py -p tools/proofs/greek-all.txt
    python tools/check_overlap.py -p ... --threshold 1 --mark uni0308

Overlap is reported as a percentage of the MARK's own ink, not of the pair, so
the number means "how much of this mark is buried" and stays comparable between
a dialytika and a hairline accent.
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fontTools.misc.transform import Transform
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.pens.transformPen import TransformPen

from proof import Renderer, codepoint_label, read_proof

PX = 200          # rasterise at this em size; fine enough to see a hairline touch
PAD = 12


def layers(r, text):
    """(name, is_mark, coverage bitmap) for each glyph, on one shared canvas."""
    infos, positions = r.shape(text)
    placed, x, y = [], 0, 0
    for info, pos in zip(infos, positions):
        placed.append((r.order[info.codepoint], x + pos.x_offset, y + pos.y_offset))
        x += pos.x_advance
        y += pos.y_advance

    # one canvas big enough for everything
    box = None
    for name, dx, dy in placed:
        pen = FreeTypePen(r.glyphset)
        r.glyphset[name].draw(TransformPen(pen, Transform().translate(dx, dy)))
        if pen.bbox is None:
            continue
        b = pen.bbox
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                     max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        return []

    scale = PX / r.upem
    w = max(1, int((box[2] - box[0]) * scale) + 2 * PAD)
    h = max(1, int((box[3] - box[1]) * scale) + 2 * PAD)
    t = (Transform().translate(PAD, PAD).scale(scale).translate(-box[0], -box[1]))

    out = []
    for name, dx, dy in placed:
        pen = FreeTypePen(r.glyphset)
        r.glyphset[name].draw(TransformPen(pen, Transform().translate(dx, dy)))
        img = pen.image(width=w, height=h, transform=t).getchannel("A")
        out.append((name, r.markglyphs.get(name) == 3, img))
    return out


def collisions(r, text, cutoff=128):
    """[(mark, what it hits, % of the mark's ink buried)] worst first."""
    ls = layers(r, text)
    if not ls:
        return []
    px = [(n, m, im.load(), im.size) for n, m, im in ls]
    found = []
    for i, (name, is_mark, get, (w, h)) in enumerate(px):
        if not is_mark:
            continue
        own = 0
        hits = {}
        for yy in range(h):
            for xx in range(w):
                if get[xx, yy] < cutoff:
                    continue
                own += 1
                for j, (other, _, oget, _) in enumerate(px):
                    if j == i:
                        continue
                    if oget[xx, yy] >= cutoff:
                        hits[other] = hits.get(other, 0) + 1
        if not own:
            continue
        for other, n in hits.items():
            found.append((name, other, 100.0 * n / own))
    return sorted(found, key=lambda t: -t[2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-f", "--fonts", default="build/*.otf")
    ap.add_argument("-p", "--proof", required=True)
    ap.add_argument("--script", default="Grek")
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="report overlaps above this %% of the mark's ink")
    ap.add_argument("--mark", default=None, help="only this mark glyph")
    ap.add_argument("--normalize", default="none", choices=["none", "nfc", "nfd"])
    args = ap.parse_args()

    faces = []
    for p in sorted(glob.glob(args.fonts)):
        r = Renderer(p, 40, args.script, "", None)
        if "alpha" in r.order:
            faces.append((os.path.basename(p).replace("Libertinus", "")
                          .replace(".otf", ""), r))

    cases = [c for s in read_proof(args.proof, args.normalize) for c in s.cases]
    worst = {}
    for name, r in faces:
        for c in cases:
            for mark, other, pct in collisions(r, c.text):
                if pct < args.threshold:
                    continue
                if args.mark and mark != args.mark:
                    continue
                key = (codepoint_label(c.text), mark, other)
                worst.setdefault(key, []).append((pct, name))

    if not worst:
        print("no ink collisions above %.1f%%" % args.threshold)
        return 0

    print("%-26s %-14s %-14s %6s  %s"
          % ("sequence", "mark", "runs into", "worst", "faces (worst first)"))
    rows = sorted(worst.items(), key=lambda kv: -max(p for p, _ in kv[1]))
    for (seq, mark, other), hits in rows:
        hits.sort(reverse=True)
        faces_s = ", ".join("%s %.0f%%" % (n, p) for p, n in hits[:4])
        print("%-26s %-14s %-14s %5.1f%%  %s"
              % (seq, mark, other, hits[0][0], faces_s))
    print("\n%d colliding combinations" % len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
