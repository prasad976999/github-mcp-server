// Builds STUDY-GUIDE.pptx: concept slides, code highlights, and clickable Q/A flashcards.
// Usage: node build_deck.js qa.json out.pptx
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.APPLY_THEME);

const [, , qaPath, outPath] = process.argv;
const CATS = JSON.parse(fs.readFileSync(qaPath, "utf8"));

const THEME = {
  name: "GitHub MCP Study",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1F2328", lt1: "FFFFFF", dk2: "0D1117", lt2: "F6F8FA",
    accent1: "2DA44E", accent2: "8250DF", accent3: "0969DA",
    accent4: "BF8700", accent5: "CF222E", accent6: "59636E",
    hlink: "0969DA", folHlink: "8250DF",
  },
};
const HEX = { ink: "1F2328", night: "0D1117", soft: "F6F8FA", green: "2DA44E", purple: "8250DF",
  blue: "0969DA", muted: "59636E", line: "D1D9E0", white: "FFFFFF", mint: "DAFBE1", lilac: "FBEFFF" };
const MONO = "Consolas";

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "GitHub MCP Server - Study Guide";
pres.author = "Prasad";
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "DARK",
  background: { color: C.text2 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 8.8, h: 0.8,
    fontSize: 32, bold: true, color: C.background1, fontFace: "Arial", valign: "top", align: "left", margin: 0 }, text: "" } }],
  slideNumber: { x: 9.2, y: 5.2, w: 0.5, h: 0.3, fontSize: 9, color: C.accent6 },
});
pres.defineSlideMaster({
  title: "LIGHT",
  background: { color: C.background1 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 8.8, h: 0.7,
    fontSize: 28, bold: true, color: C.text2, fontFace: "Arial", valign: "top", align: "left", margin: 0 }, text: "" } }],
  slideNumber: { x: 9.2, y: 5.2, w: 0.5, h: 0.3, fontSize: 9, color: C.accent6 },
});

async function icon(Comp, color) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: 256 }));
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

// Text with `code` spans rendered in monospace.
function runs(text, base = {}) {
  return text.split(/(`[^`]+`)/).filter(Boolean).map((part) =>
    part.startsWith("`")
      ? { text: part.slice(1, -1), options: { ...base, fontFace: MONO, color: base.codeColor || HEX.purple } }
      : { text: part, options: { ...base } });
}

// ---------- plan slide numbers up front so links can point anywhere ----------
const order = [];
const add = (key) => { order.push(key); return order.length; };
const N = {};
N.title = add("title");
N.contents = add("contents");
N.pitch = add("pitch");
N.roles = add("roles");
N.primitives = add("primitives");
N.handshake = add("handshake");
N.arch = add("arch");
N.toolbox = add("toolbox");
N.numbers = add("numbers");
N.anatomy = add("anatomy");
N.lifespan = add("lifespan");
N.guards = add("guards");
N.pagination = add("pagination");
N.retries = add("retries");
N.writes = add("writes");
N.tests = add("tests");
N.tests2 = add("tests2");
N.manual = add("manual");
N.ci = add("ci");
N.cards = add("cards");
const QN = {};
const TOTALQ = CATS.reduce((n, c) => n + c.qs.length, 0);
for (const cat of CATS) for (const q of cat.qs) { QN[q.n] = { q: add("q" + q.n), a: add("a" + q.n) }; }
N.practise = add("practise");
const firstQ = (cat) => QN[cat.qs[0].n].q;

function homeLink(slide, dark) {
  slide.addText("☰ Contents", { x: 0.6, y: 5.12, w: 1.4, h: 0.3, fontSize: 10, isTextBox: true, margin: 0,
    color: dark ? HEX.line : HEX.muted, hyperlink: { slide: N.contents, tooltip: "Back to contents" } });
}

