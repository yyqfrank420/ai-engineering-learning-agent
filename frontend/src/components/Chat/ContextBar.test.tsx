import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ContextBar } from './ContextBar';

it('names the action that clears selected-node context', () => {
  const onClear = vi.fn();
  render(<ContextBar selectedNode={{
    node: { id: 'retrieval', label: 'Retrieval API', type: 'service', technology: 'FastAPI',
      description: 'Finds evidence.', detail: null },
    suggestions: [],
  }} onSendMessage={vi.fn()} onClear={onClear} />);
  fireEvent.click(screen.getByRole('button', { name: 'Clear selected node' }));
  expect(onClear).toHaveBeenCalledOnce();
});
