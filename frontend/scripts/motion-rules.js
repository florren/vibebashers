/** Бесконечные utility/inline-анимации запрещены; отдельного разрешённого набора пока нет. */
export const noInfiniteMotion = {
  meta: { type: 'problem', schema: [], messages: { infinite: 'Используйте конечный переход (ТЗ 26.3), без infinite/pulse/spin/ping/bounce.' } },
  create(context) {
    const check = node => {
      const value = node.type === 'TemplateElement' ? node.value.raw : node.value
      if (typeof value === 'string' && (/\banimate-(pulse|spin|ping|bounce)\b/.test(value) || /\binfinite\b/.test(value))) context.report({ node, messageId: 'infinite' })
    }
    return { Literal: check, TemplateElement: check }
  },
}
