import { SidebarSimple, SignOut } from '@phosphor-icons/react';
import './AppChrome.css';

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
        <span className="title-bar__thread" title={threadTitle}>{threadTitle}</span>
      </div>
      <div className="title-bar__actions">
        {providerNotice && <span className="title-bar__provider" title={providerNotice}>{providerNotice}</span>}
        <div className={`title-bar__status title-bar__status--${streamStatus}`} role="status">
          <span className="title-bar__status-dot" aria-hidden="true" />
          <span>{streamStatus}</span>
        </div>
        <span className="title-bar__email" title={userEmail}>{userEmail}</span>
        {showDashboardLink && (
          <button type="button" className="chrome-button title-bar__dashboard" onClick={dashboardActive ? onOpenChat : onOpenDashboard}>
            {dashboardActive ? 'Back to chat' : 'Dashboard'}
          </button>
        )}
        <button type="button" className="chrome-button title-bar__logout" onClick={onLogout}>
          <SignOut size={16} aria-hidden="true" />
          Sign out
        </button>
      </div>
    </header>
  );
}
