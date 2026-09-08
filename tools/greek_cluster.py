"""Make a Greek cluster render the same however its marks were typed.

Greek writes at most one mark from each of five slots over a vowel -- a length
mark, a breathing, a dialytika, an accent, a ypogegrammeni -- and Unicode gives
every one of the first four combining class 230. Equal classes are exactly what
normalisation is forbidden to reorder, so the order the marks reach the font in
is whatever the keyboard, the IME or the file happened to use, and the font is
the last thing in the chain that can do anything about it.

Answering that one inversion at a time does not scale. The cases are indexed by
(which pair is inverted) x (how far composition got before the stray mark
arrived) x (precomposed or atomic input, because HarfBuzz normalises before GSUB
and DirectWrite does not), so every new input device lands in a cell nobody has
written a rule for. This module works in three stages instead, linear rather
than combinatorial:

  decompose -- every precomposed Greek letter is taken apart into its base and
    its marks. This is the load-bearing step. After it there is exactly one
    representation of a cluster regardless of what the shaper's normalisation
    did or what the keyboard sent, so nothing downstream has to be written twice
    for the two shapers, and nothing has to know whether composition had already
    happened.

  sort -- the marks are put in Unicode's own canonical order. GSUB cannot move a
    glyph, but a chaining context can rewrite two of them in place: the first
    becomes the second and the second becomes the first, which is the same
    thing.

  compose -- the canonical sequence is folded back into a precomposed glyph
    wherever Unicode has one, longest match first. What has no precomposed form
    falls through to the anchors in mark_greek.fea, which is the case that file
    exists for.

In the common case the first and third stages cancel exactly and the glyph
stream is unchanged, which is also how this is checked: see
tools/check_clusters.py, which shapes every ordering of every letter-and-mark
set and reports the ones that disagree.

Everything below is derived from Unicode's own decomposition data rather than
typed out, so the coverage cannot drift as the font's does. What is typed is the
slot order, which is a fact about Greek rather than about this font.
"""

import itertools
import unicodedata

# Greek and Coptic, and Greek Extended. Every rule either generator writes is
# restricted to a base from here, and has to be: the marks are shared with Latin
# and Cyrillic, so a rule keyed on a mark alone reaches Aacute and U+0401 as
# readily as it reaches alpha. On this side that would reorder a Latin spelling
# Unicode does distinguish; on the anchor side it redraws a Latin mark, which is
# what _composed_names in greek_anchors describes.
GREEK_BLOCKS = ((0x0370, 0x03FF), (0x1F00, 0x1FFF))

# The slots, in the order Unicode's decompositions put them, and the marks that
# fill each. The numbers are only used for their order; the gaps leave room to
# insert a slot without renumbering.
#
# Breathing and dialytika never co-occur -- Unicode encodes no character with
# both -- so their relative order is a free choice, and it is made the way
# Unicode's decompositions would have made it had the question ever come up.
SLOTS = (
    (10, (0x0304, 0x0306)),           # macron, breve
    (20, (0x0313, 0x0314)),           # psili, dasia
    (30, (0x0308,)),                  # dialytika
    (40, (0x0301, 0x0300, 0x0342)),   # oxia, varia, perispomeni
    (50, (0x0345,)),                  # ypogegrammeni
)

# One mark per slot, so this is also the longest cluster the sort has to handle.
MAX_CLUSTER = len(SLOTS)

# The slot the accents fill. A mark from an earlier slot can stand between a
# base and an accent once composition has folded part of the cluster into the
# letter, which is what the drawing rules below have to see past.
ACCENT_SLOT = 40

# The marks that can stand between a base and a later one after composition has
# run -- a breathing folded in beside a macron, say. Used as backtrack context,
# where a class is cheaper than enumerating the sequences.
MAX_TWEEN = MAX_CLUSTER - 2