(async () => {
  const ICONS = {
    pitch: await icon(fa.FaMicrophone, HEX.white), concepts: await icon(fa.FaProjectDiagram, HEX.white),
    arch: await icon(fa.FaLayerGroup, HEX.white), tools: await icon(fa.FaToolbox, HEX.white),
    code: await icon(fa.FaCode, HEX.white), tests: await icon(fa.FaVial, HEX.white),
    cards: await icon(fa.FaClone, HEX.white), check: await icon(fa.FaCheck, HEX.white),
    shield: await icon(fa.FaShieldAlt, HEX.white), cut: await icon(fa.FaCut, HEX.white),
    file: await icon(fa.FaFileImage, HEX.white), weight: await icon(fa.FaWeightHanging, HEX.white),
  };

  // 1. Title
  let s = pres.addSlide({ masterName: "DARK" });
  s.addText("GitHub MCP Server", { x: 0.6, y: 1.5, w: 8.8, h: 0.9, fontSize: 44, bold: true, color: HEX.white, fontFace: "Arial", isTextBox: true, margin: 0 });
  s.addText("Study guide · steps 1–3", { x: 0.6, y: 2.4, w: 8.8, h: 0.5, fontSize: 22, color: HEX.green, isTextBox: true, margin: 0 });
  s.addText("Concepts, code, tools, tests and interview flashcards. Click any link to jump around.", { x: 0.6, y: 3.1, w: 7.5, h: 0.6, fontSize: 14, color: HEX.line, isTextBox: true, margin: 0 });
  s.addText("Start ›", { x: 0.6, y: 4.1, w: 1.6, h: 0.45, shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.1, fill: { color: HEX.green }, color: HEX.white, bold: true, fontSize: 14, align: "center", hyperlink: { slide: N.contents } });

  // 2. Contents
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Contents", { placeholder: "title" });
  s.addText("Click a card to jump to that section.", { x: 0.6, y: 0.95, w: 8, h: 0.3, fontSize: 13, color: HEX.muted, isTextBox: true, margin: 0 });
  const toc = [
    ["Your pitch", "30-second answer", N.pitch, ICONS.pitch, HEX.green],
    ["MCP concepts", "Roles, primitives, handshake", N.roles, ICONS.concepts, HEX.purple],
    ["Architecture", "Layers and why", N.arch, ICONS.arch, HEX.blue],
    ["Toolbox", "Every tool and why", N.toolbox, ICONS.tools, HEX.green],
    ["Code tour", "Guards, retries, writes", N.anatomy, ICONS.code, HEX.purple],
    ["Tests & checks", "43 tests, CI, manual checks", N.tests, ICONS.tests, HEX.blue],
    ["Flashcards", `${TOTALQ} interview questions`, N.cards, ICONS.cards, HEX.green],
    ["Practise", "Checklist before interviews", N.practise, ICONS.check, HEX.purple],
  ];
  toc.forEach(([t, sub, target, ic, col], i) => {
    const x = 0.6 + (i % 4) * 2.25, y = 1.45 + Math.floor(i / 4) * 1.8;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 2.05, h: 1.6, rectRadius: 0.08, fill: { color: HEX.soft }, line: { color: HEX.line, width: 0.75 }, hyperlink: { slide: target }, objectName: "card " + t });
    s.addShape(pres.shapes.OVAL, { x: x + 0.2, y: y + 0.2, w: 0.5, h: 0.5, fill: { color: col } });
    s.addImage({ data: ic, x: x + 0.33, y: y + 0.33, w: 0.24, h: 0.24 });
    s.addText(t, { x: x + 0.2, y: y + 0.8, w: 1.75, h: 0.35, fontSize: 15, bold: true, color: HEX.ink, isTextBox: true, margin: 0, hyperlink: { slide: target } });
    s.addText(sub, { x: x + 0.2, y: y + 1.12, w: 1.75, h: 0.35, fontSize: 11, color: HEX.muted, isTextBox: true, margin: 0 });
  });

  // 3. Pitch
  s = pres.addSlide({ masterName: "DARK" });
  s.addText("Your 30-second pitch", { placeholder: "title" });
  s.addText("“I built an MCP server in Python that gives AI assistants like Claude safe, structured access to GitHub. It searches repositories, fetches details, browses folders and reads source files. I used the official MCP Python SDK, an async httpx client and Pydantic models to keep outputs small and typed. I focused on tool design: clear descriptions, input validation, errors the model can act on, and guards so large or binary files never flood the model’s context. Tests mock GitHub, so they run offline in about a second.”",
    { x: 0.6, y: 1.3, w: 8.8, h: 3.3, fontSize: 17, italic: true, color: HEX.white, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
  s.addText("Practise it out loud until you can say it without notes.", { x: 0.6, y: 4.65, w: 8.8, h: 0.35, fontSize: 13, color: HEX.green, isTextBox: true, margin: 0 });
  homeLink(s, true);

  // 4. Roles
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Three roles: host, client, server", { placeholder: "title" });
  const roles = [
    ["Host", "The AI app the user talks to", "Claude Desktop, Claude Code, MCP Inspector", HEX.purple],
    ["Client", "One connection inside the host", "Built into the host; mcp.Client in tests", HEX.blue],
    ["Server", "Exposes tools and does the work", "Our github-mcp server", HEX.green],
  ];
  roles.forEach(([t, d, e], i) => {
    const x = 0.6 + i * 3.05;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.5, w: 2.6, h: 2.3, rectRadius: 0.08, fill: { color: roles[i][3] } });
    s.addText(t, { x: x + 0.2, y: 1.65, w: 2.2, h: 0.5, fontSize: 22, bold: true, color: HEX.white, isTextBox: true, margin: 0 });
    s.addText(d, { x: x + 0.2, y: 2.2, w: 2.2, h: 0.7, fontSize: 14, color: HEX.white, isTextBox: true, margin: 0, valign: "top" });
    s.addText(e, { x: x + 0.2, y: 2.95, w: 2.2, h: 0.7, fontSize: 12, italic: true, color: HEX.white, isTextBox: true, margin: 0, valign: "top" });
    if (i < 2) s.addShape(pres.shapes.RIGHT_ARROW, { x: x + 2.65, y: 2.45, w: 0.35, h: 0.4, fill: { color: HEX.line } });
  });
  s.addText(runs("Why MCP exists: without a standard, N apps × M services need N×M integrations. MCP makes it N + M. Messages are JSON-RPC 2.0."), { x: 0.6, y: 4.1, w: 8.8, h: 0.7, fontSize: 14, color: HEX.ink, isTextBox: true, margin: 0 });
  homeLink(s);

  // 5. Primitives
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Tool vs resource vs prompt", { placeholder: "title" });
  const prims = [
    ["Tool", "MODEL decides", "An action the model calls", "list_issues, create_issue"],
    ["Resource", "APP / USER attaches", "Read-only data addressed by a URI", "github://repos/{owner}/{repo}/readme"],
    ["Prompt", "USER picks", "A reusable template, like a slash command", "review_pull_request, summarize_repository"],
  ];
  prims.forEach(([t, who, d, ex], i) => {
    const y = 1.3 + i * 1.2;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y, w: 8.8, h: 1.0, rectRadius: 0.06, fill: { color: HEX.soft }, line: { color: HEX.line, width: 0.75 } });
    s.addText(t, { x: 0.85, y: y + 0.15, w: 1.6, h: 0.7, fontSize: 20, bold: true, color: HEX.night, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(who, { x: 2.5, y: y + 0.3, w: 2.0, h: 0.4, fontSize: 11, bold: true, color: HEX.white, align: "center", shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.1, fill: { color: [HEX.green, HEX.blue, HEX.purple][i] } });
    s.addText(d, { x: 4.75, y: y + 0.12, w: 4.5, h: 0.4, fontSize: 14, color: HEX.ink, isTextBox: true, margin: 0 });
    s.addText(ex, { x: 4.75, y: y + 0.52, w: 4.5, h: 0.35, fontSize: 12, fontFace: MONO, color: HEX.purple, isTextBox: true, margin: 0 });
  });
  s.addText("Memorise: model-controlled, application-controlled, user-controlled.", { x: 0.6, y: 4.95, w: 8.8, h: 0.25, fontSize: 11, italic: true, color: HEX.muted, isTextBox: true, margin: 0 });
  homeLink(s);

  // 6. Handshake
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("What happens when a host connects", { placeholder: "title" });
  const hs = [
    ["1", "initialize", "Versions, capabilities, server instructions"],
    ["2", "tools/list", "Every tool’s name, description and JSON Schema"],
    ["3", "tools/call", "The model picks a tool; our function runs"],
    ["4", "result", "Data, or an error result the model can read"],
  ];
  hs.forEach(([n, m, d], i) => {
    const x = 0.6 + i * 2.25;
    s.addShape(pres.shapes.OVAL, { x: x + 0.7, y: 1.35, w: 0.6, h: 0.6, fill: { color: HEX.green } });
    s.addText(n, { x: x + 0.7, y: 1.35, w: 0.6, h: 0.6, fontSize: 18, bold: true, color: HEX.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
    if (i < 3) s.addShape(pres.shapes.LINE, { x: x + 1.4, y: 1.65, w: 1.95, h: 0, line: { color: HEX.line, width: 2 } });
    s.addText(m, { x, y: 2.15, w: 2.0, h: 0.4, fontSize: 15, bold: true, fontFace: MONO, color: HEX.purple, align: "center", isTextBox: true, margin: 0 });
    s.addText(d, { x, y: 2.6, w: 2.0, h: 0.9, fontSize: 13, color: HEX.ink, align: "center", isTextBox: true, margin: 0, valign: "top" });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 3.75, w: 8.8, h: 1.1, rectRadius: 0.06, fill: { color: HEX.mint } });
  s.addText(runs("Transport: stdio. The host starts our server as a subprocess and talks over stdin/stdout, so stdout belongs to the protocol. That’s why we never `print()` and log to stderr instead."), { x: 0.85, y: 3.85, w: 8.3, h: 0.9, fontSize: 14, color: HEX.ink, isTextBox: true, margin: 0, valign: "middle" });
  homeLink(s);

  // 7. Architecture
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Architecture: one job per layer", { placeholder: "title" });
  s.addText("Host\nClaude Desktop / Code", { x: 0.6, y: 2.0, w: 1.9, h: 1.3, shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.08, fill: { color: HEX.purple }, color: HEX.white, fontSize: 13, bold: true, align: "center", valign: "middle" });
  s.addText("JSON-RPC\nstdio", { x: 2.5, y: 2.2, w: 0.9, h: 0.6, fontSize: 9, color: HEX.muted, align: "center", isTextBox: true, margin: 0 });
  s.addShape(pres.shapes.RIGHT_ARROW, { x: 2.6, y: 2.8, w: 0.7, h: 0.3, fill: { color: HEX.line } });
  const layers = [["server.py", "MCP layer: tools, validation, errors for the model"], ["github_client.py", "HTTP layer: auth, timeouts, error mapping"], ["models.py", "Output shapes: ~100 fields → 13"], ["config.py", "Settings from environment / .env"]];
  layers.forEach(([f, d], i) => {
    const y = 1.3 + i * 0.75;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 3.45, y, w: 3.9, h: 0.62, rectRadius: 0.06, fill: { color: i === 0 ? HEX.night : HEX.soft }, line: { color: HEX.line, width: 0.75 } });
    s.addText(f, { x: 3.6, y, w: 1.55, h: 0.62, fontSize: 11, fontFace: MONO, bold: true, color: i === 0 ? HEX.green : HEX.purple, valign: "middle", isTextBox: true, margin: 0 });
    s.addText(d, { x: 5.15, y, w: 2.15, h: 0.62, fontSize: 10.5, color: i === 0 ? HEX.white : HEX.ink, valign: "middle", isTextBox: true, margin: 0 });
  });
  s.addText("HTTPS", { x: 7.4, y: 2.2, w: 0.7, h: 0.3, fontSize: 9, color: HEX.muted, align: "center", isTextBox: true, margin: 0 });
  s.addShape(pres.shapes.RIGHT_ARROW, { x: 7.45, y: 2.8, w: 0.6, h: 0.3, fill: { color: HEX.line } });
  s.addText("GitHub\nREST API", { x: 8.1, y: 2.0, w: 1.3, h: 1.3, shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.08, fill: { color: HEX.green }, color: HEX.white, fontSize: 13, bold: true, align: "center", valign: "middle" });
  s.addText("Interview line: “I separated the protocol layer from the API layer, so each can be tested on its own and changed without touching the other.”", { x: 0.6, y: 4.45, w: 8.8, h: 0.55, fontSize: 13, italic: true, color: HEX.ink, isTextBox: true, margin: 0 });
  homeLink(s);

  // 8. Toolbox
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Toolbox: what each tool does and why", { placeholder: "title" });
  const tb = [
    ["MCP SDK v2", "Protocol, schemas from type hints. Official.", "vs hand-written JSON-RPC"],
    ["httpx", "Async HTTP, pooling, timeouts, mockable", "vs requests (no async)"],
    ["Pydantic", "Validation + JSON Schema; SDK is built on it", "vs dataclasses"],
    ["python-dotenv", "Loads .env so secrets stay out of code", "vs pydantic-settings"],
    ["uv", "Python, venv, locked deps in one fast tool", "vs pip + venv, Poetry"],
    ["pytest", "Plain asserts, fixtures, clear failures", "vs unittest"],
    ["respx", "Fakes GitHub for httpx; blocks real calls", "vs pytest-httpx"],
    ["ruff", "Linter + formatter, extremely fast", "vs flake8 + black"],
  ];
  tb.forEach(([t, d, alt], i) => {
    const x = 0.6 + (i % 4) * 2.25, y = 1.2 + Math.floor(i / 4) * 1.85;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 2.05, h: 1.65, rectRadius: 0.06, fill: { color: i < 4 ? HEX.soft : HEX.lilac }, line: { color: HEX.line, width: 0.75 } });
    s.addText(t, { x: x + 0.15, y: y + 0.12, w: 1.8, h: 0.35, fontSize: 14, bold: true, color: HEX.night, isTextBox: true, margin: 0 });
    s.addText(d, { x: x + 0.15, y: y + 0.5, w: 1.8, h: 0.75, fontSize: 11, color: HEX.ink, isTextBox: true, margin: 0, valign: "top" });
    s.addText(alt, { x: x + 0.15, y: y + 1.25, w: 1.8, h: 0.3, fontSize: 10, italic: true, color: HEX.muted, isTextBox: true, margin: 0 });
  });
  s.addText("Grey: runtime libraries · Lilac: development tools · Also: MCP Inspector, Node.js, git, GitHub", { x: 0.6, y: 4.95, w: 8.8, h: 0.25, fontSize: 10, color: HEX.muted, isTextBox: true, margin: 0, align: "right" });
  homeLink(s);

  // 9. Numbers
  s = pres.addSlide({ masterName: "DARK" });
  s.addText("Numbers worth remembering", { placeholder: "title" });
  const nums = [["~100 → 13", "fields per repository after trimming"], ["60 → 5,000", "GitHub requests/hour once a token is added"], ["5", "max pages one list call can fetch"], ["3", "attempts at most; waits up to 0.5 s, then 1 s"]];
  nums.forEach(([n, l], i) => {
    const x = 0.6 + i * 2.25;
    s.addText(n, { x, y: 1.7, w: 2.15, h: 0.9, fontSize: 24, bold: true, color: HEX.green, isTextBox: true, margin: 0, fontFace: "Arial" });
    s.addText(l, { x, y: 2.65, w: 2.0, h: 0.9, fontSize: 13, color: HEX.line, isTextBox: true, margin: 0, valign: "top" });
  });
  s.addText("43 tests · ~93% coverage (floor 90%) · run by CI on 6 OS × Python combinations", { x: 0.6, y: 4.2, w: 8.8, h: 0.4, fontSize: 15, color: HEX.white, isTextBox: true, margin: 0 });
  homeLink(s, true);

  // 10. Tool anatomy
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Anatomy of a tool", { placeholder: "title" });
  const code = [
    ["@mcp.tool(annotations=READ_ONLY)", "#ff7b72"],
    ["async def get_repository(", "#e6edf3"],
    ["    owner: Owner,", "#e6edf3"], ["    repo: Repo,", "#e6edf3"], ["    ctx: Context,", "#e6edf3"],
    [") -> Repository:", "#e6edf3"],
    ['    """Get details of one GitHub', "#a5d6ff"], ['    repository: stars, topics ..."""', "#a5d6ff"],
    ["    try:", "#e6edf3"], ["        data = await _github(ctx).get(", "#e6edf3"],
    ['            f"/repos/{owner}/{repo}")', "#e6edf3"],
    ["    except GitHubAPIError as exc:", "#e6edf3"], ["        raise ToolError(str(exc)) from exc", "#e6edf3"],
    ["    return Repository.from_api(data)", "#e6edf3"],
  ];
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.15, w: 4.6, h: 3.8, rectRadius: 0.06, fill: { color: HEX.night } });
  s.addText(code.map(([t, c], i) => ({ text: t, options: { color: c.slice(1), breakLine: i < code.length - 1 } })), { x: 0.75, y: 1.25, w: 4.35, h: 3.6, fontSize: 10.5, fontFace: MONO, isTextBox: true, margin: 0, valign: "top" });
  const notes = [
    ["Decorator", "registers the tool; annotations say it’s read-only"],
    ["Name + type hints", "become the tool name and input JSON Schema"],
    ["ctx: Context", "injected by the SDK, hidden from the model"],
    ["Docstring", "is the description the model reads: it’s the prompt"],
    ["ToolError", "turns failures into isError results the model can act on"],
    ["Return model", "gives typed structured output, trimmed to 13 fields"],
  ];
  notes.forEach(([h, d], i) => {
    const y = 1.15 + i * 0.63;
    s.addShape(pres.shapes.OVAL, { x: 5.45, y: y + 0.08, w: 0.32, h: 0.32, fill: { color: HEX.green } });
    s.addText(String(i + 1), { x: 5.45, y: y + 0.08, w: 0.32, h: 0.32, fontSize: 11, bold: true, color: HEX.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
    s.addText([{ text: h + ": ", options: { bold: true, color: HEX.night } }, { text: d, options: { color: HEX.ink } }], { x: 5.9, y, w: 3.5, h: 0.55, fontSize: 12, isTextBox: true, margin: 0, valign: "middle" });
  });
  homeLink(s);

  // 11. Lifespan
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Lifespan: one shared HTTP client", { placeholder: "title" });
  const lcode = ["@asynccontextmanager", "async def lifespan(_server):", "    github = GitHubClient(settings)   # startup", "    try:", "        yield AppContext(github=github)", "    finally:", "        await github.aclose()         # shutdown"];
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.2, w: 5.2, h: 2.3, rectRadius: 0.06, fill: { color: HEX.night } });
  s.addText(lcode.map((t, i) => ({ text: t, options: { color: t.includes("#") ? "8B949E" : "E6EDF3", breakLine: i < lcode.length - 1 } })), { x: 0.8, y: 1.35, w: 4.9, h: 2.0, fontSize: 11.5, fontFace: MONO, isTextBox: true, margin: 0, valign: "top" });
  const why = [["Connection pooling", "TCP/TLS handshake once, not on every call"], ["Clean shutdown", "finally closes connections even after errors"], ["Dependency injection", "tools get the client via ctx; they never create it"], ["Async", "while waiting on GitHub, other requests are served"]];
  why.forEach(([h, d], i) => {
    const y = 1.2 + i * 0.6;
    s.addText([{ text: h, options: { bold: true, color: HEX.green, breakLine: true } }, { text: d, options: { color: HEX.ink } }], { x: 6.1, y, w: 3.3, h: 0.55, fontSize: 12, isTextBox: true, margin: 0, valign: "top" });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 3.8, w: 8.8, h: 1.0, rectRadius: 0.06, fill: { color: HEX.mint } });
  s.addText(runs("Tools reach it with `ctx.request_context.lifespan_context.github`. Code before `yield` runs at startup, code after it at shutdown."), { x: 0.85, y: 3.85, w: 8.3, h: 0.9, fontSize: 14, color: HEX.ink, isTextBox: true, margin: 0, valign: "middle" });
  homeLink(s);

  // 12. Guards
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Guarding the model’s context window", { placeholder: "title" });
  const guards = [
    [ICONS.cut, "Long text", "Cut at max_chars (default 20,000) with truncated: true", "So the model knows it saw only part of the file", HEX.green],
    [ICONS.file, "Binary file", "is_binary: true and no content", "Garbled bytes waste tokens and help no one", HEX.purple],
    [ICONS.weight, "Over 1 MB", "A clear error explaining the limit", "GitHub doesn’t inline big files (encoding: none)", HEX.blue],
    [ICONS.shield, "Wrong tool", "Error names the right tool", "The model fixes its own mistake next call", HEX.green],
  ];
  guards.forEach(([ic, t, what, why2, col], i) => {
    const x = 0.6 + (i % 2) * 4.45, y = 1.2 + Math.floor(i / 2) * 1.85;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 4.25, h: 1.65, rectRadius: 0.06, fill: { color: HEX.soft }, line: { color: HEX.line, width: 0.75 } });
    s.addShape(pres.shapes.OVAL, { x: x + 0.2, y: y + 0.2, w: 0.55, h: 0.55, fill: { color: col } });
    s.addImage({ data: ic, x: x + 0.34, y: y + 0.34, w: 0.27, h: 0.27 });
    s.addText(t, { x: x + 0.95, y: y + 0.2, w: 3.1, h: 0.4, fontSize: 16, bold: true, color: HEX.night, isTextBox: true, margin: 0 });
    s.addText(what, { x: x + 0.95, y: y + 0.62, w: 3.15, h: 0.45, fontSize: 12, color: HEX.ink, isTextBox: true, margin: 0, valign: "top" });
    s.addText(why2, { x: x + 0.95, y: y + 1.1, w: 3.15, h: 0.45, fontSize: 11, italic: true, color: HEX.muted, isTextBox: true, margin: 0, valign: "top" });
  });
  homeLink(s);

  // 12b. Pagination
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Pagination: following the Link header", { placeholder: "title" });
  const pcode = [
    ["for _ in range(MAX_PAGES):           # at most 5", "E6EDF3"],
    ["    response = await self._get_response(url, query)", "E6EDF3"],
    ["    items.extend(i for i in response.json() if keep(i))", "E6EDF3"],
    ['    url = response.links.get("next", {}).get("url")', "E6EDF3"],
    ["    if url and not url.startswith(base + \"/\"):", "E6EDF3"],
    ["        url = None                   # never leak token", "E6EDF3"],
    ["    query = None", "E6EDF3"],
    ["    if url is None or len(items) >= max_items:", "E6EDF3"],
    ["        break", "E6EDF3"],
    ["has_more = len(items) > max_items or url is not None", "E6EDF3"],
    ["return items[:max_items], has_more", "E6EDF3"],
  ];
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.15, w: 5.4, h: 3.0, rectRadius: 0.06, fill: { color: HEX.night } });
  s.addText(pcode.map(([t], i) => {
    const h = t.indexOf("#");
    const parts = h > 0 ? [[t.slice(0, h), "E6EDF3"], [t.slice(h), "8B949E"]] : [[t, "E6EDF3"]];
    return parts.map(([x, c], j) => ({ text: x, options: { color: c, breakLine: j === parts.length - 1 && i < pcode.length - 1 } }));
  }).flat(), { x: 0.75, y: 1.25, w: 5.15, h: 2.8, fontSize: 11, fontFace: MONO, isTextBox: true, margin: 0, valign: "top" });
  const pwhy = [["Link header", "GitHub says where the next page is; works for page and cursor APIs"], ["MAX_PAGES = 5", "bounds latency, rate limit and context, whatever the model asks"], ["Same-host check", "the token goes with every request; the trailing / blocks look-alike hosts"], ["has_more", "the model is told the list is partial"]];
  pwhy.forEach(([h, d], i) => {
    const y = 1.15 + i * 0.75;
    s.addText([{ text: h, options: { bold: true, color: HEX.green, breakLine: true } }, { text: d, options: { color: HEX.ink } }], { x: 6.25, y, w: 3.2, h: 0.7, fontSize: 11.5, isTextBox: true, margin: 0, valign: "top" });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 4.3, w: 8.8, h: 0.65, rectRadius: 0.06, fill: { color: HEX.mint } });
  s.addText(runs("`list_issues` passes `keep=lambda item: \"pull_request\" not in item`: every PR is also an issue on GitHub, so we drop them."), { x: 0.85, y: 4.32, w: 8.3, h: 0.6, fontSize: 12.5, color: HEX.ink, isTextBox: true, margin: 0, valign: "middle" });
  homeLink(s);

  // 12c. Retries
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Retries: what we retry, and why", { placeholder: "title" });
  const hdr = (t) => ({ text: t, options: { bold: true, color: HEX.white, fill: { color: HEX.night } } });
  const rrows = [
    ["Timeout / network error", "Retry (GET only)", "Usually temporary"],
    ["500, 502, 503, 504", "Retry (GET only)", "GitHub’s problem, often gone in a second"],
    ["429 / 403 + Retry-After ≤ 10 s", "Wait, then retry", "GitHub said when it’s OK"],
    ["Hourly limit used up", "Report reset time", "A tool call must never hang for minutes"],
    ["404, 401, 422, plain 403", "Fail at once", "Same request, same failure"],
  ];
  s.addTable([[hdr("Failure"), hdr("What we do"), hdr("Why")], ...rrows.map((r, i) => r.map((c, j) => ({ text: c, options: { bold: j === 1, color: j === 1 ? HEX.purple : HEX.ink, fill: { color: i % 2 ? HEX.soft : HEX.white } } })))],
    { x: 0.6, y: 1.15, w: 8.8, colW: [3.0, 2.0, 3.8], fontSize: 12, border: { type: "solid", color: HEX.line, pt: 0.5 }, rowH: 0.4 });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 3.75, w: 8.8, h: 1.15, rectRadius: 0.06, fill: { color: HEX.mint } });
  s.addText([
    { text: "Backoff with jitter: ", options: { bold: true, color: HEX.night } },
    { text: "wait a random time up to 0.5 s, then up to 1 s; at most 3 attempts. ", options: { color: HEX.ink, breakLine: true } },
    { text: "Idempotency: ", options: { bold: true, color: HEX.night } },
    { text: "a GET can be repeated safely. A POST like create_issue is never retried after a 5xx: it may already have worked.", options: { color: HEX.ink } },
  ], { x: 0.85, y: 3.8, w: 8.3, h: 1.05, fontSize: 13, isTextBox: true, margin: 0, valign: "middle", paraSpaceAfter: 4 });
  homeLink(s);

  // 12d. Writes
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("create_issue: five layers of safety", { placeholder: "title" });
  const safety = [
    ["Least-privilege token", "Your token is read-only, so GitHub itself refuses a write (403)."],
    ["Off by default", "GITHUB_ALLOW_WRITES must be true, checked before any request."],
    ["Annotations", "read_only_hint=False → hosts ask the user to approve each call."],
    ["Instructions", "Docstring: only when the user asked; confirm title and body first."],
    ["No blind retries", "A POST that hit a 5xx may have worked; retrying could duplicate it."],
  ];
  safety.forEach(([h, d], i) => {
    const y = 1.15 + i * 0.68;
    s.addShape(pres.shapes.OVAL, { x: 0.6, y: y + 0.08, w: 0.42, h: 0.42, fill: { color: [HEX.green, HEX.purple, HEX.blue, HEX.green, HEX.purple][i] } });
    s.addText(String(i + 1), { x: 0.6, y: y + 0.08, w: 0.42, h: 0.42, fontSize: 14, bold: true, color: HEX.white, align: "center", valign: "middle", isTextBox: true, margin: 0 });
    s.addText([{ text: h + ": ", options: { bold: true, color: HEX.night } }, { text: d, options: { color: HEX.ink } }], { x: 1.2, y, w: 8.2, h: 0.58, fontSize: 14, isTextBox: true, margin: 0, valign: "middle" });
  });
  s.addText("Annotations are hints, not security: layers 1 and 2 do the enforcing.", { x: 0.6, y: 4.6, w: 8.8, h: 0.3, fontSize: 12, italic: true, color: HEX.green, isTextBox: true, margin: 0 });
  homeLink(s);

  // 13. Tests (two slides)
  const tgroups = [
    ["Step 1 · wiring", ["server_status is listed and callable → whole MCP path works"]],
    ["Step 2 · repositories", ["fields trimmed and renamed → context saving works", "404 → readable tool error", "q and per_page sent correctly", "limit=500 rejected by schema", "timeout → tool error, not a crash"]],
    ["Step 3 · reading code", ["folders listed first", "file passed to list_directory → redirect", "base64 decoded, ref sent", "long file → truncated: true", "binary → no content", "folder passed to get_file_contents → redirect", "over 1 MB → clear error"]],
    ["Step 4 · issues, PRs, pages", ["PRs dropped from issues; fields trimmed", "state, labels, newest-first sent", "follows Link, stops at limit", "stops at 5 pages", "state=merged rejected", "PR head, base, draft", "PR 404 → tool error", "never follows links to other hosts"]],
    ["Step 5 · retries, rate limits", ["503 then 200 → retried, succeeds", "waits double: 0.5 s, then 1 s", "always 503 → gives up after 3", "timeout → retried", "404 → not retried, no wait", "Retry-After: 2 → waits 2 s", "hourly limit used up → reported, not waited", "plain 403 → not a rate limit", "get_rate_limit maps the budget"]],
    ["Step 6 · prompts, writes", ["README template listed", "README decoded; 404 readable", "prompts listed with arguments", "summary prompt names repo + tools", "review prompt loads PR + diffs", "huge diffs left out, counted", "missing PR → readable error", "create_issue hints all false", "writes off → refused, 0 requests", "POST body title/body/labels", "502 on POST → not retried", "empty title rejected"]],
  ];
  const groupColors = [HEX.green, HEX.purple, HEX.blue, HEX.green, HEX.purple, HEX.blue];
  const testSlide = (title, groups, offset) => {
    s = pres.addSlide({ masterName: "LIGHT" });
    s.addText(title, { placeholder: "title" });
    const w = 2.8, gap = 3.0;
    groups.forEach(([h, items], gi) => {
      const x = 0.6 + gi * gap;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.15, w, h: 3.75, rectRadius: 0.06, fill: { color: HEX.soft }, line: { color: HEX.line, width: 0.75 } });
      s.addText(h, { x: x + 0.15, y: 1.25, w: w - 0.3, h: 0.35, fontSize: 13, bold: true, color: groupColors[offset + gi], isTextBox: true, margin: 0 });
      s.addText(items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1 } })), { x: x + 0.1, y: 1.65, w: w - 0.2, h: 3.15, fontSize: items.length > 9 ? 10.5 : 12, color: HEX.ink, isTextBox: true, margin: 0, valign: "top", paraSpaceAfter: 4 });
    });
    homeLink(s);
  };
  testSlide("43 tests, and why each exists (1 of 2)", tgroups.slice(0, 3), 0);
  testSlide("43 tests, and why each exists (2 of 2)", tgroups.slice(3), 3);

  // 14. Manual checks
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("Manual checks against real GitHub", { placeholder: "title" });
  const mc = [["server_status", "authenticated: true", "Token loaded from .env"], ["search_repositories", "5 items of 70,718", "Trimming + limit work for real"], ["get_repository python-sdk", "13 fields, license MIT", "Field mapping matches real data"], ["get_repository nobody-xyz", "“Not found…” message", "Real errors reach the model readably"], ["git status", ".env not listed", "Token can never be pushed"]];
  s.addTable([
    [{ text: "Check", options: { bold: true, color: HEX.white, fill: { color: HEX.night } } }, { text: "What you saw", options: { bold: true, color: HEX.white, fill: { color: HEX.night } } }, { text: "Why we did it", options: { bold: true, color: HEX.white, fill: { color: HEX.night } } }],
    ...mc.map((r, i) => r.map((c, j) => ({ text: c, options: { fontFace: j === 0 ? MONO : undefined, color: j === 0 ? HEX.purple : HEX.ink, fill: { color: i % 2 ? HEX.soft : HEX.white } } }))),
  ], { x: 0.6, y: 1.2, w: 8.8, colW: [3.0, 2.6, 3.2], fontSize: 12, border: { type: "solid", color: HEX.line, pt: 0.5 }, rowH: 0.45 });
  s.addText("Mocked tests prove the logic; manual checks prove the mocks match reality.", { x: 0.6, y: 4.45, w: 8.8, h: 0.4, fontSize: 14, italic: true, color: HEX.green, isTextBox: true, margin: 0 });
  homeLink(s);

  // 14b. CI
  s = pres.addSlide({ masterName: "LIGHT" });
  s.addText("CI: every push checked on a clean machine", { placeholder: "title" });
  const jobs = [
    ["lint", "ruff check + ruff format --check", HEX.purple],
    ["test × 6", "Linux + Windows × Python 3.11, 3.12, 3.13", HEX.blue],
  ];
  s.addText("push to main / pull request", { x: 0.6, y: 1.3, w: 2.4, h: 0.6, fontSize: 13, bold: true, color: HEX.white, align: "center", valign: "middle", shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.08, fill: { color: HEX.night } });
  jobs.forEach(([h, d, c], i) => {
    const y = 1.15 + i * 0.75;
    s.addShape(pres.shapes.LINE, { x: 3.0, y: 1.6, w: 0.5, h: (y + 0.3) - 1.6, line: { color: HEX.muted, width: 1.25, endArrowType: "triangle" } });
    s.addText([{ text: h + "  ", options: { bold: true, color: HEX.white } }, { text: d, options: { color: HEX.white } }], { x: 3.5, y, w: 5.9, h: 0.6, fontSize: 13, valign: "middle", shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.08, fill: { color: c }, margin: 8 });
  });
  const ciwhy = [
    ["uv sync --locked", "exact versions; fails if uv.lock is stale"],
    ["permissions: read", "the run’s token can’t push or change settings"],
    ["--cov, fail under 90%", "new code must come with tests (~93% now)"],
    ["no secrets", "GitHub is mocked, so CI never needs your token"],
    ["Dependabot", "monthly update PRs, each tested by CI"],
  ];
  ciwhy.forEach(([h, d], i) => {
    const x = 0.6 + (i % 2) * 4.45, y = 2.8 + Math.floor(i / 2) * 0.68;
    s.addText([{ text: h, options: { bold: true, color: HEX.green, fontFace: MONO, breakLine: true } }, { text: d, options: { color: HEX.ink } }], { x, y, w: 4.3, h: 0.62, fontSize: 12, isTextBox: true, margin: 0, valign: "top" });
  });
  homeLink(s);

  // 15. Flashcards index
  s = pres.addSlide({ masterName: "DARK" });
  s.addText("Interview flashcards", { placeholder: "title" });
  s.addText("Read the question, answer out loud, then click “Show answer”. Pick a topic:", { x: 0.6, y: 1.15, w: 8.8, h: 0.4, fontSize: 14, color: HEX.line, isTextBox: true, margin: 0 });
  CATS.forEach((cat, i) => {
    const x = 0.6 + (i % 5) * 1.8, y = 1.6 + Math.floor(i / 5) * 1.15;
    const link = { slide: firstQ(cat) };
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 1.65, h: 1.0, rectRadius: 0.08, fill: { color: [HEX.green, HEX.purple, HEX.blue][i % 3] }, hyperlink: { ...link }, objectName: "topic " + cat.title });
    s.addText([{ text: cat.title.replace(/ \(step \d+\)$/, ""), options: { bold: true, fontSize: 11, breakLine: true, hyperlink: { ...link } } }, { text: `${cat.qs.length} questions · Q${cat.qs[0].n}–${cat.qs[cat.qs.length - 1].n}`, options: { fontSize: 11 } }],
      { x: x + 0.07, y, w: 1.55, h: 1.0, color: HEX.white, valign: "middle", isTextBox: true, margin: 0 });
  });
  homeLink(s, true);

  // Q/A pairs
  for (const cat of CATS) {
    for (const q of cat.qs) {
      const total = TOTALQ;
      s = pres.addSlide({ masterName: "DARK" });
      s.addText(`${cat.title.toUpperCase()} · QUESTION ${q.n} OF ${total}`, { x: 0.6, y: 0.45, w: 8.8, h: 0.3, fontSize: 12, bold: true, color: HEX.green, isTextBox: true, margin: 0 });
      s.addText(runs(q.q, { codeColor: "D2A8FF" }), { x: 0.6, y: 1.2, w: 8.8, h: 2.3, fontSize: 30, bold: true, color: HEX.white, fontFace: "Arial", isTextBox: true, margin: 0, valign: "middle" });
      s.addText("Show answer ›", { x: 0.6, y: 3.9, w: 2.2, h: 0.5, shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.1, fill: { color: HEX.green }, color: HEX.white, bold: true, fontSize: 15, align: "center", hyperlink: { slide: QN[q.n].a } });
      s.addText("Flashcard topics", { x: 7.4, y: 5.12, w: 1.6, h: 0.3, fontSize: 10, color: HEX.line, isTextBox: true, margin: 0, align: "right", hyperlink: { slide: N.cards } });
      homeLink(s, true);

      s = pres.addSlide({ masterName: "LIGHT" });
      s.addText(runs(`Q${q.n}. ${q.q}`), { x: 0.6, y: 0.4, w: 8.8, h: 0.7, fontSize: 16, bold: true, color: HEX.muted, isTextBox: true, margin: 0, valign: "top" });
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.25, w: 8.8, h: 2.7, rectRadius: 0.06, fill: { color: HEX.mint } });
      s.addText(runs(q.a, { codeColor: HEX.purple }), { x: 0.9, y: 1.4, w: 8.2, h: 2.4, fontSize: q.a.length > 200 ? 18 : 20, color: HEX.night, isTextBox: true, margin: 0, valign: "middle" });
      const next = q.n < total ? QN[q.n + 1].q : N.practise;
      s.addText(q.n < total ? "Next question ›" : "Finish ›", { x: 0.6, y: 4.3, w: 2.2, h: 0.5, shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.1, fill: { color: HEX.night }, color: HEX.white, bold: true, fontSize: 14, align: "center", hyperlink: { slide: next } });
      s.addText("‹ Back to question", { x: 3.0, y: 4.3, w: 2.2, h: 0.5, fontSize: 13, color: HEX.blue, isTextBox: true, margin: 0, valign: "middle", hyperlink: { slide: QN[q.n].q } });
      s.addText("Flashcard topics", { x: 7.4, y: 5.12, w: 1.6, h: 0.3, fontSize: 10, color: HEX.muted, isTextBox: true, margin: 0, align: "right", hyperlink: { slide: N.cards } });
      homeLink(s);
    }
  }

  // Practise
  s = pres.addSlide({ masterName: "DARK" });
  s.addText("Before your interview", { placeholder: "title" });
  const pr = ["Say the 30-second pitch without notes", "Draw the architecture from memory", "Explain initialize → tools/list → tools/call", "Explain get_paginated and the retry loop", "Explain the five safety layers of create_issue", `Answer all ${TOTALQ} flashcards out loud`];
  s.addText(pr.map((t, i) => ({ text: "☐  " + t, options: { breakLine: i < pr.length - 1 } })), { x: 0.6, y: 1.3, w: 8.8, h: 3.4, fontSize: 18, color: HEX.white, isTextBox: true, margin: 0, valign: "top", paraSpaceAfter: 8 });
  s.addText("Full detail, including every file of code: STUDY-GUIDE.pdf", { x: 0.6, y: 4.7, w: 8.8, h: 0.35, fontSize: 13, color: HEX.green, isTextBox: true, margin: 0 });
  homeLink(s, true);

  if (pres.slides.length !== order.length) throw new Error(`planned ${order.length} slides, built ${pres.slides.length}`);
  await pres.writeFile({ fileName: outPath });
  await applyTheme(outPath, THEME);
  console.log("wrote", outPath, pres.slides.length, "slides");
})();
