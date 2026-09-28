import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { CSSProperties, Dispatch, SetStateAction } from 'react';
import type { BackendReadiness } from '../../hooks/useBackendReadiness';
import './ChatInput.css';
import type { DiagramIntentAction } from '../../types';

interface ChatInputProps {
  onSend:        (content: string, action?: DiagramIntentAction) => void | Promise<void>;
  checkSubmission?: (content: string) => Promise<DiagramIntentAction>;
  hasGraph?: boolean;
  onStop:        () => void;
  onRetryReadiness?:    () => void | Promise<void>;
  onDraftChange?: (hasText: boolean) => void;
  threadId?:     string | null;
  disabled?:     boolean;   // locks textarea (loading, no thread)
  sendDisabled?: boolean;   // blocks send while backend is not ready
  backendReadiness?: BackendReadiness;
  retryDisabled?: boolean;
  isGenerating?: boolean;   // LLM actively streaming; keep steering and Stop available
  readinessMessage?: string | null; // non-null while backend is warming up or failed
  selectionSuggestion?: string | null;
  selectionReferenceActive?: boolean;
  onUseSelection?: () => void;
  onDismissSelection?: () => void;
  onClearSelectionReference?: () => void;
}

function clearDraft(
  setValue: Dispatch<SetStateAction<string>>,
  textarea: HTMLTextAreaElement | null,
) {
  setValue('');
  if (textarea) {
    textarea.style.height = 'auto';
  }
}

