import { spawn } from 'node:child_process';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const output = path.dirname(fileURLToPath(import.meta.url));
const profile = await mkdtemp(path.join(tmpdir(), 'siz3r-mail-preview-'));
const browser = spawn('C:\\Users\\suici\\.cache\\puppeteer\\chrome-headless-shell\\win64-148.0.7778.97\\chrome-headless-shell-win64\\chrome-headless-shell.exe', [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--hide-scrollbars', '--disable-extensions', '--no-first-run',
  '--no-default-browser-check', 'about:blank',
], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
let browserLog = '';
browser.stderr.on('data', chunk => { browserLog += chunk.toString(); });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const pending = new Map();
let socket;
let sequence = 0;

async function send(method, params = {}) {
  const id = ++sequence;
  const result = new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)); }, 20000);
    pending.set(id, { resolve: value => { clearTimeout(timer); resolve(value); }, reject });
  });
  socket.send(JSON.stringify({ id, method, params }));
  return result;
}

try {
  let port;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { port = (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; }
    catch { await delay(100); }
  }
  if (!port) throw new Error(`Chrome did not start: ${browserLog.slice(-3000)}`);
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(JSON.stringify(message.error)));
    else request.resolve(message.result);
  };
  await send('Page.enable');
  if (process.argv.includes('--brand')) {
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: 'https://siz3r.com/pl/' });
    for (let attempt = 0; attempt < 150; attempt++) {
      const state = await send('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true });
      if (state.result.value === 'complete') break;
      await delay(100);
    }
    const inspection = await send('Runtime.evaluate', {
      expression: `(async () => {
        await Promise.race([document.fonts.ready, new Promise(resolve => setTimeout(resolve, 10000))]);
        const summarize = element => {
          const style = getComputedStyle(element);
          return { tag: element.tagName, text: element.textContent.trim().slice(0, 150),
            font: style.fontFamily, weight: style.fontWeight, size: style.fontSize,
            lineHeight: style.lineHeight, letterSpacing: style.letterSpacing,
            textTransform: style.textTransform, color: style.color,
            background: style.backgroundColor, borderColor: style.borderColor };
        };
        const elements = [...document.querySelectorAll('h1,h2,h3,p,a')].filter(element => {
          const rect = element.getBoundingClientRect();
          return rect.width && rect.height && element.textContent.trim();
        });
        const rootStyle = getComputedStyle(document.body);
        const tokens = Object.fromEntries([...rootStyle].filter(key => key.startsWith('--')).map(key => [key, rootStyle.getPropertyValue(key)]));
        const palette = {};
        for (const element of document.querySelectorAll('body *')) {
          const rect = element.getBoundingClientRect();
          if (!rect.width || !rect.height) continue;
          const style = getComputedStyle(element);
          for (const property of ['color', 'backgroundColor']) {
            const value = style[property];
            if (value !== 'rgba(0, 0, 0, 0)') palette[value] = (palette[value] || 0) + 1;
          }
        }
        return { url: location.href, title: document.title, body: summarize(document.body),
          elements: elements.map(summarize), tokens, palette,
          fonts: [...document.fonts].map(font => ({ family: font.family, weight: font.weight, style: font.style, status: font.status })),
          stylesheets: [...document.querySelectorAll('link[rel=stylesheet]')].map(link => link.href) };
      })()`, awaitPromise: true, returnByValue: true,
    });
    if (inspection.exceptionDetails) throw new Error(JSON.stringify(inspection.exceptionDetails));
    await writeFile(path.join(output, 'brand-inspection.json'), JSON.stringify(inspection.result.value, null, 2));
    const html = await send('Runtime.evaluate', { expression: 'document.documentElement.outerHTML', returnByValue: true });
    await writeFile(path.join(output, 'brand-page.html'), html.result.value);
    const capture = await send('Page.captureScreenshot', { format: 'png' });
    await writeFile(path.join(output, 'brand-desktop.png'), Buffer.from(capture.data, 'base64'));
    console.log(JSON.stringify(inspection.result.value, null, 2));
  } else {
  await send('DOM.enable');
  await send('CSS.enable');
  const source = pathToFileURL(path.join(output, 'Siz3r_mail_ofertowy_szablon.html')).href;
  const reports = [];
  for (const variant of [
    { name: 'desktop', width: 800, height: 1000, dark: false },
    { name: 'mobile', width: 390, height: 844, dark: false },
    { name: 'mobile-dark', width: 390, height: 844, dark: true },
    { name: 'mobile-narrow', width: 320, height: 700, dark: false },
  ]) {
    await send('Emulation.setDeviceMetricsOverride', {
      width: variant.width, height: variant.height, deviceScaleFactor: 1, mobile: false,
    });
    await send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-color-scheme', value: variant.dark ? 'dark' : 'light' }],
    });
    await send('Page.navigate', { url: source });
    for (let attempt = 0; attempt < 100; attempt++) {
      const state = await send('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true });
      if (state.result.value === 'complete') break;
      await delay(50);
    }
    const details = await send('Runtime.evaluate', {
      expression: `(async () => {
        await document.fonts.ready;
        await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
        return {
          viewport: innerWidth,
          contentWidth: document.documentElement.scrollWidth,
          contentHeight: document.documentElement.scrollHeight,
          brokenImages: [...document.images].filter(image => !image.naturalWidth).length,
          imageCount: document.images.length,
          ctas: [...document.querySelectorAll('.mail-button')].map(link => ({ label: link.textContent.trim(), href: link.href })),
          sheetBackground: getComputedStyle(document.querySelector('.mail')).backgroundColor,
          headlineColor: getComputedStyle(document.querySelector('h1')).color,
          headlineFont: getComputedStyle(document.querySelector('h1')).fontFamily,
          headlineWeight: getComputedStyle(document.querySelector('h1')).fontWeight,
          sectionWeight: getComputedStyle(document.querySelector('h2')).fontWeight,
          bodyFont: getComputedStyle(document.querySelector('.intro p')).fontFamily,
          bodyWeight: getComputedStyle(document.querySelector('.intro p')).fontWeight,
          bodyColor: getComputedStyle(document.querySelector('.intro p')).color,
          accentColor: getComputedStyle(document.querySelector('h1 span')).color,
          ctaColor: getComputedStyle(document.querySelector('.mail-button')).color,
          ctaBackground: getComputedStyle(document.querySelector('.mail-button')).backgroundColor,
          introElements: [...document.querySelector('.intro').children].map(element => element.tagName),
          containsPlaceholders: /\\[[^\\]]+\\]/.test(document.body.innerText),
          fontLoaded: document.fonts.check('600 32px Figtree', 'Pomóż klientom wybrać pewniej'),
          textSizes: [...new Set([...document.querySelectorAll('body *')].filter(element => {
            const rect = element.getBoundingClientRect();
            return rect.width && rect.height && [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
          }).map(element => getComputedStyle(element).fontSize))].sort((a, b) => parseFloat(a) - parseFloat(b)),
          measurementImage: (() => { const image = document.querySelector('.story-image img'); const rect = image.getBoundingClientRect(); return { naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight, width: rect.width, height: rect.height }; })(),
          clippedText: [...document.querySelectorAll('h1,h2,h3,p,a')].filter(element => element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).display !== 'inline').map(element => element.textContent.trim()),
        };
      })()`,
      awaitPromise: true, returnByValue: true,
    });
    const report = { variant: variant.name, ...details.result.value };
    const documentNode = await send('DOM.getDocument', { depth: 0 });
    const headlineNode = await send('DOM.querySelector', { nodeId: documentNode.root.nodeId, selector: 'h1' });
    report.renderedFonts = (await send('CSS.getPlatformFontsForNode', { nodeId: headlineNode.nodeId })).fonts;
    if (report.contentWidth > variant.width || report.brokenImages || report.clippedText.length) {
      throw new Error(JSON.stringify(report));
    }
    if (report.containsPlaceholders || !report.fontLoaded || report.introElements.join(',') !== 'IMG,H1,P' || report.ctas.length !== 1 ||
        report.headlineWeight !== '600' || report.sectionWeight !== '600' || report.bodyWeight !== '500' ||
        report.textSizes.join(',') !== '12px,16px,32px' ||
        Math.abs(report.measurementImage.width / report.measurementImage.height - report.measurementImage.naturalWidth / report.measurementImage.naturalHeight) > 0.01 ||
        report.sheetBackground !== 'rgb(0, 0, 0)' || report.headlineColor !== 'rgb(255, 255, 255)' ||
        report.bodyColor !== 'rgb(204, 204, 204)' || report.accentColor !== 'rgb(0, 210, 120)' ||
        report.ctaBackground !== 'rgb(112, 75, 155)' || report.ctaColor !== 'rgb(255, 255, 255)' ||
        !report.renderedFonts.every(font => font.familyName.startsWith('Figtree') && font.isCustomFont)) {
      throw new Error(`Brand or content validation failed: ${JSON.stringify(report)}`);
    }
    const capture = await send('Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: variant.width, height: report.contentHeight, scale: 1 },
    });
    await writeFile(path.join(output, `${variant.name}.png`), Buffer.from(capture.data, 'base64'));
    reports.push(report);
  }
  await writeFile(path.join(output, 'render-validation.json'), JSON.stringify(reports, null, 2));
  console.log(JSON.stringify(reports, null, 2));
  }
} finally {
  if (socket) socket.close();
  browser.kill();
}
