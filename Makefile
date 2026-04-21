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

# Combine all markdown files into a single one
$(OUTPUT).md: $(INPUT) | $(OUTDIR)
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
	find chapters/ \( -name '*.png' -o -name '*.jpg' -o -name '*.gif' -o -name '*.jpeg' \) -exec cp "{}" $(OUTDIR)/imgs \;

# Generate HTML
html: $(OUTPUT).md
	pandoc $(OUTPUT).md -o $(OUTPUT).html \
		--metadata title=$(TITLE) \
		--css css/nlp-book.css \
		--toc \
		--standalone

# Generate PDF
pdf: $(OUTPUT).md
	cd $(OUTDIR) && \
	pandoc $(FILEBASE).md -o $(FILEBASE).pdf \
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
