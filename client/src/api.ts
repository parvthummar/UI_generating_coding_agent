export type ChatEvent = {
  name: string;
  data: any;
};

export async function sendMessage(
  text: string,
  onEvent: (name: string, data: any) => void,
) {
  const res = await fetch('http://localhost:8000/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text }),
  });
  if (!res.ok) {
    let message = 'Request failed';
    try {
      const body = await res.json();
      if (body.error) message = body.error;
    } catch {
      message = 'Request failed (' + res.status + ')';
    }
    throw new Error(message);
  }
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const result = await reader.read();
    if (result.done) break;
    buffer += decoder.decode(result.value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      const lines = part.split('\n');
      const name = lines[0].replace('event: ', '');
      const data = JSON.parse(lines[1].replace('data: ', ''));
      onEvent(name, data);
    }
  }
}

export async function loadFiles(): Promise<Record<string, string>> {
  const res = await fetch('http://localhost:8000/api/files');
  if (!res.ok) throw new Error('Could not load files');
  return res.json();
}

export async function resetSession() {
  const res = await fetch('http://localhost:8000/api/reset', { method: 'POST' });
  if (!res.ok) throw new Error('Could not reset the session');
}

export async function undoCommit(): Promise<{ files: Record<string, string>; remaining: number }> {
  const res = await fetch('http://localhost:8000/api/undo', { method: 'POST' });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || 'Could not undo');
  return body;
}
