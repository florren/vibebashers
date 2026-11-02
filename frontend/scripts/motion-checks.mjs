import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Linter } from 'eslint'
import { noInfiniteMotion } from './motion-rules.js'
import { checkMotionCss } from './check-motion.mjs'

test('lint rejects infinite CSS shorthands and iteration count, allows finite motion', () => {
  assert.equal(checkMotionCss('.x { animation: pulse 1s infinite; }').length, 1)
  assert.equal(checkMotionCss('.x { animation-iteration-count: infinite; }').length, 1)
  assert.equal(checkMotionCss('.x { animation: settle 1500ms ease-out 1; }').length, 0)
})
test('ESLint rejects infinite utilities and inline styles, allows finite classes', () => {
  const linter = new Linter()
  const config = [{ plugins: { attention: { rules: { motion: noInfiniteMotion } } }, rules: { 'attention/motion': 'error' } }]
  for (const source of ['const a = "animate-pulse"', 'const a = `animate-spin`', 'const a = { animation: "pulse 1s infinite" }']) assert.equal(linter.verify(source, config).length, 1)
  assert.equal(linter.verify('const a = "status-indicator fade-in"', config).length, 0)
})
