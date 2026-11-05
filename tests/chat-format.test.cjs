const {test} = require('node:test');
const assert = require('node:assert/strict');
require('../web/chat-format.js');
const {plainAnswer, sourceLabel} = globalThis.ChatFormat;

test('remove prose emphasis and convert star bullets, including escaped markers', () => {
  assert.equal(plainAnswer('**结论：不能。**\n* 要求 **审批**[S1]\n\\*\\*附注\\*\\*'),
    '结论：不能。\n• 要求 审批[S1]\n附注');
  assert.equal(plainAnswer('这是 *强调*。[S2]'), '这是 强调。[S2]');
});

test('preserve multiplication, wildcards, and code examples', () => {
  const text = '2 * 3 = 6；文件 *.pdf 和 *.md。\n`**保留**`\n```python\nx = 2 * 3\nprint("**原文**")\n```';
  assert.equal(plainAnswer(text), text);
});

test('source labels distinguish answer numbering from actual chunk numbering', () => {
  assert.equal(sourceLabel({id: 'S1', filename: 'D10_信息系统.md', ordinal: 7}),
    'S1 · D10_信息系统.md · 片段 7');
  assert.equal(sourceLabel({id: 'S2', filename: '制度.pdf', page: 3}),
    'S2 · 制度.pdf · 历史片段（序号未记录） · 第 3 页');
});
