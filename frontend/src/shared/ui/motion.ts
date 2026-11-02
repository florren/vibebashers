/** ТЗ 26.3: короткие конечные переходы; бесконечная анимация запрещена. */
export const MOTION = { enterMs: 300, revealMs: 400, liftPx: 2, statusFadeMs: 1500, minBlinkIntervalMs: 3000 } as const
export const MAX_CALM_BLOCKS = 9
export function assertBlockBudget(root: ParentNode): void {
  const count = root.querySelectorAll('[data-block]').length
  if (count > MAX_CALM_BLOCKS) throw new Error(`Calm block budget exceeded: ${count}/${MAX_CALM_BLOCKS}`)
}
