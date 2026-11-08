# Study guide build files

Rebuilds docs/STUDY-GUIDE.pdf and docs/STUDY-GUIDE.pptx from docs/STUDY-GUIDE.md.
Not part of the MCP server itself.

    npm install pptxgenjs react-icons react react-dom sharp   # in a scratch dir (network mounts can't symlink)
    pandoc STUDY-GUIDE.md -s --toc --toc-depth=2 --highlight-style=pygments --css style.css --embed-resources -o guide.html
    node pdf.js $PWD/guide.html $PWD/STUDY-GUIDE.pdf             # needs playwright + chromium
    python3 extract_qa.py STUDY-GUIDE.md qa.json
    NODE_PATH=node_modules APPLY_THEME=<pptx skill>/scripts/apply_theme.js node build_deck.js qa.json STUDY-GUIDE.pptx

The deck's concept slides are written in build_deck.js; flashcards come from Part 6 of the guide.
After each new step: update STUDY-GUIDE.md, extend the concept slides, and rebuild both.
