import { useEffect, useRef, useState } from 'react';
import { loadFiles, resetSession, sendMessage } from './api';

type ChatItem = {
  id: number;
  kind: 'user' | 'assistant' | 'error' | 'status' | 'tool';
  text: string;
};

type Files = Record<string, string>;

let nextId = 1;

function statusText(data: { phase?: string; step?: number; attempt?: number }) {
  if (data.phase === 'thinking') return 'Thinking (step ' + data.step + ')';
  if (data.phase === 'validating') return 'Checking the compiler';
  if (data.phase === 'fixing_error') return 'Fixing a compiler error (attempt ' + data.attempt + ')';
  if (data.phase === 'waiting_for_rate_limit') return 'Waiting for the rate limit';
  return data.phase || 'Working';
}

export default function App() {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [files, setFiles] = useState<Files>({});
  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState<'preview' | 'code'>('preview');
  const [previewKey, setPreviewKey] = useState(0);
  const chatEnd = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ block: 'end' });
  }, [items]);

  function addItem(kind: ChatItem['kind'], text: string) {
    setItems((prev) => prev.concat({ id: nextId++, kind, text }));
  }

  async function refreshFiles() {
    const next = await loadFiles();
    setFiles(next);
    const names = Object.keys(next);
    setSelected((current) => (current && next[current] != null ? current : names[0] || ''));
  }

  useEffect(() => {
    refreshFiles().catch((err) => addItem('error', String(err.message || err)));
  }, []);

  async function onSend() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    setBusy(true);
    addItem('user', text);
    try {
      await sendMessage(text, (name, data) => {
        if (name === 'status') addItem('status', statusText(data));
        if (name === 'tool_call') {
          const path = data.path ? ' ' + data.path : '';
          addItem('tool', data.name + path + ', ' + (data.ok ? 'ok' : 'failed'));
        }
        if (name === 'files_updated') {
          setFiles(data.files || {});
          const names = Object.keys(data.files || {});
          setSelected((current) => (current && data.files[current] != null ? current : names[0] || ''));
          setPreviewKey((key) => key + 1);
        }
        if (name === 'assistant_message') addItem('assistant', data.text || '');
        if (name === 'error') addItem('error', data.message || 'The turn failed');
      });
    } catch (err: any) {
      addItem('error', err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onReset() {
    if (busy) return;
    setBusy(true);
    try {
      await resetSession();
      setItems([]);
      setPreviewKey((key) => key + 1);
      await refreshFiles();
    } catch (err: any) {
      addItem('error', err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  const names = Object.keys(files);

  return (
    <div className="flex h-screen bg-stone-100 text-stone-900">
      <section className="flex w-[420px] shrink-0 flex-col border-r border-stone-300 bg-white">
        <header className="flex items-center justify-between border-b border-stone-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-semibold">UI Agent</h1>
            <p className="text-xs text-stone-500">One session on this machine</p>
          </div>
          <button
            className="rounded border border-stone-300 px-3 py-1 text-sm disabled:opacity-50"
            onClick={onReset}
            disabled={busy}
          >
            New session
          </button>
        </header>
        <div className="flex-1 space-y-2 overflow-auto px-4 py-3">
          {items.length === 0 && (
            <p className="text-sm text-stone-500">Describe a UI. Follow-ups edit the same preview.</p>
          )}
          {items.map((item) => (
            <ChatLine key={item.id} item={item} />
          ))}
          <div ref={chatEnd} />
        </div>
        <form
          className="border-t border-stone-200 p-3"
          onSubmit={(event) => {
            event.preventDefault();
            onSend();
          }}
        >
          <textarea
            className="h-24 w-full resize-none rounded border border-stone-300 p-2 text-sm"
            value={draft}
            placeholder="Build a personal finance dashboard..."
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                onSend();
              }
            }}
          />
          <button
            className="mt-2 rounded bg-stone-900 px-4 py-2 text-sm text-white disabled:opacity-50"
            type="submit"
            disabled={busy || draft.trim() === ''}
          >
            {busy ? 'Working' : 'Send'}
          </button>
        </form>
      </section>
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex gap-2 border-b border-stone-300 bg-white px-4 py-2">
          <TabButton active={tab === 'preview'} onClick={() => setTab('preview')}>
            Preview
          </TabButton>
          <TabButton active={tab === 'code'} onClick={() => setTab('code')}>
            Code
          </TabButton>
        </div>
        {tab === 'preview' ? (
          <iframe
            key={previewKey}
            title="Preview"
            className="h-full w-full bg-white"
            src="http://localhost:5174"
            sandbox="allow-scripts allow-same-origin"
          />
        ) : (
          <div className="flex min-h-0 flex-1">
            <ul className="w-56 shrink-0 overflow-auto border-r border-stone-300 bg-white text-sm">
              {names.map((name) => (
                <li key={name}>
                  <button
                    className={
                      'block w-full truncate px-3 py-2 text-left ' +
                      (name === selected ? 'bg-stone-200' : 'hover:bg-stone-50')
                    }
                    onClick={() => setSelected(name)}
                  >
                    {name}
                  </button>
                </li>
              ))}
            </ul>
            <pre className="flex-1 overflow-auto p-4 text-xs leading-5">{files[selected] || ''}</pre>
          </div>
        )}
      </section>
    </div>
  );
}

function TabButton(props: { active: boolean; onClick: () => void; children: string }) {
  const tone = props.active ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-700';
  return (
    <button className={'rounded px-3 py-1 text-sm ' + tone} onClick={props.onClick}>
      {props.children}
    </button>
  );
}

function ChatLine(props: { item: ChatItem }) {
  const item = props.item;
  if (item.kind === 'tool') {
    return <p className="inline-block rounded-full bg-stone-200 px-3 py-1 text-xs">{item.text}</p>;
  }
  if (item.kind === 'status') {
    return <p className="text-xs text-stone-500">{item.text}</p>;
  }
  if (item.kind === 'error') {
    return <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">{item.text}</p>;
  }
  if (item.kind === 'user') {
    return <p className="rounded bg-stone-900 px-3 py-2 text-sm text-white">{item.text}</p>;
  }
  return <p className="rounded bg-stone-100 px-3 py-2 text-sm">{item.text}</p>;
}
