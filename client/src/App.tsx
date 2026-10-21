import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { loadFiles, resetSession, sendMessage, undoCommit } from './api';

type ToolInfo = {
  name: string;
  path: string;
  ok: boolean;
};

type ChatItem = {
  id: number;
  kind: 'user' | 'assistant' | 'error' | 'status' | 'tool';
  text: string;
  phase?: string;
  tool?: ToolInfo;
};

type Files = Record<string, string>;

type RuntimeError = {
  message?: string;
  stack?: string;
};

type Block =
  | { kind: 'message'; item: ChatItem }
  | { kind: 'activity'; id: number; items: ChatItem[] };

let nextId = 1;

const SUGGESTIONS = [
  { label: 'Form', text: 'Contact form with name, email and message, validation, and a success message' },
  { label: 'Dashboard', text: 'Finance dashboard with summary cards, a bar chart of spending, and a transactions table' },
  { label: 'Landing page', text: 'Landing page for a fictional coffee brand with hero, features, pricing and footer' },
  { label: 'Small app', text: 'Kanban board with 3 columns and buttons to move cards' },
];

function statusText(data: { phase?: string; step?: number; attempt?: number; count?: number }) {
  if (data.phase === 'thinking') return 'Thinking (step ' + data.step + ')';
  if (data.phase === 'type_errors') return 'Type check found ' + data.count + ' error(s), sending them back to the agent';
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
  const [chatPct, setChatPct] = useState(30);
  const [dragging, setDragging] = useState(false);
  const [ready, setReady] = useState(false);
  const chatEnd = useRef<HTMLDivElement | null>(null);
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ block: 'end' });
  }, [items]);

  function addItem(kind: ChatItem['kind'], text: string, extra?: { phase?: string; tool?: ToolInfo }) {
    setItems((prev) => prev.concat({ id: nextId++, kind, text, phase: extra?.phase, tool: extra?.tool }));
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
        if (name === 'status') addItem('status', statusText(data), { phase: data.phase });
        if (name === 'tool_call') {
          const path = data.path ? ' ' + data.path : '';
          addItem('tool', data.name + path + ', ' + (data.ok ? 'ok' : 'failed'), {
            tool: { name: data.name || '', path: data.path || '', ok: !!data.ok },
          });
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

  function pickSuggestion(text: string) {
    setDraft(text);
    inputRef.current?.focus();
  }

  const names = Object.keys(files);
  const blocks = groupItems(items);

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
      setChatPct(clamp(startChat + delta, 22, 60));
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
      className={'flex h-screen bg-zinc-950 text-zinc-100 antialiased ' + (dragging ? 'cursor-col-resize select-none' : '')}
    >
      <section className="flex min-w-0 shrink-0 flex-col bg-zinc-900/60" style={{ width: chatPct + '%' }}>
        <header className="flex items-center justify-between gap-3 border-b border-white/5 px-5 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-900/40">
              <Icon paths={ICONS.sparkle} className="h-5 w-5 text-white" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-[15px] font-semibold tracking-tight">UI Agent</h1>
              <p className="truncate text-xs text-zinc-500">Prompt to live React</p>
            </div>
          </div>
          <div className="flex shrink-0 gap-1.5">
            <HeaderButton onClick={onUndo} disabled={busy || !canUndo} title="Restore the previous committed UI">
              <Icon paths={ICONS.undo} className="h-4 w-4" />
              Undo
            </HeaderButton>
            <HeaderButton onClick={onReset} disabled={busy} title="Clear the chat and start from a blank page">
              <Icon paths={ICONS.plus} className="h-4 w-4" />
              New session
            </HeaderButton>
          </div>
        </header>

        <div className="chat-scroll flex-1 overflow-auto px-5 py-5">
          {items.length === 0 ? (
            <EmptyState onPick={pickSuggestion} />
          ) : (
            <div className="space-y-4">
              {blocks.map((block, index) =>
                block.kind === 'activity' ? (
                  <ActivityGroup key={block.id} items={block.items} live={busy && index === blocks.length - 1} />
                ) : (
                  <ChatLine key={block.item.id} item={block.item} />
                ),
              )}
              {busy && blocks.length > 0 && blocks[blocks.length - 1].kind !== 'activity' && (
                <div className="flex items-center gap-2 pl-10 text-xs text-zinc-500">
                  <Spinner />
                  Starting
                </div>
              )}
            </div>
          )}
          <div ref={chatEnd} />
        </div>

        <form
          className="px-4 pb-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSend();
          }}
        >
          <div className="relative rounded-2xl border border-white/10 bg-zinc-950/80 shadow-xl shadow-black/20 transition focus-within:border-violet-500/60 focus-within:ring-4 focus-within:ring-violet-500/10">
            <textarea
              ref={inputRef}
              className="block h-24 w-full resize-none bg-transparent px-4 pt-3 pb-12 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
              value={draft}
              placeholder={items.length === 0 ? 'Build a personal finance dashboard...' : 'Ask for a change, for example "make the header green"'}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  onSend();
                }
              }}
            />
            <div className="absolute inset-x-3 bottom-3 flex items-center justify-between gap-2">
              <span className="truncate pl-1 text-[11px] text-zinc-600">
                <Kbd>Enter</Kbd> to send, <Kbd>Shift</Kbd> + <Kbd>Enter</Kbd> for a new line
              </span>
              <button
                className="flex h-8 shrink-0 items-center gap-1.5 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 px-3 text-sm font-medium text-white shadow-md shadow-violet-900/40 transition hover:brightness-110 disabled:cursor-not-allowed disabled:from-zinc-700 disabled:to-zinc-700 disabled:text-zinc-400 disabled:shadow-none"
                type="submit"
                disabled={busy || draft.trim() === ''}
              >
                {busy ? <Spinner light /> : <Icon paths={ICONS.send} className="h-4 w-4" />}
                {busy ? 'Working' : 'Send'}
              </button>
            </div>
          </div>
        </form>
      </section>

      <ResizeHandle label="Resize chat" onPointerDown={startResize} />

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-white/5 px-4 py-3">
          <div className="flex rounded-xl bg-zinc-900 p-1 ring-1 ring-white/5">
            <TabButton active={tab === 'preview'} onClick={() => setTab('preview')} icon={ICONS.eye}>
              Preview
            </TabButton>
            <TabButton active={tab === 'code'} onClick={() => setTab('code')} icon={ICONS.code}>
              Code
            </TabButton>
          </div>
          <div className="ml-auto flex min-w-0 items-center gap-2 text-xs text-zinc-500">
            {busy ? (
              <>
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-violet-500" />
                </span>
                <span className="truncate">Agent is working, the preview updates when the change passes all checks</span>
              </>
            ) : (
              <>
                <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" />
                <span className="truncate" title={lastChanged.join('\n')}>
                  {lastChanged.length > 0
                    ? 'Last change: ' + lastChanged.length + ' file' + (lastChanged.length === 1 ? '' : 's') + ' updated'
                    : 'Committed preview'}
                </span>
              </>
            )}
          </div>
        </div>

        {runtimeError && (
          <div className="mx-4 mt-3 flex items-start justify-between gap-3 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            <div className="flex min-w-0 gap-3">
              <Icon paths={ICONS.alert} className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
              <div className="min-w-0">
                <p className="font-medium">This preview crashed: {runtimeError.message}</p>
                {runtimeError.stack && (
                  <pre className="mt-1 max-h-16 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-red-300/80">
                    {runtimeError.stack}
                  </pre>
                )}
              </div>
            </div>
            <button
              className="flex shrink-0 items-center gap-1.5 rounded-lg bg-red-500 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-red-400 disabled:opacity-50"
              onClick={onFix}
              disabled={busy}
            >
              <Icon paths={ICONS.wrench} className="h-3.5 w-3.5" />
              Ask the agent to fix this
            </button>
          </div>
        )}

        <div className="flex min-h-0 flex-1 p-4">
          {tab === 'preview' ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-2xl shadow-black/40 ring-1 ring-white/10">
              <div className="flex h-10 shrink-0 items-center gap-3 border-b border-zinc-200 bg-zinc-100 px-4">
                <div className="flex gap-1.5">
                  <span className="h-3 w-3 rounded-full bg-red-400" />
                  <span className="h-3 w-3 rounded-full bg-amber-400" />
                  <span className="h-3 w-3 rounded-full bg-emerald-400" />
                </div>
                <div className="mx-auto flex w-full max-w-sm items-center justify-center gap-2 rounded-md bg-white px-3 py-1 text-xs text-zinc-500 ring-1 ring-zinc-200">
                  <Icon paths={ICONS.lock} className="h-3 w-3" />
                  localhost:5174
                </div>
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-emerald-700 uppercase">
                  Live
                </span>
              </div>
              {ready ? (
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
                <div className="grid min-h-0 flex-1 place-items-center bg-white text-sm text-zinc-400">
                  <div className="flex items-center gap-2">
                    <Spinner />
                    Loading preview
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 overflow-hidden rounded-2xl bg-zinc-900 ring-1 ring-white/10">
              <div className="flex w-60 shrink-0 flex-col border-r border-white/5">
                <p className="px-4 pt-4 pb-2 text-[11px] font-semibold tracking-wider text-zinc-500 uppercase">
                  Files
                </p>
                <ul className="chat-scroll flex-1 space-y-0.5 overflow-auto px-2 pb-3 text-sm">
                  {names.map((name) => (
                    <li key={name}>
                      <FileButton
                        name={name}
                        active={name === selected}
                        changed={lastChanged.includes(name)}
                        onClick={() => setSelected(name)}
                      />
                    </li>
                  ))}
                </ul>
                {lastChanged.length > 0 && (
                  <p className="flex items-center gap-2 border-t border-white/5 px-4 py-3 text-[11px] text-zinc-500">
                    <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
                    Changed in the last turn
                  </p>
                )}
              </div>
              <CodeView name={selected} text={files[selected] || ''} changed={lastChanged.includes(selected)} />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function groupItems(items: ChatItem[]) {
  const blocks: Block[] = [];
  for (const item of items) {
    const isActivity = item.kind === 'status' || item.kind === 'tool';
    const last = blocks[blocks.length - 1];
    if (isActivity && last && last.kind === 'activity') {
      last.items.push(item);
    } else if (isActivity) {
      blocks.push({ kind: 'activity', id: item.id, items: [item] });
    } else {
      blocks.push({ kind: 'message', item });
    }
  }
  return blocks;
}

function EmptyState(props: { onPick: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col justify-center py-6">
      <div className="mb-5 grid h-12 w-12 place-items-center rounded-2xl bg-violet-500/10 ring-1 ring-violet-500/20">
        <Icon paths={ICONS.sparkle} className="h-6 w-6 text-violet-300" />
      </div>
      <h2 className="text-xl font-semibold tracking-tight">What should we build?</h2>
      <p className="mt-2 text-sm leading-6 text-zinc-400">
        Describe a UI in plain English. The agent writes React code, checks that it builds and renders, then shows
        it live. Follow-ups edit the same UI.
      </p>
      <div className="mt-6 grid gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion.label}
            className="group rounded-xl border border-white/5 bg-white/[0.03] px-4 py-3 text-left transition hover:border-violet-500/30 hover:bg-violet-500/5"
            onClick={() => props.onPick(suggestion.text)}
          >
            <span className="text-[11px] font-semibold tracking-wider text-violet-300/80 uppercase">
              {suggestion.label}
            </span>
            <span className="mt-0.5 block text-sm text-zinc-300 group-hover:text-zinc-100">{suggestion.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function ActivityGroup(props: { items: ChatItem[]; live: boolean }) {
  const tools = props.items.filter((item) => item.kind === 'tool');
  const corrected = props.items.some((item) => item.phase === 'type_errors' || item.phase === 'fixing_error');
  const failedTools = tools.filter((item) => item.tool && !item.tool.ok).length;
  const latest = props.items[props.items.length - 1];
  return (
    <details open={props.live || undefined} className="group ml-10 rounded-xl border border-white/5 bg-white/[0.02]">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs text-zinc-400 select-none">
        {props.live ? <Spinner /> : <Icon paths={ICONS.chevron} className="h-3.5 w-3.5 transition group-open:rotate-90" />}
        <span className="truncate">
          {props.live && latest ? latest.text : 'Worked through ' + tools.length + ' tool call' + (tools.length === 1 ? '' : 's')}
        </span>
        {corrected && (
          <span className="ml-auto shrink-0 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300 ring-1 ring-amber-500/20">
            self-corrected
          </span>
        )}
        {failedTools > 0 && !corrected && (
          <span className="ml-auto shrink-0 text-[10px] text-zinc-500">{failedTools} retried</span>
        )}
      </summary>
      <ol className="space-y-1 border-t border-white/5 px-3 py-2">
        {props.items.map((item) => (item.kind === 'tool' ? <ToolLine key={item.id} item={item} /> : <StatusLine key={item.id} item={item} />))}
      </ol>
    </details>
  );
}

function StatusLine(props: { item: ChatItem }) {
  const phase = props.item.phase;
  let tone = 'text-zinc-500';
  let dot = 'bg-zinc-600';
  if (phase === 'type_errors' || phase === 'fixing_error') {
    tone = 'text-amber-300/90';
    dot = 'bg-amber-400';
  } else if (phase === 'validating') {
    tone = 'text-sky-300/90';
    dot = 'bg-sky-400';
  }
  return (
    <li className={'flex items-start gap-2 text-xs ' + tone}>
      <span className={'mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ' + dot} />
      <span>{props.item.text}</span>
    </li>
  );
}

function ToolLine(props: { item: ChatItem }) {
  const tool = props.item.tool;
  if (!tool) return <li className="text-xs text-zinc-500">{props.item.text}</li>;
  const verbs: Record<string, string> = {
    write_file: 'Wrote',
    edit_file: 'Edited',
    read_file: 'Read',
    delete_file: 'Deleted',
  };
  const icons: Record<string, string[]> = {
    write_file: ICONS.filePlus,
    edit_file: ICONS.pencil,
    read_file: ICONS.file,
    delete_file: ICONS.trash,
  };
  return (
    <li className="flex items-center gap-2 text-xs">
      <Icon paths={icons[tool.name] || ICONS.file} className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
      <span className="text-zinc-400">{verbs[tool.name] || tool.name}</span>
      <code className="truncate rounded bg-white/5 px-1.5 py-0.5 font-mono text-[11px] text-zinc-300">
        {tool.path || '-'}
      </code>
      {tool.ok ? (
        <Icon paths={ICONS.check} className="ml-auto h-3.5 w-3.5 shrink-0 text-emerald-400" />
      ) : (
        <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] text-red-300">
          <Icon paths={ICONS.x} className="h-3.5 w-3.5" />
          failed
        </span>
      )}
    </li>
  );
}

function ChatLine(props: { item: ChatItem }) {
  const item = props.item;
  if (item.kind === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-violet-500 to-indigo-600 px-4 py-2.5 text-sm leading-6 whitespace-pre-wrap text-white shadow-lg shadow-violet-950/40">
          {item.text}
        </p>
      </div>
    );
  }
  if (item.kind === 'error') {
    return (
      <div className="ml-10 flex gap-2.5 rounded-xl border border-red-500/20 bg-red-500/10 px-3.5 py-2.5 text-sm leading-6 text-red-200">
        <Icon paths={ICONS.alert} className="mt-1 h-4 w-4 shrink-0 text-red-400" />
        <p className="min-w-0 break-words whitespace-pre-wrap">{item.text}</p>
      </div>
    );
  }
  return (
    <div className="flex gap-3">
      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-zinc-800 ring-1 ring-white/10">
        <Icon paths={ICONS.sparkle} className="h-3.5 w-3.5 text-violet-300" />
      </div>
      <p className="min-w-0 pt-0.5 text-sm leading-6 whitespace-pre-wrap text-zinc-200">
        <InlineCode text={item.text} />
      </p>
    </div>
  );
}

function InlineCode(props: { text: string }) {
  // The agent wraps names in backticks. Odd-numbered pieces are inside a pair of backticks.
  const parts = props.text.split('`');
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 && index < parts.length - 1 ? (
          <code key={index} className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-[12px] text-violet-200">
            {part}
          </code>
        ) : (
          <span key={index}>{index % 2 === 1 ? '`' + part : part}</span>
        ),
      )}
    </>
  );
}

function FileButton(props: { name: string; active: boolean; changed: boolean; onClick: () => void }) {
  const slash = props.name.lastIndexOf('/');
  const dir = props.name.slice(0, slash).replace(/^src\/?/, '');
  const base = props.name.slice(slash + 1);
  return (
    <button
      className={
        'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition ' +
        (props.active ? 'bg-white/10 text-zinc-100' : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200')
      }
      onClick={props.onClick}
      title={props.name}
    >
      <Icon paths={ICONS.file} className={'h-4 w-4 shrink-0 ' + (props.active ? 'text-violet-300' : 'text-zinc-500')} />
      <span className="shrink-0">{base}</span>
      {dir && <span className="min-w-0 truncate text-[11px] text-zinc-600">{dir}</span>}
      {props.changed && <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" title="Changed in the last turn" />}
    </button>
  );
}

function CodeView(props: { name: string; text: string; changed: boolean }) {
  const lines = props.text.split('\n');
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-white/5 px-4 text-xs">
        <span className="truncate font-mono text-zinc-300">{props.name || 'No file selected'}</span>
        {props.changed && (
          <span className="rounded-full bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-300 ring-1 ring-violet-500/20">
            changed
          </span>
        )}
        <span className="ml-auto shrink-0 text-zinc-600">{props.name ? lines.length + ' lines' : ''}</span>
      </div>
      <div className="chat-scroll min-h-0 flex-1 overflow-auto bg-zinc-950/60">
        <pre className="min-w-max py-3 font-mono text-[12.5px] leading-6 text-zinc-300">
          {lines.map((line, index) => (
            <div key={index} className="flex hover:bg-white/[0.03]">
              <span className="w-14 shrink-0 pr-4 text-right text-zinc-600 select-none">{index + 1}</span>
              <span className="pr-6 whitespace-pre">{line === '' ? ' ' : line}</span>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

function HeaderButton(props: { onClick: () => void; disabled: boolean; title: string; children: ReactNode }) {
  return (
    <button
      className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-xs font-medium text-zinc-300 transition hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-white/[0.03]"
      onClick={props.onClick}
      disabled={props.disabled}
      title={props.title}
    >
      {props.children}
    </button>
  );
}

function TabButton(props: { active: boolean; onClick: () => void; icon: string[]; children: string }) {
  const tone = props.active ? 'bg-zinc-700/80 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200';
  return (
    <button
      className={'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition ' + tone}
      onClick={props.onClick}
    >
      <Icon paths={props.icon} className="h-4 w-4" />
      {props.children}
    </button>
  );
}

function Kbd(props: { children: string }) {
  return (
    <kbd className="rounded border border-white/10 bg-white/5 px-1 py-px font-sans text-[10px] text-zinc-500">
      {props.children}
    </kbd>
  );
}

function Spinner(props: { light?: boolean }) {
  const tone = props.light ? 'border-white/40 border-t-white' : 'border-zinc-600 border-t-violet-400';
  return <span className={'inline-block h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 ' + tone} />;
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
      className="group relative w-px shrink-0 cursor-col-resize bg-white/5"
      onPointerDown={props.onPointerDown}
    >
      <span className="absolute inset-y-0 -left-1.5 -right-1.5 transition group-hover:bg-violet-500/30" />
    </div>
  );
}

const ICONS: Record<string, string[]> = {
  sparkle: ['M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z', 'M19 15l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z'],
  undo: ['M9 14 4 9l5-5', 'M4 9h10.5a5.5 5.5 0 0 1 0 11H11'],
  plus: ['M12 5v14', 'M5 12h14'],
  send: ['M12 19V5', 'M5 12l7-7 7 7'],
  eye: ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z', 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z'],
  code: ['m16 18 6-6-6-6', 'M8 6l-6 6 6 6'],
  check: ['M20 6 9 17l-5-5'],
  x: ['M18 6 6 18', 'M6 6l12 12'],
  alert: ['M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z', 'M12 9v4', 'M12 17h.01'],
  file: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6'],
  filePlus: ['M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z', 'M14 2v6h6', 'M12 18v-6', 'M9 15h6'],
  pencil: ['M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z'],
  trash: ['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6', 'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'],
  chevron: ['m9 18 6-6-6-6'],
  lock: ['M5 11h14v10H5z', 'M8 11V7a4 4 0 0 1 8 0v4'],
  wrench: [
    'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z',
  ],
};

function Icon(props: { paths: string[]; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={props.className}
      aria-hidden="true"
    >
      {props.paths.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
