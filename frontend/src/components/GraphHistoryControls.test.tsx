import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GraphHistoryControls } from './GraphHistoryControls';
const history = { current_revision_id: 'r2', revisions: ['r1', 'r2'].map((id, i) => ({ id, parent_revision_id: i ? 'r1' : null, revision_number: i + 1, label: `Version ${i + 1}`, created_at: '', node_count: 1, edge_count: 0 })) };
const props = () => ({ history, previewId: null, undoId: 'r1', redoId: null, disabled: false, busy: false, error: null, onUndo: vi.fn(), onRedo: vi.fn(), onPreview: vi.fn(), onRestore: vi.fn(), onReturn: vi.fn(), onReload: vi.fn() });
describe('GraphHistoryControls', () => {
  it('omits history until there is a revision to revisit', () => {
    const handlers = props();
    const firstHistory = { current_revision_id: 'r1', revisions: [history.revisions[0]] };
    const view = render(<GraphHistoryControls {...handlers} history={firstHistory} undoId={null} />);
    expect(view.container.childElementCount).toBe(0);
    view.rerender(<GraphHistoryControls {...handlers} history={null} undoId={null} />);
    expect(view.container.childElementCount).toBe(0);
    view.rerender(<GraphHistoryControls {...handlers} />);
    expect(screen.getByRole('group', { name: 'Diagram history' })).toBeTruthy();
  });
  it.each([
    { busy: true },
    { error: 'History unavailable' },
    { previewId: 'r1' },
    { undoId: 'r1' },
    { redoId: 'r1' },
  ])('retains first-version history for an active action or recoverable state: %j', state => {
    render(<GraphHistoryControls {...props()} history={{ current_revision_id: 'r1', revisions: [history.revisions[0]] }} undoId={null} {...state} />);
    expect(screen.getByRole('group', { name: 'Diagram history' })).toBeTruthy();
  });
  it('restores immediately on Undo while picker only previews', () => {
    const handlers = props();render(<GraphHistoryControls {...handlers} />);
    expect(screen.getByRole('option', { name: 'Version 1' })).toBeTruthy();
    expect(screen.getByRole('option', { name: 'Version 2 (current)' })).toBeTruthy();
    expect(screen.queryByText(/Saved positions/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Undo diagram change' }));
    expect(handlers.onUndo).toHaveBeenCalledOnce();
    fireEvent.change(screen.getByRole('combobox'), {target:{value:'r1'}});
    expect(handlers.onPreview).toHaveBeenCalledWith('r1');
    expect(handlers.onRestore).not.toHaveBeenCalled();
  });
  it('makes preview restore explicit and freezes actions while busy', () => {
    const handlers = props();const view=render(<GraphHistoryControls {...handlers} previewId="r1" />);
    expect(screen.getByText('Preview')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name:'Restore'}));
    expect(handlers.onRestore).toHaveBeenCalledWith('r1');
    fireEvent.click(screen.getByRole('button', {name:'Return to current'}));expect(handlers.onReturn).toHaveBeenCalledOnce();
    view.rerender(<GraphHistoryControls {...handlers} previewId="r1" busy />);
    expect((screen.getByRole('button', {name:'Restore'}) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('combobox') as HTMLSelectElement).disabled).toBe(true);
  });
});
