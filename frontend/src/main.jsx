import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    window.__NAS_BOOT__?.reportError?.('react-boundary', {
      message: error?.message || String(error),
      stack: error?.stack || '',
      componentStack: info?.componentStack || '',
    });
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          background: '#06070b',
          color: '#f8fafc',
          padding: '32px',
        }}
        >
          <div style={{
            width: 'min(720px, 100%)',
            borderRadius: '24px',
            border: '1px solid rgba(255,255,255,0.08)',
            background: 'rgba(255,255,255,0.04)',
            padding: '28px',
            boxShadow: '0 24px 60px rgba(0,0,0,0.45)',
          }}
          >
            <div style={{ fontSize: '12px', letterSpacing: '0.24em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.42)', marginBottom: '12px' }}>
              NAS Diagnostics
            </div>
            <h1 style={{ margin: '0 0 12px', fontSize: '28px', fontWeight: 800 }}>前端启动失败</h1>
            <p style={{ margin: '0 0 16px', color: 'rgba(255,255,255,0.68)', lineHeight: 1.7 }}>
              应用已经捕获到一个运行时错误，并已写入本地诊断日志。您可以把当前界面截图给我，我会继续定点修复。
            </p>
            <div style={{
              borderRadius: '18px',
              background: 'rgba(0,0,0,0.35)',
              border: '1px solid rgba(255,255,255,0.08)',
              padding: '16px',
              fontFamily: 'JetBrains Mono, Consolas, monospace',
              fontSize: '13px',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              color: '#fca5a5',
            }}
            >
              {this.state.error?.stack || this.state.error?.message || String(this.state.error)}
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </React.StrictMode>,
);
