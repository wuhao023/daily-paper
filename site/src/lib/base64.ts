/** GitHub Contents API 使用的 UTF-8 Base64 编解码。 */
export function b64encode(str: string): string {
  const bytes = new TextEncoder().encode(str);
  const chunks: string[] = [];
  // 限制每次调用的参数数量，避免大书库触发浏览器的调用栈上限。
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + chunkSize)));
  }
  // 合并字节串后统一编码，分块边界不会引入 Base64 填充或破坏 UTF-8。
  return btoa(chunks.join(''));
}

export function b64decode(b64: string): string {
  const bin = atob(b64.replace(/\s/g, ''));
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}
