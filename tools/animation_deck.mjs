// Native editable diagrams from a compiled task; no creative decisions here.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [bundlePath, outputDir, modulesDir] = process.argv.slice(2);
if (!bundlePath || !outputDir || !modulesDir) throw new Error('bundle output modules required');
const { Presentation, PresentationFile } = await import(pathToFileURL(
  path.join(modulesDir, '@oai/artifact-tool/dist/artifact_tool.mjs')).href);
const bundle = JSON.parse(await fs.readFile(bundlePath, 'utf8'));
await fs.mkdir(outputDir, { recursive: true });

function addPage(presentation, page, scene, objects) {
  const slide = presentation.slides.add();
  slide.background.fill = scene.background;
  for (const object of objects) {
    const item = slide.shapes.add({ geometry: object.geometry, name: object.name,
      position: object.position, fill: object.fill,
      line: { ...object.line, style: 'solid' } });
    if (object.text) {
      item.text = object.text;
      item.text.style = { fontFamily: 'Microsoft YaHei', fontSize: object.font_size,
        color: object.color || '#F2F4F7', bold: object.name === 'title' };
      item.text.insets = 0;
    }
  }
  slide.speakerNotes.text = page.narration.text + '\n\n事实来源\n' + page.sources.join('\n');
  return slide;
}

const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
for (let i = 0; i < bundle.pages.length; i++) {
  const { page, scene, previews } = bundle.pages[i];
  addPage(presentation, page, scene, scene.objects);
  for (const { frame, objects } of previews) {
    const preview = Presentation.create({ slideSize: { width: 1280, height: 720 } });
    const slide = addPage(preview, page, scene, objects);
    const png = await preview.export({ slide, format: 'png', scale: 1 });
    await fs.writeFile(path.join(outputDir, `${page.id}-f${frame}.png`), new Uint8Array(await png.arrayBuffer()));
  }
  console.log(`Native shapes and previews ready: ${page.id}`);
}
await (await PresentationFile.exportPptx(presentation)).save(path.join(outputDir, 'static.pptx'));
console.log('Static native deck exported; animation adapter is the next stage.');
