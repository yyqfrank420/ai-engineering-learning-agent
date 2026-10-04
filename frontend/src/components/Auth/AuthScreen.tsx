import { useEffect, useId, useState } from 'react';
import { BookOpen, GoogleLogo } from '@phosphor-icons/react';
import './AuthScreen.css';
import { trackEvent } from '../../services/analytics';
import { requestOtp, signInWithGoogle, verifyOtp } from '../../services/auth';
import type { AuthSession } from '../../types';
import { TurnstileWidget } from './TurnstileWidget';

interface AuthScreenProps {
  onAuthenticated: (session: AuthSession) => void;
}

export function AuthScreen({ onAuthenticated }: AuthScreenProps) {
  const [email, setEmail]               = useState('');
  const [code, setCode]                 = useState('');
  const [step, setStep]                 = useState<'email' | 'verify'>('email');
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState<string | null>(null);
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const formId = useId();
  const errorId = `${formId}-error`;
  const canSubmit = !loading && !!email && (step === 'email' || code.length === 8) && (!captchaRequired || !!captchaToken);

  useEffect(() => {
    void trackEvent('auth_viewed');
  }, []);

  const submitEmail = async () => {
    setLoading(true);
    setError(null);
    void trackEvent('otp_requested', { value: captchaRequired ? 'captcha_required' : 'direct' });
    try {
      const result = await requestOtp(email, captchaToken ?? undefined);
      if (result.captcha_required) {
        setCaptchaRequired(true);
        setError('Please complete the CAPTCHA challenge.');
        return;
      }
      setStep('verify');
      setCaptchaRequired(false);
      setCaptchaToken(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send code');
    } finally {
      setLoading(false);
    }
  };

  const submitCode = async () => {
    setLoading(true);
    setError(null);
    try {
      const session = await verifyOtp(email, code, captchaToken ?? undefined);
      setCaptchaRequired(false);
      setCaptchaToken(null);
      void trackEvent('otp_verified', {}, session);
      onAuthenticated(session);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to verify code';
      setError(message);
      if (message.toLowerCase().includes('captcha')) {
        setCaptchaRequired(true);
      }
    } finally {
      setLoading(false);
    }
  };

  const submitGoogle = async () => {
    setLoading(true);
    setError(null);
    void trackEvent('google_signin_started');
    try {
      await signInWithGoogle();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start Google sign-in');
      setLoading(false);
    }
  };

  const submit = () => {
    if (canSubmit) void (step === 'email' ? submitEmail() : submitCode());
  };

  return (
    <main className="auth-screen">
      <section className="auth-card" aria-labelledby={`${formId}-heading`}>
        <div className="auth-brand">
          <div className="auth-brand-name">AI Engineering</div>
          <div className="auth-book-badge">
            <BookOpen size={16} aria-hidden="true" />
            <span>Chip Huyen · O'Reilly</span>
          </div>
        </div>

        <header className="auth-heading">
          <h1 id={`${formId}-heading`}>
            {step === 'email' ? 'Sign in' : 'Check your email'}
          </h1>
          <p>
            {step === 'email'
              ? 'Enter your email to receive a one-time code.'
              : `We sent an 8-digit code to ${email}`}
          </p>
        </header>

        {step === 'email' && (
          <>
            <button
              type="button"
              onClick={submitGoogle}
              disabled={loading}
              className="auth-button auth-button-google"
            >
              <GoogleLogo size={20} aria-hidden="true" />
              Continue with Google
            </button>
            <div className="auth-divider"><span>or email a code</span></div>
          </>
        )}

        <div className="auth-fields">
          <form
            id={formId}
            className="auth-form"
            onSubmit={event => { event.preventDefault(); submit(); }}
          >
            <div className="auth-field">
              <label htmlFor={`${formId}-email`}>Email address</label>
              <input
                id={`${formId}-email`}
                name="email"
                type="email"
                value={email}
                disabled={step === 'verify' || loading}
                onChange={event => setEmail(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="you@example.com"
                autoComplete="email"
                aria-describedby={error ? errorId : undefined}
                className="auth-input"
                required
              />
            </div>

            {step === 'verify' && (
              <div className="auth-field">
                <label htmlFor={`${formId}-code`}>Verification code</label>
                <input
                  id={`${formId}-code`}
                  name="code"
                  type="text"
                  value={code}
                  disabled={loading}
                  onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 8))}
                  onKeyDown={event => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                  placeholder="00000000"
                  autoComplete="one-time-code"
                  inputMode="numeric"
                  aria-describedby={error ? errorId : undefined}
                  className="auth-input auth-input-code"
                  required
                />
              </div>
            )}
          </form>

          {captchaRequired && (
            <div className="auth-captcha">
              <TurnstileWidget
                onVerify={token => { setCaptchaToken(token); setError(null); }}
                onExpire={() => setCaptchaToken(null)}
              />
            </div>
          )}

          {error && <div id={errorId} className="auth-error" role="alert">{error}</div>}

          <button
            type="submit"
            form={formId}
            disabled={!canSubmit}
            className="auth-button auth-button-primary"
            aria-busy={loading}
          >
            {loading ? 'Working…' : step === 'email' ? 'Send code' : 'Verify code'}
          </button>

          {step === 'verify' && (
            <button
              type="button"
              onClick={() => { setStep('email'); setCode(''); setCaptchaRequired(false); setCaptchaToken(null); setError(null); }}
              disabled={loading}
              className="auth-button auth-button-ghost"
            >
              Use a different email
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