export function ChatInput({
  onSend, checkSubmission, hasGraph = false, onStop, onRetryReadiness, onDraftChange, threadId, disabled, isGenerating,
  sendDisabled, backendReadiness = 'ready', retryDisabled, readinessMessage,
  selectionSuggestion, selectionReferenceActive, onUseSelection, onDismissSelection, onClearSelectionReference,
}: ChatInputProps) {
  const [value, setValue]         = useState('');
  const [checkingIntent, setCheckingIntent] = useState(false);
  const [needsGraphChoice, setNeedsGraphChoice] = useState(false);
  const submittingRef = useRef(false);
  const sendingRef = useRef(false);
  const startingChatRef = useRef(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const intentRequestRef = useRef(0);
  const [containerHovered, setContainerHovered] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previousThreadIdRef = useRef<string | null>(threadId ?? null);

  useEffect(() => () => { intentRequestRef.current += 1; }, []);

  useEffect(() => {
    if (sendingRef.current || (!disabled && !sendDisabled && backendReadiness === 'ready')) return;
    intentRequestRef.current += 1;
    setCheckingIntent(false);
  }, [disabled, sendDisabled, backendReadiness]);

  const resizeTextarea = useCallback((element: HTMLTextAreaElement) => {
    element.style.height = 'auto';
    // Empty placeholders can wrap, but only the draft should grow the composer.
    if (!element.value) return;
    const borderHeight = element.offsetHeight - element.clientHeight;
    element.style.height = `${Math.min(element.scrollHeight + borderHeight, 120)}px`;
  }, []);

  useLayoutEffect(() => {
    if (textareaRef.current) resizeTextarea(textareaRef.current);
  }, [resizeTextarea, value]);

  const seedSelection = useCallback(() => {
    if (!selectionSuggestion) return;
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
    onUseSelection?.();
  }, [onUseSelection, selectionSuggestion]);

  const submit = async (chosenAction?: DiagramIntentAction) => {
    const trimmed = value.trim();
    if (!trimmed || disabled || sendDisabled || backendReadiness !== 'ready' || submittingRef.current) return;
    submittingRef.current = true;
    setSubmissionError(null);
    const requestId = ++intentRequestRef.current;
    setCheckingIntent(true);
    try {
      const action = chosenAction ?? (checkSubmission && !isGenerating ? await checkSubmission(trimmed) : undefined);
      if (requestId !== intentRequestRef.current) return;
      if (action === 'ask' && hasGraph) {
        setNeedsGraphChoice(true);
        return;
      }
      sendingRef.current = true;
      startingChatRef.current = action === 'new_chat';
      const sent = action === undefined ? onSend(trimmed) : onSend(trimmed, action);
      if (sent) await sent;
      if (requestId !== intentRequestRef.current) return;
      setNeedsGraphChoice(false);
      clearDraft(setValue, textareaRef.current);
    } catch (error) {
      if (requestId === intentRequestRef.current) {
        setSubmissionError(error instanceof Error ? error.message : 'Could not send. Your message is saved here. Please try again.');
      }
    } finally {
      sendingRef.current = false;
      startingChatRef.current = false;
      submittingRef.current = false;
      if (requestId === intentRequestRef.current) setCheckingIntent(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  };

  const onInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    intentRequestRef.current += 1;
    setCheckingIntent(false);
    setSubmissionError(null);
    if (selectionSuggestion && !selectionReferenceActive && e.target.value.trim() !== '') {
      onUseSelection?.();
    }
    setNeedsGraphChoice(false);
    setValue(e.target.value);
  };

  useEffect(() => {
    onDraftChange?.(value.trim().length > 0);
  }, [onDraftChange, value]);

  useEffect(() => {
    const previousThreadId = previousThreadIdRef.current;
    const nextThreadId = threadId ?? null;

    // Preserve the draft for the initial bootstrap from "no thread yet" to the
    // first real thread after startup. Clear only on real thread switches.
    // Creating a chat can switch threads before its first send is accepted.
    // That send owns clearing the draft, so a failed handoff keeps it available.
    if (previousThreadId && previousThreadId !== nextThreadId && !startingChatRef.current) {
      intentRequestRef.current += 1;
      setCheckingIntent(false);
      setSubmissionError(null);
      setNeedsGraphChoice(false);
      clearDraft(setValue, textareaRef.current);
    }

    previousThreadIdRef.current = nextThreadId;
  }, [threadId]);

  const isReady = backendReadiness === 'ready' && !disabled && !sendDisabled && !checkingIntent && !!value.trim();
  const readinessNotice = readinessMessage ?? (backendReadiness === 'error'
    ? 'Could not connect. Please retry.'
    : backendReadiness !== 'ready' ? 'Connecting…' : null);
  const placeholder = isGenerating
    ? 'Add a follow-up…'
    : (selectionReferenceActive || !!selectionSuggestion)
    ? 'Ask a question about the highlighted text…'
    : 'Ask a question…';

  return (
    <div style={{
      padding:             '0.75rem 1rem',
      background:          'rgba(10,13,19,0.65)',
      backdropFilter:      'blur(40px) saturate(160%)',
      WebkitBackdropFilter:'blur(40px) saturate(160%)',
      borderTop:           '1px solid rgba(255,255,255,0.06)',
      boxShadow:           'inset 0 1px 0 rgba(255,255,255,0.04)',
      flexShrink:          0,
      position:            'relative',
    }}
    onMouseEnter={() => setContainerHovered(true)}
    onMouseLeave={() => setContainerHovered(false)}
    >
      {checkingIntent && <div role="status" style={prepareNoticeStyle}>Preparing your request…</div>}
      {submissionError && <div role="alert" style={prepareNoticeStyle}>{submissionError}</div>}
      {needsGraphChoice && (
        <div className="chat-graph-choice" role="group" aria-label="Where to continue">
          <p>Keep building on this diagram, or start a separate conversation?</p>
          <div>
            <button disabled={checkingIntent || disabled || sendDisabled} onClick={() => void submit('extend')}>Extend this diagram</button>
            <button disabled={checkingIntent || disabled || sendDisabled} onClick={() => void submit('new_chat')}>Start a new chat</button>
            <button disabled={checkingIntent} onClick={() => setNeedsGraphChoice(false)}>Dismiss</button>
          </div>
          <small>A new chat keeps this conversation and its diagram here.</small>
        </div>
      )}
      {selectionSuggestion && (
        <div
          style={selectionSuggestionStyle(containerHovered, !!selectionReferenceActive)}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.7rem' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '0.64rem', color: '#a78bfa', fontWeight: 700, letterSpacing: '0.05em' }}>
                {selectionReferenceActive ? 'REFERENCE ACTIVE' : 'HIGHLIGHTED TEXT'}
              </div>
              <div style={{
                fontSize: '0.7rem',
                color: '#c9d1d9',
                lineHeight: 1.45,
                marginTop: '0.18rem',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: '28rem',
              }}>
                {selectionSuggestion}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexShrink: 0 }}>
              <button
                onClick={seedSelection}
                style={selectionActionButtonStyle}
              >
                {selectionReferenceActive ? 'Referenced' : 'Use in chat'}
              </button>
              <button
                onClick={onDismissSelection}
                aria-label="Dismiss highlighted text"
                style={selectionDismissButtonStyle}
              >
                ×
              </button>
            </div>
          </div>
        </div>
      )}

      {readinessNotice && (
        <div
          role={backendReadiness === 'error' ? 'alert' : 'status'}
          aria-atomic="true"
          className={backendReadiness === 'error' ? undefined : 'chat-readiness-status'}
          style={backendReadiness === 'error' ? prepareNoticeStyle : undefined}
        >
          {(backendReadiness === 'unknown' || backendReadiness === 'preparing') && (
            <span className="chat-readiness-spinner" aria-hidden="true" />
          )}
          <span>{readinessNotice}</span>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'flex-end', gap: '0.5rem' }}>
        {/* Text input */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={onInput}
          onKeyDown={onKeyDown}
          onClick={() => {
            if (selectionReferenceActive && !value.trim()) {
              onClearSelectionReference?.();
            }
          }}
          onFocus={() => {
            if (selectionReferenceActive && !value.trim()) {
              onClearSelectionReference?.();
            }
          }}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          style={{ ...textareaStyle, ...(!value ? emptyTextareaStyle : {}) }}
          onFocusCapture={e => {
            setContainerHovered(true);
            e.currentTarget.style.borderColor = 'rgba(167,139,250,0.5)';
            e.currentTarget.style.boxShadow   = '0 0 0 3px rgba(167,139,250,0.12), inset 0 1px 0 rgba(255,255,255,0.06)';
          }}
          onBlur={e => {
            setContainerHovered(false);
            e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
            e.currentTarget.style.boxShadow   = 'inset 0 1px 0 rgba(255,255,255,0.04)';
          }}
        />

        {/* An active WebSocket can accept a steer without ending the run. */}
        {isGenerating ? (
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <button
              onClick={() => void submit()}
              disabled={!isReady}
              aria-label="Send message"
              style={sendButtonStyle(isReady, 'Send')}
            >
              <SendArrow />
            </button>
            <button
              onClick={onStop}
              aria-label="Stop generation"
              style={stopButtonStyle}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(248, 81, 73, 0.2)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'rgba(248, 81, 73, 0.1)'; }}
            >
              Stop
            </button>
          </div>
        ) : backendReadiness === 'error' ? (
          <button
            onClick={() => void onRetryReadiness?.()}
            disabled={retryDisabled}
            aria-label="Retry connection"
            style={sendButtonStyle(!retryDisabled, 'Retry')}
          >
            Retry
          </button>
        ) : (
          <button
            onClick={() => void submit()}
            disabled={!isReady}
            aria-label="Send message"
            style={sendButtonStyle(isReady, 'Send')}
          >
            <SendArrow />
          </button>
        )}
      </div>
    </div>
  );
}

