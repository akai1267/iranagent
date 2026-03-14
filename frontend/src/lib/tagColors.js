export const TAG_BORDER_COLORS = {
  nuclear: 'var(--accent)',
  urgent: 'var(--accent)',
  escalation: 'var(--accent-warm)',
  watch: 'var(--accent-warm)',
  military: 'var(--accent-warm)',
  intelligence: 'var(--accent-blue)',
  data: 'var(--accent-blue)',
  confirmed: 'var(--accent-green)',
  verified: 'var(--accent-green)',
  geopolitics: 'var(--accent-purple)',
  diplomacy: 'var(--accent-purple)',
  analysis: 'var(--accent-teal)',
  orbat: 'var(--accent-brown)',
  weapons: 'var(--accent-brown)',
}

const TAG_CLASS_MAP = {
  urgent: 'tag-urgent',
  nuclear: 'tag-urgent',
  escalation: 'tag-watch',
  watch: 'tag-watch',
  military: 'tag-watch',
  intelligence: 'tag-intel',
  data: 'tag-intel',
  confirmed: 'tag-pass',
  verified: 'tag-pass',
  geopolitics: 'tag-geo',
  diplomacy: 'tag-geo',
}

export function getCardBorderColor(tags) {
  const list = Array.isArray(tags)
    ? tags
    : String(tags || '')
        .split(',')
        .map((tag) => tag.trim().toLowerCase())
        .filter(Boolean)

  for (const tag of list) {
    if (TAG_BORDER_COLORS[tag]) {
      return TAG_BORDER_COLORS[tag]
    }
  }
  return null
}

export function getTagClass(tag) {
  return TAG_CLASS_MAP[String(tag || '').toLowerCase()] || 'tag-neutral'
}
