import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { loadFiles, resetSession, sendMessage, undoCommit } from './api';

type ChatItem = {
  id: number;
  kind: 'user' | 'assistant' | 'error' | 'status' | 'tool';
  text: string;
};

type Files = Record<string, string>;

type RuntimeError = {
  message?: string;
  stack?: string;
};

let nextId = 1;

function statusText(data: { phase?: string; step?: number; attempt?: number }) {
  if (data.phase === 'thinking') return 'Thinking (step ' + data.step + ')';
  if (data.phase === 'validating') return 'Checking types, build and render';
  if (data.phase === 'fixing_error') return 'Fixing an error (attempt ' + data.attempt + ' of 3)';
  if (data.phase === 'waiting_for_rate_limit') return 'Waiting for the rate limit';
  return data.phase || 'Working';
}

export default function App() {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [files, setFiles] = useState<Files>({});
  const [selected, setSelected] = useState('');
  const [previewKey, setPreviewKey] = useState(0);
  const [runtimeError, setRuntimeError] = useState<RuntimeError | null>(null);
  const [lastChanged, setLastChanged] = useState<string[]>([]);
  const [canUndo, setCanUndo] = useState(false);
  const [tab, setTab] = useState<'preview' | 'code'>('preview');
  const [chatPct, setChatPct] = useState(28);
  const [dragging, setDragging] = useState(false);
  const [ready, setReady] = useState(false);
  const chatEnd = useRef<HTMLDivElement | null>(null);
  const layoutRef = useRef<HTMLDivElement | null>(null);

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
    let cancelled = false;
    async function startFresh() {
      await refreshFiles();
      if (cancelled) return;
      setPreviewKey((key) => key + 1);
      setReady(true);
    }
    startFresh().catch((err) => {
      if (!cancelled) addItem('error', String(err.message || err));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.origin !== 'http://localhost:5174') return;
      if (event.data && event.data.type === 'SANDBOX_RUNTIME_ERROR') {
        const message = event.data.message || 'Unknown runtime error';
        setRuntimeError(event.data);
        addItem('error', 'Preview crashed: ' + message);
      }
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  function applyFiles(next: Files) {
    setFiles(next);
    const names = Object.keys(next);
    setSelected((current) => (current && next[current] != null ? current : names[0] || ''));
  }

  async function runTurn(text: string) {
    if (!text || busy) return;
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
          const changed: string[] = data.changed || [];
          applyFiles(data.files || {});
          setLastChanged(changed);
          if (changed.length > 0) setSelected(changed[changed.length - 1]);
          setPreviewKey((key) => key + 1);
          setRuntimeError(null);
          setCanUndo(true);
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

  async function onSend() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    await runTurn(text);
  }

  function onFix() {
    if (!runtimeError || busy) return;
    const text =
      'The preview compiled, then crashed at runtime. Repair the committed UI so this interaction works.\n' +
      'Error: ' +
      (runtimeError.message || '') +
      '\n' +
      'Stack: ' +
      (runtimeError.stack || '');
    runTurn(text);
  }

  async function onUndo() {
    if (busy || !canUndo) return;
    setBusy(true);
    try {
      const result = await undoCommit();
      applyFiles(result.files);
      setLastChanged([]);
      setPreviewKey((key) => key + 1);
      setRuntimeError(null);
      setCanUndo(result.remaining > 0);
      addItem('assistant', 'Restored the previous committed UI.');
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
      setRuntimeError(null);
      setLastChanged([]);
      setCanUndo(false);
      setPreviewKey((key) => key + 1);
      await refreshFiles();
    } catch (err: any) {
      addItem('error', err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  const names = Object.keys(files);

  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    const layout = layoutRef.current;
    if (!layout) return;
    event.preventDefault();
    const width = layout.getBoundingClientRect().width;
    const startX = event.clientX;
    const startChat = chatPct;
    setDragging(true);

    function move(ev: PointerEvent) {
      const delta = ((ev.clientX - startX) / width) * 100;
      setChatPct(clamp(startChat + delta, 18, 60));
    }

    function stop() {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
    }

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
  }

  return (
    <div
      ref={layoutRef}
      className={'flex h-screen bg-stone-100 text-stone-900 ' + (dragging ? 'select-none' : '')}
    >
      <section
        className="flex min-w-0 shrink-0 flex-col border-r border-stone-300 bg-white"
        style={{ width: chatPct + '%' }}
      >
        <header className="flex items-center justify-between border-b border-stone-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-semibold">UI Agent</h1>
            <p className="text-xs text-stone-500">One session on this machine</p>
          </div>
          <div className="flex gap-2">
            <button
              className="rounded border border-stone-300 px-3 py-1 text-sm disabled:opacity-50"
              onClick={onUndo}
              disabled={busy || !canUndo}
            >
              Undo
            </button>
            <button
              className="rounded border border-stone-300 px-3 py-1 text-sm disabled:opacity-50"
              onClick={onReset}
              disabled={busy}
            >
              New session
            </button>
          </div>
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
      <ResizeHandle label="Resize chat" onPointerDown={startResize} />
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex gap-2 border-b border-stone-300 bg-white px-4 py-2">
          <TabButton active={tab === 'preview'} onClick={() => setTab('preview')}>
            Preview
          </TabButton>
          <TabButton active={tab === 'code'} onClick={() => setTab('code')}>
            Code
          </TabButton>
          <p className="ml-auto self-center text-xs text-stone-500">
            {lastChanged.length > 0 ? 'Last change: ' + lastChanged.join(', ') : 'Committed preview'}
          </p>
        </div>
        {runtimeError && (
          <div className="flex items-start justify-between gap-3 border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
            <div className="min-w-0">
              <p>This preview crashed: {runtimeError.message}</p>
              {runtimeError.stack && (
                <pre className="mt-1 max-h-16 overflow-auto whitespace-pre-wrap text-xs">{runtimeError.stack}</pre>
              )}
            </div>
            <button
              className="shrink-0 rounded bg-red-800 px-3 py-1 text-white disabled:opacity-50"
              onClick={onFix}
              disabled={busy}
            >
              Ask the agent to fix this
            </button>
          </div>
        )}
        {tab === 'preview' ? (
          ready ? (
            <iframe
              key={previewKey}
              title="Preview"
              className={'min-h-0 w-full flex-1 border-0 bg-white ' + (dragging ? 'pointer-events-none' : '')}
              src="http://localhost:5174"
              sandbox="allow-scripts allow-same-origin allow-modals"
              referrerPolicy="no-referrer"
              allow=""
            />
          ) : (
            <div className="min-h-0 flex-1 bg-white" />
          )
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
                    {lastChanged.includes(name) ? '● ' : ''}
                    {name}
                  </button>
                </li>
              ))}
            </ul>
            <pre className="min-w-0 flex-1 overflow-auto p-4 text-xs leading-5">{files[selected] || ''}</pre>
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

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function ResizeHandle(props: {
  label: string;
  onPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={props.label}
      title={props.label}
      className="w-1.5 shrink-0 cursor-col-resize bg-stone-300 hover:bg-stone-500"
      onPointerDown={props.onPointerDown}
    />
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
