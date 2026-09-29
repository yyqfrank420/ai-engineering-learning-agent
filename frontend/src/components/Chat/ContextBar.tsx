import { Crosshair, X } from '@phosphor-icons/react';
import type { SelectedNode } from '../../types';
import './ContextBar.css';

interface ContextBarProps {
  selectedNode: SelectedNode | null;
  onSendMessage: (content: string) => void;
  onClear: () => void;
}

export function ContextBar({ selectedNode, onSendMessage, onClear }: ContextBarProps) {
  if (!selectedNode) return null;

  return (
    <div className="context-bar">
      <div className="context-bar__selection">
        <span className="context-bar__node">
          <Crosshair size={16} aria-hidden="true" />
          <span>{selectedNode.node.label}</span>
        </span>
        <button
          className="context-bar__dismiss"
          type="button"
          onClick={onClear}
          aria-label="Clear selected node"
          title="Clear selected node"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      {selectedNode.suggestions.length > 0 && (
        <div className="context-bar__suggestions">
          {selectedNode.suggestions.map((question, index) => (
            <button
              className="context-bar__suggestion"
              key={index}
              type="button"
              data-testid="suggested-question"
              onClick={() => onSendMessage(question)}
            >
              {question}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
