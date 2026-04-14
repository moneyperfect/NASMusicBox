import React, { useEffect, useState, useRef } from 'react';
import { ChevronDown, Sparkles, CloudRain, Flame, Zap, Wind, Play, Pause, SkipBack, SkipForward, Repeat, Shuffle, Star, MoreHorizontal, Share2, Copy, UserRound } from 'lucide-react';

const VIBES = [
    { id: 'vibe-cyber', name: 'Cyberpunk', icon: Zap },
    { id: 'vibe-rain', name: 'Melancholic', icon: CloudRain },
    { id: 'vibe-space', name: 'Nebula', icon: Sparkles },
    { id: 'vibe-fire', name: 'Inferno', icon: Flame },
    { id: 'vibe-breeze', name: 'Breeze', icon: Wind },
];

const parseLrc = (lrcString) => {
    if (!lrcString) return [];
    const lines = lrcString.split('\n');
    const result = [];
    const timeRegex = /\[(\d{2}):(\d{2})\.(\d{2,3})\]/;

    lines.forEach(line => {
        const match = timeRegex.exec(line);
        if (match) {
            const min = parseInt(match[1], 10);
            const sec = parseInt(match[2], 10);
            const ms = parseInt(match[3].padEnd(3, '0'), 10);
            const timeInSec = min * 60 + sec + ms / 1000;
            const text = line.replace(timeRegex, '').trim();
            if (text) {
                result.push({ time: timeInSec, text });
            }
        }
    });
    return result;
};

const lyricsCache = new Map();

const getLyricsSourceLabel = (source) => {
    if (source === 'lrclib') return 'LRCLIB';
    if (source === 'qqmusic') return 'QQ 音乐歌词';
    if (source === 'ytmusicapi') return 'YT Music 歌词';
    if (source === 'youtube_subtitles') return 'YouTube 字幕';
    if (source === 'youtube_auto_captions') return 'YouTube 自动字幕';
    return '未标注';
};

const LYRICS_EMPTY_STATE_TEXT = '暂无歌词';
const LYRICS_NOTICE_DURATION = 3000;