# The Latin drawing of each mark and the Greek one that replaces it over a Greek
# base. build.py draws the Greek copies; why they are needed at all is above
# GREEK_MARKS there.
#
# These three are the marks that differ enough to be worth a lookup:
#
#     acutecomb  159x162     U+1FFD oxia         124x183
#     gravecomb  158x163     U+1FEF varia        128x177
#     uni0342    278x106     U+1FC0 perispomeni  260x93
#
# The breathings are deliberately absent. They do split -- U+0313 is 113x182
# against U+1FBF's 107x179, U+0314 113x182 against U+1FFE's 110x179 -- but six
# units of width is under half what the accents show, and substituting them
# would spend a lookup to move a mark by three units.
#
# The swap this feeds is keyed on the BASE, not on `script grek`. A script
# statement only reaches runs the shaper tagged as Greek, and the tag is not a
# property of the text: a Greek word inside a Latin paragraph is routinely
# tagged latn, and the same sequence would then take the Latin mark while the
# precomposed vowel beside it kept the Greek one -- which is the mismatch the
# swap exists to remove.
SHAPES = {
    "acutecomb": "acutecomb.grek",
    "gravecomb": "gravecomb.grek",
    "uni0342": "uni0342.grek",
}

# The two glyphs build.py draws for capitals; what each is for is above
# CAPITAL_DIALYTIKA and ADSCRIPT there. Named here because all three files have
# to agree on the strings -- build.py draws the glyphs, this file substitutes
# them in, greek_anchors places them -- and both of the others import them from
# here, so each is written once.
#
# The adscript is a MARK, not the spacing U+1FBE it is copied from: it has to be
# placed per letter, because the face's own composites place it differently on
# each -- 605 units along on Alpha, 616 on Eta, 589 on Omega -- and only a mark
# anchor can say that.
CAPITAL_DIALYTIKA = "uni0308.cap"
ADSCRIPT = "uni0345.cap"
ADSCRIPT_SOURCE = "uni1FBE"

# The accents ccmp.fea swaps in after a capital, and what each stands for. Those
# rules are written for Latin, where a cap-height accent is the house style, and
# they fire on Greek capitals too because the class that triggers them lists
# both alphabets. A Greek capital wants its own accent shapes and its own
# placement, so the swap is undone here before anything else looks at the mark.
#
# Undone rather than prevented: the class in ccmp.fea is shared with Latin, and
# narrowing it there to exclude Greek would be a change to code this file has no
# business in. Nothing is lost by letting the substitution happen and reversing
# it, because it happens in a lookup that runs earlier and cannot see this one.
CAP_ACCENTS = {
    "acute.cap": "acutecomb",
    "grave.cap": "gravecomb",
    "breve.cap": "uni0306",
}

# Marks that are canonically equivalent to a spelling everything else is written
# for. Substituting them changes nothing about what the text says, but a source
# that uses them would otherwise miss every rule here. Older Greek texts and
# some OCR output still emit both.
EQUIVALENTS = {0x0343: "̓", 0x0344: "̈́"}

# The spacing ypogegrammeni. Keyboards emit it for the subscript iota about as
# often as they emit the combining U+0345, and its compatibility decomposition
# says it is a space plus that mark -- so after a Greek letter it can only have
# been meant as the mark. Folded contextually rather than outright, because on
# its own it is a legitimate spacing character and turning it into a zero-width
# combining mark would make it disappear.
SPACING_YPOGEGRAMMENI = 0x037A


def codepoints(font):
    """{codepoint: glyph name}, first glyph wins.

    Also used by greek_anchors, which is why it lives here and is public: the
    two modules have to agree about which glyph a character means.
    """
    out = {}
    for glyph in font:
        for cp in glyph.unicodes or ():
            out.setdefault(cp, glyph.name)
    return out


def _is_greek_letter(cp):
    return (unicodedata.category(chr(cp)).startswith("L")
            and any(lo <= cp <= hi for lo, hi in GREEK_BLOCKS))


def _rank():
    return {cp: r for r, cps in SLOTS for cp in cps}


