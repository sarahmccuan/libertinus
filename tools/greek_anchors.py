"""Derive the Greek mark-attachment anchors from a face's own outlines.

Every number here was originally measured by hand against Serif Regular and then
shared across all fourteen faces. That held for the uprights and fell apart for
Bold Italic -- 105 units of centring error, and a 28% ink overlap between a
breathing and the accent beside it -- because the measurements were only ever
Regular-specific in practice, not in principle. This module takes them per face
at build time instead.

What is derived and what is not:

  * derived -- where the macron sits inside a precomposed vowel, how wide each
    mark is, how the font's own precomposed forms stack a dialytika.
  * not derived -- the clearances. Those are judgement calls and live in the
    tables below. They are distances in font units and carry across weights.

The distinction is the point: a value that can be measured should never be
typed in, because it goes stale silently when its source changes. Constants
here have repeatedly outlived the geometry they were taken from -- most
recently GAP_OVER_BREATHING, still set for a perispomeni the font had already
stopped drawing.

Capitals are placed by hand in sources/features/mark_greek.fea, as is the
ypogegrammeni -- a below-mark needs no clearance from the bar above, so there is
nothing face-specific to derive. Both live there, not here. The clearance tables
below pair with the grk_caps_room allowances in that file and only make sense
read together; see the note above CAPITAL_PAIR.

Two cautions when adding to this file:

  * mark_greek.fea anchors marks by the .sfd's own attach height, this file by
    ink centre and ink bottom. Same-looking numbers, different meanings; do not
    copy values between them.
  * bounding boxes lie about slanted and diagonal glyphs. An italic stem leans
    out of its own box as it rises, and a diagonal's contact point falls between
    sampled contour points. Measure within a band (_top_centre, _top_within,
    _letter_body) or rasterise (tools/check_overlap.py); every wrong number
    found in this file so far came from a bbox, most recently a dialytika 47
    units off centre on Serif Italic. See _letter_shift.
"""

import re
import unicodedata

from fontTools.pens.recordingPen import DecomposingRecordingPen

# --- judgement calls -------------------------------------------------------

# Clearance between a macron or breve and the mark above it, roughly two thirds
# of what clearing a letter asks for. A bar is a flat horizontal edge with no
# shape for the eye to tuck a mark into, so the gap that looks right over a
# letter reads as floating over a bar.
GAP_OVER_BAR = {
    "oxia": 36, "varia": 37, "psili": 45, "dasia": 50,
    "perispomeni": 61, "dialytika": 61, "macron": 45,
}

# Space between a breathing and the accent beside it. The grave needs more: it
# leans the other way, so its heavy end is at the top left, exactly where the
# breathing's top right is.
GAP_IN_CLUSTER = {"oxia": 15, "varia": 30}

# Fallback clearance between a perispomeni and the breathing it sits over -- too
# wide to go beside one. Only used where the face has no U+1FCF or U+1FDF to
# measure; see _over_breathing(), which prefers the font's own answer.
GAP_OVER_BREATHING = 13

# The font's own combined breathing-and-perispomeni glyphs. U+1FCF is psili with
# perispomeni and U+1FDF is dasia with perispomeni, each drawn as one mark, and
# each is this face's opinion about how the pair stacks -- which is the question
# GAP_OVER_BREATHING was guessing at.
PERISPOMENI_REFS = {"uni0313": "uni1FCF", "uni0314": "uni1FDF"}

# The dialytika a capital gets. Anchored like the plain one everywhere, but
# deliberately absent from the mark-to-mark stacking below, which is what keeps
# an accent after it beside the letter instead of on top of it. build.py draws
# it and imports the name from here, so the string is written once.
CAPITAL_DIALYTIKA = "uni0308.cap"

MARKS = {
    "acutecomb": "oxia", "acutecomb.grek": "oxia",
    "gravecomb": "varia", "gravecomb.grek": "varia",
    "uni0313": "psili", "uni0314": "dasia",
    "uni0342": "perispomeni", "uni0342.grek": "perispomeni",
    "uni0308": "dialytika", CAPITAL_DIALYTIKA: "dialytika",
    "uni0304": "macron",
}
BREATHINGS = ("uni0313", "uni0314")
ACCENTS = ("acutecomb", "acutecomb.grek", "gravecomb", "gravecomb.grek")
# Both drawings of the perispomeni, for the same reason as ACCENTS: build.py
# centres one on the other, so every rule has to name both and either may be the
# one that survives ccmp.
PERISPOMENI = ("uni0342", "uni0342.grek")

# Vowels carrying a macron or breve, and the plain letter each is built on.
BARRED = {
    "uni1FB1": "alpha", "uni1FB0": "alpha",
    "uni1FD1": "iota", "uni1FD0": "iota",
    "uni1FE1": "upsilon", "uni1FE0": "upsilon",
}

# Capitals hang their marks off the left of the letter instead of over it, and
# how far depends on the letter's own silhouette rather than on the marks. Those
# placements are hand-set in mark_greek.fea; what lives here is the cluster
# shift, because it shares a lookup with the derived one and first match wins --
# split across two lookups they would both fire and both shift.
#
# Every table below pairs with an allowance in grk_caps_room: that rule shifts
# the letter right and the mark travels with it, so the pull-back here is what
# decides where the mark ends up relative to the letter. Change one without the
# other and the space opens in front of the letter instead of beside it.
#
# The iota figures carry 40 units beyond what clearance alone asks for. Iota is
# the narrowest capital, so a mark hung beside it lands nearer the letter than
# the same mark does on Upsilon, and on the dialytika forms it is the dots the
# mark must clear -- they reach further left than the stem. Measured gap before
# the adjustment ran 2 to 48 units on iota against 165 to 416 on upsilon.
CAPITAL_PAIR = {
    "Alpha": -125, "uni1FB9": -125, "uni1FB8": -125,
    "Iota": -212, "uni1FD9": -212, "uni1FD8": -212, "Iotadieresis": -212,
    "Upsilon": -207, "uni1FE9": -207, "uni1FE8": -207, "Upsilondieresis": -207,
}
CAPITAL_PAIR_VARIA = {"Upsilon": -223, "uni1FE9": -223, "uni1FE8": -223,
                      "Upsilondieresis": -223,
                      "Iota": -212, "uni1FD9": -212, "uni1FD8": -212,
                      "Iotadieresis": -212,
                      "Alpha": -150, "uni1FB9": -150, "uni1FB8": -150}

