import { readdir, readFile, writeFile } from 'node:fs/promises';
import { join, extname } from 'node:path';
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';

/**
 * Кладёт рядом с текстовыми файлами их .br и .gz версии.
 *
 * Нужно только для варианта с Web Service: сжатием там никто не занимается,
 * а sirv отдаёт готовые архивы, если они лежат рядом. У Static Site сжатие
 * делает CDN Render, и этот шаг не запускается.
 */

const ROOT = join(import.meta.dirname, '..', 'dist');
const COMPRESSIBLE = new Set(['.html', '.css', '.js', '.mjs', '.svg', '.xml', '.txt', '.json']);
/** Мелочь сжимать смысла нет: заголовки съедят выигрыш. */
const MIN_BYTES = 1024;

const collect = async (dir) => {
  const entries = await readdir(dir, { withFileTypes: true });

  const nested = await Promise.all(
    entries.map((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return collect(path);
      return COMPRESSIBLE.has(extname(entry.name)) ? [path] : [];
    }),
  );

  return nested.flat();
};

const files = await collect(ROOT);
let compressed = 0;
let savedBytes = 0;

await Promise.all(
  files.map(async (path) => {
    const source = await readFile(path);
    if (source.byteLength < MIN_BYTES) return;

    const brotli = brotliCompressSync(source, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: 11,
        [constants.BROTLI_PARAM_SIZE_HINT]: source.byteLength,
      },
    });
    const gzip = gzipSync(source, { level: 9 });

    await Promise.all([
      writeFile(`${path}.br`, brotli),
      writeFile(`${path}.gz`, gzip),
    ]);

    compressed += 1;
    savedBytes += source.byteLength - brotli.byteLength;
  }),
);

const savedKb = Math.round(savedBytes / 1024);
process.stdout.write(`precompress: сжато файлов — ${compressed}, экономия по brotli — ${savedKb} КБ\n`);
