const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const [,, input, output] = process.argv;
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + input, { waitUntil: 'load' });
  await page.pdf({
    path: output, format: 'A4', printBackground: true, outline: true, tagged: true,
    displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#59636e;font-family:Arial">GitHub MCP Server · Study Guide · <span class="pageNumber"></span>/<span class="totalPages"></span></div>',
    margin: { top: '16mm', bottom: '18mm', left: '14mm', right: '14mm' },
  });
  await browser.close();
})();
