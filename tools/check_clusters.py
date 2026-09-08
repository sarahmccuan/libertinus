"""Check that a Greek cluster renders the same however it was typed.

The property this tests is not "does this stack look right" -- the proof sheets
answer that -- but the weaker and more mechanical one underneath it: a vowel and
a set of diacritics should shape to the same glyphs whatever order the marks
arrived in. Nothing in Unicode enforces an order among them, for the reason set
out at the head of tools/greek_cluster.py -- which is the module that has to
make this true, and the one to look at when it is not.

    python tools/check_clusters.py -i build/LibertinusSerif-Regular.otf
    python tools/check_clusters.py                       # every face in build/
    python tools/check_clusters.py --dump build/check/before.json
    python tools/check_clusters.py --compare before.json after.json

Three things are reported per face:

  * split -- one letter-and-mark set that shapes more than one way. The count of
    these is the number this whole exercise exists to drive to zero.
  * notdef -- a spelling that reaches a missing glyph.
  * loose -- a mark that GPOS left at the origin, which is an anchor gap rather
    than an ordering one. Reported because a fix for the first can expose it.

A split or a notdef exits nonzero. A loose mark does not: it is a finding about
anchors rather than about ordering, and a face can carry a known one for a while
without that meaning the last change broke something.

--dump and --compare are the safety net for changing any of it: dump the glyph
streams before a change and after, and diff. A refactor that only fixes broken
orderings shows up as changes confined to spellings that were split before, and
--compare exits nonzero exactly where that is violated -- where a set that
agreed with itself before the change does not after.
"""

import argparse
import glob
import itertools
import json
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proof import Renderer

# The letters worth testing, and what each of them can carry.
#
# Restricted to the vowels plus rho because those are the only letters Greek
# puts these marks on, and testing the consonants would only measure that the
# font does nothing to them. Rho is here for the breathings, which it takes
# without ever taking an accent.
#
# The per-letter restrictions are not orthographic rules -- an invalid cluster
# should still be order-independent, and is still tested -- but coverage ones:
# a macron on epsilon is a stack no font draws and no reader wants, so including
# it would fill the report with failures that are not the ones being hunted.
DICHRONA = "αιυΑΙΥ"          # the vowels whose length is not fixed
IOTA_SUB = "αηωΑΗΩ"          # the vowels that take a ypogegrammeni
DIALYTIKA = "ιυΙΥ"           # the vowels that take a dialytika

BASES = "αειουηωρΑΕΙΟΥΗΩΡ"

# One mark per slot, in the order Unicode's own decompositions put them. The
# slots are what makes the test space finite: two marks from the same slot never
# co-occur in a real cluster, so the sets tested are the products of these.
SLOTS = (
    ("length",    ("̄", "̆")),
    ("breathing", ("̓", "̔")),
    ("dialytika", ("̈",)),
    ("accent",    ("́", "̀", "͂")),
    ("ypo",       ("ͅ",)),
)


def applicable(base, slot, mark):
    if slot == "length":
        return base in DICHRONA
    if slot == "ypo":
        return base in IOTA_SUB
    if slot == "dialytika":
        return base in DIALYTIKA
    # Breathings and accents go on every letter tested, rho included.
    return True


def cases(bases=BASES):
    """(base, marks) for every letter-and-mark set worth testing.

    Yielded as a set rather than a spelling; the orderings come from permuting
    it. Sets of one mark are included even though they have only one ordering,
    because they are still worth checking for a notdef or a loose mark.
    """
    for base in bases:
        choices = []
        for slot, marks in SLOTS:
            options = [None] + [m for m in marks if applicable(base, slot, m)]
            choices.append(options)
        for combo in itertools.product(*choices):
            marks = tuple(m for m in combo if m)
            if marks:
                yield base, marks


def spellings(base, marks):
    """Every ordering of one mark set, as strings.

    Deduplicated through a set because permutations of a tuple with repeats
    would otherwise be counted more than once; the slots make repeats
    impossible today, and the dedup keeps that from being load-bearing.
    """
    return sorted({base + "".join(p) for p in itertools.permutations(marks)})


def label(text):
    return " ".join("%04X" % ord(c) for c in text)


def survey(renderer, bases=BASES):
    """Shape every spelling of every case. Returns (rows, traces).

    rows is one record per mark set, carrying the distinct traces it produced.
    traces is a flat {spelling: trace} map for --dump, which wants every
    spelling rather than the grouping.
    """
    rows, traces = [], {}
    for base, marks in cases(bases):
        by_trace = {}
        for text in spellings(base, marks):
            trace = renderer.trace(text)
            traces[label(text)] = trace
            by_trace.setdefault(trace, []).append(text)
        rows.append((base, marks, by_trace))
    return rows, traces


