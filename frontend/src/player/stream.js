// A response can split an SSE event at any UTF-8 byte boundary.
export async function readSearchStream(response, onResults, signal) {
  if (!response.ok) throw new Error(`search_${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const consume = (frame) => {
    const lines = frame.split('\n');
    const type = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
    const body = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
    if (body && type === 'results') onResults(JSON.parse(body));
  };
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        consume(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
      }
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
  } finally { reader.releaseLock(); }
}
