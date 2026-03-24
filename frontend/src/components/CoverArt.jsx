import { useEffect, useMemo, useState } from 'react';

const normalizeSource = (value) => (typeof value === 'string' ? value.trim() : '');

export default function CoverArt({
  src = '',
  fallbackSrc = '',
  alt = '',
  className = '',
  imgClassName = '',
  loading = 'lazy',
  onClick,
}) {
  const primarySrc = normalizeSource(src);
  const placeholderSrc = normalizeSource(fallbackSrc);
  const stableFallback = useMemo(() => placeholderSrc || primarySrc, [placeholderSrc, primarySrc]);
  const [currentSrc, setCurrentSrc] = useState(stableFallback);
  const [isReady, setIsReady] = useState(!primarySrc || primarySrc === stableFallback);

  useEffect(() => {
    let active = true;
    const desiredSrc = primarySrc || stableFallback;

    if (!primarySrc || primarySrc === stableFallback) {
      setCurrentSrc(desiredSrc);
      setIsReady(true);
      return () => {
        active = false;
      };
    }

    setCurrentSrc(stableFallback || primarySrc);
    setIsReady(false);

    const image = new Image();
    image.decoding = 'async';
    image.src = primarySrc;
    image.onload = () => {
      if (!active) return;
      setCurrentSrc(primarySrc);
      setIsReady(true);
    };
    image.onerror = () => {
      if (!active) return;
      setCurrentSrc(stableFallback || primarySrc);
      setIsReady(true);
    };

    return () => {
      active = false;
    };
  }, [primarySrc, stableFallback]);

  return (
    <div className={`cover-art-shell ${className}`.trim()} data-ready={isReady ? '1' : '0'} onClick={onClick}>
      <img
        src={currentSrc || stableFallback}
        alt={alt}
        loading={loading}
        className={`cover-art-image ${isReady ? 'cover-art-image--ready' : 'cover-art-image--loading'} ${imgClassName}`.trim()}
      />
    </div>
  );
}