def report(renderer, rows, verbose):
    """Print the split, notdef and loose counts for one face."""
    splits, notdefs, loose = [], [], []
    for base, marks, by_trace in rows:
        if len(by_trace) > 1:
            splits.append((base, marks, by_trace))
        # Checked on the canonical spelling only. A notdef or an unattached
        # mark in a mis-ordered spelling is a symptom of the split, and
        # reporting it separately would count the same problem twice.
        canonical = unicodedata.normalize("NFC", base + "".join(marks))
        if renderer.has_notdef(canonical):
            notdefs.append(canonical)
        bad = renderer.unattached(canonical)
        if bad:
            loose.append((canonical, bad))

    print("  %-6d sets tested" % len(rows))
    print("  %-6d split across orderings" % len(splits))
    print("  %-6d reach a notdef" % len(notdefs))
    print("  %-6d leave a mark unattached" % len(loose))

    if verbose:
        for base, marks, by_trace in splits:
            print("    %s + %s -> %d renderings"
                  % (base, label("".join(marks)), len(by_trace)))
            for trace, texts in sorted(by_trace.items(),
                                       key=lambda kv: -len(kv[1])):
                print("      %-3d %s" % (len(texts), trace))
                for t in texts[:4]:
                    print("          %s" % label(t))
        for text, names in loose:
            print("    loose %s  %s" % (label(text), " ".join(names)))
    return len(splits), len(notdefs), len(loose)


def agreed(traces):
    """The mark sets in one dump whose spellings all shaped the same way.

    A dump is flat -- spelling to trace -- but the spelling carries its own
    grouping: same first codepoint, same set of the rest. Regrouping here rather
    than writing the sets into the dump keeps the file diffable by hand.
    """
    sets = {}
    for spelling, trace in traces.items():
        cps = spelling.split()
        sets.setdefault((cps[0], frozenset(cps[1:])), set()).add(trace)
    return {k for k, seen in sets.items() if len(seen) == 1}


def compare(old_path, new_path):
    """Diff two --dump files, keyed on spelling. Returns the regression count.

    The interesting number is not how many spellings changed -- a fix is
    supposed to change some -- but whether any spelling that already agreed
    with its siblings changed, which is what a regression looks like. So the
    changes are printed for a human to read and the number returned is the
    narrower one: sets that were of one mind before the change and are not
    after.

    A set that changed uniformly is not one of them. Moving every ordering of a
    cluster together is what a fix is.
    """
    with open(old_path, encoding="utf-8") as f:
        old = json.load(f)
    with open(new_path, encoding="utf-8") as f:
        new = json.load(f)

    faces = sorted(set(old) | set(new))
    total = 0
    for face in faces:
        a, b = old.get(face, {}), new.get(face, {})
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        only_a = sorted(set(a) - set(b))
        only_b = sorted(set(b) - set(a))
        # Only where the face is on both sides. A face that one dump has and
        # the other does not is a change in what was built, which the dropped
        # and added counts already say; scoring every one of its sets as a
        # regression would bury a real one.
        broken = sorted(agreed(a) - agreed(b)) if a and b else []
        total += len(broken)
        print("%s: %d changed, %d dropped, %d added, %d newly split"
              % (face, len(changed), len(only_a), len(only_b), len(broken)))
        for k in changed[:40]:
            print("    %s\n      - %s\n      + %s" % (k, a[k], b[k]))
        if len(changed) > 40:
            print("    ... %d more" % (len(changed) - 40))
        for base, marks in broken:
            print("    REGRESSION %s + %s no longer agrees across orderings"
                  % (base, " ".join(sorted(marks))))
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", action="append",
                        help="font to check; repeatable, defaults to build/*.otf")
    parser.add_argument("-b", "--bases", default=BASES,
                        help="letters to test, as a string")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--script", default="Grek")
    parser.add_argument("--language", default="el")
    parser.add_argument("--dump", help="write every spelling's glyph stream here")
    parser.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"))
    args = parser.parse_args()

    if args.compare:
        return 1 if compare(*args.compare) else 0

    paths = args.input or sorted(glob.glob(os.path.join("build", "*.otf")))
    dump, worst = {}, 0
    for path in paths:
        renderer = Renderer(path, 100, args.script, args.language, {})
        # A face with no Greek has nothing to say here, and reporting zeroes for
        # it buries the faces that do.
        if "alpha" not in renderer.order:
            continue
        print(os.path.basename(path))
        rows, traces = survey(renderer, args.bases)
        splits, notdefs, _ = report(renderer, rows, args.verbose)
        worst = max(worst, splits + notdefs)
        dump[os.path.basename(path)] = traces

    if args.dump:
        os.makedirs(os.path.dirname(args.dump) or ".", exist_ok=True)
        with open(args.dump, "w", encoding="utf-8") as f:
            json.dump(dump, f, indent=0, sort_keys=True)
        print("wrote %s" % args.dump)
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
