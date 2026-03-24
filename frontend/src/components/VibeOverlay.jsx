import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  Sparkles,
  CloudRain,
  Flame,
  Zap,
  Wind,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Repeat,
  Shuffle,
  Star,
  MoreHorizontal,
  ListMusic,
  Share2,
  Copy,
  Search,
  Download,
  Image as ImageIcon,
  UserRound,
} from 'lucide-react';

import CoverArt from './CoverArt';

const VIBES = [
  { id: 'vibe-cyber', name: 'Cyberpunk', icon: Zap },
  { id: 'vibe-rain', name: 'Melancholic', icon: CloudRain },
  { id: 'vibe-space', name: 'Nebula', icon: Sparkles },
  { id: 'vibe-fire', name: 'Inferno', icon: Flame },
  { id: 'vibe-breeze', name: 'Breeze', icon: Wind },
];

const LYRICS_EMPTY_STATE_TEXT = '暂无歌词';
const LYRICS_NOTICE_DURATION = 3000;
const lyricsCache = new Map();

const parseLrc = (lrcString) => {
  if (!lrcString) return [];
  return lrcString
    .split('\n')
    .map((line) => {
      const match = /\[(\d{2}):(\d{2})\.(\d{2,3})\]/.exec(line);
      if (!match) return null;
      const minutes = Number.parseInt(match[1], 10);
      const seconds = Number.parseInt(match[2], 10);
      const millis = Number.parseInt(match[3].padEnd(3, '0'), 10);
      const text = line.replace(match[0], '').trim();
      if (!text) return null;
      return {
        time: minutes * 60 + seconds + millis / 1000,
        text,
      };
    })
    .filter(Boolean);
};

const getLyricsSourceLabel = (source) => {
  if (source === 'lrclib') return 'LRCLIB';
  if (source === 'youtube_subtitles') return 'YouTube 字幕';
  if (source === 'youtube_auto_captions') return 'YouTube 自动字幕';
  return '未标注';
};

const repeatTitle = (repeatMode) => {
  if (repeatMode === 'one') return '单曲循环';
  if (repeatMode === 'all') return '列表循环';
  return '关闭循环';
};

const closeAfter = (callback, close) => () => {
  close();
  callback?.();
};

