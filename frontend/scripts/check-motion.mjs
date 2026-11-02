import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import postcss from 'postcss'

export function checkMotionCss(source) {
  const errors = []
  postcss.parse(source).walkDecls(/^animation(?:-.+)?$/, decl => {
    if (/\binfinite\b/.test(decl.value)) errors.push(`${decl.source.start.line}: ${decl.toString()}`)
  })
  return errors
}
function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? walk(resolve(directory, entry.name)) : entry.name.endsWith('.css') ? [resolve(directory, entry.name)] : [])
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const errors = walk(fileURLToPath(new URL('../src', import.meta.url))).flatMap(path => checkMotionCss(readFileSync(path, 'utf8')).map(error => `${path}:${error}`))
  if (errors.length) { process.stderr.write(errors.join('\n') + '\n'); process.exitCode = 1 }
}