function SendArrow() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
      <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const selectionSuggestionStyle = (hovered: boolean, active: boolean): CSSProperties => ({
  background: 'rgba(10,13,19,0.82)',
  border: active ? '1px solid rgba(167,139,250,0.35)' : '1px solid rgba(167,139,250,0.22)',
  borderRadius: '12px',
  padding: '0.65rem 0.8rem',
  backdropFilter: 'blur(18px)',
  WebkitBackdropFilter: 'blur(18px)',
  boxShadow: '0 12px 32px rgba(0,0,0,0.42)',
  opacity: hovered ? 1 : 0.66,
  transition: 'opacity 0.15s ease',
  marginBottom: '0.65rem',
});

const selectionActionButtonStyle: CSSProperties = {
  border: '1px solid rgba(167,139,250,0.3)',
  background: 'rgba(167,139,250,0.12)',
  color: '#d9c9ff',
  borderRadius: '999px',
  padding: '0.32rem 0.72rem',
  fontSize: '0.68rem',
  cursor: 'pointer',
};

const selectionDismissButtonStyle: CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#6e7681',
  fontSize: '1rem',
  lineHeight: 1,
  cursor: 'pointer',
  padding: '0.1rem',
};

const prepareNoticeStyle: CSSProperties = {
  marginBottom: '0.65rem',
  padding: '0.55rem 0.8rem',
  borderRadius: '10px',
  border: '1px solid rgba(96,165,250,0.18)',
  background: 'rgba(37,99,235,0.08)',
  color: '#c9d1d9',
  fontSize: '0.72rem',
  lineHeight: 1.45,
};