# A lone psili beside a capital, which needs more room than its bounding box
# suggests: it matches the dasia's box exactly -- same width, same anchor -- but
# its tail hangs down and to the right, into the space the letter is reaching
# back into, so the two clear by very different amounts at the same nominal
# position. The iota values carry the extra 40 described above on top of that.
# Alpha is absent: its arm falls away from the mark rather than toward it.
CAPITAL_PSILI = {
    "Iota": -54, "uni1FD9": -54, "uni1FD8": -54, "Iotadieresis": -54,
    "Upsilon": -95, "uni1FE9": -95, "uni1FE8": -95, "Upsilondieresis": -95,
}

# Same for a bare accent, which is wider and steeper than either breathing and
# widens further in the bold faces, so no single figure equalises every face --
# these clear the tightest one. The iota values carry the extra 40 as well.
CAPITAL_ACCENT = {
    "Iota": -75, "uni1FD9": -75, "uni1FD8": -75, "Iotadieresis": -75,
    "Upsilon": -90, "uni1FE9": -90, "uni1FE8": -90, "Upsilondieresis": -90,
}

# Overrides CAPITAL_ACCENT for the oxia only. This is about direction, not fit:
# the acute leans up and to the right, so the further left it hangs the more it
# reads as pointing away from the letter, and the dots overhead leave nothing
# for the eye to connect it back to. The varia leans the other way and wants the
# ordinary figure, which is why this is keyed on the role rather than being a
# smaller number in the table above.
CAPITAL_ACCENT_OXIA = {
    "Upsilondieresis": -55,
}

# A perispomeni with no breathing under it -- the widest mark that hangs off a
# capital, 260 units against a breathing's 113. Unicode only ever encoded one on
# a capital paired with a breathing, so the font had no precedent for it alone.
CAPITAL_PERISPOMENI_SOLO = {
    "Iota": -127, "uni1FD9": -127, "uni1FD8": -127, "Iotadieresis": -127,
    "Upsilon": -122, "uni1FE9": -122, "uni1FE8": -122, "Upsilondieresis": -122,
    # Alpha is here although its arm falls away from the mark, because on the
    # barred forms the mark sits 50 units lower -- the bar takes the space above
    # -- and by that height the diagonal has spread under it. Contact begins at
    # 5 units; the rest is clearance. Bare Alpha does not need it and gets it
    # anyway, since the room rule keys on @GRK_CAPS_A and cannot tell the three
    # apart; that also keeps a perispomeni in one place whether or not the
    # letter carries a bar.
    #
    # Only rasterising finds this. Sampling contour points reports Alpha clear,
    # because the contact is with a diagonal edge and falls between the points.
    "Alpha": -45, "uni1FB9": -45, "uni1FB8": -45,
}

# A perispomeni stacked on a breathing, over a capital that also carries a bar --
# the one cluster tall enough to reach the macron. The breathing sits beside the
# letter, deliberately, so the bar keeps the space above to itself; the
# perispomeni then goes above the breathing, which lands it in the bar's own
# band. Neither mark is wrong about where it sits relative to the other, so the
# whole cluster moves left rather than either being nudged.
#
# Deliberately not CAPITAL_PAIR's numbers, though the problem looks the same:
# that table clears an accent sitting BESIDE a breathing, a wider cluster and a
# different measurement. Upsilon wants 96 units here against 207 there. Set so
# the tightest face clears with 20 of gap, which costs the loosest about 15.
CAPITAL_PERISPOMENI = {
    "uni1FB9": -132, "uni1FB8": -117,
    "uni1FD9": -227, "uni1FD8": -211,
    "uni1FE9": -116, "uni1FE8": -108,
}

# Precomposed dialytika stacks, to read that convention off the face itself.
DIALYTIKA_REFS = {"oxia": "uni1FD3", "varia": "uni1FD2", "perispomeni": "uni1FD7"}


