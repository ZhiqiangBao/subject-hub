/* Persistent JSONL OCR helper. Images stay local; language models are cached. */
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');

async function main() {
  const argv = process.argv.slice(2);
  const option = (name, fallback) => {
    const index = argv.indexOf(name);
    return index < 0 ? fallback : argv[index + 1];
  };
  const languages = option('--languages', 'rus+chi_sim');
  const cachePath = path.resolve(option('--cache-path', path.join(__dirname, '..', 'tmp', 'ocr-languages')));
  const modulePath = process.env.SUBJECT_HUB_TESSERACT_MODULE || 'tesseract.js';
  const { createWorker } = require(modulePath);
  const engine = `Tesseract.js ${require(modulePath + '/package.json').version}`;
  fs.mkdirSync(cachePath, { recursive: true });
  const worker = await createWorker(languages.split('+'), 1, { cachePath });
  await worker.setParameters({ tessedit_pageseg_mode: '3' });
  const send = (value) => process.stdout.write(JSON.stringify(value) + '\n');
  send({ ready: true, language: languages, engine, confidence_available: true });
  const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  try {
    for await (const line of input) {
      let request;
      try {
        request = JSON.parse(line);
        const result = await worker.recognize(path.resolve(request.path));
        send({ ok: true, request_id: request.request_id, text: result.data.text,
          confidence_available: true, average_word_confidence: result.data.confidence / 100,
          engine, language: languages });
      } catch (error) {
        send({ ok: false, request_id: request?.request_id, stage: 'recognize', error: error.message });
      }
    }
  } finally {
    await worker.terminate();
  }
}

main().catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
