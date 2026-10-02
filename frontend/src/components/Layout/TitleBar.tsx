import './TitleBar.css';

interface TitleBarProps {
  streamStatus: 'generating' | 'connected' | 'disconnected';
  providerNotice: string | null;
  userEmail: string;
  threadTitle: string;
  sidebarOpen: boolean;
  showDashboardLink?: boolean;
  dashboardActive?: boolean;
  onToggleSidebar: () => void;
  onOpenDashboard?: () => void;
  onOpenChat?: () => void;
  onLogout: () => void;
}

const STATUS_COLORS = { connected: '#3fb950', generating: '#a78bfa', disconnected: '#f85149' };

export function TitleBar({ streamStatus, providerNotice, userEmail, threadTitle, sidebarOpen,
  showDashboardLink = false, dashboardActive = false, onToggleSidebar, onOpenDashboard, onOpenChat, onLogout }: TitleBarProps) {
  const dashboardLabel = dashboardActive ? 'Back to chat' : 'Dashboard';
  const openDashboard = dashboardActive ? onOpenChat : onOpenDashboard;
  return <header className="title-bar">
    <div className="title-bar__identity">
      <button className="title-bar__history" type="button" onClick={onToggleSidebar} aria-controls="chat-history" aria-expanded={sidebarOpen}
        aria-label={sidebarOpen ? 'Hide chat history' : 'Show chat history'} title={sidebarOpen ? 'Hide chat history' : 'Show chat history'}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"><path d="M4 5h16v14H4zM9 5v14M12 9h5M12 13h5" /></svg>
      </button>
      <span className="title-bar__product">AI Engineering</span>
      <span className="title-bar__book">Chip Huyen · O'Reilly</span>
      <span className="title-bar__thread" title={threadTitle}>{threadTitle}</span>
    </div>
    <div className="title-bar__actions">
      <div className="title-bar__status" role="status" aria-label={`Connection status: ${streamStatus}`}>
        <span className="title-bar__status-dot" style={{ background: STATUS_COLORS[streamStatus] }} aria-hidden="true" />
        <span className="title-bar__status-text">{streamStatus}</span>
      </div>
      {providerNotice && <span className="title-bar__provider" title={providerNotice}>{providerNotice}</span>}
      <span className="title-bar__email" title={userEmail}>{userEmail}</span>
      {showDashboardLink && <button type="button" className="title-bar__dashboard title-bar__desktop-action" onClick={openDashboard}>{dashboardLabel}</button>}
      <button type="button" className="title-bar__logout title-bar__desktop-action" onClick={onLogout}>Sign out</button>
      <details className="title-bar__account" onKeyDown={event => {
        if (event.key === 'Escape') {
          event.currentTarget.removeAttribute('open');
          event.currentTarget.querySelector('summary')?.focus();
        }
      }}>
        <summary aria-label="Account and navigation" title="Account and navigation">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="8" r="3" /><path d="M5 20v-2a7 7 0 0 1 14 0v2" /></svg>
        </summary>
        <div className="title-bar__account-menu">
          <span className="title-bar__account-email">{userEmail}</span>
          {providerNotice && <span className="title-bar__account-provider">{providerNotice}</span>}
          {showDashboardLink && <button type="button" onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); openDashboard?.(); }}>{dashboardLabel}</button>}
          <button type="button" onClick={onLogout}>Sign out</button>
        </div>
      </details>
    </div>
  </header>;
}
