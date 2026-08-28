# Documentation

| File | What it is |
|---|---|
| `Tedlar-Lead-Agent-Writeup.pdf` | The 3-page write-up: agent workflow, data processing, implementation results. |
| `Tedlar-Lead-Agent.pptx` | 9-slide presentation covering the process and the prototype. |
| `Tedlar-Lead-Agent-Paper.pdf` | 3-page paper: agent workflow, data processing, implementation results. |
| `writeup.md` | Markdown source for the PDF. |
| `DESIGN.md` | Dashboard design notes — palette, layout, accessibility choices. |
| `build_deck.js` | Regenerates the deck: `npm install pptxgenjs && node build_deck.js`. |

Regenerating the PDF from the markdown:

```bash
python3 -c "import markdown,pathlib;print('ok')" && node -e "0"   # deps check
```

The PDF is produced by rendering `writeup.html` with headless Chrome:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
  --no-pdf-header-footer --print-to-pdf=Tedlar-Lead-Agent-Writeup.pdf \
  file://$PWD/writeup.html
```
