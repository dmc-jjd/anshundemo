// This build owns one bundle. Other vendors (including deep-chat) are independent.
import { rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

rmSync(fileURLToPath(new URL('../app/static/vendor/canvas-editor.js', import.meta.url)), { force: true })
