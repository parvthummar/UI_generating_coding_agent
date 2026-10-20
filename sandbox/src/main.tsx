import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

const HOST_ORIGIN = 'http://localhost:5173';

let lastReported = '';

function errorText(value: unknown) {
  if (value == null || value === '') return 'Unknown runtime error';
  if (typeof value === 'string') return value;
  if (value instanceof Error) return value.message || 'Unknown runtime error';
  if (typeof value === 'object' && 'message' in value) return String((value as { message: unknown }).message);
  return String(value);
}

function report(message: string, stack?: string) {
  const text = message + '\n' + (stack || '');
  if (text === lastReported) return;
  lastReported = text;
  window.parent.postMessage({ type: 'SANDBOX_RUNTIME_ERROR', message, stack }, HOST_ORIGIN);
}

window.addEventListener('error', (event) => {
  const stack = event.error && event.error.stack ? event.error.stack : undefined;
  report(errorText(event.error || event.message), stack);
});

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason;
  const stack = reason && reason.stack ? reason.stack : undefined;
  report(errorText(reason), stack);
});

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error: error };
  }

  componentDidCatch(error: Error) {
    report(error.message, error.stack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="p-6 text-red-700">
          <p>This preview crashed: {this.state.error.message}</p>
          {this.state.error.stack && (
            <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap text-xs">{this.state.error.stack}</pre>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}

function Root() {
  const [boundaryKey, setBoundaryKey] = React.useState(0);

  React.useEffect(() => {
    if (!import.meta.hot) return;
    const onUpdate = () => {
      lastReported = '';
      setBoundaryKey((key) => key + 1);
    };
    import.meta.hot.on('vite:afterUpdate', onUpdate);
  }, []);

  return (
    <ErrorBoundary key={boundaryKey}>
      <App />
    </ErrorBoundary>
  );
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(<Root />);
