import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ufo2ft
import ufoLib2

from fontTools import subset
from fontTools.misc.transform import Offset
from fontTools.pens.transformPen import TransformPen
from io import StringIO
from pcpp.preprocessor import Preprocessor
from sfdLib.parser import SFDParser, CATEGORIES_KEY, MATH_KEY

import greek_anchors

# Greek marks are drawn differently from Latin ones, but the font only has the
# Greek drawings as spacing characters, so a Greek base with a combining mark
# gets the Latin shape -- and next to a precomposed vowel, which is built from
# the spacing drawing, the two visibly disagree. The perispomeni is the worst of
# it: U+0342 is contour for contour the Latin tildecomb, so a macron plus
# perispomeni renders a tilde. Nothing in the glyph name says so.
#
# These are zero width copies of the spacing forms, positioned on top of the
# Latin mark they stand in for so that a single set of anchors serves both.
#
# The measurements and the full argument are in sources/features/mark_greek.fea
# under "Greek-shaped marks", and are deliberately not repeated here: they
# describe outlines that can be redrawn, and two copies would drift.
GREEK_MARKS = {
    "acutecomb.grek": ("uni1FFD", "acutecomb"),   # oxia
    "gravecomb.grek": ("uni1FEF", "gravecomb"),   # varia
    "uni0342.grek":   ("uni1FC0", "uni0342"),     # perispomeni
}

# An identical copy of the dialytika, substituted in after a Greek capital.
#
# It exists to be a different glyph, not a different drawing. An accent
# following a dialytika stacks on top of it, which is right for lowercase --
# U+1FD3 is drawn that way and a barred vowel has nowhere else to put it -- and
# wrong for a capital, where accents belong off the left shoulder. That stacking
# is a mark-to-mark rule, and mark-to-mark cannot see what the base was, so the
# only way to exempt capitals is to give them a dialytika the rule does not
# name. See sources/features/mark_greek.fea.
#
# The name itself lives in greek_anchors, which also has to write rules about
# this glyph; drawn here, named there, one string.
CAPITAL_DIALYTIKA = greek_anchors.CAPITAL_DIALYTIKA

# Three faces -- Serif Semibold, Serif Semibold Italic and Sans Italic -- have no
# U+0345 at all, so an iota subscript on any of them comes out as a .notdef box.
# They do have the spacing form U+037A, and they build their own alpha with
# ypogegrammeni from it, which is what tells us where the combining form belongs:
# the faces that ship a U+0345 place it in that composite at (422, 18).
YPOGEGRAMMENI_ORIGIN = (422, 18)


