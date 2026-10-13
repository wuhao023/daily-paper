import assert from 'node:assert/strict';
import test from 'node:test';
import { b64encode, b64decode } from '../src/lib/base64.ts';

for (const [name, text] of [
  ['empty', ''],
  ['multilingual', '人形机器人 🤖 café 日本語 🌍'],
  ['before chunk boundary', 'a'.repeat(32767)],
  ['at chunk boundary', 'a'.repeat(32768)],
  ['multibyte character across chunk boundary', 'a'.repeat(32767) + '🤖中文'],
  ['large library', JSON.stringify({ items: Array.from({ length: 1000 }, (_, id) => ({
    id: String(id), title: '人形机器人 🤖', text: '论文摘要与项目说明'.repeat(60),
    liked: true, status: 'liked',
  })) })],
]) {
  test(`UTF-8 Base64 round trip: ${name}`, () => {
    const encoded = b64encode(text);
    assert.equal(encoded, Buffer.from(text, 'utf8').toString('base64'));
    assert.equal(b64decode(encoded), text);
  });
}

test('decode GitHub Base64 line wrapping', () => {
  const text = '中文书库 🤖'.repeat(100);
  const wrapped = Buffer.from(text).toString('base64').match(/.{1,60}/g).join('\r\n');
  assert.equal(b64decode(wrapped), text);
});
