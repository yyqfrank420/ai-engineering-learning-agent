import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, Dispatch, SetStateAction } from 'react';
import type { BackendPrepareProgress } from '../../hooks/useBackendReadiness';

interface ChatInputProps {
  onSend:        (content: string, diagramRequested?: boolean) => void;
  checkSubmission?: (content: string) => Promise<'send' | 'answer' | 'ask'>;
  onStop:        () => void;
  onPrepare?:    () => void | Promise<void>;
  onDraftChange?: (hasText: boolean) => void;
  threadId?:     string | null;
  disabled?:     boolean;   // locks textarea (loading, no thread)
  sendDisabled?: boolean;   // blocks send while backend is not ready
  showPrepare?:  boolean;
  prepareDisabled?: boolean;
  isGenerating?: boolean;   // LLM actively streaming; keep steering and Stop available
  prepareMessage?: string | null; // non-null while backend is warming up or failed
  prepareProgress?: BackendPrepareProgress | null;
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
  onSend, checkSubmission, onStop, onPrepare, onDraftChange, threadId, disabled, isGenerating,
  sendDisabled, showPrepare, prepareDisabled, prepareMessage,
  prepareProgress,
  selectionSuggestion, selectionReferenceActive, onUseSelection, onDismissSelection, onClearSelectionReference,
}: ChatInputProps) {
  const [value, setValue]         = useState('');
  const [checkingIntent, setCheckingIntent] = useState(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const intentRequestRef = useRef(0);
  const [containerHovered, setContainerHovered] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previousThreadIdRef = useRef<string | null>(threadId ?? null);

  useEffect(() => () => { intentRequestRef.current += 1; }, []);

  useEffect(() => {
    if (!disabled && !sendDisabled) return;
    intentRequestRef.current += 1;
    setCheckingIntent(false);
  }, [disabled, sendDisabled]);

  const resizeTextarea = useCallback((element: HTMLTextAreaElement) => {
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, 120)}px`;
  }, []);

  const seedSelection = useCallback(() => {
    if (!selectionSuggestion) return;
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
    onUseSelection?.();
  }, [onUseSelection, selectionSuggestion]);

  const submit = async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || sendDisabled || checkingIntent) return;
    setSubmissionError(null);
    if (!checkSubmission || isGenerating) {
      clearDraft(setValue, textareaRef.current);
      onSend(trimmed);
      return;
    }
    const requestId = ++intentRequestRef.current;
    setCheckingIntent(true);
    try {
      const action = await checkSubmission(trimmed);
      if (requestId !== intentRequestRef.current) return;
      clearDraft(setValue, textareaRef.current);
      onSend(trimmed, action === 'ask');
    } catch {
      if (requestId === intentRequestRef.current) {
        setSubmissionError('Could not connect. Your message is saved here. Please try again.');
      }
    } finally {
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
    setValue(e.target.value);
    resizeTextarea(e.target);
  };

  useEffect(() => {
    onDraftChange?.(value.trim().length > 0);
  }, [onDraftChange, value]);

  useEffect(() => {
    const previousThreadId = previousThreadIdRef.current;
    const nextThreadId = threadId ?? null;

    // Preserve the draft for the initial bootstrap from "no thread yet" to the
    // first real thread after Prepare. Clear only on real thread switches.
    if (previousThreadId && previousThreadId !== nextThreadId) {
      intentRequestRef.current += 1;
      setCheckingIntent(false);
      setSubmissionError(null);
      clearDraft(setValue, textareaRef.current);
    }

    previousThreadIdRef.current = nextThreadId;
  }, [threadId]);

  const isReady = !disabled && !sendDisabled && !checkingIntent && !!value.trim();
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
      {checkingIntent && <div role="status" style={prepareNoticeStyle}>Checking your request…</div>}
      {submissionError && <div role="alert" style={prepareNoticeStyle}>{submissionError}</div>}
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

      {prepareMessage && (
        <div style={prepareNoticeStyle}>
          <div style={prepareNoticeHeaderStyle}>
            <span>{prepareMessage}</span>
            {prepareProgress && <span>{prepareProgress.percent}%</span>}
          </div>
          {prepareProgress && (
            <div
              role="progressbar"
              aria-label="Backend preparation progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={prepareProgress.percent}
              style={prepareProgressTrackStyle}
            >
              <div style={prepareProgressFillStyle(prepareProgress.percent)} />
            </div>
          )}
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
          style={textareaStyle}
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
              onClick={submit}
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
        ) : showPrepare ? (
          <button
            onClick={() => void onPrepare?.()}
            disabled={prepareDisabled}
            aria-label="Prepare backend"
            style={sendButtonStyle(!prepareDisabled, 'Prepare')}
          >
            {prepareMessage && !prepareMessage.toLowerCase().includes('unavailable')
              ? 'Preparing…'
              : 'Prepare'}
          </button>
        ) : (
          <button
            onClick={submit}
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

const prepareNoticeHeaderStyle: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: '0.75rem',
};

const prepareProgressTrackStyle: CSSProperties = {
  height: '4px',
  marginTop: '0.5rem',
  overflow: 'hidden',
  borderRadius: '999px',
  background: 'rgba(96,165,250,0.14)',
};

const prepareProgressFillStyle = (percent: number): CSSProperties => ({
  width: `${percent}%`,
  height: '100%',
  borderRadius: 'inherit',
  background: 'linear-gradient(90deg, #3b82f6, #a78bfa)',
  transition: 'width 220ms ease',
});

const textareaStyle: CSSProperties = {
  flex:                1,
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

function sendButtonStyle(isReady: boolean, variant: 'Send' | 'Prepare'): CSSProperties {
  const isPrepare = variant === 'Prepare';
  return {
    padding:              isPrepare ? '0.5rem 1rem' : '0.5rem',
    width:                isPrepare ? undefined : '38px',
    display:              'inline-flex',
    alignItems:           'center',
    justifyContent:       'center',
    flexShrink:           0,
    borderRadius:         '10px',
    background:           isReady
      ? isPrepare
        ? 'linear-gradient(135deg, rgba(37,99,235,0.9), rgba(14,165,233,0.88))'
        : 'linear-gradient(135deg, rgba(124,58,237,0.9), rgba(59,130,246,0.9))'
      : 'rgba(255,255,255,0.04)',
    backdropFilter:       'blur(8px)',
    WebkitBackdropFilter: 'blur(8px)',
    boxShadow:            isReady
      ? isPrepare
        ? 'inset 0 1px 0 rgba(255,255,255,0.2), 0 4px 12px rgba(37,99,235,0.25)'
        : 'inset 0 1px 0 rgba(255,255,255,0.2), 0 4px 12px rgba(124,58,237,0.25)'
      : 'inset 0 1px 0 rgba(255,255,255,0.04)',
    color:                isReady ? '#fff' : '#6e7681',
    border:               isReady
      ? isPrepare
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
