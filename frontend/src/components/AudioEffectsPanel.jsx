import React, { useEffect, useId, useRef } from 'react';
import { AudioLines, Check, CircleOff, SlidersHorizontal, X } from 'lucide-react';
import { AUDIO_EFFECTS } from '../audio/effects';
import './AudioEffectsPanel.css';

export default function AudioEffectsPanel({ value = 'off', onChange, onClose, status }) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const current = AUDIO_EFFECTS.find((item) => item.id === value) || AUDIO_EFFECTS[0];
  useEffect(() => {
    const previousFocus = document.activeElement;
    const panel = panelRef.current;
    panel?.querySelector('[aria-checked="true"]')?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current?.(); }
      if (event.key !== 'Tab') return;
      const buttons = [...panel.querySelectorAll('button:not(:disabled)')];
      if (!buttons.length) return;
      const first = buttons[0];
      const last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => { document.removeEventListener('keydown', onKeyDown); previousFocus?.focus?.(); };
  }, []);

  const moveChoice = (event, index) => {
    const step = ({ ArrowRight: 1, ArrowDown: 2, ArrowLeft: -1, ArrowUp: -2 })[event.key];
    if (step === undefined && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    let nextIndex = (index + (step || 0) + AUDIO_EFFECTS.length) % AUDIO_EFFECTS.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = AUDIO_EFFECTS.length - 1;
    const selected = AUDIO_EFFECTS[nextIndex];
    panelRef.current.querySelector(`[data-effect="${selected.id}"]`)?.focus();
    onChange?.(selected.id);
  };

  return (
    <div className="nas-effects-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <section ref={panelRef} className="nas-effects-panel" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}>
        <header className="nas-effects-header">
          <div><SlidersHorizontal size={18} /><h2 id={titleId}>音效</h2></div>
          <button type="button" className="nas-effects-close" onClick={onClose} aria-label="关闭音效面板"><X size={20} /></button>
        </header>
        <div className="nas-effects-current"><AudioLines size={22} /><div><span>正在使用</span><strong>{current.name}</strong></div><Check size={17} /></div>
        <p id={descriptionId} className="nas-effects-description">为桌面音箱调校，选择即刻试听。</p>
        <div className="nas-effects-grid" role="radiogroup" aria-label="播放音效">
          {AUDIO_EFFECTS.map((effect, index) => (
            <button type="button" key={effect.id} data-effect={effect.id} role="radio" aria-checked={effect.id === value}
              tabIndex={effect.id === value ? 0 : -1} onKeyDown={(event) => moveChoice(event, index)} onClick={() => onChange?.(effect.id)}
              className={`nas-effects-choice${effect.id === value ? ' is-selected' : ''}`}>
              <span className="nas-effects-choice-title">{effect.id === 'off' && <CircleOff size={15} />}{effect.name}{effect.id === value && <Check size={17} />}</span>
              <span className="nas-effects-choice-description">{effect.description}</span>
            </button>
          ))}
        </div>
        {status?.error && <p className="nas-effects-error" role="status">{status.error}，当前已恢复原声。</p>}
        <p className="nas-effects-footnote">不同音源的听感会略有差异，可随时切回原声。</p>
      </section>
    </div>
  );
}