def contours(font, name):
    """Flattened point lists, one per contour, with components resolved.

    Public because build.py needs the same reading of a composite to find the
    ypogegrammeni inside U+1FB3.
    """
    pen = DecomposingRecordingPen(font)
    font[name].draw(pen)
    out, cur = [], []
    for op, args in pen.value:
        if op == "moveTo":
            if cur:
                out.append(cur)
            cur = [args[0]]
        elif op in ("lineTo", "curveTo", "qCurveTo"):
            cur.extend(args)
        elif op == "closePath" and cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _box(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox(font, name):
    cs = contours(font, name)
    return _box([p for c in cs for p in c]) if cs else None


def _above(font, name, floor):
    pts = [p for c in contours(font, name) for p in c if p[1] > floor]
    return _box(pts) if pts else None


def _cx(b):
    return (b[0] + b[2]) / 2


# Marks that can legitimately appear in either order in a source text, because
# Unicode forbids normalisation from reordering them: a breathing and an accent
# are both combining class 230, so NFC leaves whatever order it was given.
BREATHING_CP = {0x0313, 0x0314}
ACCENT_CP = {0x0300, 0x0301, 0x0342}


def _codepoints(font):
    out = {}
    for glyph in font:
        for cp in glyph.unicodes or ():
            out.setdefault(cp, glyph.name)
    return out


def _reordered(font):
    """Rules for text that spells the accent before the breathing.

    Greek convention writes the breathing first, but nothing enforces it, and
    normalisation cannot correct it -- both marks are combining class 230, so
    NFC will not reorder them. Worse, it makes the problem harder to see: given
    alpha + oxia + psili it composes the accent into the vowel and leaves the
    breathing stranded on a precomposed glyph that has nowhere to put it. The
    breathing then lands at the pen position, which reads as an accent adrift to
    the right of the word.

    Every one of these spellings has a precomposed character that means exactly
    the same thing, so the fix is to substitute it: a two-glyph-to-one ligature
    in ccmp, before anything tries to position a mark. The pairs are read out of
    Unicode's own decomposition data rather than typed, so the set cannot drift.
    """
    cps = _codepoints(font)
    out = []
    for cp in range(0x1F00, 0x2000):
        target = cps.get(cp)
        if target is None:
            continue
        d = unicodedata.normalize("NFD", chr(cp))
        if len(d) < 3 or ord(d[1]) not in BREATHING_CP or ord(d[2]) not in ACCENT_CP:
            continue
        swapped = d[0] + d[2] + d[1] + d[3:]
        spelling = unicodedata.normalize("NFC", swapped)
        if spelling == chr(cp):
            continue
        names = [cps.get(ord(c)) for c in spelling]
        if any(n is None for n in names):
            continue
        out.append("    sub %s by %s;" % (" ".join(names), target))
    return out


def _equivalents(font):
    """Fold the deprecated marks onto the ones everything else is written for.

    U+0343 is canonically equivalent to U+0313 and U+0344 to U+0308 U+0301, so
    substituting them changes nothing about what the text says -- but a source
    that uses them would otherwise miss every rule written against the usual
    spellings. Older Greek texts and some OCR output still emit them.
    """
    cps = _codepoints(font)
    out = []
    for cp, replacement in ((0x0343, "̓"), (0x0344, "̈́")):
        src = cps.get(cp)
        names = [cps.get(ord(c)) for c in replacement]
        if src and all(names):
            out.append("    sub %s by %s;" % (src, " ".join(names)))
    return out


# The marks NFC folds into a capital. A composed glyph whose decomposition ends
# in one of these is one this module has to anchor; anything else is either not
# a capital or not a mark we place. Why that matters is in _composed_capitals.
CAPITAL_FOLDED = frozenset((0x0300, 0x0301, 0x0308, 0x0313,
                            0x0314, 0x0342, 0x0345))

# Greek and Coptic, and Greek Extended.
#
# Every mark in CAPITAL_FOLDED is shared with the Latin and Cyrillic blocks, and
# so is the shape of the problem -- Aacute, Adieresis and U+0401 all decompose to
# a capital plus one of those marks. Without this filter _composed_names picked
# them up too, and the rules written from it swapped the Latin acute for the
# Greek oxia on a Latin base. That drawing is a synthesised glyph with no .sfd
# anchors, so the Latin mark lookup stopped covering it and it fell to the
# origin: 27 non-Greek bases affected on Serif Regular, marks unattached on all
# of them. The test is on the BARE letter, which is what decides the script; the
# composed glyph follows it.
GREEK_BLOCKS = ((0x0370, 0x03FF), (0x1F00, 0x1FFF))

_ANCHOR_RE = re.compile(
    r"pos\s+base\s+(\S+)\s+<anchor\s+(-?\d+)\s+(-?\d+)>\s+mark\s+(@GRK_ABOVE|@GRK_BELOW)")


def _hand_set_anchors(fea):
    """The capital anchors as mark_greek.fea actually wrote them.

    Read rather than copied. These are judgement calls that belong in the
    feature file, but the composed capitals below are those same positions
    shifted, so the generator needs the numbers -- and a second copy of a value
    that already exists somewhere is the failure this whole module was written
    to avoid.
    """
    out = {"above": {}, "below": {}}
    for name, x, y, cls in _ANCHOR_RE.findall(fea or ""):
        out["above" if cls == "@GRK_ABOVE" else "below"][name] = (int(x), int(y))
    return out


def _resolve(font, name, depth=0):
    """Follow component references down to the glyph that owns the outlines.

    The faces are not consistent about this: one builds Alphatonos from 'A',
    another from 'Alpha' which is itself a component of 'A'. Resolving both ends
    to the same root is what lets the two be compared at all.
    """
    if depth > 4 or name not in font:
        return name, 0.0, 0.0
    glyph = font[name]
    if glyph.contours or len(glyph.components) != 1:
        return name, 0.0, 0.0
    c = glyph.components[0]
    root, dx, dy = _resolve(font, c.baseGlyph, depth + 1)
    return root, dx + c.transformation[4], dy + c.transformation[5]


def _letter_body(font, name, frac=0.2):
    """Optical centre of the letter itself, ignoring anything folded in beside it.

    The letter is the largest contour. A Greek capital's body dwarfs a breathing
    or an accent, and the pieces that are not the body -- a counter, the dots of
    a dieresis -- are smaller still, so "largest" picks out the letter without
    having to know which mark is present.

    Measured across the top of that contour rather than over its whole box, for
    the slant reason in _top_centre.
    """
    cs = contours(font, name)
    if not cs:
        return None
    boxes = [(_box(c), c) for c in cs]
    b, body = max(boxes, key=lambda kv: ((kv[0][2] - kv[0][0])
                                         * (kv[0][3] - kv[0][1])))
    floor = b[3] - (b[3] - b[1]) * frac
    xs = [x for x, y in body if y >= floor]
    return (min(xs) + max(xs)) / 2 if xs else _cx(b)


def _letter_shift(font, composed, bare):
    """How far the letter moved inside the composed glyph, in font units.

    Exact where the face builds the glyph as a composite, which most do. Where it
    is drawn as outlines instead -- 88% of Serif Italic's composed capitals and
    75% of Bold Italic's -- locate the letter in both glyphs and difference them.

    This used to compare the bounding-box edge that the added mark cannot have
    moved, which needed to know which side the mark hung on and, underneath that,
    assumed the composed glyph was the bare one translated. On the slanted faces
    it is redrawn rather than moved, so there is no translation for an edge to
    recover: the dialytika on Serif Italic's U+1F68 came out 47 units right of
    the letter's own centre, which is visible. Measuring the letter itself needs
    neither assumption, and is side-agnostic because a centre has no sides.

    Checked against the 288 composed capitals across the faces that do carry a
    resolvable component -- the ones with an exact answer to compare to -- this
    reproduces the component offset in every single case, where the edge
    comparison was out by up to 102 units.

    Only x is measured: not one of those 288 moves the letter vertically.
    """
    root, bx, by = _resolve(font, bare)
    for c in font[composed].components:
        croot, cdx, cdy = _resolve(font, c.baseGlyph)
        if croot == root:
            return (c.transformation[4] + cdx - bx,
                    c.transformation[5] + cdy - by)

    cc, bc = _letter_body(font, composed), _letter_body(font, bare)
    if cc is None or bc is None:
        return None
    return cc - bc, 0.0


def _composed_names(font):
    """(composed capital, bare capital) for each one NFC produces.

    Shared by the anchor generator and the Greek-drawing substitution so the two
    cannot disagree about which bases exist -- they did once, and the marks on
    every composed capital silently kept their Latin drawing.

    Greek only; see GREEK_BLOCKS for what goes wrong without that.
    """
    cps = _codepoints(font)
    for cp in sorted(cps):
        name = cps[cp]
        d = unicodedata.normalize("NFD", chr(cp))
        if len(d) != 2 or not d[0].isupper():
            continue
        if not any(lo <= ord(d[0]) <= hi for lo, hi in GREEK_BLOCKS):
            continue
        bare = cps.get(ord(d[0]))
        if bare is None or name == bare or ord(d[1]) not in CAPITAL_FOLDED:
            continue
        yield name, bare


def _grek_on_composed(font, marks):
    """Extend the Greek-drawing substitution to the composed capitals.

    mark_greek.fea keys that substitution on @GRK_MARK_BASE, which lists the
    bases it can name at parse time -- the plain letters and the barred vowels.
    The composed capitals are enumerated from Unicode here rather than listed
    there, so they have to be added from this side or a mark landing on one
    keeps the Latin drawing: an acute rather than an oxia, and for the
    perispomeni the Latin tildecomb outright.

    Reuses the lookups mark_greek.fea already defines, which is why this must be
    written after it -- and being later also puts it after the reorder rules, so
    those still only ever have to match the plain drawing of a mark.
    """
    rules = []
    for plain, guard, lookup in (
            ("acutecomb", "acutecomb.grek", "grk_shape_oxia"),
            ("gravecomb", "gravecomb.grek", "grk_shape_varia"),
            ("uni0342", "uni0342.grek", "grk_shape_perisp"),
            # Same split for the capital dialytika: mark_greek.fea covers the
            # capitals it can name, this covers the composed ones.
            ("uni0308", CAPITAL_DIALYTIKA, "grk_dial_to_cap")):
        if guard not in marks:
            continue
        for name, _ in _composed_names(font):
            rules.append("    sub %s %s' lookup %s;" % (name, plain, lookup))
            if plain != "uni0308":
                rules.append("    sub %s @GRK_TWEEN %s' lookup %s;"
                             % (name, plain, lookup))
    return rules


def _composed_capitals(font, hand, marks, ink, cls):
    """Base anchors for the capitals normalisation has already composed.

    NFC folds a capital and its first mark into one glyph before the second mark
    arrives -- Alpha plus oxia becomes Alphatonos, Iota plus dialytika becomes
    Iotadieresis -- and the hand-set anchors are written for the bare capital, so
    without these the second mark has nothing to attach to. Lowercase never shows
    the problem: it has a precomposed character for the whole stack.

    The set is enumerated from Unicode decomposition data rather than listed, so
    it cannot drift as coverage changes. Placement follows the same rule the bare
    capitals use, shifted by however far the composed glyph moved the letter --
    except for the dialytika, which goes over the letter rather than beside it.
    """
    if not (hand["above"] or hand["below"]):
        return []
    rows = []
    for name, bare in _composed_names(font):
        shift = _letter_shift(font, name, bare)
        if shift is None:
            continue

        # A dialytika goes over the letter whatever else the capital carries,
        # so it is placed first and independently of the anchors below.
        if "uni0308" in marks:
            lb = _bbox(font, bare)
            if lb:
                # Centred on the letter at the height the dots occupy, not on
                # its bounding box: the two agree on the uprights and differ by
                # 58 units on Serif Italic's Iota. See _top_centre.
                dcx = _top_centre(font, bare) + shift[0]
                # Raised over whatever is actually beneath the dots rather than
                # over the whole composite. The breathing folded in here sits up
                # and to the left, clear of them on the uprights, but the italics
                # lean it right until it is underneath.
                half = (ink["uni0308"][2] - ink["uni0308"][0]) / 2
                over = _top_within(font, name, dcx - half, dcx + half)
                top = max(lb[3] + shift[1], over if over is not None else 0)
                # Both drawings: the capital form is what ccmp substitutes in,
                # the plain one is the fallback if that rule ever misses.
                for dn in ("uni0308", CAPITAL_DIALYTIKA):
                    if dn in marks:
                        rows.append(
                            "    pos base %-16s <anchor %5d %5d> mark %s;"
                            % (name, round(dcx),
                               round(top + _dialytika_gap(font)), cls[dn]))

        # Everything else hangs off the left shoulder, exactly as it does on a
        # capital carrying no folded mark at all -- accents and breathings
        # alike. Emitted whenever the bare capital has an above anchor, without
        # regard to what is already folded in, because a second mark has to land
        # somewhere whichever the first one was.
        #
        # Lowercase disagrees about the accent, and that is not an
        # inconsistency: U+1FD3 tucks it between the dots because a lowercase
        # vowel has nowhere else to put it. A capital does. The dots mark how
        # the vowel is pronounced and sit over it; accents and breathings mark
        # the word and sit beside it.
        above = hand["above"].get(bare)
        if above:
            for n in sorted(marks):
                if MARKS[n] == "dialytika":
                    continue            # placed over the letter, above
                rows.append("    pos base %-16s <anchor %5d %5d> mark %s;"
                            % (name, round(above[0] + shift[0]),
                               round(above[1] + shift[1]), cls[n]))

        # The only below-mark is the ypogegrammeni, which this module does not
        # own -- it has no clearance to derive, so mark_greek.fea keeps both its
        # markClass and its anchors. Point at that class rather than inventing a
        # second one for the same glyph.
        below = hand["below"].get(bare)
        if below:
            rows.append("    pos base %-16s <anchor %5d %5d> mark @GRK_BELOW;"
                        % (name, round(below[0] + shift[0]),
                           round(below[1] + shift[1])))
    return rows


def _over_breathing(font, breathing):
    """(lean, gap) for a perispomeni stacked on this breathing, per face.

    Read out of the face's own U+1FCF or U+1FDF, which draw exactly this pair as
    a single mark. Those glyphs are composites of the breathing and U+1FC0, so
    the two halves can be located exactly rather than guessed at from contours.

    The constant this replaces was 13 for every face. Serif Regular's own answer
    is 23 and Sans Bold's is 16 -- not a large error on its own, but it is the
    kind that only moves in one direction as a design is revised, and it had
    already outlived the mark it was measured against: the perispomeni was the
    Latin tildecomb when 13 was chosen.
    """
    ref = PERISPOMENI_REFS.get(breathing)
    if ref is None or ref not in font or breathing not in font:
        return None
    parts = {c.baseGlyph: c.transformation[4:6] for c in font[ref].components}
    per = next((n for n in parts if n in ("uni1FC0", "uni0342", "uni0342.grek")), None)
    br = next((n for n in parts if n != per), None)
    if per is not None and br is not None:
        pb, bb = _bbox(font, per), _bbox(font, br)
        if pb and bb:
            pdx, pdy = parts[per]
            bdx, bdy = parts[br]
            # both halves placed inside the reference glyph
            p = (pb[0] + pdx, pb[1] + pdy, pb[2] + pdx, pb[3] + pdy)
            b = (bb[0] + bdx, bb[1] + bdy, bb[2] + bdx, bb[3] + bdy)
            return _cx(p) - _cx(b), p[1] - b[3]

    # Drawn as outlines rather than assembled -- Serif Italic, Display and Math
    # all do. Split by height instead: the perispomeni is the flat one, barely a
    # third as tall as the breathing, so a simple aspect test separates them
    # where a bounding box comparison would not.
    cs = contours(font, ref)
    if len(cs) < 2:
        return None
    boxes = [_box(c) for c in cs]
    flat = [b for b in boxes if (b[3] - b[1]) < (b[2] - b[0]) * 0.75]
    tall = [b for b in boxes if b not in flat]
    if not flat or not tall:
        return None
    p = _box([(b[0], b[1]) for b in flat] + [(b[2], b[3]) for b in flat])
    b = _box([(b[0], b[1]) for b in tall] + [(b[2], b[3]) for b in tall])
    return _cx(p) - _cx(b), p[1] - b[3]


def _dialytika_offsets(font):
    """How far the face's own precomposed stacks lean and drop an accent.

    Read off U+1FD3, U+1FD2 and U+1FD7 rather than assumed: the accent drops
    INTO the gap between the dots rather than clearing them, which is what keeps
    the stack compact and is impossible to guess from bounding boxes -- the
    stack is barely taller than the dots alone.

    Returns {role: (lean, rise)} in font units, both relative to the dots: lean
    from dot-centre to accent-centre, rise from the dots' top to the accent's
    ink bottom. A negative rise means it really does drop in.
    """
    if "iotadieresis" not in font or "iota" not in font:
        return {}
    floor = _bbox(font, "iota")[3]
    dot = [c for c in contours(font, "iotadieresis") if _box(c)[1] > floor]
    if len(dot) != 2:
        return {}
    dw = _box(dot[0])[2] - _box(dot[0])[0]
    dh = _box(dot[0])[3] - _box(dot[0])[1]

    out = {}
    for role, ref in DIALYTIKA_REFS.items():
        if ref not in font:
            continue
        cs = [c for c in contours(font, ref) if _box(c)[1] > floor]
        # Separate the accent from the dots by shape, not by bounding box.
        acc = [c for c in cs
               if not (abs((_box(c)[2] - _box(c)[0]) - dw) < dw * 0.25
                       and abs((_box(c)[3] - _box(c)[1]) - dh) < dh * 0.25)]
        keep = [c for c in cs if c not in acc]
        if not acc or len(keep) != 2:
            continue
        ab = _box([p for c in acc for p in c])
        db = _box([p for c in keep for p in c])
        out[role] = (_cx(ab) - _cx(db), ab[1] - db[3])
    return out


def _dialytika_gap(font):
    """How high this face sets its own dots above a capital.

    Read off Iotadieresis rather than reused from GAP_OVER_BAR, which answers
    the different question of clearing a macron.
    """
    if "Iotadieresis" in font and "Iota" in font:
        letter = _bbox(font, "Iota")
        # Contours lying ENTIRELY above the letter, not points above a floor set
        # just under its top: the second catches the I's own serif, which puts
        # the dots' bottom level with the letter and reports a gap of nothing.
        if letter:
            dots = [c for c in contours(font, "Iotadieresis")
                    if min(y for _, y in c) > letter[3]]
            if dots:
                return min(y for c in dots for _, y in c) - letter[3]
    return GAP_OVER_BAR["dialytika"]


def _top_centre(font, name, frac=0.2):
    """Ink centre near the top of a glyph, where an above-mark actually sits.

    An upright letter's bounding box is centred on its stem and this returns the
    same answer. A slanted one is not: the stem leans out of the box as it
    rises, so the box centre describes where the letter is on average rather
    than where it is up at cap height. Serif Italic's Iota differs by 58 units
    between the two, which is most of a dot.
    """
    b = _bbox(font, name)
    if not b:
        return None
    floor = b[3] - (b[3] - b[1]) * frac
    xs = [x for c in contours(font, name) for x, y in c if y >= floor]
    return (min(xs) + max(xs)) / 2 if xs else _cx(b)


def _top_within(font, name, x0, x1):
    """Highest ink in this glyph between two x positions.

    A mark only has to clear what is actually underneath it. Using the whole
    glyph's top instead would lift a dialytika over a breathing that sits well
    off to the left and never comes near it.
    """
    ys = [y for c in contours(font, name) for x, y in c if x0 <= x <= x1]
    return max(ys) if ys else None


def _capital_dialytika(font, hand, marks, cls):
    """Put the dialytika above a capital rather than off its left shoulder.

    mark_greek.fea hangs a capital's marks to the upper left, which is right for
    a breathing or an accent and wrong for this one: the dialytika is more than
    twice as wide, so the same anchor drives its right dot into the letter.

    The height is read off the face's own Iotadieresis rather than reused from
    GAP_OVER_BAR, because that constant describes clearing a macron and this is
    the different question of how high the font likes its own dots to sit. The
    gap is then applied over whatever the base's ink tops out at, which is the
    bar on U+1FD9 and the cap height on a bare Iota, so one measurement serves
    both without knowing which it is looking at.
    """
    if "uni0308" not in marks:
        return []
    gap = _dialytika_gap(font)

    bycp = _codepoints(font)
    cps = {}
    for cp, n in bycp.items():
        cps.setdefault(n, cp)

    rows = []
    for name in sorted(hand["above"]):
        cp = cps.get(name)
        if cp is None or not chr(cp).isupper():
            continue
        b = _bbox(font, name)
        if not b:
            continue

        # Centre on the bar, not on the glyph, wherever there is one. The
        # dialytika sits directly on top of a macron or breve, so the bar is
        # what it has to look centred against -- and the two centres are not the
        # same. An italic letter leans out from under its own bar, dragging the
        # glyph's bounding box with it, so centring on the box walks the dots
        # off the end of the bar in exactly the faces where it shows most.
        over = None
        d = unicodedata.normalize("NFD", chr(cp))
        if len(d) == 2 and ord(d[1]) in (0x0304, 0x0306):
            plain = bycp.get(ord(d[0]))
            pb = _bbox(font, plain) if plain else None
            if pb:
                bar = [c for c in contours(font, name)
                       if min(y for _, y in c) > pb[3]]
                if bar:
                    over = _box([p for c in bar for p in c])
        # Centre on the bar where there is one -- it is a horizontal edge, so its
        # own centre is the right target. Otherwise use the letter's ink near the
        # top rather than its box, for the slant reason in _top_centre.
        if over:
            cx, top = _cx(over), over[3]
        else:
            cx, top = _top_centre(font, name), b[3]
        for dn in ("uni0308", CAPITAL_DIALYTIKA):
            if dn in marks:
                rows.append("    pos base %-16s <anchor %5d %5d> mark %s;"
                            % (name, round(cx), round(top + gap), cls[dn]))
    return rows


def _pair_shifts(font, marks, ink):
    """Every context in which a mark has to move sideways from its own anchor.

    Returns (backtrack, mark, dx, lookahead) tuples in the order they must be
    tested: within a contextual lookup the first matching rule wins, so the
    longer clusters are written before the rules that would also match a prefix
    of them.

    These used to be contextual GPOS -- `pos br' <dx 0 0 0> acc` -- which is the
    direct way to say it and does not work: luaotfload's node renderer, the
    default for LuaLaTeX, silently drops a chained contextual GPOS adjustment
    when the target is a mark. It applies the same construct on a base glyph
    (grk_caps_room in mark_greek.fea still relies on that), and it applies
    chained contextual GSUB on marks, so what is left is to say it as a
    substitution: swap the mark for a variant drawn dx to the left and let plain
    mark-to-base put it there. See the note above generate() for the numbers.
    """
    out = []

    def rule(back, mark, dx, ahead):
        out.append((tuple(back), mark, int(round(dx)), tuple(ahead)))

    for cap, dx in sorted(CAPITAL_PAIR.items()):
        if cap not in font:
            continue
        for br in BREATHINGS:
            if br not in marks:
                continue
            for acc in ACCENTS:
                if acc not in marks:
                    continue
                v = CAPITAL_PAIR_VARIA[cap] if MARKS[acc] == "varia" else dx
                rule([cap], br, v, [acc])
    # Same idea for a perispomeni stacked on a breathing, which is the only
    # cluster tall enough to reach a capital's bar. Written before the single
    # breathing rules below for the same first-match-wins reason.
    for cap, dx in sorted(CAPITAL_PERISPOMENI.items()):
        if cap not in font:
            continue
        for br in BREATHINGS:
            if br not in marks:
                continue
            for per in PERISPOMENI:
                if per in marks:
                    rule([cap], br, dx, [per])

    # An accent after a dialytika. Three glyphs, so it has to be written
    # separately from the two-glyph rule further down -- and it pairs with a
    # matching three-glyph allowance in grk_caps_room, because the shift there
    # moves the letter and the mark together and only this pulls the mark back.
    for cap, dx in sorted(CAPITAL_ACCENT.items()):
        if cap not in font:
            continue
        for dial in ("uni0308", CAPITAL_DIALYTIKA):
            if dial not in marks:
                continue
            for acc in ACCENTS:
                if acc not in marks:
                    continue
                v = CAPITAL_ACCENT_OXIA.get(cap, dx) if MARKS[acc] == "oxia" else dx
                rule([cap, dial], acc, v, [])

    for br in BREATHINGS:
        if br not in marks:
            continue
        bw = ink[br][2] - ink[br][0]
        for acc in ACCENTS:
            if acc not in marks:
                continue
            aw = ink[acc][2] - ink[acc][0]
            gap = GAP_IN_CLUSTER[MARKS[acc]]
            shift = (bw + gap + aw) / 2 - bw / 2
            rule([], br, -round(shift), [acc])
    # Single breathing on a capital. These come after the cluster rules: within
    # a contextual lookup the first matching rule wins, so the pairs are already
    # claimed by the time we get here.
    for cap, dx in sorted(CAPITAL_PSILI.items()):
        if cap in font and "uni0313" in marks:
            rule([cap], "uni0313", dx, [])
    for cap, dx in sorted(CAPITAL_ACCENT.items()):
        if cap not in font:
            continue
        for acc in ACCENTS:
            if acc in marks:
                v = CAPITAL_ACCENT_OXIA.get(cap, dx) if MARKS[acc] == "oxia" else dx
                rule([cap], acc, v, [])
    for cap, dx in sorted(CAPITAL_PERISPOMENI_SOLO.items()):
        if cap not in font:
            continue
        for per in PERISPOMENI:
            if per in marks:
                rule([cap], per, dx, [])
    return out


def _mark_ink(font):
    """The mark glyphs this face has, and their bounding boxes, or (None, None).

    Same test generate() makes, so the two agree about which faces get Greek
    treatment at all.
    """
    if "alpha" not in font:
        return None, None
    marks = {n: r for n, r in MARKS.items() if n in font}
    if not marks or any(_bbox(font, n) is None for n in marks):
        return None, None
    return marks, {n: _bbox(font, n) for n in marks}


def pair_variants(font):
    """{mark: {dx: variant name}} -- every shifted copy this face needs.

    Wanted before the feature file is preprocessed, because the classes that
    match a breathing as *context* have to name the variants too, and a glyph
    class cannot be extended after it is defined. See shift_classes().
    """
    marks, ink = _mark_ink(font)
    if not marks:
        return {}
    shifts = {}
    for _, mark, dx, _ in _pair_shifts(font, marks, ink):
        shifts.setdefault(mark, {}).setdefault(dx, variant_name(mark, dx))
    return shifts


# The role each shifted class covers, and the class name mark_greek.fea knows it
# by. Named per role rather than per glyph because that is how the hand-written
# rules already think -- an oxia is an oxia whichever drawing survived ccmp.
SHIFT_CLASSES = {
    "oxia": "@GRK_SH_OXIA", "varia": "@GRK_SH_VARIA",
    "perispomeni": "@GRK_SH_PERISP",
    "psili": "@GRK_SH_PSILI", "dasia": "@GRK_SH_DASIA",
}


def shift_classes(font):
    """Glyph classes naming each mark together with its shifted copies.

    Written ahead of mark_greek.fea rather than after it, which is the whole
    reason this is a separate function: that file matches a breathing and an
    accent as context when it makes room beside a capital, and after the
    substitution the glyph sitting there is a variant. A class that did not name
    it would quietly stop matching, the capital would keep its narrow advance,
    and the marks would pile onto the letter.

    Each class carries the originals as well, so it is a drop-in replacement for
    the plain list it stands in for.
    """
    marks, _ = _mark_ink(font)
    if not marks:
        return ""
    shifts = pair_variants(font)
    L = ["# " + "-" * 70,
         "# Marks and their shifted copies, from tools/greek_anchors.py.",
         "# " + "-" * 70]
    for role in sorted(set(SHIFT_CLASSES)):
        members = []
        for n in sorted(marks):
            if MARKS[n] != role:
                continue
            members.append(n)
            members += [shifts[n][d] for d in sorted(shifts.get(n, {}))]
        if members:
            L.append("%s = [%s];" % (SHIFT_CLASSES[role], " ".join(members)))
    return "\n".join(L) + "\n\n"


def variant_name(mark, dx):
    """The glyph name for `mark` drawn `dx` units to the left.

    Named here rather than in build.py for the same reason CAPITAL_DIALYTIKA is:
    the rules that name the glyph and the code that draws it have to agree, so
    the string is written once.
    """
    return "%s.p%d" % (mark, -dx)


def generate(font, fea=""):
    """Return the .fea text for this face, or "" if it has no Greek to anchor.

    Returning nothing is right for Keyboard and Initials, which have no Greek at
    all. It would be the wrong answer for a face missing a single mark -- that
    face would silently lose every Greek anchor -- so say so rather than guess.
    """
    if "alpha" not in font:
        return ""
    marks = {n: r for n, r in MARKS.items() if n in font}
    if not marks:
        return ""
    missing = [n for n in marks if _bbox(font, n) is None]
    if missing:
        print("  greek_anchors: no anchors emitted, empty glyphs: %s"
              % " ".join(sorted(missing)))
        return ""
    ink = {n: _bbox(font, n) for n in marks}

    # Parsed once and passed down, rather than by each consumer separately. It
    # is a regex over another file's formatting, so it can stop matching without
    # anything else changing -- and the failure is silent, every capital anchor
    # simply absent from the output. Say so rather than emit a quietly smaller
    # feature file.
    hand = _hand_set_anchors(fea)
    if fea and not (hand["above"] or hand["below"]):
        print("  greek_anchors: no hand-set capital anchors matched in "
              "mark_greek.fea, so capitals will be left unanchored -- check "
              "_ANCHOR_RE still matches how that file writes 'pos base'")

    cls = {n: "@MCG_%s" % n.replace(".", "_") for n in marks}
    L = ["", "# " + "-" * 70,
         "# Greek mark anchors, derived from this face by tools/greek_anchors.py.",
         "# Rebuild rather than edit; the clearances live in that file.",
         "# " + "-" * 70, ""]

    # Worked out before the anchors because the variants join their original's
    # mark class. build.py has already drawn them -- it needs the same list
    # earlier still, to write the context classes ahead of mark_greek.fea.
    pair_rules = _pair_shifts(font, marks, ink)
    shifts = pair_variants(font)

    # One class per mark, anchored at its ink centre and ink bottom, so a base
    # anchor below reads as "put the bottom centre of the mark here". One class
    # per mark rather than one shared class is what lets each base/mark pair
    # keep its own clearance.
    #
    # A shifted variant joins its original's class and takes the original's
    # anchor, not its own ink centre: the drawing has already moved, so reading
    # the anchor off it a second time would move it twice. Sharing the class is
    # also what keeps every base rule below written once instead of once per
    # variant.
    for n in sorted(marks):
        b = ink[n]
        names = [n] + [shifts[n][d] for d in sorted(shifts.get(n, {}))]
        target = names[0] if len(names) == 1 else "[%s]" % " ".join(names)
        L.append("markClass %-16s <anchor %5d %5d> %s;"
                 % (target, round(_cx(b)), round(b[1]), cls[n]))

    def base_rule(base, mark, x, bottom):
        return ("    pos base %-10s <anchor %5d %5d> mark %s;"
                % (base, round(x), round(bottom), cls[mark]))

    L += ["", "feature mark {", "  lookup grkgen_above {"]
    for base, letter in BARRED.items():
        if base not in font or letter not in font:
            continue
        bar = _above(font, base, _bbox(font, letter)[3] + 5)
        if not bar:
            continue
        for n, role in sorted(marks.items()):
            L.append(base_rule(base, n, _cx(bar), bar[3] + GAP_OVER_BAR[role]))
    L.append("  } grkgen_above;")

    # The one above-mark that does not hang off a capital's left shoulder.
    caps_dial = _capital_dialytika(font, hand, marks, cls)
    if caps_dial:
        L += ["", "  lookup grkgen_capdial {"] + caps_dial + ["  } grkgen_capdial;"]

    # Capitals that normalisation composed before the second mark arrived.
    composed = _composed_capitals(font, hand, marks, ink, cls)
    if composed:
        L += ["", "  lookup grkgen_composed {"] + composed + ["  } grkgen_composed;"]

    # The rules that centre a breathing-and-accent cluster are no longer GPOS;
    # they are emitted as substitutions further down. See _pair_shifts.
    L.append("} mark;")

    # --- mark to mark ------------------------------------------------------
    L += ["", "feature mkmk {", "  lookup grkgen_mkmk {"]

    def mark_rule(base, mark, x, y):
        """The mark-to-mark rule for `base`, plus one per shifted variant of it.

        A variant is the same drawing moved dx sideways, and it keeps its
        original's mark-to-base anchor, so its own origin lands where the
        original's would and everything measured in its glyph space has moved
        with the ink. The anchor an accent attaches to is measured in exactly
        that space, so it moves by the same dx -- otherwise the breathing slides
        out from under the accent instead of carrying it along.
        """
        rules = [("    pos mark %-10s <anchor %5d %5d> mark %s;"
                  % (base, round(x), round(y), cls[mark]))]
        for d in sorted(shifts.get(base, {})):
            rules.append("    pos mark %-10s <anchor %5d %5d> mark %s;"
                         % (shifts[base][d], round(x) + d, round(y), cls[mark]))
        return rules

    for br in BREATHINGS:
        if br not in marks:
            continue
        b = ink[br]
        for acc in ACCENTS:
            if acc not in marks:
                continue
            a = ink[acc]
            step = (b[2] - b[0]) / 2 + GAP_IN_CLUSTER[MARKS[acc]] + (a[2] - a[0]) / 2
            # centres level: the two shapes differ in height, and aligning an
            # edge instead shows the whole difference at one end.
            mid = (b[1] + b[3]) / 2
            L.extend(mark_rule(br, acc, _cx(b) + step, mid - (a[3] - a[1]) / 2))
        over = _over_breathing(font, br)
        lean, gap = over if over else (0, GAP_OVER_BREATHING)
        for per in PERISPOMENI:
            if per in marks:
                L.extend(mark_rule(br, per, _cx(b) + lean, b[3] + gap))

    # An accent over a macron: centred on the bar.
    if "uni0304" in marks:
        m = ink["uni0304"]
        for acc in ACCENTS:
            if acc in marks:
                L.extend(mark_rule("uni0304", acc, _cx(m),
                                   m[3] + GAP_OVER_BAR[MARKS[acc]]))

    # An accent over a dialytika, read off the face's own precomposed stacks:
    # the accent leans aside and drops into the gap between the dots rather than
    # clearing them, which is what keeps the stack compact.
    if "uni0308" in marks:
        d = ink["uni0308"]
        for role, (lean, rise) in sorted(_dialytika_offsets(font).items()):
            for n in [n for n in marks if MARKS[n] == role]:
                L.extend(mark_rule("uni0308", n, _cx(d) + lean, d[3] + rise))
    L += ["  } grkgen_mkmk;", "} mkmk;"]

    # Substitutions. These are GSUB and run before any of the positioning above,
    # whatever order they appear in the file; the order that does matter is
    # among themselves, and the Greek-drawing swap has to come last so the two
    # before it only ever match the plain drawing of a mark.
    equiv, reord = _equivalents(font), _reordered(font)
    grek = _grek_on_composed(font, marks)

    # One lookup per distinct shift rather than one per mark: several marks move
    # by the same amount in different contexts, and a single-substitution lookup
    # can carry all of them because each names its own destination.
    for dx in sorted({d for _, _, d, _ in pair_rules}):
        body = ["    sub %-16s by %s;" % (m, shifts[m][dx])
                for m in sorted(shifts) if dx in shifts[m]]
        name = "grkgen_shift_%d" % -dx
        L += ["", "lookup %s {" % name] + body + ["} %s;" % name]

    def pair_sub(back, mark, dx, ahead):
        ctx = " ".join(list(back) + ["%s'" % mark, "lookup grkgen_shift_%d" % -dx]
                       + list(ahead))
        return "    sub %s;" % ctx

    pairs = [pair_sub(*r) for r in pair_rules]

    if equiv or reord or grek or pairs:
        L += ["", "feature ccmp {"]
        if equiv:
            L += ["  lookup grkgen_equiv {"] + equiv + ["  } grkgen_equiv;"]
        if reord:
            L += ["  lookup grkgen_reorder {"] + reord + ["  } grkgen_reorder;"]
        L += grek
        # Last, and after the drawing swaps above on purpose. Which variant a
        # mark takes depends on the width of the accent beside it, and the two
        # drawings of an accent are different widths, so a rule that matched
        # before the swap would pick the shift measured for the other one.
        if pairs:
            L += ["  lookup grkgen_pair {"] + pairs + ["  } grkgen_pair;"]
        L.append("} ccmp;")
    return "\n".join(L) + "\n"
