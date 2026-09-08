# tools

    pip install -r requirements.txt

build.py compiles one .sfd.

Greek is generated in two halves. greek_cluster.py writes the GSUB: it takes
every precomposed Greek letter apart, sorts the marks into canonical order and
puts them back together, so a cluster renders the same however it was typed.
greek_anchors.py writes the GPOS, deriving each face's mark anchors from its own
outlines. The judgement calls -- where a mark goes on a capital, how much room to
make for it -- stay in sources/features/mark_greek.fea.

proof.py and proof_matrix.py draw proofs, check_overlap.py finds collisions, and
check_clusters.py shapes every ordering of every letter-and-mark set and reports
the ones that disagree. Run that last one before and after touching either
generator:

    python tools/check_clusters.py --dump build/check/before.json
    ...
    python tools/check_clusters.py --compare build/check/before.json build/check/after.json

## proofs/

Sources only. The `.txt` files are input to proof.py and proof_matrix.py;
`macron-stacks.tex` is a LaTeX sheet compiled by either engine. Everything
generated goes to `build/`, which is gitignored — LaTeX writes beside the
current directory unless told otherwise, so it has to be told:

    mkdir -p build/proof
    lualatex -output-directory=build/proof -jobname=macron-stacks-lua \
             tools/proofs/macron-stacks.tex
    xelatex  -output-directory=build/proof -jobname=macron-stacks-xe \
             tools/proofs/macron-stacks.tex

The `-jobname` is what lets one source serve both engines; the sheet switches
its HarfBuzz-versus-node section on by engine, since that comparison only means
anything under LuaTeX.
