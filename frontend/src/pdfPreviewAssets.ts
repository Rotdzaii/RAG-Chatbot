export { default as workerUrl } from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'

const assets = import.meta.glob<string>(
  '/node_modules/pdfjs-dist/{cmaps,standard_fonts,wasm}/*.{bcmap,pfb,ttf,wasm}',
  { import: 'default', query: '?url&no-inline' },
)
const folders = { cMapUrl: 'cmaps', standardFontDataUrl: 'standard_fonts', wasmUrl: 'wasm' }

export class PdfAssetLoader {
  async fetch({ kind, filename }: { kind: keyof typeof folders; filename: string }) {
    const asset = assets[`/node_modules/pdfjs-dist/${folders[kind]}/${filename}`]
    if (!asset) throw new Error(`Missing PDF asset: ${filename}`)
    const response = await fetch(await asset())
    if (!response.ok) throw new Error(`Cannot load PDF asset: ${filename}`)
    return new Uint8Array(await response.arrayBuffer())
  }
}