export default function VibeOverlay({
  track,
  audioRef,
  audioDuration,
  playQueue = [],
  queueIndex = -1,
  jumpQueue = () => {},
  queueSource = 'direct',
  queuePanelAvailable = false,
  isPlaying = false,
  handleTogglePlay = () => {},
  currentTime = 0,
  formatTime = () => '0:00',
  isFavoriteItem = () => false,
  toggleFavoriteItem = () => {},
  repeatMode = 'off',
  onCycleRepeatMode = () => {},
  shuffleEnabled = false,
  onToggleShuffle = () => {},
  canGoPrevious = false,
  canGoNext = false,
  onPreviousTrack = () => {},
  onNextTrack = () => {},
  onDownloadTrack = () => {},
  onShareTrack = () => {},
  onCopyTrackInfo = () => {},
  onSearchArtist = () => {},
  onSearchTrack = () => {},
  onViewCover = () => {},
  onClose,
  apiUrl,
  resolveCoverArt = (_song, _artist, cover) => cover || '',
}) {
  const [lyrics, setLyrics] = useState([]);
  const [activeVibe, setActiveVibe] = useState(VIBES[0]);
  const [isFetching, setIsFetching] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [timeOffset, setTimeOffset] = useState(0);
  const [lyricsSource, setLyricsSource] = useState('');
  const [lyricsNotice, setLyricsNotice] = useState('');
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [queuePanelOpen, setQueuePanelOpen] = useState(false);

  const lyricsViewportRef = useRef(null);
  const lyricsLineRefs = useRef([]);
  const offsetLoadedRef = useRef(false);
  const noticeTimerRef = useRef(null);
  const queuePanelRef = useRef(null);
  const moreMenuRef = useRef(null);

  const displayCover = useMemo(
    () => resolveCoverArt(track?.title, track?.artist, track?.cover),
    [resolveCoverArt, track?.artist, track?.cover, track?.title],
  );

  const showLyricsNotice = (text) => {
    if (!text) return;
    setLyricsNotice(text);
    if (noticeTimerRef.current) {
      window.clearTimeout(noticeTimerRef.current);
    }
    noticeTimerRef.current = window.setTimeout(() => {
      setLyricsNotice('');
      noticeTimerRef.current = null;
    }, LYRICS_NOTICE_DURATION);
  };

  useEffect(() => {
    lyricsLineRefs.current = [];
    setActiveIndex(0);
  }, [lyrics]);

  useEffect(() => {
    setTimeOffset(0);
    setLyricsSource('');
    setLyricsNotice('');
    setMoreMenuOpen(false);
    setQueuePanelOpen(false);
    offsetLoadedRef.current = false;
    if (lyricsViewportRef.current) {
      lyricsViewportRef.current.scrollTop = 0;
    }
  }, [track?.key, track?.videoId, track?.query]);

  useEffect(() => () => {
    if (noticeTimerRef.current) {
      window.clearTimeout(noticeTimerRef.current);
    }
  }, []);

  useEffect(() => {
    if (!queuePanelAvailable) {
      setQueuePanelOpen(false);
    }
  }, [queuePanelAvailable, queueSource]);

  useEffect(() => {
    let frameId;
    const updateLyricsSync = () => {
      if (audioRef?.current && lyrics.length > 1) {
        const adjustedAudioTime = audioRef.current.currentTime + timeOffset;
        let nextIndex = 0;
        for (let index = lyrics.length - 1; index >= 0; index -= 1) {
          if (adjustedAudioTime >= lyrics[index].time) {
            nextIndex = index;
            break;
          }
        }
        setActiveIndex((previous) => (previous === nextIndex ? previous : nextIndex));
      }
      frameId = window.requestAnimationFrame(updateLyricsSync);
    };

    frameId = window.requestAnimationFrame(updateLyricsSync);
    return () => window.cancelAnimationFrame(frameId);
  }, [audioRef, lyrics, timeOffset]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === '[') {
        event.preventDefault();
        setTimeOffset((previous) => Math.max(previous - 0.5, -10));
      } else if (event.key === ']') {
        event.preventDefault();
        setTimeOffset((previous) => Math.min(previous + 0.5, 10));
      } else if (event.key === '\\') {
        event.preventDefault();
        setTimeOffset(0);
      } else if (event.key === 'Escape') {
        setMoreMenuOpen(false);
        setQueuePanelOpen(false);
      }
    };

    const handlePointerDown = (event) => {
      const targetElement = event.target instanceof Element ? event.target : null;
      if (moreMenuOpen && moreMenuRef.current && !moreMenuRef.current.contains(event.target)) {
        setMoreMenuOpen(false);
      }
      if (queuePanelOpen && queuePanelRef.current && !queuePanelRef.current.contains(event.target) && !targetElement?.closest('.vibe-queue-toggle')) {
        setQueuePanelOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('mousedown', handlePointerDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('mousedown', handlePointerDown);
    };
  }, [moreMenuOpen, queuePanelOpen]);

  useEffect(() => {
    let active = true;
    if (!track) return undefined;

    const cacheKey = track.key || track.videoId || track.title || 'unknown';
    if (lyricsCache.has(cacheKey)) {
      const cached = lyricsCache.get(cacheKey);
      setLyrics(cached.parsed || []);
      setLyricsSource(cached.source || '');
      setTimeOffset(Number(cached.offsetSeconds) || 0);
      offsetLoadedRef.current = true;
      setIsFetching(false);
      return () => {
        active = false;
      };
    }

    setIsFetching(true);
    setLyrics([]);

    const query = new URLSearchParams({
      track_name: track.title || '',
      artist_name: track.artist || '',
      video_id: track.videoId || '',
      track_key: track.key || '',
    });

    const durationCandidate = Number(audioDuration);
    if (Number.isFinite(durationCandidate) && durationCandidate > 0) {
      query.set('audio_duration', String(Math.round(durationCandidate)));
    }

    fetch(apiUrl(`/lyrics?${query.toString()}`))
      .then((response) => response.json())
      .then((data) => {
        if (!active) return;
        let parsed = [];
        if (data.syncedLyrics) {
          parsed = parseLrc(data.syncedLyrics);
        } else if (data.plainLyrics) {
          parsed = [{ time: 0, text: data.plainLyrics }];
        } else {
          parsed = [];
          showLyricsNotice('未找到歌词');
        }
        const offsetSeconds = Number.isFinite(Number(data.offsetSeconds)) ? Number(data.offsetSeconds) : 0;
        setLyrics(parsed);
        setLyricsSource(data.source || '');
        setTimeOffset(offsetSeconds);
        offsetLoadedRef.current = true;
        lyricsCache.set(cacheKey, {
          parsed,
          source: data.source || '',
          offsetSeconds,
        });
      })
      .catch(() => {
        if (!active) return;
        setLyrics([]);
        setLyricsSource('');
        setTimeOffset(0);
        showLyricsNotice('未找到歌词');
        offsetLoadedRef.current = true;
        lyricsCache.set(cacheKey, {
          parsed: [],
          source: '',
          offsetSeconds: 0,
        });
      })
      .finally(() => {
        if (active) setIsFetching(false);
      });

    return () => {
      active = false;
    };
  }, [track, audioDuration, apiUrl]);

  useEffect(() => {
    const cacheKey = track?.key || track?.videoId || track?.title || '';
    if (!cacheKey || !offsetLoadedRef.current) return undefined;

    const cached = lyricsCache.get(cacheKey);
    if (cached && Math.abs((Number(cached.offsetSeconds) || 0) - timeOffset) < 0.01) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      fetch(apiUrl('/lyrics-offset'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trackKey: track?.key || cacheKey,
          videoId: track?.videoId || null,
          title: track?.title || '',
          artist: track?.artist || '',
          offsetSeconds: Number(timeOffset.toFixed(2)),
        }),
      })
        .then((response) => (response.ok ? response.json() : null))
        .then((data) => {
          const current = lyricsCache.get(cacheKey) || { parsed: lyrics, source: lyricsSource };
          lyricsCache.set(cacheKey, {
            ...current,
            offsetSeconds: Number(data?.offsetSeconds ?? timeOffset),
          });
        })
        .catch(() => {});
    }, 450);

    return () => window.clearTimeout(timer);
  }, [apiUrl, lyrics, lyricsSource, timeOffset, track?.artist, track?.key, track?.title, track?.videoId]);

  useEffect(() => {
    if (lyrics.length <= 1) return;
    const viewport = lyricsViewportRef.current;
    const activeLine = lyricsLineRefs.current[activeIndex];
    if (!viewport || !activeLine) return;

    const targetTop = activeLine.offsetTop - viewport.clientHeight * 0.42 + activeLine.clientHeight / 2;
    const maxScrollTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
    const nextTop = Math.max(0, Math.min(targetTop, maxScrollTop));
    viewport.scrollTo({
      top: nextTop,
      behavior: 'smooth',
    });
  }, [activeIndex, lyrics.length, track?.key, track?.videoId]);

  return (
    <div className={`vibe-overlay ${activeVibe.id}`}>
      <div className="vibe-overlay-bg">
        <div className="vibe-effect effect-1" />
        <div className="vibe-effect effect-2" />
        <div className="vibe-grain" />
      </div>

      {lyricsNotice && (
        <div className="fixed top-6 right-6 z-30 rounded-full border border-white/10 bg-black/45 px-4 py-2 text-sm font-medium text-white/90 backdrop-blur-xl shadow-2xl">
          {lyricsNotice}
        </div>
      )}

      <button className="vibe-close-btn" onClick={onClose}>
        <ChevronDown size={32} />
      </button>

      <div className="vibe-content">
        <div className="vibe-left">
          <div className="vibe-left-inner">
            <div className="vibe-cover-container group">
              <div className="vibe-cover-shadow" style={{ backgroundImage: `url(${displayCover})` }} />
              <CoverArt
                src={displayCover}
                fallbackSrc={resolveCoverArt(track?.title, track?.artist, '')}
                alt={track?.title || 'Cover'}
                className="w-full h-full overflow-hidden rounded-[inherit]"
                imgClassName="vibe-cover group-hover:scale-[1.02] transition-transform duration-500"
              />
            </div>

            <div className="vibe-meta-card">
              <div className="flex justify-between items-start gap-4 mb-4">
                <div className="flex flex-col text-left min-w-0">
                  <h2 className="vibe-title text-2xl font-bold text-white drop-shadow-md tracking-tight truncate">{track?.title}</h2>
                  <p className="vibe-artist text-white/50 text-lg font-medium mt-1 truncate">{track?.artist}</p>
                  {lyricsSource && (
                    <p className="text-[11px] uppercase tracking-[0.24em] text-white/35 mt-2">
                      {getLyricsSourceLabel(lyricsSource)}
                    </p>
                  )}
                </div>
                <div className="relative" ref={moreMenuRef}>
                  <div className="flex gap-3 items-center">
                    <button
                      className="transition-colors drop-shadow-md"
                      onClick={(event) => {
                        event.stopPropagation();
                        toggleFavoriteItem(track);
                      }}
                      title="收藏"
                    >
                      <Star size={20} fill={isFavoriteItem(track) ? 'currentColor' : 'none'} className={isFavoriteItem(track) ? 'text-amber-400' : 'text-white/50 hover:text-white'} />
                    </button>
                    <button
                      className={`text-white/50 hover:text-white transition-colors ${moreMenuOpen ? 'text-white' : ''}`}
                      title="更多"
                      onClick={(event) => {
                        event.stopPropagation();
                        setMoreMenuOpen((previous) => !previous);
                      }}
                    >
                      <MoreHorizontal size={20} />
                    </button>
                  </div>

                  {moreMenuOpen && (
                    <div className="vibe-more-menu">
                      <button type="button" className="vibe-more-item" onClick={closeAfter(() => onShareTrack(track), () => setMoreMenuOpen(false))}>
                        <Share2 size={15} /> 分享歌曲
                      </button>
                      <button type="button" className="vibe-more-item" onClick={closeAfter(() => onCopyTrackInfo(track), () => setMoreMenuOpen(false))}>
                        <Copy size={15} /> 复制歌曲信息
                      </button>
                      <button type="button" className="vibe-more-item" onClick={closeAfter(() => onSearchArtist(track?.artist || ''), () => setMoreMenuOpen(false))}>
                        <UserRound size={15} /> 搜索该歌手
                      </button>
                      <button type="button" className="vibe-more-item" onClick={closeAfter(() => onSearchTrack(track), () => setMoreMenuOpen(false))}>
                        <Search size={15} /> 搜索同名歌曲
                      </button>
                      <button type="button" className="vibe-more-item" onClick={closeAfter(() => onDownloadTrack(track), () => setMoreMenuOpen(false))}>
                        <Download size={15} /> 加入下载队列
                      </button>
                      <button type="button" className="vibe-more-item" onClick={closeAfter(() => onViewCover(track), () => setMoreMenuOpen(false))}>
                        <ImageIcon size={15} /> 查看封面
                      </button>
                    </div>
                  )}
                </div>
              </div>

              <div
                className="w-full h-1.5 bg-white/20 rounded-full cursor-pointer overflow-hidden mb-2 relative group"
                onClick={(event) => {
                  const rect = event.currentTarget.getBoundingClientRect();
                  const x = event.clientX - rect.left;
                  if (audioRef?.current && audioDuration) {
                    audioRef.current.currentTime = (x / rect.width) * audioDuration;
                  }
                }}
              >
                <div
                  className="absolute top-0 left-0 h-full bg-white opacity-90 transition-all rounded-full"
                  style={{ width: audioDuration > 0 ? `${(currentTime / audioDuration) * 100}%` : '0%' }}
                />
              </div>

              <div className="w-full flex justify-between items-center text-[11px] text-white/50 mb-6 font-medium">
                <span>{formatTime(currentTime)}</span>
                <span>-{formatTime(Math.max(audioDuration - currentTime, 0))}</span>
              </div>

              <div className="vibe-controls-row">
                <button
                  className={`transition-colors ${shuffleEnabled ? 'text-white' : 'text-white/40 hover:text-white'}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onToggleShuffle();
                  }}
                  title={shuffleEnabled ? '关闭随机播放' : '随机播放'}
                >
                  <Shuffle size={20} />
                </button>
                <button className="text-white hover:text-white/70 transition-colors disabled:text-white/20" onClick={onPreviousTrack} disabled={!canGoPrevious} title="上一首">
                  <SkipBack size={36} fill="currentColor" />
                </button>
                <button className="text-white hover:scale-105 transition-transform drop-shadow-lg" onClick={handleTogglePlay} title="播放/暂停">
                  {isPlaying ? <Pause size={48} fill="currentColor" /> : <Play size={48} fill="currentColor" className="ml-1" />}
                </button>
                <button className="text-white hover:text-white/70 transition-colors disabled:text-white/20" onClick={onNextTrack} disabled={!canGoNext} title="下一首">
                  <SkipForward size={36} fill="currentColor" />
                </button>
                <button
                  className={`transition-colors flex relative ${repeatMode !== 'off' ? 'text-white' : 'text-white/40 hover:text-white'}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onCycleRepeatMode();
                  }}
                  title={repeatTitle(repeatMode)}
                >
                  <Repeat size={20} />
                  {repeatMode === 'one' && <span className="vibe-repeat-badge">1</span>}
                </button>
              </div>

              {queuePanelAvailable && (
                <button
                  type="button"
                  className={`vibe-queue-toggle ${queuePanelOpen ? 'is-active' : ''}`}
                  onClick={() => setQueuePanelOpen((previous) => !previous)}
                >
                  <ListMusic size={16} />
                  <span>接下来播放</span>
                  <span className="vibe-queue-count">{playQueue.length}</span>
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="vibe-lyrics-column">
          <div className="vibe-lyrics-shell">
            <div className="vibe-lyrics-container" ref={lyricsViewportRef}>
              {isFetching ? (
                <div className="vibe-lyrics-placeholder animate-pulse">
                  [ 正在跨越光年捕获歌词信号... ]
                </div>
              ) : lyrics.length > 0 ? (
                lyrics.length === 1 && lyrics[0].time === 0 && lyrics[0].text.length > 50 ? (
                  <div className="vibe-lyric-line active whitespace-pre-wrap leading-loose text-center">
                    {lyrics[0].text}
                  </div>
                ) : (
                  lyrics.map((line, index) => {
                    const isActive = index === activeIndex;
                    return (
                      <div
                        key={`${line.time}-${index}`}
                        ref={(node) => {
                          lyricsLineRefs.current[index] = node;
                        }}
                        className={`vibe-lyric-line transition-all duration-500 ${isActive ? 'active' : ''}`}
                      >
                        {line.text}
                      </div>
                    );
                  })
                )
              ) : (
                <div className="vibe-lyrics-placeholder text-white/35">
                  {LYRICS_EMPTY_STATE_TEXT}
                </div>
              )}
            </div>
          </div>

          {queuePanelAvailable && (
            <aside ref={queuePanelRef} className={`vibe-queue-panel ${queuePanelOpen ? 'is-open' : ''}`}>
              <div className="vibe-queue-panel-header">
                <div>
                  <div className="text-xs font-bold text-white/40 uppercase tracking-widest">接下来播放</div>
                  <div className="text-sm text-white/55 mt-1">
                    {queueSource === 'search' ? '搜索结果队列' : queueSource === 'continue' ? '继续听队列' : '推荐队列'}
                  </div>
                </div>
                <button type="button" className="text-white/40 hover:text-white transition-colors" onClick={() => setQueuePanelOpen(false)}>
                  <ChevronDown size={18} />
                </button>
              </div>
              <div className="vibe-queue-list">
                {playQueue.map((queuedTrack, index) => {
                  const isActive = index === queueIndex;
                  const queueCover = resolveCoverArt(queuedTrack.title, queuedTrack.artist, queuedTrack.cover || queuedTrack.img);
                  return (
                    <button
                      key={`${queuedTrack.videoId || queuedTrack.key || queuedTrack.title}-${index}`}
                      type="button"
                      className={`vibe-queue-item ${isActive ? 'is-active' : ''}`}
                      onClick={() => {
                        setQueuePanelOpen(false);
                        jumpQueue(index);
                      }}
                    >
                      <CoverArt
                        src={queueCover}
                        fallbackSrc={resolveCoverArt(queuedTrack.title, queuedTrack.artist, '')}
                        className="w-11 h-11 rounded-xl overflow-hidden shrink-0"
                        imgClassName="w-full h-full object-cover"
                        alt={queuedTrack.title}
                      />
                      <div className="flex flex-col min-w-0 text-left">
                        <span className="text-sm font-semibold truncate">{queuedTrack.title}</span>
                        <span className="text-xs text-white/45 truncate">{queuedTrack.artist}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </aside>
          )}
        </div>
      </div>

      <div className="vibe-settings-dock group">
        <div className="dock-trigger">
          <Sparkles size={24} />
        </div>
        <div className="dock-menu">
          <span className="text-xs uppercase tracking-widest text-white/50 mb-3 block text-center">Atmosphere</span>
          <div className="flex flex-col gap-2">
            {VIBES.map((vibe) => (
              <button
                key={vibe.id}
                className={`vibe-chip ${activeVibe.id === vibe.id ? 'active' : ''}`}
                onClick={() => setActiveVibe(vibe)}
                title={vibe.name}
              >
                <vibe.icon size={16} /> {vibe.name}
              </button>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-white/10">
            <span className="text-xs uppercase tracking-widest text-white/50 mb-2 block text-center">Lyrics Sync</span>
            {lyricsSource && (
              <span className="text-[10px] uppercase tracking-[0.2em] text-white/35 mb-3 block text-center">
                {getLyricsSourceLabel(lyricsSource)}
              </span>
            )}
            <div className="flex items-center justify-center gap-2">
              <button
                className="vibe-chip"
                title="歌词偏慢时点这里（[）"
                onClick={() => setTimeOffset((previous) => Math.max(previous - 0.5, -10))}
              >
                -0.5s
              </button>
              <button
                className="vibe-chip"
                title="重置偏移（\\）"
                onClick={() => setTimeOffset(0)}
              >
                {timeOffset >= 0 ? `+${timeOffset.toFixed(1)}s` : `${timeOffset.toFixed(1)}s`}
              </button>
              <button
                className="vibe-chip"
                title="歌词偏快时点这里（]）"
                onClick={() => setTimeOffset((previous) => Math.min(previous + 0.5, 10))}
              >
                +0.5s
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