class Font:
    def __init__(self, filename, features):
        self._font = font = ufoLib2.Font()

        parser = SFDParser(filename, font, ufo_anchors=False,
            ufo_kerning=False, minimal=True)
        parser.parse()

        # Both of these add glyphs, so they have to run before the feature file
        # is preprocessed -- the HAS_* guards below test for what they produce.
        #
        # Gated on the same test greek_anchors.generate() makes, so that a face
        # with no Greek gets nothing from either of them. The capital dialytika
        # is the one that needs saying so: it is copied from uni0308 alone, which
        # a face can have without having a single Greek letter. Mono does, and is
        # built with no feature file at all (see nofea in fontship.mk), so the
        # copy shipped unencoded, referenced by no lookup, and flagged as a mark
        # in GDEF.
        if "alpha" in font:
            self._make_greek_marks()
            self._make_ypogegrammeni()
            self._make_shifted_marks()

        if features:
            preprocessor = Preprocessor()
            for d in ("italic", "sans", "display", "math"):
                if d in filename.lower():
                    preprocessor.define(d.upper())
            # Coverage is not uniform across the faces, so let feature files
            # guard on a glyph rather than on a face name -- and on the glyph
            # they actually name, which is the one synthesised above rather than
            # the spacing character it was drawn from. Those two can disagree:
            # _make_greek_marks needs the Latin model and a real bounding box as
            # well as the Greek source, so a face can carry U+1FFD and still end
            # up with no acutecomb.grek. Testing the source would then define the
            # flag for a glyph that does not exist and fail the feature compile.
            for name in ["uni0345"] + list(GREEK_MARKS):
                if name in font:
                    preprocessor.define(
                        "HAS_%s" % name.replace(".", "_").upper())
            # mark_greek.fea matches a breathing and an accent as context, and
            # after the pair substitution the glyph in that position is a
            # shifted variant. A glyph class cannot be extended once defined, so
            # the classes naming those variants have to be in hand before that
            # file is read rather than appended with the rest of the generated
            # anchors below.
            classes = greek_anchors.shift_classes(font)
            if classes:
                preprocessor.define("HAS_PAIR_SHIFTS")
            with open(features) as f:
                preprocessor.parse(f)
            pre = StringIO()
            preprocessor.write(pre)
            feafile = StringIO()
            feafile.write(classes)
            feafile.write(pre.getvalue())
            # Anchors measured from this face, ahead of the .sfd's own lookups
            # so ours take the lower lookup indices. The preprocessed text goes
            # in with them: the capital anchors are hand-set in mark_greek.fea,
            # and the composed capitals are derived by shifting those, so the
            # generator reads them from the one place they are written rather
            # than keeping a second copy that can drift.
            feafile.write(greek_anchors.generate(font, pre.getvalue()))
            feafile.write(font.features.text)
            font.features.text = feafile.getvalue()

    def _update_metadata(self):
        font = self._font
        info = font.info

        year = datetime.date.today().year
        info.copyright = (u"Copyright © 2012-%s " % year +
                          u"The Libertinus Project Authors.")
        info.openTypeNameManufacturerURL = "https://github.com/alerque/libertinus"

    def _draw_over_under_line(self, name, widths):
        font = self._font
        bbox = font[name].getBounds(font)
        pos = bbox[1]
        height = bbox[-1] - bbox[1]

        for width in sorted(widths):
            glyph = font.newGlyph(f"{name}.{width}")
            glyph.width = 0
            glyph.lib[CATEGORIES_KEY] = "mark"

            pen = glyph.getPen()
            pen.moveTo((-25 - width, pos))
            pen.lineTo((-25 - width, pos + height))
            pen.lineTo((25, pos + height))
            pen.lineTo((25, pos))
            pen.closePath()

    def _make_over_under_line(self):
        font = self._font
        minwidth = 50

        bases = [n for n in ("uni0305", "uni0332") if n in font]
        if not bases:
            return

        # Collect glyphs grouped by their widths rounded by minwidth, we will
        # use them to decide the widths of over/underline glyphs we will draw
        widths = {}
        for glyph in font:
            glyphclass = glyph.lib.get(CATEGORIES_KEY)
            if glyphclass != 'mark' and glyph.width > 0:
                width = round(glyph.width / minwidth) * minwidth
                width = max(width, minwidth)
                if width not in widths:
                    widths[width] = []
                widths[width].append(glyph.name)

        if len(widths) == 1:
            return

        for name in bases:
            self._draw_over_under_line(name, widths)

        fea = []
        fea.append("feature mark {")
        fea.append(f"  @OverSet = [{' '.join(bases)}];")
        fea.append("  lookupflag UseMarkFilteringSet @OverSet;")
        for width in sorted(widths):
            # For each width group we create an over/underline glyph with the
            # same width, and add a contextual substitution lookup to use it
            # when an over/underline follows any glyph in this group
            replacements = ['%s.%d' % (name, width) for name in bases]
            fea.append("  sub [%s] [%s]' by [%s];" % (" ".join(widths[width]),
                                                      " ".join(bases),
                                                      " ".join(replacements)))
        fea.append("} mark;")

        self._font.features.text += "\n".join(fea)

    def _make_greek_marks(self):
        font = self._font

        for name, (source, model) in GREEK_MARKS.items():
            if name in font or source not in font or model not in font:
                continue
            sbox = font[source].getBounds(font)
            mbox = font[model].getBounds(font)
            if not sbox or not mbox:
                continue

            # Line the two up centre on centre. The Greek form is taller and
            # narrower than the Latin one, so matching centres rather than an
            # edge means every anchor written for the Latin mark places the
            # Greek one identically, and the difference in proportion shows up
            # symmetrically instead of piling up at one end.
            dx = (mbox[0] + mbox[2] - sbox[0] - sbox[2]) / 2
            dy = (mbox[1] + mbox[3] - sbox[1] - sbox[3]) / 2

            glyph = font.newGlyph(name)
            glyph.width = 0
            glyph.lib[CATEGORIES_KEY] = "mark"
            font[source].draw(TransformPen(glyph.getPen(), Offset(dx, dy)))

        # See CAPITAL_DIALYTIKA. A plain duplicate, drawn at the same origin, so
        # every anchor written for uni0308 places it identically.
        if "uni0308" in font and CAPITAL_DIALYTIKA not in font:
            glyph = font.newGlyph(CAPITAL_DIALYTIKA)
            glyph.width = 0
            glyph.lib[CATEGORIES_KEY] = "mark"
            font["uni0308"].draw(glyph.getPen())

    def _make_shifted_marks(self):
        """A copy of each mark that has to move sideways in some context.

        Centring a breathing-and-accent cluster means moving one mark sideways
        from where its own anchor puts it, which is a contextual question -- and
        the direct way to answer it, a contextual GPOS adjustment on the mark,
        is silently ignored by luaotfload's node renderer. So the context is
        asked in GSUB instead, and what it selects is one of these: the shift is
        already in the outline, and plain mark-to-base does the rest.

        The anchor is deliberately not moved to match. greek_anchors keeps the
        original's anchor on the variant, so the glyph's origin still lands
        where the unshifted mark's would and only the ink has moved -- which is
        also what carries the accent along, since the anchor it attaches to is
        measured in this glyph's space. See variant_name().
        """
        font = self._font
        for source, by_dx in greek_anchors.pair_variants(font).items():
            if source not in font:
                continue
            for dx, name in by_dx.items():
                if name in font:
                    continue
                glyph = font.newGlyph(name)
                glyph.width = 0
                glyph.lib[CATEGORIES_KEY] = "mark"
                font[source].draw(TransformPen(glyph.getPen(), Offset(dx, 0)))

    def _make_ypogegrammeni(self):
        """Build a combining U+0345 for faces that only have the spacing U+037A.

        The position is read out of the face's own alpha-with-ypogegrammeni
        rather than copied from another face, so a slanted or heavier design
        gets the subscript exactly where its designer put it. Reproducing that
        composite is the whole specification: whatever offset the drawn glyph
        uses, the combining form has to sit that far from where U+0345 would
        have been placed in it.
        """
        font = self._font
        if "uni0345" in font or "uni037A" not in font or "uni1FB3" not in font:
            return

        # The subscript is the only part of the composite that hangs below the
        # baseline, which makes it easy to pick out whether the face draws it or
        # references it.
        below = [c for c in greek_anchors.contours(font, "uni1FB3")
                 if max(y for _, y in c) < -20]
        if not below:
            return
        sub_x = min(x for c in below for x, _ in c)
        sub_y = min(y for c in below for _, y in c)

        source = font["uni037A"].getBounds(font)
        if not source:
            return
        dx = sub_x - YPOGEGRAMMENI_ORIGIN[0] - source[0]
        dy = sub_y - YPOGEGRAMMENI_ORIGIN[1] - source[1]

        glyph = font.newGlyph("uni0345")
        glyph.width = 0
        glyph.unicodes = [0x0345]
        glyph.lib[CATEGORIES_KEY] = "mark"
        font["uni037A"].draw(TransformPen(glyph.getPen(), Offset(dx, dy)))

    def _post_process(self, otf):
        font = self._font
        gdef = otf["GDEF"].table
        classdef = gdef.GlyphClassDef.classDefs
        for glyph in font:
            if glyph.lib.get(CATEGORIES_KEY) == "mark":
                classdef[glyph.name] = 3

        constants = font.lib.get(MATH_KEY)
        if constants:
            from fontTools.ttLib import newTable
            from fontTools.ttLib.tables import otTables
            from fontTools.otlLib import builder as otl

            glyphMap = {n: i for i, n in enumerate(font.glyphOrder)}
            table = otTables.MATH()
            table.Version = 0x00010000
            table.MathConstants = otTables.MathConstants()
            for c in constants:
                if c == "MinConnectorOverlap":
                    continue
                v = constants[c]
                if c not in ("ScriptPercentScaleDown",
                        "ScriptScriptPercentScaleDown",
                        "DelimitedSubFormulaMinHeight",
                        "DisplayOperatorMinHeight",
                        "RadicalDegreeBottomRaisePercent"):
                    vr = otTables.MathValueRecord()
                    vr.Value = v
                    v = vr
                setattr(table.MathConstants, c, v)
            extended = set()
            italic = {}
            accent = {}
            vvars = {}
            hvars = {}
            vcomp = {}
            hcomp = {}
            for glyph in font:
                math = glyph.lib.get(MATH_KEY)
                if math:
                    if "IsExtendedShape" in math:
                        extended.add(glyph.name)
                    if "ItalicCorrection" in math:
                        italic[glyph.name] = otTables.MathValueRecord()
                        italic[glyph.name].Value = math["ItalicCorrection"]
                    if "TopAccentHorizontal" in math:
                        accent[glyph.name] = otTables.MathValueRecord()
                        accent[glyph.name].Value = math["TopAccentHorizontal"]
                    if "GlyphVariantsVertical" in math:
                        vvars[glyph.name] = math["GlyphVariantsVertical"]
                        if "GlyphCompositionVertical" in math:
                            vcomp[glyph.name] = math["GlyphCompositionVertical"]
                    if "GlyphVariantsHorizontal" in math:
                        hvars[glyph.name] = math["GlyphVariantsHorizontal"]
                        if "GlyphCompositionHorizontal" in math:
                            hcomp[glyph.name] = math["GlyphCompositionHorizontal"]

            table.MathGlyphInfo = otTables.MathGlyphInfo()
            table.MathGlyphInfo.populateDefaults()

            coverage = otl.buildCoverage(italic.keys(), glyphMap)
            table.MathGlyphInfo.MathItalicsCorrectionInfo = otTables.MathItalicsCorrectionInfo()
            table.MathGlyphInfo.MathItalicsCorrectionInfo.Coverage = coverage
            table.MathGlyphInfo.MathItalicsCorrectionInfo.ItalicsCorrection = [italic[n] for n in coverage.glyphs]

            coverage = otl.buildCoverage(accent.keys(), glyphMap)
            table.MathGlyphInfo.MathTopAccentAttachment = otTables.MathTopAccentAttachment()
            table.MathGlyphInfo.MathTopAccentAttachment.TopAccentCoverage = coverage
            table.MathGlyphInfo.MathTopAccentAttachment.TopAccentAttachment = [accent[n] for n in coverage.glyphs]

            table.MathGlyphInfo.ExtendedShapeCoverage = otl.buildCoverage(extended, glyphMap)

            table.MathVariants = otTables.MathVariants()
            table.MathVariants.MinConnectorOverlap = constants["MinConnectorOverlap"]

            coverage = otl.buildCoverage(vvars.keys(), glyphMap)
            table.MathVariants.VertGlyphCoverage = coverage
            table.MathVariants.VertGlyphConstruction = []
            for name in coverage.glyphs:
                variants = vvars[name]
                construction = otTables.MathGlyphConstruction()
                construction.populateDefaults()
                construction.VariantCount = len(variants)
                construction.MathGlyphVariantRecord = []
                for variant in variants:
                    bbox = font[variant].getBounds(font)
                    record = otTables.MathGlyphVariantRecord()
                    record.VariantGlyph = variant
                    record.AdvanceMeasurement = int(bbox[-1] - bbox[1] + 1)
                    construction.MathGlyphVariantRecord.append(record)
                if name in vcomp:
                    construction.GlyphAssembly = otTables.GlyphAssembly()
                    construction.GlyphAssembly.ItalicsCorrection = otTables.MathValueRecord()
                    construction.GlyphAssembly.ItalicsCorrection.Value = 0
                    construction.GlyphAssembly.PartRecords = []
                    for comp in vcomp[name]:
                        record = otTables.GlyphPartRecord()
                        record.glyph = comp[0]
                        f, s, e, a = [int(v) for v in comp[1].split(",")]
                        record.StartConnectorLength = s
                        record.EndConnectorLength = e
                        record.FullAdvance = a
                        record.PartFlags = f
                        construction.GlyphAssembly.PartRecords.append(record)
                table.MathVariants.VertGlyphConstruction.append(construction)

            coverage = otl.buildCoverage(hvars.keys(), glyphMap)
            table.MathVariants.HorizGlyphCoverage = coverage
            table.MathVariants.HorizGlyphConstruction = []
            for name in coverage.glyphs:
                variants = hvars[name]
                construction = otTables.MathGlyphConstruction()
                construction.populateDefaults()
                construction.VariantCount = len(variants)
                construction.MathGlyphVariantRecord = []
                for variant in variants:
                    bbox = font[variant].getBounds(font)
                    record = otTables.MathGlyphVariantRecord()
                    record.VariantGlyph = variant
                    record.AdvanceMeasurement = int(bbox[-2] - bbox[0] + 1)
                    construction.MathGlyphVariantRecord.append(record)
                if name in hcomp:
                    construction.GlyphAssembly = otTables.GlyphAssembly()
                    construction.GlyphAssembly.ItalicsCorrection = otTables.MathValueRecord()
                    construction.GlyphAssembly.ItalicsCorrection.Value = 0
                    construction.GlyphAssembly.PartRecords = []
                    for comp in hcomp[name]:
                        record = otTables.GlyphPartRecord()
                        record.glyph = comp[0]
                        f, s, e, a = [int(v) for v in comp[1].split(",")]
                        record.StartConnectorLength = s
                        record.EndConnectorLength = e
                        record.FullAdvance = a
                        record.PartFlags = f
                        construction.GlyphAssembly.PartRecords.append(record)
                table.MathVariants.HorizGlyphConstruction.append(construction)


            otf["MATH"] = newTable("MATH")
            otf["MATH"].table = table

    def _prune(self, otf):
        options = subset.Options()
        options.set(layout_features='*', name_IDs='*', notdef_outline=True,
            recalc_average_width=True, recalc_bounds=True)
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(unicodes=otf['cmap'].getBestCmap().keys())
        # subsetter.subset(otf)

    def generate(self, output):
        self._update_metadata()
        self._make_over_under_line()
        otf = ufo2ft.compileOTF(self._font, inplace=True, optimizeCFF=0,
            removeOverlaps=True, overlapsBackend="pathops", featureWriters=[])
        self._post_process(otf)
        self._prune(otf)
        otf.save(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("-f", "--feature-file", required=False)

    args = parser.parse_args()
    font = Font(args.input, args.feature_file)
    font.generate(args.output)


if __name__ == "__main__":
    main()
