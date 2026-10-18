import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

const HOST_ORIGIN = 'http://localhost:5173';

function report(message: string, stack?: string) {
  window.parent.postMessage({ type: 'SANDBOX_RUNTIME_ERROR', message, stack }, HOST_ORIGIN);
}

window.addEventListener('error', (e) => report(e.message, e.error ? e.error.stack : undefined));
window.addEventListener('unhandledrejection', (e) => report(String(e.reason)));

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
      return <div className='p-6 text-red-700'>This preview crashed: {this.state.error.message}</div>;
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
