import { SidebarSimple, SignOut, User } from '@phosphor-icons/react';
import './AppChrome.css';
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

export function TitleBar({
  streamStatus,
  providerNotice,
  userEmail,
  threadTitle,
  sidebarOpen,
  showDashboardLink = false,
  dashboardActive = false,
  onToggleSidebar,
  onOpenDashboard,
  onOpenChat,
  onLogout,
}: TitleBarProps) {
  return (
    <header className="title-bar">
      <div className="title-bar__identity">
        <button
          type="button"
          className="chrome-button title-bar__toggle"
          onClick={onToggleSidebar}
          aria-label={sidebarOpen ? 'Hide chat history' : 'Show chat history'}
          aria-expanded={sidebarOpen}
          aria-controls="chat-history"
          title={sidebarOpen ? 'Hide chat history' : 'Show chat history'}
        >
          <SidebarSimple size={19} weight={sidebarOpen ? 'fill' : 'regular'} aria-hidden="true" />
        </button>
        <span className="title-bar__product">AI Engineering</span>
        <span className="title-bar__book">Chip Huyen · O'Reilly</span>
        {threadTitle !== 'New chat' && (
          <span className="title-bar__thread" title={threadTitle}>{threadTitle}</span>
        )}
      </div>
      <div className="title-bar__actions">
        {providerNotice && <span className="title-bar__provider" title={providerNotice}>{providerNotice}</span>}
        <div className={`title-bar__status title-bar__status--${streamStatus}`} role="status" aria-label={`Connection status: ${streamStatus}`}>
          <span className="title-bar__status-dot" aria-hidden="true" />
          <span className="title-bar__status-text">{streamStatus}</span>
        </div>
        <span className="title-bar__email" title={userEmail}>{userEmail}</span>
        {showDashboardLink && (
          <button type="button" className="chrome-button title-bar__dashboard title-bar__desktop-action" onClick={dashboardActive ? onOpenChat : onOpenDashboard}>
            {dashboardActive ? 'Back to chat' : 'Dashboard'}
          </button>
        )}
        <button type="button" className="chrome-button title-bar__logout title-bar__desktop-action" onClick={onLogout}>
          <SignOut size={16} aria-hidden="true" />
          Sign out
        </button>
        <details className="title-bar__account" onKeyDown={event => {
          if (event.key === 'Escape') {
            event.currentTarget.removeAttribute('open');
            event.currentTarget.querySelector('summary')?.focus();
          }
        }}>
          <summary className="chrome-button" aria-label="Account and navigation" title="Account and navigation">
            <User size={20} aria-hidden="true" />
          </summary>
          <div className="title-bar__account-menu">
            <span className="title-bar__account-email">{userEmail}</span>
            {providerNotice && <span className="title-bar__account-provider">{providerNotice}</span>}
            {showDashboardLink && <button className="chrome-button" type="button" onClick={event => {
              event.currentTarget.closest('details')?.removeAttribute('open');
              (dashboardActive ? onOpenChat : onOpenDashboard)?.();
            }}>{dashboardActive ? 'Back to chat' : 'Dashboard'}</button>}
            <button className="chrome-button" type="button" onClick={onLogout}>Sign out</button>
          </div>
        </details>
      </div>
    </header>
  );
}
