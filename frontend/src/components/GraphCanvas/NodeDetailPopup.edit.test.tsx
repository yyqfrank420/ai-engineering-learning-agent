import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { GraphEdge, GraphNode } from '../../types';
import { NodeDetailPopup } from './NodeDetailPopup';

const node: GraphNode = {
  id: 'service',
  label: 'Retrieval API',
  type: 'service',
  technology: 'FastAPI',
  description: 'Retrieves grounded evidence.',
  detail: 'Evidence from the book.',
  book_refs: ['Chapter 6'],
};

const edges: GraphEdge[] = [
  { source: 'other', target: 'store', label: 'unrelated', technology: '', sync: 'sync', description: 'Unrelated.' },
  { source: 'service', target: 'store', label: 'queries index', technology: 'HTTPS', sync: 'sync', description: 'Queries the index.' },
  { source: 'service', target: 'store', label: 'sends metrics', technology: 'OTLP', sync: 'async', description: 'Sends metrics.' },
];

const props = {
  node,
  edges,
  onClose: vi.fn(),
  onTellMeMore: vi.fn(),
  onExpandGraph: vi.fn(),
};

describe('NodeDetailPopup editing', () => {
  it('saves only changed node fields and keeps source detail read-only', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onDirtyChange = vi.fn();
    render(<NodeDetailPopup {...props} onSave={onSave} onDirtyChange={onDirtyChange} />);

    fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
    expect(screen.getByRole('textbox', { name: 'Name' })).toBe(document.activeElement);
    expect(screen.getByRole('option', { name: 'Application service' })).toHaveProperty('value', 'service');
    expect(screen.getByRole('option', { name: 'Data store' })).toHaveProperty('value', 'datastore');
    expect(screen.getByRole('option', { name: 'External system' })).toHaveProperty('value', 'external');
    expect(screen.getByText('Evidence from the book.')).toBeTruthy();
    expect(screen.getByText('Chapter 6')).toBeTruthy();
    expect(screen.queryByRole('textbox', { name: 'Book refs' })).toBeNull();

    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Search API' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Type' }), { target: { value: 'gateway' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Technology' }), { target: { value: '' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Description' }), { target: { value: 'Searches the index.' } });
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
    expect(screen.getByRole('button', { name: 'Tell me more' })).toHaveProperty('disabled', true);

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({
      nodes: [{ id: 'service', label: 'Search API', type: 'gateway', technology: '', description: 'Searches the index.' }],
    }));
    expect(screen.getByRole('status').textContent).toBe('Changes saved');
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it('edits the selected directed edge by its original graph index', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailPopup {...props} onSave={onSave} autoFocusEdgeIndex={2} />);

    expect(screen.getByRole('textbox', { name: 'Label' })).toBe(document.activeElement);
    expect(screen.getByRole('option', { name: 'Control flow' })).toHaveProperty('value', 'control');
    fireEvent.change(screen.getByRole('textbox', { name: 'Label' }), { target: { value: 'publishes metrics' } });
    const connection = screen.getByRole('region', { name: 'Connections' });
    fireEvent.change(within(connection).getByRole('textbox', { name: 'Technology' }), { target: { value: 'gRPC' } });
    fireEvent.change(within(connection).getByRole('textbox', { name: 'Description' }), { target: { value: 'Publishes bounded metrics.' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Flow' }), { target: { value: 'control' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Timing' }), { target: { value: 'sync' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({
      edges: [{ index: 2, label: 'publishes metrics', technology: 'gRPC', description: 'Publishes bounded metrics.', flow: 'control', sync: 'sync' }],
    }));
  });

  it('retains a failed draft, offers retry, and guards close until discard is chosen', async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error('Version changed')).mockResolvedValueOnce(undefined);
    const onClose = vi.fn();
    render(<NodeDetailPopup {...props} onSave={onSave} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'New name' } });

    fireEvent.click(screen.getByRole('button', { name: 'Close node detail' }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText('Discard unsaved changes?')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Version changed'));
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Name' }).value).toBe('New name');
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('status').textContent).toBe('Changes saved');
  });

  it('cancels a draft and opens the name editor on a rising focus request', () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onDirtyChange = vi.fn();
    const view = render(<NodeDetailPopup {...props} onSave={onSave} onDirtyChange={onDirtyChange} />);
    view.rerender(<NodeDetailPopup {...props} onSave={onSave} onDirtyChange={onDirtyChange} autoFocusName />);
    expect(screen.getByRole('textbox', { name: 'Name' })).toBe(document.activeElement);
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Draft name' } });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText('Retrieval API')).toBeTruthy();
    expect(screen.queryByRole('textbox', { name: 'Name' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Edit details' })).toBe(document.activeElement);
    expect(onSave).not.toHaveBeenCalled();
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
  });

  it('reopens the same node editor after Done and after Save when the request token advances', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const view = render(<NodeDetailPopup {...props} onSave={onSave} autoFocusName editRequestId={1} />);

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByRole('textbox', { name: 'Name' })).toBeNull();
    view.rerender(<NodeDetailPopup {...props} onSave={onSave} autoFocusName editRequestId={2} />);
    expect(screen.getByRole('textbox', { name: 'Name' })).toBe(document.activeElement);

    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Updated API' } });
    view.rerender(<NodeDetailPopup {...props} onSave={onSave} autoFocusName editRequestId={3} />);
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Name' }).value).toBe('Updated API');
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Changes saved'));
    view.rerender(<NodeDetailPopup {...props} onSave={onSave} autoFocusName editRequestId={4} />);
    expect(screen.getByRole('textbox', { name: 'Name' })).toBe(document.activeElement);
  });

  it('reopens the same connection editor after Done when the request token advances', () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const view = render(<NodeDetailPopup {...props} onSave={onSave} autoFocusEdgeIndex={2} editRequestId={1} />);

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByRole('textbox', { name: 'Label' })).toBeNull();
    view.rerender(<NodeDetailPopup {...props} onSave={onSave} autoFocusEdgeIndex={2} editRequestId={2} />);
    expect(screen.getByRole('textbox', { name: 'Label' })).toBe(document.activeElement);
  });

  it('expands and focuses a collapsed connection with an invalid label', () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailPopup {...props} onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
    const connectionToggle = screen.getByRole('button', { name: 'Outgoing connection: queries index' });
    fireEvent.click(connectionToggle);
    fireEvent.change(screen.getByRole('textbox', { name: 'Label' }), { target: { value: '   ' } });
    fireEvent.click(connectionToggle);

    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(screen.getByRole('alert').textContent).toBe('Connection label is required.');
    expect(screen.getByRole('textbox', { name: 'Label' })).toBe(document.activeElement);
    expect(onSave).not.toHaveBeenCalled();
  });

  it('retains a dirty draft when the selected node prop changes', () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const view = render(<NodeDetailPopup {...props} onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Unsent draft' } });

    view.rerender(<NodeDetailPopup {...props} node={{ ...node, id: 'other', label: 'Other node' }} onSave={onSave} />);
    expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Name' }).value).toBe('Unsent draft');
    expect(screen.getByRole('heading', { name: 'Retrieval API' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(onSave).toHaveBeenCalledWith({ nodes: [{ id: 'service', label: 'Unsent draft' }] });
  });

  it('refreshes a pristine editor when graph content with the same node ID changes', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const view = render(<NodeDetailPopup {...props} onSave={onSave} autoFocusName />);
    view.rerender(<NodeDetailPopup {...props} node={{ ...node, label: 'Updated API' }}
      edges={[edges[0], { ...edges[1], label: 'new query' }, edges[2]]} onSave={onSave} autoFocusName />);

    await waitFor(() => expect(screen.getByRole<HTMLInputElement>('textbox', { name: 'Name' }).value).toBe('Updated API'));
    expect(screen.getByRole('button', { name: 'Outgoing connection: new query' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Save changes' })).toBeNull();
  });

  it('disables closing during a pending save', async () => {
    let finishSave: (() => void) | undefined;
    const onSave = vi.fn(() => new Promise<void>(resolve => { finishSave = resolve; }));
    const onClose = vi.fn();
    render(<NodeDetailPopup {...props} onSave={onSave} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Search API' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(screen.getByRole('button', { name: 'Close node detail' })).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Saving…' })).toHaveProperty('disabled', true);
    fireEvent.click(screen.getByRole('button', { name: 'Close node detail' }));
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => { finishSave?.(); });
    expect(screen.getByRole('status').textContent).toBe('Changes saved');
  });
});
