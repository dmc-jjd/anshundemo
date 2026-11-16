// 把 canvas-editor 打成单文件 IIFE，供 app/static 直接 <script> 引入。
// 产物：app/static/vendor/canvas-editor.js（含 JS 内置样式注入）

import * as esbuild from 'esbuild'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'

const here = path.dirname(fileURLToPath(import.meta.url))
const outDir = path.resolve(here, '..', 'app', 'static', 'vendor')
fs.mkdirSync(outDir, { recursive: true })

const result = await esbuild.build({
  entryPoints: [path.join(here, 'src', 'entry.js')],
  bundle: true,
  format: 'iife',
  globalName: 'KNCanvasBundle',
  platform: 'browser',
  target: ['es2020'],
  minify: true,
  legalComments: 'none',
  outfile: path.join(outDir, 'canvas-editor.js'),
  metafile: true,
})

const out = path.join(outDir, 'canvas-editor.js')
const size = fs.statSync(out).size
console.log(`✓ ${path.relative(process.cwd(), out)}  ${(size / 1024).toFixed(0)} KB`)