def _passes_needed(k):
    """Sorting passes a shaper needs for a cluster of k marks, worst case.

    Not the textbook bubble-sort figure. A chaining lookup that matches two
    glyphs advances the shaper past both, so a pass cannot cascade the way a
    loop over adjacent pairs does: having swapped positions 1 and 2 it resumes
    at 3 and never compares the glyph it just moved with the one after it. That
    costs passes, and how many is easier to measure than to reason about.
    """
    worst = 0
    for perm in itertools.permutations(range(k)):
        seq, passes = list(perm), 0
        while seq != sorted(seq):
            i = 0
            while i < len(seq) - 1:
                if seq[i] > seq[i + 1]:
                    seq[i], seq[i + 1] = seq[i + 1], seq[i]
                    i += 2
                else:
                    i += 1
            passes += 1
        worst = max(worst, passes)
    return worst


PASSES = _passes_needed(MAX_CLUSTER)


def tables(font):
    """What this face can decompose, sort and compose.

    Returns (compose, decompose, late, marks):

      compose   {(base, mark, ...): glyph} -- the sequence Unicode composes into
                each precomposed letter the face has.
      decompose {glyph: (base, mark, ...)} -- the reverse, but only where the
                round trip lands back on the same glyph. That test is what makes
                taking every letter apart safe: a glyph is only decomposed when
                the compose stage is known to put it back together.
      late      {glyph: (base, mark, ...)} -- letters whose round trip lands
                somewhere else, and which are therefore only taken apart when a
                further mark makes it necessary. See below.
      marks     {glyph: slot} for the sortable marks this face has, in slot
                order, which is the order the sort is trying to reach.

    The `late` set is the polytonic oxia forms and their relatives -- U+1F71
    ALPHA WITH OXIA against U+03AC ALPHA WITH TONOS, and a dozen more. Unicode
    calls those pairs canonically equivalent, so NFC folds one onto the other,
    and Libertinus draws them differently: on the italic faces every one of the
    seven lowercase pairs has its own outlines. Decomposing U+1F71 and composing
    the result would therefore silently redraw it as U+03AC.

    So they are left alone -- until a further mark arrives, at which point the
    stack has no precomposed form at all, the accent will be drawn from the
    font's own U+1FFD oxia whichever spelling asked for it, and leaving the
    letter whole would strand the mark. That is a spelling that renders as
    nothing sensible today, so there is no behaviour to preserve.
    """
    cps = codepoints(font)
    rank = _rank()
    compose, decompose, late = {}, {}, {}

    for cp in sorted(cps):
        if not _is_greek_letter(cp):
            continue
        name = cps[cp]
        d = unicodedata.normalize("NFD", chr(cp))
        if d == chr(cp):
            continue

        # A canonical singleton -- U+1FBE PROSGEGRAMMENI is the only Greek
        # letter with one -- has no marks to sort, so it only matters when a
        # mark follows and it is holding up the cluster.
        if len(d) == 1:
            target = cps.get(ord(d))
            if target and target != name:
                late[name] = (target,)
            continue

        if any(ord(c) not in rank for c in d[1:]):
            continue
        base = cps.get(ord(d[0]))
        if base is None or not _is_greek_letter(ord(d[0])):
            continue
        marks = [cps.get(ord(c)) for c in d[1:]]
        if any(m is None for m in marks):
            continue
        seq = (base,) + tuple(marks)

        if unicodedata.normalize("NFC", d) == chr(cp):
            compose[seq] = name
            decompose[name] = seq
        else:
            late[name] = seq

    # Sorted by slot so the swap rules below read in the order the marks belong
    # in, and so the generated file is stable between runs.
    order = {cp: i for i, (_, cps_) in enumerate(SLOTS) for cp in cps_}
    marks = {}
    for cp in sorted(rank, key=lambda c: (rank[c], order[c])):
        name = cps.get(cp)
        if name and name in font:
            marks[name] = rank[cp]
    return compose, decompose, late, marks


def _lookup(name, body, indent="  "):
    if not body:
        return []
    return ([indent + "lookup %s {" % name]
            + [indent + "  " + line for line in body]
            + [indent + "} %s;" % name])


