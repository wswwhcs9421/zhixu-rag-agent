'use strict';

globalThis.ChatFormat = Object.freeze({
  plainAnswer(value) {
    // Keep code examples intact; remove presentation markers only in prose.
    return String(value ?? '').split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`+[^\n]*?`+)/g)
      .map((part, index) => index % 2 ? part : part
        .replace(/\\(?=\*)/g, '')
        .replace(/^(\s*)\*\s+/gm, '$1• ')
        .replace(/(\*{2,3})(\S(?:[\s\S]*?\S)?)\1/g, '$2')
        .replace(/(^|[\s（(：:])\*(\S(?:[^*\n]*?\S)?)\*(?=$|[\s，。！？；：,.!?;:）)\[\]])/g, '$1$2'))
      .join('');
  },

  sourceLabel(source) {
    const ordinal = Number.isInteger(source.ordinal) && source.ordinal > 0
      ? `片段 ${source.ordinal}` : '历史片段（序号未记录）';
    return `${source.id} · ${source.filename} · ${ordinal}${source.page ? ` · 第 ${source.page} 页` : ''}`;
  },
});