const textareaStyle: CSSProperties = {
  flex:                1,
  minWidth:            0,
  boxSizing:           'border-box',
  resize:              'none',
  background:          'rgba(255,255,255,0.04)',
  backdropFilter:      'blur(8px)',
  WebkitBackdropFilter:'blur(8px)',
  border:              '1px solid rgba(255,255,255,0.08)',
  borderRadius:        '10px',
  padding:             '0.5rem 0.75rem',
  color:               '#e6edf3',
  fontSize:            '0.875rem',
  lineHeight:          1.5,
  outline:             'none',
  fontFamily:          'inherit',
  minHeight:           '38px',
  maxHeight:           '120px',
  overflow:            'auto',
  transition:          'border-color 0.15s, box-shadow 0.15s',
  boxShadow:           'inset 0 1px 0 rgba(255,255,255,0.04)',
};

const emptyTextareaStyle: CSSProperties = {
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
};

const stopButtonStyle: CSSProperties = {
  padding:              '0.5rem 1rem',
  borderRadius:         '10px',
  background:           'rgba(248,81,73,0.08)',
  backdropFilter:       'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
  color:                '#f85149',
  border:               '1px solid rgba(248,81,73,0.25)',
  boxShadow:            'inset 0 1px 0 rgba(255,255,255,0.04)',
  cursor:               'pointer',
  fontSize:             '0.875rem',
  fontWeight:           500,
  whiteSpace:           'nowrap',
  minHeight:            '38px',
  transition:           'background 0.15s',
};

function sendButtonStyle(isReady: boolean, variant: 'Send' | 'Retry'): CSSProperties {
  const isRetry = variant === 'Retry';
  return {
    padding:              isRetry ? '0.5rem 1rem' : '0.5rem',
    width:                isRetry ? undefined : '38px',
    display:              'inline-flex',
    alignItems:           'center',
    justifyContent:       'center',
    flexShrink:           0,
    borderRadius:         '10px',
    background:           isReady
      ? isRetry
        ? 'linear-gradient(135deg, rgba(37,99,235,0.9), rgba(14,165,233,0.88))'
        : 'linear-gradient(135deg, rgba(124,58,237,0.9), rgba(59,130,246,0.9))'
      : 'rgba(255,255,255,0.04)',
    backdropFilter:       'blur(8px)',
    WebkitBackdropFilter: 'blur(8px)',
    boxShadow:            isReady
      ? isRetry
        ? 'inset 0 1px 0 rgba(255,255,255,0.2), 0 4px 12px rgba(37,99,235,0.25)'
        : 'inset 0 1px 0 rgba(255,255,255,0.2), 0 4px 12px rgba(124,58,237,0.25)'
      : 'inset 0 1px 0 rgba(255,255,255,0.04)',
    color:                isReady ? '#fff' : '#6e7681',
    border:               isReady
      ? isRetry
        ? '1px solid rgba(96,165,250,0.3)'
        : '1px solid rgba(167,139,250,0.3)'
      : '1px solid rgba(255,255,255,0.06)',
    cursor:               isReady ? 'pointer' : 'not-allowed',
    fontSize:             '0.875rem',
    fontWeight:           500,
    transition:           'opacity 0.15s, box-shadow 0.15s',
    whiteSpace:           'nowrap',
    minHeight:            '38px',
    opacity:              isReady ? 1 : 0.5,
  };
}