def _cls(names):
    return "[%s]" % " ".join(names)


def _sanitise(name):
    return name.replace(".", "_")


def generate(font, anchored, adscript_bases=()):
    """Return (prelude, body) as line lists.

    prelude holds the glyph classes and the single-substitution lookups the
    contextual rules call into, and belongs outside any feature block. body
    holds the stages themselves and belongs inside `feature ccmp`, after
    everything mark_greek.fea and ccmp.fea define -- the stages read what those
    produce and must run later than all of it.

    `anchored` is the set of bases carrying Greek mark anchors, which decides
    where a mark takes its Greek drawing. `adscript_bases` is the same thing for
    the adscript iota. Both are passed in rather than worked out here because
    greek_anchors is what writes those anchors, and a substitution that reached
    further than its anchors would drop the mark at the origin -- which is
    exactly what happened on the italic faces when this module decided for
    itself which capitals could take an iota.
    """
    compose, decompose, late, marks = tables(font)
    if not marks or not compose:
        return [], []

    cps = codepoints(font)
    greek = sorted({n for cp, n in cps.items() if _is_greek_letter(cp)})
    # Titlecase as well as uppercase: the ypogegrammeni capitals -- U+1FBC and
    # its two siblings -- are category Lt, and isupper() says no to them.
    caps = sorted({n for cp, n in cps.items()
                   if _is_greek_letter(cp)
                   and (chr(cp).isupper()
                        or unicodedata.category(chr(cp)) == "Lt")})
    tween = [n for n, slot in marks.items() if slot < ACCENT_SLOT]
    if CAPITAL_DIALYTIKA in font:
        tween.append(CAPITAL_DIALYTIKA)

    prelude = ["# " + "-" * 70,
               "# Greek cluster normalisation, from tools/greek_cluster.py.",
               "# Rebuild rather than edit.",
               "# " + "-" * 70,
               "@GRKC_ANY   = %s;" % _cls(greek),
               "@GRKC_MARK  = %s;" % _cls(marks),
               "@GRKC_TWEEN = %s;" % _cls(tween)]
    if caps:
        prelude.append("@GRKC_CAPS  = %s;" % _cls(caps))
    prelude.append("")

    body = []

    # --- stage 0: one spelling per mark ------------------------------------
    #
    # Everything that follows is written against a single spelling of each mark,
    # so the alternatives are folded onto it first. None of this changes what
    # the text says; it changes only which of several equivalent spellings the
    # rest of the file has to know about.
    fold = []
    for cp, replacement in sorted(EQUIVALENTS.items()):
        src = cps.get(cp)
        names = [cps.get(ord(c)) for c in replacement]
        if src and all(names):
            fold.append("sub %s by %s;" % (src, " ".join(names)))
    body += _lookup("grkgen_equiv", fold)

    uncap = [(src, dst) for src, dst in sorted(CAP_ACCENTS.items())
             if src in font and dst in font]
    if uncap and caps:
        prelude += _lookup("grkgen_uncap",
                           ["sub %-14s by %s;" % (s, d) for s, d in uncap], "")
        prelude.append("")
        body += _lookup("grkgen_capaccent",
                        ["sub @GRKC_CAPS %s' lookup grkgen_uncap;"
                         % _cls([s for s, _ in uncap])])

    ypo, spacing = cps.get(0x0345), cps.get(SPACING_YPOGEGRAMMENI)
    if ypo and spacing:
        body += _lookup("grkgen_ypogegrammeni",
                        ["sub [@GRKC_ANY @GRKC_MARK] %s' by %s;"
                         % (spacing, ypo)])

    # --- stage A: decompose ------------------------------------------------
    #
    # First the letters that are only taken apart when a further mark makes it
    # necessary, because their round trip lands on a canonically equivalent
    # character the font draws differently -- see the `late` paragraph in
    # tables(). Left whole they would strand the mark; taken apart they render
    # as their twin, so the trigger is a following mark and nothing else.
    #
    # Split by output length. A named lookup holding both a one-to-one and a
    # one-to-many rule compiles, but it is two lookups by the time it reaches
    # the font, and a chaining rule can only name one of them.
    for suffix, width in (("split", lambda n: n > 1), ("fold", lambda n: n == 1)):
        rows = {n: seq for n, seq in late.items() if width(len(seq))}
        if not rows:
            continue
        prelude += _lookup(
            "grkgen_%s" % suffix,
            ["sub %-16s by %s;" % (n, " ".join(seq))
             for n, seq in sorted(rows.items())], "")
        prelude.append("")
        body += _lookup("grkgen_late_%s" % suffix,
                        ["sub %s' lookup grkgen_%s @GRKC_MARK;"
                         % (_cls(sorted(rows)), suffix)])

    body += _lookup("grkgen_decompose",
                    ["sub %-16s by %s;" % (n, " ".join(seq))
                     for n, seq in sorted(decompose.items())])

    # --- stage B: sort into canonical order --------------------------------
    #
    # Each rule names two single-substitution lookups, one per position, and
    # each of those is "become this particular mark" -- so the identity the
    # first position is losing survives in which lookup the second position is
    # handed. That is what keeps this at one lookup per mark instead of one per
    # pair.
    pairs = [(a, b) for a in marks for b in marks if marks[a] > marks[b]]
    if pairs:
        for target in marks:
            sources = sorted({a for a, b in pairs if b == target}
                             | {b for a, b in pairs if a == target})
            if sources:
                prelude += _lookup(
                    "grkgen_be_%s" % _sanitise(target),
                    ["sub %-16s by %s;" % (s, target) for s in sources], "")
                prelude.append("")

        # The base has to be in the context or these would reorder Latin marks,
        # where the spelling is meaningful -- but the pair being swapped can sit
        # anywhere in the cluster, so the distance back to it varies. Enumerated
        # rather than expressed as a repeat, which chaining context has no way
        # to say.
        swaps = []
        for depth in range(MAX_TWEEN + 1):
            back = " ".join(["@GRKC_ANY"] + ["@GRKC_MARK"] * depth)
            for a, b in pairs:
                swaps.append("sub %s %s' lookup grkgen_be_%s"
                             " %s' lookup grkgen_be_%s;"
                             % (back, a, _sanitise(b), b, _sanitise(a)))
        # One lookup per pass. The same lookup listed twice in a feature is not
        # applied twice, so the passes have to be distinct lookups; see
        # _passes_needed for where the count comes from.
        for n in range(1, PASSES + 1):
            body += _lookup("grkgen_sort_%d" % n, swaps)

    # --- the one place canonical order and composition disagree ------------
    #
    # U+0345 is combining class 240 and every other mark here is 230, which is
    # what makes it the only mark normalisation can compose past another one.
    # Blocking works on class: a mark can only reach the letter if nothing
    # between them has a class at least as high as its own, so the marks in the
    # first four slots have to be adjacent to the letter to compose at all --
    # and the ypogegrammeni does not.
    #
    # NFC uses that. Given a capital alpha with a perispomeni and an adscript
    # iota it composes the iota into the letter, reaching over the accent, and
    # leaves U+1FBC with the perispomeni still on it. A ligature lookup cannot
    # reach over anything, so canonical order would strand the iota as a
    # subscript mark -- which is the lowercase convention, and wrong for a
    # capital, where the iota is written full size beside the letter.
    #
    # So for exactly the sequences where Unicode composes the letter with its
    # iota but has no character for the letter with an accent as well, the two
    # are put back in the other order before composing. That is the whole of the
    # divergence: on lowercase every accent-and-iota combination has its own
    # character, so nothing here matches, and the rule is derived rather than
    # listed so it stays that way if Unicode ever fills the gap.
    #
    # The third test is what keeps this from overshooting. Composition is
    # greedy and left to right: given a capital alpha with an oxia and an iota
    # it takes the oxia first, because U+0386 exists, and the iota is then
    # blocked by a starter it has no composition with -- so the answer there is
    # U+0386 with a subscript iota, not U+1FBC with an accent. Only where the
    # accent has nothing to compose into does the iota get its turn.
    if ypo in marks:
        accents = [n for n, slot in marks.items() if slot == ACCENT_SLOT]
        rules = []
        for accent in accents:
            bases = sorted(b for (b, *rest), _ in compose.items()
                           if rest == [ypo]
                           and (b, accent, ypo) not in compose
                           and (b, accent) not in compose)
            if bases:
                rules.append("sub %s %s' lookup grkgen_be_%s"
                             " %s' lookup grkgen_be_%s;"
                             % (_cls(bases), accent, _sanitise(ypo),
                                ypo, _sanitise(accent)))
        body += _lookup("grkgen_adscript", rules)

    # --- stage C: compose --------------------------------------------------
    #
    # Longest first: alpha with a psili and an oxia has a precomposed form and
    # so does alpha with a psili, and taking the shorter one would leave the
    # accent stranded on a glyph that has nowhere to put it. feaLib orders
    # ligatures by length itself, and this does not rely on that.
    rules = ["sub %-34s by %s;" % (" ".join(seq), name)
             for seq, name in sorted(compose.items(),
                                     key=lambda kv: (-len(kv[0]), kv[0]))]
    body += _lookup("grkgen_compose", rules)

    # --- after the stages: drawings ----------------------------------------
    #
    # Which drawing each mark ends up wearing. They read the composed stream, so
    # they run last, and each is keyed on the base rather than on a glyph list a
    # .fea could name at parse time -- the bases here are enumerated from
    # Unicode, and most of them cannot be written down.

    # The iota a capital takes goes beside the letter rather than under it; the
    # glyph and the reason for it are above ADSCRIPT in build.py. Composition
    # covers the pairings Unicode encoded, and what falls through it -- a
    # capital with a macron and an iota, say -- is left holding a bare U+0345,
    # which is the lowercase subscript. Swapping the drawing here is what puts
    # the iota back beside the letter; greek_anchors places it and widens the
    # advance.
    #
    # After the compose stage on purpose. Run before it, this would consume the
    # iota that U+1FBC and its relatives are built from and leave every capital
    # setting the pair by hand.
    if adscript_bases and ypo in marks and ADSCRIPT in font:
        prelude += _lookup("grkgen_ad_swap",
                           ["sub %s by %s;" % (ypo, ADSCRIPT)], "")
        prelude.append("")
        rules = []
        bases = _cls(sorted(adscript_bases))
        for depth in range(MAX_TWEEN + 1):
            ctx = " ".join([bases] + ["@GRKC_MARK"] * depth)
            rules.append("sub %s %s' lookup grkgen_ad_swap;" % (ctx, ypo))
        body += _lookup("grkgen_adscript_cap", rules)

    if caps and CAPITAL_DIALYTIKA in font and "uni0308" in font:
        prelude += _lookup("grkgen_dial_swap",
                           ["sub uni0308 by %s;" % CAPITAL_DIALYTIKA], "")
        prelude.append("")
        body += _lookup("grkgen_dialytika",
                        ["sub @GRKC_CAPS uni0308' lookup grkgen_dial_swap;"])

    swap = {p: g for p, g in SHAPES.items() if p in font and g in font}
    if swap and anchored:
        prelude += _lookup("grkgen_greekshape",
                           ["sub %-14s by %s;" % (p, swap[p])
                            for p in sorted(swap)], "")
        prelude.append("")
        bases, rules = _cls(sorted(anchored)), []
        for depth in range(MAX_TWEEN + 1):
            ctx = " ".join([bases] + ["@GRKC_TWEEN"] * depth)
            rules.append("sub %s %s' lookup grkgen_greekshape;"
                         % (ctx, _cls(sorted(swap))))
        body += _lookup("grkgen_shape", rules)

    return prelude, body
