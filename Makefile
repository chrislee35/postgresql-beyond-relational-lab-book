# Book Metadata
TITLE="The Portsmith Papers: A Hands-On Tour of PostgreSQL Beyond the Relational Model"
AUTHOR="Chris Lee"
OUTDIR=psql-book
FILEBASE=psql-book
OUTPUT=$(OUTDIR)/$(FILEBASE)
include chapters.conf

# Default rule
all: $(OUTDIR) html pdf epub

# Ensure output directory exists
$(OUTDIR):
	mkdir $(OUTDIR)

# Render Mermaid diagram sources (diagrams/*.mmd) to SVG in imgs/, forest theme
DIAGRAM_SRC := $(wildcard diagrams/*.mmd)
DIAGRAM_SVG := $(patsubst diagrams/%.mmd,imgs/%.svg,$(DIAGRAM_SRC))
DIAGRAM_PNG := $(patsubst diagrams/%.mmd,imgs/%.png,$(DIAGRAM_SRC))

imgs/%.svg: diagrams/%.mmd diagrams/mermaid.config.json
	mermaidx -i $< -o $@ -c diagrams/mermaid.config.json
	# python3 utils/fix_svg_descenders.py $@

imgs/%.png: diagrams/%.mmd diagrams/mermaid.config.json
	mermaidx -i $< -o $@ -c diagrams/mermaid.config.json

# Hand-made SVGs that have no diagrams/*.mmd source (map, cover art, and a
# few older figures predating the mermaid pipeline). Rasterized so the PDF
# build can use PNG instead of feeding SVG through weasyprint.
EXTRA_SVG := imgs/portsmith_map.svg \
	imgs/cover.svg \
	imgs/ch05_trigram_window.svg \
	imgs/ch06_ivfflat_clustering.svg \
	imgs/ch06_vector_disagreement.svg \
	imgs/ch07_cidr_nesting.svg
EXTRA_PNG := $(EXTRA_SVG:.svg=.png)

$(EXTRA_PNG): imgs/%.png: imgs/%.svg
	inkscape --export-type=png --export-filename=$@ -w 2000 $<

.PHONY: diagrams
diagrams: $(DIAGRAM_SVG) $(DIAGRAM_PNG) $(EXTRA_PNG)

# Combine all markdown files into a single one
$(OUTPUT).md: $(INPUT) diagrams | $(OUTDIR)
	mkdir -p $(OUTDIR)/imgs $(OUTDIR)/css
	rm -rf $(OUTPUT).md
	for file in $(INPUT); do \
		cat "$$file" >> $(OUTPUT).md; \
		echo '<div style="page-break-before: always;"></div>' >> $(OUTPUT).md; \
	done
	cat $(OUTPUT).md | utils/fix_links.py > $(OUTPUT).md2
	mv $(OUTPUT).md2 $(OUTPUT).md

	# copy resources
	cp imgs/* $(OUTDIR)/imgs
	cp css/* $(OUTDIR)/css
	#find chapters/ \( -name '*.png' -o -name '*.jpg' -o -name '*.gif' -o -name '*.jpeg' \) -exec cp "{}" $(OUTDIR)/imgs \;

# Generate HTML
html: $(OUTPUT).md
	pandoc $(OUTPUT).md -o $(OUTPUT).html \
		--metadata title=$(TITLE) \
		--css css/book.css \
		--toc \
		--standalone

# Generate PDF
# weasyprint renders the mermaid/hand-made SVGs poorly, so the PDF build
# swaps <img src="imgs/*.svg"> to the PNG versions; HTML and EPUB keep SVG.
pdf: $(OUTPUT).md
	cd $(OUTDIR) && \
	sed -E 's#(src="imgs/[A-Za-z0-9_-]+)\.svg#\1.png#g' $(FILEBASE).md > $(FILEBASE).pdf.md && \
	pandoc $(FILEBASE).pdf.md -o $(FILEBASE).pdf \
		--metadata title=$(TITLE) \
		--pdf-engine=weasyprint \
		--toc \
		--standalone

# Generate EPUB
epub: $(OUTPUT).md
	cd $(OUTDIR) && \
	pandoc $(FILEBASE).md -o $(FILEBASE).epub \
		--metadata title=$(TITLE) \
		--toc \
		--standalone

# Clean up
clean:
	rm -rf $(OUTDIR)
