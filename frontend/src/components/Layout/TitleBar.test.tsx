import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { TitleBar } from './TitleBar';

describe('TitleBar compact navigation', () => {
  it('retains account and dashboard actions in the compact disclosure', () => {
    const onOpenDashboard = vi.fn();
    const onLogout = vi.fn();
    render(<TitleBar streamStatus="connected" providerNotice="Provider fallback" userEmail="reader@example.com"
      threadTitle="Current conversation" sidebarOpen={false} showDashboardLink onToggleSidebar={vi.fn()}
      onOpenDashboard={onOpenDashboard} onLogout={onLogout} />);
    const summary = screen.getByLabelText('Account and navigation');
    const details = summary.closest('details')!;
    fireEvent.click(summary);
    expect(details.open).toBe(true);
    const dashboard = details.querySelector('button')!;
    fireEvent.click(dashboard);
    expect(onOpenDashboard).toHaveBeenCalledTimes(1);
    expect(details.open).toBe(false);
    fireEvent.click(summary);
    fireEvent.click(details.querySelectorAll('button')[1]);
    expect(onLogout).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(summary, { key: 'Escape' });
    expect(details.open).toBe(false);
    expect(document.activeElement).toBe(summary);
    expect(screen.getByRole('status').getAttribute('aria-label')).toBe('Connection status: connected');
    expect(screen.getByRole('button', { name: 'Show chat history' }).getAttribute('aria-controls')).toBe('chat-history');
  });
});
