/** Та же output boundary, что trace/privacy.py: контакты скрыты до ограничения длины. */
export function maskBusinessText(value: string | null | undefined, limit = 300): string {
  return (value ?? '')
    .replace(/(?<![\p{L}\p{N}_])(?:\+?[78][\s()-]*)?(?:\p{Nd}[\s()-]*){10,19}(?![\p{L}\p{N}_])/gu, text => `**** ${text.replace(/\P{Nd}/gu, '').slice(-4)}`)
    .replace(/[\p{L}\p{N}_.+-]+@[\p{L}\p{N}_.-]+\.[A-Za-z]{2,}/gu, '[email]')
    .replace(/@[\p{L}\p{N}_.-]+/gu, '@***').slice(0, limit)
}