export default function VibeOverlay({
    track,
    audioRef,
    audioDuration,
    playQueue = [],
    queueIndex = -1,
    jumpQueue = () => { },
    isPlaying = false,
    handleTogglePlay = () => { },
    currentTime = 0,
    formatTime = () => '0:00',
    isFavoriteItem = () => false,
    toggleFavoriteItem = () => { },
    onShareTrack = () => { },
    onCopyTrackInfo = () => { },
    onSearchArtist = () => { },
    onClose,
    apiUrl,
}) {
    const [lyrics, setLyrics] = useState([]);
    const [activeVibe, setActiveVibe] = useState(VIBES[0]);
    const [isFetching, setIsFetching] = useState(false);
    const [activeIndex, setActiveIndex] = useState(0);
    const [timeOffset, setTimeOffset] = useState(0);
    const [lyricsSource, setLyricsSource] = useState('');
    const [lyricsNotice, setLyricsNotice] = useState('');
    const [moreMenuOpen, setMoreMenuOpen] = useState(false);
    const [isShuffle, setIsShuffle] = useState(false);
    const [repeatMode, setRepeatMode] = useState(0); // 0: none, 1: all, 2: one

    const lyricsViewportRef = useRef(null);
    const lyricsLineRefs = useRef([]);
    const lyricsRef = useRef([]);
    const offsetLoadedRef = useRef(false);
    const noticeTimerRef = useRef(null);
    const moreMenuRef = useRef(null);

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

    // Keep ref in sync for the animation loop
    useEffect(() => {
        lyricsRef.current = lyrics;
        lyricsLineRefs.current = [];
        setActiveIndex(0);
    }, [lyrics]);

    useEffect(() => {
        setTimeOffset(0);
        setLyricsSource('');
        setLyricsNotice('');
        setMoreMenuOpen(false);
        offsetLoadedRef.current = false;
        if (lyricsViewportRef.current) {
            lyricsViewportRef.current.scrollTop = 0;
        }
    }, [track?.key, track?.videoId, track?.source, track?.sourceId, track?.query]);

    useEffect(() => () => {
        if (noticeTimerRef.current) {
            window.clearTimeout(noticeTimerRef.current);
        }
    }, []);

    useEffect(() => {
        let frameId;
        const updateLyricsSync = () => {
            if (audioRef?.current && lyricsRef.current.length > 1) {
                const currentAudioTime = audioRef.current.currentTime;
                const adjustedAudioTime = currentAudioTime + timeOffset;
                const currentLyrics = lyricsRef.current;

                // Apply user calibration to whole timeline.
                let newIndex = 0;
                for (let i = currentLyrics.length - 1; i >= 0; i--) {
                    if (adjustedAudioTime >= currentLyrics[i].time) {
                        newIndex = i;
                        break;
                    }
                }

                setActiveIndex(prev => {
                    if (prev !== newIndex) return newIndex;
                    return prev;
                });
            }
            frameId = requestAnimationFrame(updateLyricsSync);
        };
        frameId = requestAnimationFrame(updateLyricsSync);
        return () => cancelAnimationFrame(frameId);
    }, [audioRef, timeOffset]);

    useEffect(() => {
        const onKeyDown = (event) => {
            if (!audioRef?.current) return;
            if (event.key === '[') {
                event.preventDefault();
                setTimeOffset((prev) => Math.max(prev - 0.5, -10));
            } else if (event.key === ']') {
                event.preventDefault();
                setTimeOffset((prev) => Math.min(prev + 0.5, 10));
            } else if (event.key === '\\') {
                event.preventDefault();
                setTimeOffset(0);
            } else if (event.key === 'Escape') {
                setMoreMenuOpen(false);
            }
        };

        const onPointerDown = (event) => {
            if (moreMenuOpen && moreMenuRef.current && !moreMenuRef.current.contains(event.target)) {
                setMoreMenuOpen(false);
            }
        };

        window.addEventListener('keydown', onKeyDown);
        window.addEventListener('mousedown', onPointerDown);
        return () => {
            window.removeEventListener('keydown', onKeyDown);
            window.removeEventListener('mousedown', onPointerDown);
        };
    }, [audioRef, moreMenuOpen]);

    useEffect(() => {
        let active = true;
        if (!track) return;

        const cacheKey = track.key || track.videoId || track.title || 'unknown';
        if (lyricsCache.has(cacheKey)) {
            const cached = lyricsCache.get(cacheKey);
            setLyrics(cached.parsed || []);
            setLyricsSource(cached.source || '');
            setTimeOffset(Number(cached.offsetSeconds) || 0);
            offsetLoadedRef.current = true;
            setIsFetching(false);
            return;
        }

        setIsFetching(true);
        setLyrics([]);

        const query = new URLSearchParams({
            track_name: track.title || '',
            artist_name: track.artist || '',
            video_id: track.videoId || '',
            source: track.source || '',
            source_id: track.sourceId || '',
            track_key: track.key || '',
        });

        const durationCandidate = Number(audioDuration);
        if (Number.isFinite(durationCandidate) && durationCandidate > 0) {
            query.set('audio_duration', String(Math.round(durationCandidate)));
        }

        // Attempt to fetch lyrics
        fetch(apiUrl(`/lyrics?${query.toString()}`))
            .then(r => r.json())
            .then(data => {
                if (!active) return;
                let parsed = [];
                if (data.syncedLyrics) {
                    parsed = parseLrc(data.syncedLyrics);
                } else if (data.plainLyrics) {
                    // Fake synced item for plain text
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
                if (active) {
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
                }
            })
            .finally(() => {
                if (active) setIsFetching(false);
            });

        return () => { active = false; };
    }, [track?.key, track?.videoId, track?.source, track?.sourceId, track?.query, audioDuration, apiUrl]);

    useEffect(() => {
        const cacheKey = track?.key || track?.videoId || track?.title || '';
        if (!cacheKey || !offsetLoadedRef.current) return;

        const cached = lyricsCache.get(cacheKey);
        if (cached && Math.abs((Number(cached.offsetSeconds) || 0) - timeOffset) < 0.01) {
            return;
        }

        const timer = window.setTimeout(() => {
            fetch(apiUrl('/lyrics-offset'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    trackKey: track?.key || cacheKey,
                    videoId: track?.videoId || null,
                    source: track?.source || null,
                    sourceId: track?.sourceId || null,
                    title: track?.title || '',
                    artist: track?.artist || '',
                    offsetSeconds: Number(timeOffset.toFixed(2)),
                }),
            })
                .then((response) => response.ok ? response.json() : null)
                .then((data) => {
                    const current = lyricsCache.get(cacheKey) || { parsed: lyricsRef.current, source: lyricsSource };
                    lyricsCache.set(cacheKey, {
                        ...current,
                        offsetSeconds: Number(data?.offsetSeconds ?? timeOffset),
                    });
                })
                .catch(() => { });
        }, 450);

        return () => window.clearTimeout(timer);
    }, [timeOffset, track?.key, track?.videoId, track?.source, track?.sourceId, track?.title, track?.artist, apiUrl, lyricsSource]);

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
            {/* Dynamic Backgrounds based on activeVibe */}
            <div className="vibe-overlay-bg">
                {/* We'll animate these in CSS */}
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
                    <div className="vibe-cover-container group">
                        <div className="vibe-cover-shadow" style={{ backgroundImage: `url(${track?.cover})` }} />
                        <img src={track?.cover} alt="Cover" className="vibe-cover group-hover:scale-[1.02] transition-transform duration-500" />
                    </div>
                    <div className="w-full max-w-[400px] mb-8">
                        <div className="flex justify-between items-end mb-4">
                            <div className="flex flex-col text-left">
                                <h2 className="vibe-title text-2xl font-bold text-white drop-shadow-md tracking-tight">{track?.title}</h2>
                                <p className="vibe-artist text-white/50 text-lg font-medium mt-1">{track?.artist}</p>
                                {lyricsSource && (
                                    <p className="text-[11px] uppercase tracking-[0.24em] text-white/35 mt-2">
                                        {getLyricsSourceLabel(lyricsSource)}
                                    </p>
                                )}
                            </div>
                            <div className="relative flex gap-4 items-center mb-1" ref={moreMenuRef}>
                                <button
                                    className="transition-colors drop-shadow-md"
                                    onClick={(e) => { e.stopPropagation(); toggleFavoriteItem(track); }}
                                    title="收藏"
                                >
                                    <Star size={20} fill={isFavoriteItem(track) ? "currentColor" : "none"} className={isFavoriteItem(track) ? "text-amber-400" : "text-white/50 hover:text-white"} />
                                </button>
                                <button
                                    className={`text-white/50 hover:text-white transition-colors ${moreMenuOpen ? 'text-white' : ''}`}
                                    title="更多"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setMoreMenuOpen((prev) => !prev);
                                    }}
                                >
                                    <MoreHorizontal size={20} />
                                </button>
                                {moreMenuOpen && (
                                    <div className="vibe-more-menu">
                                        <button
                                            type="button"
                                            className="vibe-more-item"
                                            onClick={() => {
                                                setMoreMenuOpen(false);
                                                onShareTrack(track);
                                            }}
                                        >
                                            <Share2 size={15} /> 分享歌曲
                                        </button>
                                        <button
                                            type="button"
                                            className="vibe-more-item"
                                            onClick={() => {
                                                setMoreMenuOpen(false);
                                                onCopyTrackInfo(track);
                                            }}
                                        >
                                            <Copy size={15} /> 复制歌曲信息
                                        </button>
                                        <button
                                            type="button"
                                            className="vibe-more-item"
                                            onClick={() => {
                                                setMoreMenuOpen(false);
                                                onSearchArtist(track?.artist || '');
                                            }}
                                        >
                                            <UserRound size={15} /> 搜索该歌手
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Progress Bar */}
                        <div
                            className="w-full h-1.5 bg-white/20 rounded-full cursor-pointer overflow-hidden mb-2 relative group"
                            onClick={(e) => {
                                const rect = e.currentTarget.getBoundingClientRect();
                                const x = e.clientX - rect.left;
                                if (audioRef && audioRef.current && audioDuration) {
                                    audioRef.current.currentTime = (x / rect.width) * audioDuration;
                                }
                            }}
                        >
                            <div className="absolute top-0 left-0 h-full bg-white opacity-90 transition-all rounded-full" style={{ width: `${(currentTime / audioDuration) * 100}%` }} />
                        </div>

                        <div className="w-full flex justify-between items-center text-[11px] text-white/50 mb-6 font-medium">
                            <span>{formatTime(currentTime)}</span>
                            <span>-{formatTime(audioDuration - currentTime)}</span>
                        </div>

                        {/* Controls */}
                        <div className="flex items-center justify-between w-full px-2">
                            <button
                                className={`transition-colors ${isShuffle ? 'text-white' : 'text-white/40 hover:text-white'}`}
                                onClick={(e) => { e.stopPropagation(); setIsShuffle(!isShuffle); }}
                                title="随机播放"
                            >
                                <Shuffle size={20} />
                            </button>
                            <button className="text-white hover:text-white/70 transition-colors" onClick={() => jumpQueue(queueIndex - 1)} disabled={queueIndex <= 0} title="上一首">
                                <SkipBack size={36} fill="currentColor" />
                            </button>
                            <button className="text-white hover:scale-105 transition-transform drop-shadow-lg" onClick={handleTogglePlay} title="播放/暂停">
                                {isPlaying ? <Pause size={48} fill="currentColor" /> : <Play size={48} fill="currentColor" className="ml-1" />}
                            </button>
                            <button className="text-white hover:text-white/70 transition-colors" onClick={() => jumpQueue(queueIndex + 1)} disabled={queueIndex < 0 || queueIndex >= playQueue.length - 1} title="下一首">
                                <SkipForward size={36} fill="currentColor" />
                            </button>
                            <button
                                className={`transition-colors flex relative ${repeatMode > 0 ? 'text-white' : 'text-white/40 hover:text-white'}`}
                                onClick={(e) => { e.stopPropagation(); setRepeatMode((prev) => (prev + 1) % 3); }}
                                title={repeatMode === 2 ? "单曲循环" : "列表循环"}
                            >
                                <Repeat size={20} />
                                {repeatMode === 2 && <span className="absolute top-0 right-0 transform translate-x-1 -translate-y-1 text-[8px] font-bold text-white bg-[#101015] rounded-full w-[12px] h-[12px] flex items-center justify-center">1</span>}
                            </button>
                        </div>
                    </div>

                    {playQueue && playQueue.length > 0 && (
                        <div className="vibe-queue w-full max-w-[400px] flex-1 overflow-y-auto pr-2 custom-scrollbar">
                            <div className="text-xs font-bold text-white/40 uppercase tracking-widest mb-4 px-2">接下来播放</div>
                            <div className="flex flex-col gap-1">
                                {playQueue.map((qTrack, idx) => {
                                    const isActive = idx === queueIndex;
                                    return (
                                        <div
                                            key={idx}
                                            className={`flex items-center gap-3 p-2 rounded-xl cursor-pointer transition-all duration-300 ${isActive ? 'bg-white/10 shadow-[0_4px_12px_rgba(0,0,0,0.2)] scale-[1.02]' : 'hover:bg-white/5 opacity-60 hover:opacity-100'}`}
                                            onClick={() => jumpQueue(idx)}
                                        >
                                            <img src={qTrack.cover || qTrack.img || track?.cover} className={`w-10 h-10 rounded-md object-cover shadow-md ${isActive ? 'animate-pulse' : ''}`} alt="" />
                                            <div className="flex flex-col flex-1 min-w-0">
                                                <div className={`text-sm font-semibold truncate ${isActive ? 'text-white' : 'text-white/80'}`}>{qTrack.title}</div>
                                                <div className={`text-xs truncate ${isActive ? 'text-white/70' : 'text-white/40'}`}>{qTrack.artist}</div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>

                <div className="vibe-lyrics-container" ref={lyricsViewportRef}>
                    {isFetching ? (
                        <div className="vibe-lyrics-placeholder animate-pulse">
                            [ 正在跨越光年捕获歌词信号... ]
                        </div>
                    ) : (
                        lyrics.length > 0 ? (
                            lyrics.length === 1 && lyrics[0].time === 0 && lyrics[0].text.length > 50 ? (
                                // Plain lyrics block
                                <div className="vibe-lyric-line active whitespace-pre-wrap leading-loose text-center">
                                    {lyrics[0].text}
                                </div>
                            ) : (
                                // Synced lyrics
                                lyrics.map((line, idx) => {
                                    const isActive = idx === activeIndex;
                                    return (
                                        <div
                                            key={idx}
                                            ref={(node) => {
                                                lyricsLineRefs.current[idx] = node;
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
                        )
                    )}
                </div>
            </div>

            {/* Floating Hidden Dock UI */}
            <div className="vibe-settings-dock group">
                <div className="dock-trigger">
                    <Sparkles size={24} />
                </div>
                <div className="dock-menu">
                    <span className="text-xs uppercase tracking-widest text-white/50 mb-3 block text-center">Atmosphere</span>
                    <div className="flex flex-col gap-2">
                        {VIBES.map(v => (
                            <button
                                key={v.id}
                                className={`vibe-chip ${activeVibe.id === v.id ? 'active' : ''}`}
                                onClick={() => setActiveVibe(v)}
                                title={v.name}
                            >
                                <v.icon size={16} /> {v.name}
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
                                onClick={() => setTimeOffset((prev) => Math.max(prev - 0.5, -10))}
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
                                onClick={() => setTimeOffset((prev) => Math.min(prev + 0.5, 10))}
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
