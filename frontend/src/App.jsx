import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Compass,
  Search,
  Disc3,
  Heart,
  History,
  ShieldCheck,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Volume2,
  ListMusic,
  LoaderCircle,
  MoreVertical,
  Plus,
  Check,
  TrendingUp,
  Radio,
  User,
  Settings,
  X,
  Sparkles,
  Info,
  ExternalLink,
  ChevronRight,
  Download,
  RefreshCw,
  Clock3,
  CheckCircle2,
  AlertTriangle,
  Trash2,
  FolderDown,
} from 'lucide-react';

import VibeOverlay from './components/VibeOverlay';

const HISTORY_STORAGE_KEY = 'nsrl_local_history_v2';
const FAVORITES_STORAGE_KEY = 'nsrl_local_favorites_v2';
const LIBRARY_MIGRATION_KEY = 'nas_library_db_migrated_v1';
const DOWNLOAD_HISTORY_STORAGE_KEY = 'nas_recent_downloads_v1';
const DOWNLOAD_CENTER_STORAGE_KEY = 'nas_download_center_v1';

const NAV_ITEMS = [
  { id: 'search', label: '搜索', icon: Search },
  { id: 'discover', label: '现在就听', icon: Play },
  { id: 'browse', label: '浏览', icon: Compass },
  { id: 'radio', label: '广播', icon: Radio },
];

const LIBRARY_ITEMS = [
  { id: 'history', label: '最近添加', icon: History },
  { id: 'artists', label: '音乐人', icon: User },
  { id: 'songs', label: '歌曲', icon: ListMusic },
  { id: 'favorites', label: '收藏夹', icon: Heart },
];

const PLAYLIST_ITEMS = [
  { id: 'downloads', label: '下载中心', icon: FolderDown },
  { id: 'system', label: '系统检测', icon: ShieldCheck },
];

const BRAND = {
  name: 'NAS',
  tagline: 'Next Audio Station',
};

const QUICK_PRESETS = [
  { song: 'Yellow', artist: 'Coldplay', cover: 'https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=400' },
  { song: 'Viva La Vida', artist: 'Coldplay', cover: 'https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=400' },
  { song: 'Take On Me', artist: 'a-ha', cover: 'https://images.unsplash.com/photo-1493225255756-d9584f8606e9?w=400' },
  { song: 'A Thousand Years', artist: 'Christina Perri', cover: 'https://images.unsplash.com/photo-1514525253361-bee8a197c0c5?w=400' },
  { song: 'Nightcall', artist: 'Kavinsky', cover: 'https://images.unsplash.com/photo-1557683316-973673baf926?w=400' },
  { song: 'Blinding Lights', artist: 'The Weeknd', cover: 'https://images.unsplash.com/photo-1619983081563-430f63602796?w=400' },
];

const BROWSE_CATEGORIES = [
  { id: 'pop', title: '流行', color: 'from-blue-500 to-cyan-500' },
  { id: 'hiphop', title: '嘻哈', color: 'from-orange-500 to-red-500' },
  { id: 'electronic', title: '电子', color: 'from-purple-500 to-indigo-600' },
  { id: 'rock', title: '摇滚', color: 'from-red-600 to-rose-700' },
  { id: 'rnb', title: 'R&B / 灵魂乐', color: 'from-pink-500 to-rose-500' },
  { id: 'kpop', title: 'K-Pop', color: 'from-teal-400 to-emerald-500' },
  { id: 'jazz', title: '爵士', color: 'from-amber-600 to-orange-700' },
  { id: 'classical', title: '古典', color: 'from-slate-600 to-slate-800' },
];

const RADIO_STATIONS = [
  { id: 'nas1', title: 'NAS 1', subtitle: '编辑精选与最新热单。', img: 'https://images.unsplash.com/photo-1598488035139-bdbb2231ce04?w=800' },
  { id: 'naspulse', title: 'NAS Pulse', subtitle: '全天候氛围与电子律动。', img: 'https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=800' },
  { id: 'nasrewind', title: 'NAS Rewind', subtitle: '经典回放与熟悉旋律。', img: 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=800' },
];

const searchCache = new Map();
const IS_MINI_MODE = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('mini') === '1';
const PLAYER_STATE_STORAGE_KEY = 'nas_player_state_v1';
const DESKTOP_ACTION_STORAGE_KEY = 'nas_desktop_action_v1';
const DESKTOP_SYNC_CHANNEL = 'nas_desktop_sync_v1';
const LIBRARY_SYNC_INTERVAL_MS = 6000;

const trimTrailingSlash = (value) => value.replace(/\/+$/, '');
const normalizeSearchQuery = (value) => (value || '').trim().replace(/\s+/g, ' ');

const getDefaultApiBase = () => {
  if (typeof window === 'undefined') return 'http://127.0.0.1:8010';
  const { protocol, hostname, port } = window.location;
  if (!hostname) return 'http://127.0.0.1:8010';
  if (port === '5173') return `${protocol}//${hostname}:8010`;
  return `${protocol}//${hostname}${port ? `:${port}` : ''}`;
};

const API_BASE = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL || getDefaultApiBase());

const apiUrl = (path) => {
  if (!path) return API_BASE;
  if (path.startsWith('http')) return path;
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
};

const resolveAudioUrl = (audioSrc) => {
  if (!audioSrc) return '';
  if (audioSrc.startsWith('http') || audioSrc.startsWith('//')) return audioSrc;
  return apiUrl(audioSrc);
};

const readStorage = (key, fallback) => {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
};

const readObjectStorage = (key, fallback) => {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : fallback;
  } catch {
    return fallback;
  }
};

const readBooleanStorage = (key) => {
  try {
    return localStorage.getItem(key) === '1';
  } catch {
    return false;
  }
};

const formatTime = (seconds) => {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
};

const makeQuery = (song, artist) => [song?.trim(), artist?.trim()].filter(Boolean).join(' ').trim();
const trackKey = (videoId, title, artist) => videoId ? `vid:${videoId}` : `${(title || '').trim().toLowerCase()}::${(artist || '').trim().toLowerCase()}`;
const downloadTaskId = () => `dl_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

const formatBytes = (bytes) => {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
};

const formatRelativeTime = (timestamp) => {
  if (!timestamp) return '刚刚';
  const target = new Date(timestamp).getTime();
  if (!Number.isFinite(target)) return '刚刚';
  const diff = Date.now() - target;
  const minutes = Math.max(0, Math.floor(diff / 60000));
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
};

const normalizeDownloadHistoryItem = (item) => ({
  key: item?.key || trackKey(item?.videoId, item?.title, item?.artist),
  title: item?.title || '',
  artist: item?.artist || '',
  filename: item?.filename || '',
  sourceUrl: item?.sourceUrl || '',
  downloadedAt: item?.downloadedAt || new Date().toISOString(),
});

const mergeDownloadHistory = (primary, secondary, limit = 30) => {
  const merged = new Map();
  [...primary, ...secondary].forEach((rawItem) => {
    const item = normalizeDownloadHistoryItem(rawItem);
    const dedupeKey = `${item.filename}::${item.sourceUrl}::${item.downloadedAt}`;
    if (!merged.has(dedupeKey)) {
      merged.set(dedupeKey, item);
    }
  });
  return Array.from(merged.values())
    .sort((a, b) => (b.downloadedAt || '').localeCompare(a.downloadedAt || ''))
    .slice(0, limit);
};

const normalizeDownloadTask = (item) => ({
  id: item?.id || downloadTaskId(),
  key: item?.key || trackKey(item?.videoId, item?.title, item?.artist),
  title: item?.title || '',
  artist: item?.artist || '',
  cover: item?.cover || '',
  query: item?.query || makeQuery(item?.title, item?.artist),
  videoId: item?.videoId || null,
  audioSrc: item?.audioSrc || '',
  audioExt: item?.audioExt || 'm4a',
  filename: item?.filename || '',
  status: item?.status || 'queued',
  progress: Number.isFinite(Number(item?.progress)) ? Number(item.progress) : 0,
  bytesReceived: Number(item?.bytesReceived || 0),
  totalBytes: Number(item?.totalBytes || 0),
  createdAt: item?.createdAt || new Date().toISOString(),
  startedAt: item?.startedAt || null,
  completedAt: item?.completedAt || null,
  error: item?.error || '',
  sourceUrl: item?.sourceUrl || '',
});

const buildLibraryRecord = (item, timestampField) => {
  const key = item?.key || trackKey(item?.videoId, item?.title, item?.artist);
  const timestamp = item?.[timestampField] || item?.savedAt || item?.playedAt || new Date().toISOString();

  return {
    key,
    title: item?.title || '',
    artist: item?.artist || '',
    cover: item?.cover || '',
    query: item?.query || makeQuery(item?.title, item?.artist),
    videoId: item?.videoId || null,
    savedAt: timestampField === 'savedAt' ? timestamp : (item?.savedAt || null),
    playedAt: timestampField === 'playedAt' ? timestamp : (item?.playedAt || null),
  };
};

const toFavoriteRecord = (item) => buildLibraryRecord(item, 'savedAt');
const toHistoryRecord = (item) => buildLibraryRecord(item, 'playedAt');

const mergeLibraryRecords = (primary, secondary, limit, timestampField) => {
  const merged = new Map();

  [...primary, ...secondary].forEach((rawItem) => {
    const item = timestampField === 'savedAt' ? toFavoriteRecord(rawItem) : toHistoryRecord(rawItem);
    if (!item.key) return;

    const previous = merged.get(item.key);
    const nextTimestamp = item[timestampField] || '';
    const prevTimestamp = previous?.[timestampField] || '';

    if (!previous || nextTimestamp > prevTimestamp) {
      merged.set(item.key, item);
    }
  });

  return Array.from(merged.values())
    .sort((a, b) => (b[timestampField] || '').localeCompare(a[timestampField] || ''))
    .slice(0, limit);
};

function App() {
  const isMiniMode = IS_MINI_MODE;
  const [activePage, setActivePage] = useState('discover');
  const [querySong, setQuerySong] = useState('');
  const [queryArtist, setQueryArtist] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchRan, setSearchRan] = useState(false);
  const [searchResults, setSearchResults] = useState([]);

  const [resolvingTrack, setResolvingTrack] = useState(false);
  const [track, setTrack] = useState(null);
  const [playQueue, setPlayQueue] = useState([]);
  const [queueIndex, setQueueIndex] = useState(-1);

  const [historyItems, setHistoryItems] = useState(() => readStorage(HISTORY_STORAGE_KEY, []).map(toHistoryRecord));
  const [favorites, setFavorites] = useState(() => readStorage(FAVORITES_STORAGE_KEY, []).map(toFavoriteRecord));
  const [downloadHistory, setDownloadHistory] = useState(() => readStorage(DOWNLOAD_HISTORY_STORAGE_KEY, []).map(normalizeDownloadHistoryItem));
  const [downloadTasks, setDownloadTasks] = useState(() => readStorage(DOWNLOAD_CENTER_STORAGE_KEY, []).map((item) => {
    const task = normalizeDownloadTask(item);
    if (task.status === 'downloading' || task.status === 'resolving') {
      return {
        ...task,
        status: 'failed',
        error: '应用已重新打开，请重试下载',
      };
    }
    return task;
  }));

  const [vibeModeEnabled, setVibeModeEnabled] = useState(false);

  const [backendStatus, setBackendStatus] = useState('checking');
  const [systemCheck, setSystemCheck] = useState(null);
  const [notice, setNotice] = useState('');
  const [remotePlayerState, setRemotePlayerState] = useState(() => readObjectStorage(PLAYER_STATE_STORAGE_KEY, {
    track: null,
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    volume: 0.8,
    queueIndex: -1,
    queueLength: 0,
    canGoPrevious: false,
    canGoNext: false,
    vibeModeEnabled: false,
    updatedAt: 0,
  }));

  const audioRef = useRef(null);
  const syncChannelRef = useRef(null);
  const lastHandledActionIdRef = useRef('');
  const libraryMigrationRef = useRef(readBooleanStorage(LIBRARY_MIGRATION_KEY));
  const librarySyncInFlightRef = useRef(false);
  const downloadRunnerRef = useRef(false);
  const downloadAbortControllersRef = useRef(new Map());
  const [isPlaying, setIsPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [volume, setVolume] = useState(0.8);

  const queryText = useMemo(() => makeQuery(querySong, queryArtist), [querySong, queryArtist]);

  const apiRequest = async (path, options = {}) => {
    const { headers, ...rest } = options;
    const response = await fetch(apiUrl(path), {
      ...rest,
      headers: {
        ...(rest.body ? { 'Content-Type': 'application/json' } : {}),
        ...(headers || {}),
      },
    });

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(data?.detail || `request_failed_${response.status}`);
    }
    return data;
  };

  const postDesktopMessage = (message) => {
    if (!message) return;
    syncChannelRef.current?.postMessage(message);
  };

  const sendDesktopAction = (type, payload = {}) => {
    const action = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      type,
      payload,
      sentAt: Date.now(),
    };
    localStorage.setItem(DESKTOP_ACTION_STORAGE_KEY, JSON.stringify(action));
    postDesktopMessage({ type: 'action', payload: action });
  };

  const setNoticeText = (text) => {
    setNotice(text);
    setTimeout(() => setNotice(''), 3000);
  };

  const markLibraryMigrated = () => {
    libraryMigrationRef.current = true;
    localStorage.setItem(LIBRARY_MIGRATION_KEY, '1');
  };

  const refreshLibraryState = async ({ bootstrapLocal = false } = {}) => {
    if (librarySyncInFlightRef.current) return;
    librarySyncInFlightRef.current = true;

    const localFavorites = readStorage(FAVORITES_STORAGE_KEY, []).map(toFavoriteRecord);
    const localHistory = readStorage(HISTORY_STORAGE_KEY, []).map(toHistoryRecord);
    const localDownloads = readStorage(DOWNLOAD_HISTORY_STORAGE_KEY, []).map(normalizeDownloadHistoryItem);

    try {
      const data = await apiRequest('/library', { cache: 'no-store' });
      const remoteFavorites = Array.isArray(data?.favorites) ? data.favorites.map(toFavoriteRecord) : [];
      const remoteHistory = Array.isArray(data?.history) ? data.history.map(toHistoryRecord) : [];
      const remoteDownloads = Array.isArray(data?.recentDownloads) ? data.recentDownloads.map(normalizeDownloadHistoryItem) : [];

      if (bootstrapLocal && !libraryMigrationRef.current) {
        const mergedFavorites = mergeLibraryRecords(remoteFavorites, localFavorites, 100, 'savedAt');
        const mergedHistory = mergeLibraryRecords(remoteHistory, localHistory, 50, 'playedAt');
        const mergedDownloads = mergeDownloadHistory(remoteDownloads, localDownloads, 30);

        setFavorites(mergedFavorites);
        setHistoryItems(mergedHistory);
        setDownloadHistory(mergedDownloads);

        const remoteFavoriteKeys = new Set(remoteFavorites.map((item) => item.key));
        const remoteHistoryKeys = new Set(remoteHistory.map((item) => item.key));

        await Promise.all([
          ...localFavorites
            .filter((item) => item.key && !remoteFavoriteKeys.has(item.key))
            .map((item) => apiRequest('/library/favorites', {
              method: 'POST',
              body: JSON.stringify(item),
            }).catch(() => null)),
          ...localHistory
            .filter((item) => item.key && !remoteHistoryKeys.has(item.key))
            .map((item) => apiRequest('/library/history', {
              method: 'POST',
              body: JSON.stringify(item),
            }).catch(() => null)),
        ]);

        markLibraryMigrated();
        return;
      }

      setFavorites(remoteFavorites);
      setHistoryItems(remoteHistory);
      setDownloadHistory(mergeDownloadHistory(remoteDownloads, localDownloads, 30));

      if (!libraryMigrationRef.current) {
        markLibraryMigrated();
      }
    } catch {
      if (bootstrapLocal && !libraryMigrationRef.current) {
        setFavorites(localFavorites);
        setHistoryItems(localHistory);
        setDownloadHistory(localDownloads);
      }
    } finally {
      librarySyncInFlightRef.current = false;
    }
  };

  useEffect(() => {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(historyItems));
  }, [historyItems]);

  useEffect(() => {
    localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(favorites));
  }, [favorites]);

  useEffect(() => {
    localStorage.setItem(DOWNLOAD_HISTORY_STORAGE_KEY, JSON.stringify(downloadHistory));
  }, [downloadHistory]);

  useEffect(() => {
    localStorage.setItem(DOWNLOAD_CENTER_STORAGE_KEY, JSON.stringify(downloadTasks));
  }, [downloadTasks]);

  useEffect(() => {
    void refreshLibraryState({ bootstrapLocal: true });
  }, []);

  useEffect(() => {
    const syncFromServer = () => {
      if (document.visibilityState === 'hidden') return;
      void refreshLibraryState();
    };

    const handleFocus = () => {
      void refreshLibraryState();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void refreshLibraryState();
      }
    };

    const timer = window.setInterval(syncFromServer, LIBRARY_SYNC_INTERVAL_MS);
    window.addEventListener('focus', handleFocus);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', handleFocus);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  // --- Helpers (Defined before use in hooks/renders) ---
  const isFavoriteItem = (item) => {
    const key = trackKey(item.videoId, item.title, item.artist);
    return favorites.some((fav) => fav.key === key);
  };

  const toggleFavoriteItem = async (item) => {
    const nextItem = toFavoriteRecord(item);
    const exists = favorites.some((fav) => fav.key === nextItem.key);

    if (exists) {
      setFavorites((prev) => prev.filter((fav) => fav.key !== nextItem.key));
      setNoticeText('已从收藏中移除');
      try {
        await apiRequest(`/library/favorites?key=${encodeURIComponent(nextItem.key)}`, {
          method: 'DELETE',
        });
      } catch (err) {
        console.error(err);
      }
      return;
    }

    setFavorites((prev) => mergeLibraryRecords([nextItem], prev, 100, 'savedAt'));
    setNoticeText('已加入我的收藏');
    try {
      await apiRequest('/library/favorites', {
        method: 'POST',
        body: JSON.stringify(nextItem),
      });
    } catch (err) {
      console.error(err);
      setNoticeText('已本地收藏，但数据库同步失败');
    }
  };

  const updateDownloadTask = (taskId, updater) => {
    setDownloadTasks((prev) => prev.map((task) => {
      if (task.id !== taskId) return task;
      const patch = typeof updater === 'function' ? updater(task) : updater;
      return normalizeDownloadTask({ ...task, ...(patch || {}) });
    }));
  };

  const addCompletedDownloadHistory = (entry) => {
    setDownloadHistory((prev) => mergeDownloadHistory([normalizeDownloadHistoryItem(entry)], prev, 30));
  };

  const triggerBlobDownload = (blob, filename) => {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 15_000);
  };

  const resolveDownloadPlan = async (item) => {
    let downloadUrl = item.audioSrc;
    let audioExt = item.audioExt || 'm4a';
    if (!downloadUrl) {
      const query = item.query || makeQuery(item.title, item.artist);
      const data = await apiRequest('/visualize', {
        method: 'POST',
        body: JSON.stringify({ query, videoId: item.videoId || null }),
      });
      downloadUrl = data.audioSrc;
      audioExt = data.audioExt || audioExt;
    }

    if (!downloadUrl) throw new Error('未能解析到可下载音源');

    const resolvedUrl = resolveAudioUrl(downloadUrl);
    const parsedUrl = new URL(resolvedUrl);
    const rawUrl = parsedUrl.searchParams.get('url');
    if (!rawUrl) throw new Error('未能提取上游音频地址');

    const normalizedExt = String(audioExt || 'm4a').replace(/^\./, '') || 'm4a';
    const filename = `${item.title || '未命名曲目'} - ${item.artist || '未知歌手'}.${normalizedExt}`;
    const requestUrl = apiUrl(`/download?url=${encodeURIComponent(rawUrl)}&filename=${encodeURIComponent(filename)}`);

    return {
      requestUrl,
      filename,
      rawUrl,
      audioExt: normalizedExt,
    };
  };

  const processDownloadTask = async (task) => {
    const controller = new AbortController();
    downloadAbortControllersRef.current.set(task.id, controller);

    try {
      updateDownloadTask(task.id, {
        status: 'resolving',
        startedAt: new Date().toISOString(),
        error: '',
        progress: 0,
        bytesReceived: 0,
        totalBytes: 0,
      });

      const plan = await resolveDownloadPlan(task);
      updateDownloadTask(task.id, {
        status: 'downloading',
        filename: plan.filename,
        sourceUrl: plan.rawUrl,
        audioExt: plan.audioExt,
      });

      const response = await fetch(plan.requestUrl, {
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`下载请求失败 (${response.status})`);
      }

      const totalBytes = Number(response.headers.get('content-length') || 0);
      const contentType = response.headers.get('content-type') || 'application/octet-stream';
      const reader = response.body?.getReader();
      const chunks = [];
      let received = 0;

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (value) {
            chunks.push(value);
            received += value.length;
            updateDownloadTask(task.id, {
              status: 'downloading',
              bytesReceived: received,
              totalBytes,
              progress: totalBytes > 0 ? received / totalBytes : 0,
            });
          }
        }
      } else {
        const blob = await response.blob();
        received = blob.size;
        chunks.push(blob);
      }

      const blob = chunks[0] instanceof Blob
        ? chunks[0]
        : new Blob(chunks, { type: contentType });

      triggerBlobDownload(blob, plan.filename);
      const downloadedAt = new Date().toISOString();

      updateDownloadTask(task.id, {
        status: 'completed',
        progress: 1,
        bytesReceived: received || totalBytes,
        totalBytes: totalBytes || received,
        completedAt: downloadedAt,
        error: '',
        filename: plan.filename,
        sourceUrl: plan.rawUrl,
      });

      const historyEntry = {
        key: task.key || trackKey(task.videoId, task.title, task.artist),
        title: task.title || '',
        artist: task.artist || '',
        filename: plan.filename,
        sourceUrl: plan.rawUrl,
        downloadedAt,
      };
      addCompletedDownloadHistory(historyEntry);
      void apiRequest('/library/downloads', {
        method: 'POST',
        body: JSON.stringify(historyEntry),
      }).catch(() => {});

      setNoticeText(`已完成下载: ${task.title || '音频文件'}`);
    } catch (err) {
      if (err?.name === 'AbortError') {
        updateDownloadTask(task.id, {
          status: 'failed',
          error: '下载已取消',
        });
        setNoticeText('已取消当前下载');
      } else {
        console.error(err);
        updateDownloadTask(task.id, {
          status: 'failed',
          error: err instanceof Error ? err.message : '下载失败',
        });
        setNoticeText('下载失败，可在下载中心重试');
      }
    } finally {
      downloadAbortControllersRef.current.delete(task.id);
      downloadRunnerRef.current = false;
    }
  };

  const enqueueDownload = (item) => {
    if (!item) return;
    const task = normalizeDownloadTask({
      ...item,
      id: downloadTaskId(),
      status: 'queued',
      progress: 0,
      createdAt: new Date().toISOString(),
    });
    setDownloadTasks((prev) => [task, ...prev].slice(0, 40));
    setActivePage('downloads');
    setNoticeText('已加入下载队列');
  };

  const retryDownloadTask = (taskId) => {
    updateDownloadTask(taskId, {
      status: 'queued',
      progress: 0,
      bytesReceived: 0,
      totalBytes: 0,
      error: '',
      startedAt: null,
      completedAt: null,
    });
    setNoticeText('已重新加入下载队列');
  };

  const removeDownloadTask = (taskId) => {
    const controller = downloadAbortControllersRef.current.get(taskId);
    if (controller) {
      controller.abort();
    }
    setDownloadTasks((prev) => prev.filter((task) => task.id !== taskId));
  };

  const clearFinishedDownloads = () => {
    downloadTasks
      .filter((task) => task.status === 'completed' || task.status === 'failed')
      .forEach((task) => {
        const controller = downloadAbortControllersRef.current.get(task.id);
        if (controller) controller.abort();
      });
    setDownloadTasks((prev) => prev.filter((task) => task.status !== 'completed' && task.status !== 'failed'));
    setNoticeText('已清理已完成与失败任务');
  };

  const handleDownload = async (item) => {
    enqueueDownload(item);
  };


  useEffect(() => {
    if (!audioRef.current) return;
    audioRef.current.volume = volume;
  }, [volume]);

  const currentIsFavorite = useMemo(() => {
    if (!track) return false;
    return isFavoriteItem(track);
  }, [track, favorites]);

  const checkBackend = async () => {
    try {
      const healthRes = await fetch(apiUrl('/health'), { cache: 'no-store' });
      if (!healthRes.ok) throw new Error();
      const checkRes = await fetch(apiUrl('/system-check'), { cache: 'no-store' });
      const checkData = checkRes.ok ? await checkRes.json() : null;
      setBackendStatus('online');
      setSystemCheck(checkData);
    } catch {
      setBackendStatus('offline');
      setSystemCheck(null);
    }
  };

  useEffect(() => {
    checkBackend();
    const timer = setInterval(checkBackend, 15000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (downloadRunnerRef.current) return undefined;
    const activeTask = downloadTasks.find((task) => task.status === 'resolving' || task.status === 'downloading');
    if (activeTask) return undefined;
    const nextTask = downloadTasks.find((task) => task.status === 'queued');
    if (!nextTask) return undefined;

    downloadRunnerRef.current = true;
    void processDownloadTask(nextTask);
    return undefined;
  }, [downloadTasks]);

  useEffect(() => () => {
    downloadAbortControllersRef.current.forEach((controller) => controller.abort());
    downloadAbortControllersRef.current.clear();
  }, []);

  const runSearch = async (overrideQuery) => {
    const q = normalizeSearchQuery(typeof overrideQuery === 'string' ? overrideQuery : queryText);
    if (!q) return;
    if (typeof overrideQuery === 'string') {
      setQuerySong(q);
      setQueryArtist('');
    }
    setSearching(true);
    setSearchRan(true);

    if (searchCache.has(q)) {
      setSearchResults(searchCache.get(q));
      setActivePage('search');
      void apiRequest('/library/searches', {
        method: 'POST',
        body: JSON.stringify({ query: q, searchedAt: new Date().toISOString() }),
      }).catch(() => {});
      setSearching(false);
      return;
    }

    try {
      const data = await apiRequest('/search', {
        method: 'POST',
        body: JSON.stringify({ query: q, limit: 12 }),
      });
      const results = Array.isArray(data.results) ? data.results : [];
      setSearchResults(results);
      searchCache.set(q, results);
      setActivePage('search');
      void apiRequest('/library/searches', {
        method: 'POST',
        body: JSON.stringify({ query: q, searchedAt: new Date().toISOString() }),
      }).catch(() => {});
      if (results.length === 0) {
        setNoticeText('没有找到可用音源，试试加上歌手名');
      }
    } catch (err) {
      setSearchResults([]);
      const message = err instanceof Error ? err.message : '';
      if (message.includes('Failed to fetch')) {
        setNoticeText('搜索服务不可用，请检查网络或后端状态');
      } else {
        setNoticeText('搜索暂时失败，请稍后再试');
      }
    } finally {
      setSearching(false);
    }
  };

  const resolveAndPlay = async (candidate, options = {}) => {
    const { queue = null, index = -1 } = options;
    const query = candidate.query || makeQuery(candidate.title, candidate.artist);

    setResolvingTrack(true);
    try {
      const data = await apiRequest('/visualize', {
        method: 'POST',
        body: JSON.stringify({ query, videoId: candidate.videoId || null }),
      });
      const resolved = {
        key: trackKey(data.videoId || candidate.videoId, data.title || candidate.title, data.artist || candidate.artist),
        title: data.title || candidate.title,
        artist: data.artist || candidate.artist,
        cover: data.cover || candidate.cover,
        theme: data.theme || 'Vibe Resonating',
        colors: data.colors || ['#22d3ee', '#000000'],
        audioSrc: resolveAudioUrl(data.audioSrc),
        audioExt: data.audioExt || candidate.audioExt || null,
        videoId: data.videoId || candidate.videoId || null,
        query: data.query || query,
      };

      setTrack(resolved);
      setCurrentTime(0);
      setDuration(0);
      setIsPlaying(false);

      if (queue) {
        setPlayQueue(queue);
        setQueueIndex(index);
      }

      const historyEntry = toHistoryRecord({
        key: resolved.key,
        title: resolved.title,
        artist: resolved.artist,
        cover: resolved.cover,
        query: resolved.query,
        videoId: resolved.videoId,
        playedAt: new Date().toISOString(),
      });
      setHistoryItems((prev) => mergeLibraryRecords([historyEntry], prev, 50, 'playedAt'));
      void apiRequest('/library/history', {
        method: 'POST',
        body: JSON.stringify(historyEntry),
      }).catch(() => {});

      // Auto play
      setTimeout(() => {
        if (audioRef.current) {
          audioRef.current.play();
          setIsPlaying(true);
        }
      }, 300);

    } catch {
      setNoticeText('加载音频失败，请重试');
    } finally {
      setResolvingTrack(false);
    }
  };

  const handleTogglePlay = () => {
    if (!audioRef.current || !track) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play().then(() => setIsPlaying(true)).catch(() => setNoticeText('请点击播放按钮'));
    }
  };

  const jumpQueue = (nextIndex) => {
    if (nextIndex < 0 || nextIndex >= playQueue.length) return;
    resolveAndPlay(playQueue[nextIndex], { queue: playQueue, index: nextIndex });
  };

  const onLoadedMetadata = () => setDuration(audioRef.current?.duration || 0);
  const onTimeUpdate = () => setCurrentTime(audioRef.current?.currentTime || 0);
  const seekTo = (nextTime) => {
    if (audioRef.current) audioRef.current.currentTime = nextTime;
  };

  const performDesktopAction = (action) => {
    const type = action?.type;
    if (!type || isMiniMode) return;

    if (type === 'toggle-play') {
      handleTogglePlay();
      return;
    }
    if (type === 'next') {
      jumpQueue(queueIndex + 1);
      return;
    }
    if (type === 'previous') {
      jumpQueue(queueIndex - 1);
      return;
    }
    if (type === 'toggle-vibe') {
      setVibeModeEnabled((prev) => !prev);
      return;
    }
    if (type === 'volume-up') {
      setVolume((prev) => Math.min(1, Number((prev + 0.05).toFixed(2))));
      return;
    }
    if (type === 'volume-down') {
      setVolume((prev) => Math.max(0, Number((prev - 0.05).toFixed(2))));
      return;
    }
    if (type === 'seek' && Number.isFinite(action?.payload?.seconds)) {
      seekTo(action.payload.seconds);
    }
  };

  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return undefined;
    const channel = new BroadcastChannel(DESKTOP_SYNC_CHANNEL);
    syncChannelRef.current = channel;

    channel.onmessage = (event) => {
      const message = event.data;
      if (!message) return;

      if (message.type === 'player-state' && isMiniMode) {
        setRemotePlayerState(message.payload || {});
        return;
      }

      if (message.type === 'action') {
        const action = message.payload;
        if (!action?.id || lastHandledActionIdRef.current === action.id) return;
        lastHandledActionIdRef.current = action.id;
        performDesktopAction(action);
      }
    };

    return () => {
      channel.close();
      if (syncChannelRef.current === channel) syncChannelRef.current = null;
    };
  }, [isMiniMode, queueIndex, playQueue.length, track, isPlaying]);

  useEffect(() => {
    const handleStorage = (event) => {
      if (event.key === PLAYER_STATE_STORAGE_KEY && isMiniMode) {
        setRemotePlayerState(readObjectStorage(PLAYER_STATE_STORAGE_KEY, remotePlayerState));
        return;
      }

      if (event.key === DESKTOP_ACTION_STORAGE_KEY && event.newValue) {
        try {
          const action = JSON.parse(event.newValue);
          if (!action?.id || lastHandledActionIdRef.current === action.id) return;
          lastHandledActionIdRef.current = action.id;
          performDesktopAction(action);
        } catch {
          // ignore malformed storage payloads
        }
      }
    };

    const handleShellAction = (event) => {
      performDesktopAction(event.detail || {});
    };

    window.addEventListener('storage', handleStorage);
    window.addEventListener('nas-desktop-shell-action', handleShellAction);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener('nas-desktop-shell-action', handleShellAction);
    };
  }, [isMiniMode, remotePlayerState, queueIndex, playQueue.length, track, isPlaying]);

  useEffect(() => {
    if (isMiniMode) return undefined;

    const payload = {
      track,
      isPlaying,
      currentTime: Number(currentTime.toFixed(2)),
      duration: Number(duration.toFixed(2)),
      volume,
      queueIndex,
      queueLength: playQueue.length,
      canGoPrevious: queueIndex > 0,
      canGoNext: queueIndex >= 0 && queueIndex < playQueue.length - 1,
      vibeModeEnabled,
      updatedAt: Date.now(),
    };

    localStorage.setItem(PLAYER_STATE_STORAGE_KEY, JSON.stringify(payload));
    postDesktopMessage({ type: 'player-state', payload });
    return undefined;
  }, [isMiniMode, track, isPlaying, currentTime, duration, volume, queueIndex, playQueue.length, vibeModeEnabled]);

  const renderCard = (song, artist, cover, onClick, isPlayable = true) => {
    let displayCover = cover;
    if (!displayCover) {
      if (song) {
        displayCover = `https://ui-avatars.com/api/?name=${encodeURIComponent(song)}&background=random&color=fff&size=512&font-size=0.33`;
      } else {
        displayCover = 'https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=400';
      }
    }

    return (
      <div className="music-card animate-slide-up group" onClick={onClick}>
        <div className="card-image-wrap">
          <img src={displayCover} className="card-image" alt="" />
          {isPlayable && (
            <div className="play-hover-btn">
              <Play fill="currentColor" size={16} className="ml-0.5" />
            </div>
          )}
        </div>
        <div className="card-title">{song}</div>
        <div className="card-subtitle">{artist}</div>
        <div className="absolute bottom-12 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity z-10">
          <button
            onClick={(e) => { e.stopPropagation(); toggleFavoriteItem({ title: song, artist, cover: displayCover }); }}
            className={`p-1.5 rounded-full bg-black/40 backdrop-blur-md hover:bg-black/60 transition-colors ${isFavoriteItem({ title: song, artist }) ? 'text-[var(--accent)]' : 'text-white/70'}`}
          >
            <Heart size={14} fill={isFavoriteItem({ title: song, artist }) ? 'currentColor' : 'none'} />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); handleDownload({ title: song, artist }); }}
            className="p-1.5 rounded-full bg-black/40 backdrop-blur-md text-white/70 hover:text-white hover:bg-black/60 transition-colors"
          >
            <Download size={14} />
          </button>
        </div>
      </div>
    );
  };

  const miniTrack = remotePlayerState?.track || null;
  const miniCurrentTime = Number(remotePlayerState?.currentTime || 0);
  const miniDuration = Number(remotePlayerState?.duration || 0);
  const miniProgress = miniDuration > 0 ? Math.min(100, (miniCurrentTime / miniDuration) * 100) : 0;
  const activeDownloadTask = downloadTasks.find((taskItem) => taskItem.status === 'resolving' || taskItem.status === 'downloading') || null;
  const queuedDownloadCount = downloadTasks.filter((taskItem) => taskItem.status === 'queued').length;
  const failedDownloadCount = downloadTasks.filter((taskItem) => taskItem.status === 'failed').length;
  const completedDownloadCount = downloadTasks.filter((taskItem) => taskItem.status === 'completed').length;

  if (isMiniMode) {
    return (
      <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(73,220,177,0.28),_transparent_55%),linear-gradient(135deg,_#08111d,_#02060c)] text-white">
        <div className="h-screen flex flex-col justify-between p-4">
          <div className="flex items-center gap-3">
            {miniTrack?.cover ? (
              <img src={miniTrack.cover} alt="" className="w-16 h-16 rounded-2xl object-cover shadow-2xl border border-white/10" />
            ) : (
              <div className="w-16 h-16 rounded-2xl bg-white/10 border border-white/10 flex items-center justify-center">
                <Disc3 size={22} className="text-white/50" />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/35 mb-1">{BRAND.name} Mini Player</div>
              <div className="text-sm font-semibold truncate">{miniTrack?.title || '等待主窗口播放'}</div>
              <div className="text-xs text-white/50 truncate">{miniTrack?.artist || '打开主窗口并开始播放'}</div>
            </div>
          </div>

          <div className="mt-4">
            <div className="flex items-center justify-between text-[11px] text-white/45 mb-2">
              <span>{formatTime(miniCurrentTime)}</span>
              <span>{formatTime(miniDuration)}</span>
            </div>
            <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
              <div className="h-full bg-[var(--accent)] rounded-full transition-all" style={{ width: `${miniProgress}%` }} />
            </div>
          </div>

          <div className="mt-5 flex items-center justify-between gap-3">
            <button
              className="w-12 h-12 rounded-2xl bg-white/8 border border-white/10 flex items-center justify-center disabled:opacity-30"
              onClick={() => sendDesktopAction('previous')}
              disabled={!remotePlayerState?.canGoPrevious}
            >
              <SkipBack size={20} fill="currentColor" />
            </button>
            <button
              className="flex-1 h-14 rounded-2xl bg-white text-slate-900 font-semibold flex items-center justify-center gap-2 shadow-xl disabled:opacity-60"
              onClick={() => sendDesktopAction('toggle-play')}
              disabled={!miniTrack}
            >
              {remotePlayerState?.isPlaying ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
              <span>{remotePlayerState?.isPlaying ? '暂停' : '播放'}</span>
            </button>
            <button
              className="w-12 h-12 rounded-2xl bg-white/8 border border-white/10 flex items-center justify-center disabled:opacity-30"
              onClick={() => sendDesktopAction('next')}
              disabled={!remotePlayerState?.canGoNext}
            >
              <SkipForward size={20} fill="currentColor" />
            </button>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2">
            <button className="rounded-xl bg-white/6 border border-white/10 py-2 text-xs text-white/75" onClick={() => sendDesktopAction('volume-down')}>
              音量 -
            </button>
            <button className="rounded-xl bg-white/6 border border-white/10 py-2 text-xs text-white/75" onClick={() => sendDesktopAction('toggle-vibe')} disabled={!miniTrack}>
              Vibe
            </button>
            <button className="rounded-xl bg-white/6 border border-white/10 py-2 text-xs text-white/75" onClick={() => sendDesktopAction('volume-up')}>
              音量 +
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <div className="vibe-bg">
        <div className="orb orb-1" />
        <div className="orb-2 orb" />
      </div>
      <div className="grain" />

      {/* Notice Overlay */}
      {notice && (
        <div className="fixed top-8 left-1/2 -translate-x-1/2 z-[100] bg-slate-800 text-white px-6 py-3 rounded-full font-bold shadow-2xl border border-white/10 animate-slide-up flex items-center gap-2">
          <Sparkles size={18} className="text-cyan-400" /> {notice}
        </div>
      )}

      {/* Loading Overlay */}
      {resolvingTrack && (
        <div className="fixed inset-0 z-[90] bg-black/80 backdrop-blur-xl flex flex-col items-center justify-center gap-4">
          <LoaderCircle size={48} className="text-slate-300 animate-spin" />
          <p className="font-bold text-lg tracking-widest text-slate-300 animate-pulse">{BRAND.name} 正在解析音频...</p>
        </div>
      )}

      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">
            <Disc3 size={18} />
          </div>
          <div className="min-w-0">
            <div className="brand-name">{BRAND.name}</div>
            <div className="brand-tag">{BRAND.tagline}</div>
          </div>
        </div>

        <div className="px-2 mb-4 relative">
          <Search size={14} className="absolute left-5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] font-bold pointer-events-none" />
          <input
            className="w-full bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.05)] focus:border-[var(--border)] rounded-md text-xs py-1.5 pl-9 pr-3 outline-none transition-all text-white placeholder-[var(--text-muted)] shadow-inner"
            placeholder="搜索"
            value={querySong}
            onChange={e => setQuerySong(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') runSearch();
            }}
          />
        </div>

        <nav className="nav-group mb-4">
          <span className="nav-label">{BRAND.name}</span>
          {NAV_ITEMS.map(item => (
            <button
              key={item.id}
              className={`nav-btn ${activePage === item.id ? 'active' : ''}`}
              onClick={() => setActivePage(item.id)}
            >
              <item.icon size={16} className={activePage === item.id ? 'text-[var(--accent)]' : 'text-[var(--accent)]'} />
              <span className="text-sm">{item.label}</span>
            </button>
          ))}
        </nav>

        <nav className="nav-group mb-4">
          <span className="nav-label">资料库</span>
          {LIBRARY_ITEMS.map(item => (
            <button
              key={item.id}
              className={`nav-btn ${activePage === item.id ? 'active' : ''}`}
              onClick={() => setActivePage(item.id)}
            >
              <item.icon size={16} className="text-[var(--accent)]" />
              <span className="text-sm">{item.label}</span>
            </button>
          ))}
        </nav>

        <nav className="nav-group">
          <span className="nav-label">播放列表</span>
          {PLAYLIST_ITEMS.map(item => (
            <button
              key={item.id}
              className={`nav-btn ${activePage === item.id ? 'active' : ''}`}
              onClick={() => setActivePage(item.id)}
            >
              <item.icon size={16} className="text-slate-400" />
              <span className="text-sm">{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="mt-auto px-4 py-4 bg-[rgba(0,0,0,0.1)] rounded-xl border border-[rgba(255,255,255,0.02)] relative overflow-hidden group">
          <div className="absolute inset-0 bg-white/5 opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
          <div className="flex items-center gap-3 mb-3 relative z-10">
            <div className={`w-2 h-2 rounded-full ${backendStatus === 'online' ? 'bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.8)] animate-pulse' : 'bg-slate-600'}`} />
            <span className="text-xs font-bold uppercase tracking-widest text-slate-200">
              {backendStatus === 'online' ? `${BRAND.name} Core Online` : `${BRAND.name} Core Offline`}
            </span>
          </div>
          <p className="text-[10px] text-slate-500 relative z-10 font-medium tracking-wide">{BRAND.name} Engine v3.1<br />Local Resonance UI</p>
        </div>
      </aside>

      <main className="content-area">
        <div className="page-wrapper">
          {activePage === 'discover' && (
            <div className="animate-slide-up">
              <h1 className="text-3xl font-bold text-white mb-6 tracking-tight">现在就听</h1>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
                {[
                  { subtitle: '主打推荐', title: '今日热门精选', desc: '发现属于你的新节奏', img: 'https://images.unsplash.com/photo-1514525253361-bee8a197c0c5?w=600' },
                  { subtitle: '新发布', title: '本周新歌', desc: '不容错过的全球首发', img: 'https://images.unsplash.com/photo-1614613535308-eb5fbd3d2c17?w=600' },
                  { subtitle: '沉浸氛围', title: '深夜电子乐', desc: '感受强劲的低音频率', img: 'https://images.unsplash.com/photo-1557683316-973673baf926?w=600' },
                ].map((banner, i) => (
                  <div key={i} className="relative rounded-xl overflow-hidden aspect-[4/3] cursor-pointer group hover:opacity-90 transition-opacity" onClick={() => setActivePage('search')}>
                    <img src={banner.img} alt={banner.title} className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105" />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
                    <div className="absolute bottom-0 left-0 p-5 w-full">
                      <p className="text-[10px] font-bold text-white/70 uppercase tracking-wider mb-1">{banner.subtitle}</p>
                      <h3 className="text-xl font-bold text-white mb-1 leading-tight">{banner.title}</h3>
                      <p className="text-sm text-white/50">{banner.desc}</p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex justify-between items-end mb-4 border-b border-white/5 pb-2">
                <h2 className="text-xl font-bold text-white tracking-tight">最近播放的推荐</h2>
                <button className="text-xs font-semibold text-[var(--accent)] hover:opacity-80">查看全部 <ChevronRight size={12} className="inline -mt-0.5" /></button>
              </div>
              <div className="card-grid">
                {QUICK_PRESETS.map((item, idx) => renderCard(
                  item.song,
                  item.artist,
                  item.cover,
                  () => resolveAndPlay({ title: item.song, artist: item.artist })
                ))}
              </div>
            </div>
          )}

          {activePage === 'search' && (
            <div>
              <h2 className="section-title">
                {searching ? '正在搜寻宇宙中的频率...' : (searchResults.length > 0 ? `找到 ${searchResults.length} 个匹配项` : '准备好开始你的搜索')}
              </h2>
              {searchResults.length > 0 ? (
                <div className="card-grid">
                  {searchResults.map((item, idx) => renderCard(
                    item.title,
                    item.artist,
                    item.cover,
                    () => resolveAndPlay(item, { queue: searchResults, index: idx })
                  ))}
                </div>
              ) : (
                !searching && (
                  <div className="empty-placeholder">
                    <Search size={64} className="opacity-20" />
                    <p>{searchRan ? '没有找到可用音源，试试输入“歌名 + 歌手名”' : '输入关键词，寻找你心底的声音'}</p>
                  </div>
                )
              )}
            </div>
          )}

          {activePage === 'favorites' && (
            <div>
              <h2 className="section-title">我的收藏</h2>
              {favorites.length > 0 ? (
                <div className="card-grid">
                  {favorites.map(item => renderCard(
                    item.title,
                    item.artist,
                    item.cover,
                    () => resolveAndPlay(item)
                  ))}
                </div>
              ) : (
                <div className="empty-placeholder">
                  <Heart size={64} className="opacity-20" />
                  <p>收藏的歌曲将出现在这里</p>
                </div>
              )}
            </div>
          )}

          {activePage === 'history' && (
            <div>
              <h2 className="section-title">播放记录</h2>
              {historyItems.length > 0 ? (
                <div className="card-grid">
                  {historyItems.map((item, idx) => renderCard(
                    item.title,
                    item.artist,
                    item.cover,
                    () => resolveAndPlay(item),
                    true
                  ))}
                </div>
              ) : (
                <div className="empty-placeholder">
                  <History size={64} className="opacity-20" />
                  <p>你的音乐旅程从这里开始</p>
                </div>
              )}
            </div>
          )}

          {activePage === 'downloads' && (
            <div className="animate-slide-up">
              <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between mb-6">
                <div>
                  <h2 className="section-title mb-2 border-b-0 pb-0">下载中心</h2>
                  <p className="text-sm text-white/45">单任务顺序下载，支持进度跟踪、失败重试和最近下载记录。</p>
                </div>
                <div className="flex flex-wrap gap-3">
                  <button
                    className="px-4 py-2 rounded-xl bg-white/6 border border-white/10 text-sm text-white/70 hover:bg-white/10 transition-colors"
                    onClick={() => void refreshLibraryState()}
                  >
                    刷新记录
                  </button>
                  <button
                    className="px-4 py-2 rounded-xl bg-white/6 border border-white/10 text-sm text-white/70 hover:bg-white/10 transition-colors disabled:opacity-40"
                    onClick={clearFinishedDownloads}
                    disabled={completedDownloadCount === 0 && failedDownloadCount === 0}
                  >
                    清理已结束任务
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                {[
                  { label: '进行中', value: activeDownloadTask ? '1' : '0', accent: 'text-cyan-400' },
                  { label: '等待中', value: String(queuedDownloadCount), accent: 'text-amber-300' },
                  { label: '已完成', value: String(completedDownloadCount), accent: 'text-emerald-400' },
                  { label: '失败', value: String(failedDownloadCount), accent: 'text-rose-400' },
                ].map((stat) => (
                  <div key={stat.label} className="rounded-2xl border border-white/10 bg-white/5 px-5 py-4">
                    <div className="text-xs uppercase tracking-[0.24em] text-white/35 mb-2">{stat.label}</div>
                    <div className={`text-3xl font-black ${stat.accent}`}>{stat.value}</div>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-6">
                <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2 text-white/85">
                      <Download size={18} className="text-cyan-400" />
                      <span className="font-semibold">下载任务</span>
                    </div>
                    {activeDownloadTask && (
                      <span className="text-xs px-3 py-1 rounded-full bg-cyan-500/10 text-cyan-300">
                        {activeDownloadTask.status === 'resolving' ? '解析中' : '下载中'}
                      </span>
                    )}
                  </div>

                  {downloadTasks.length > 0 ? (
                    <div className="space-y-4">
                      {downloadTasks.map((taskItem) => {
                        const progressPercent = Math.max(0, Math.min(100, Math.round((taskItem.progress || 0) * 100)));
                        const isRunning = taskItem.status === 'resolving' || taskItem.status === 'downloading';
                        const isFinished = taskItem.status === 'completed';
                        const isFailed = taskItem.status === 'failed';

                        return (
                          <div key={taskItem.id} className="rounded-2xl border border-white/8 bg-black/20 p-4">
                            <div className="flex items-start justify-between gap-4">
                              <div className="min-w-0">
                                <div className="font-semibold text-white truncate">{taskItem.title || '未命名曲目'}</div>
                                <div className="text-sm text-white/45 truncate">{taskItem.artist || '未知歌手'}</div>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                {isRunning && <LoaderCircle size={16} className="text-cyan-400 animate-spin" />}
                                {isFinished && <CheckCircle2 size={16} className="text-emerald-400" />}
                                {isFailed && <AlertTriangle size={16} className="text-rose-400" />}
                                {taskItem.status === 'queued' && <Clock3 size={16} className="text-amber-300" />}
                              </div>
                            </div>

                            <div className="mt-3">
                              <div className="h-2 rounded-full bg-white/8 overflow-hidden">
                                <div
                                  className={`h-full rounded-full transition-all ${isFinished ? 'bg-emerald-400' : isFailed ? 'bg-rose-400' : 'bg-[var(--accent)]'}`}
                                  style={{ width: `${isFailed ? 100 : progressPercent}%` }}
                                />
                              </div>
                              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-white/45">
                                <span>
                                  {taskItem.status === 'queued' && '等待下载'}
                                  {taskItem.status === 'resolving' && '正在解析音源'}
                                  {taskItem.status === 'downloading' && `${progressPercent}% · ${formatBytes(taskItem.bytesReceived)} / ${taskItem.totalBytes > 0 ? formatBytes(taskItem.totalBytes) : '未知大小'}`}
                                  {taskItem.status === 'completed' && `已完成 · ${formatRelativeTime(taskItem.completedAt)}`}
                                  {taskItem.status === 'failed' && (taskItem.error || '下载失败')}
                                </span>
                                <span>{taskItem.filename || '等待生成文件名'}</span>
                              </div>
                            </div>

                            <div className="mt-4 flex flex-wrap gap-2">
                              {isFailed && (
                                <button
                                  className="px-3 py-1.5 rounded-lg bg-white/8 border border-white/10 text-sm text-white/75 hover:bg-white/12 transition-colors"
                                  onClick={() => retryDownloadTask(taskItem.id)}
                                >
                                  <span className="inline-flex items-center gap-2"><RefreshCw size={14} /> 重试</span>
                                </button>
                              )}
                              {taskItem.sourceUrl && (
                                <button
                                  className="px-3 py-1.5 rounded-lg bg-white/8 border border-white/10 text-sm text-white/75 hover:bg-white/12 transition-colors"
                                  onClick={() => window.open(taskItem.sourceUrl, '_blank', 'noopener,noreferrer')}
                                >
                                  <span className="inline-flex items-center gap-2"><ExternalLink size={14} /> 源地址</span>
                                </button>
                              )}
                              <button
                                className="px-3 py-1.5 rounded-lg bg-white/8 border border-white/10 text-sm text-white/75 hover:bg-white/12 transition-colors"
                                onClick={() => removeDownloadTask(taskItem.id)}
                              >
                                <span className="inline-flex items-center gap-2"><Trash2 size={14} /> 移除</span>
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="py-20 text-center text-white/45">
                      <FolderDown size={56} className="mx-auto mb-4 opacity-30" />
                      <p>还没有下载任务，试试从搜索结果或播放器里下载一首歌。</p>
                    </div>
                  )}
                </div>

                <div className="rounded-3xl border border-white/10 bg-white/5 p-6">
                  <div className="flex items-center gap-2 text-white/85 mb-4">
                    <CheckCircle2 size={18} className="text-emerald-400" />
                    <span className="font-semibold">最近下载</span>
                  </div>

                  {downloadHistory.length > 0 ? (
                    <div className="space-y-3">
                      {downloadHistory.map((entry, index) => (
                        <div key={`${entry.filename}-${entry.downloadedAt}-${index}`} className="rounded-2xl border border-white/8 bg-black/20 px-4 py-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="font-medium text-white truncate">{entry.title || entry.filename}</div>
                              <div className="text-sm text-white/45 truncate">{entry.artist || '未知歌手'}</div>
                            </div>
                            <span className="text-xs text-white/35 shrink-0">{formatRelativeTime(entry.downloadedAt)}</span>
                          </div>
                          <div className="mt-2 text-xs text-white/35 truncate">{entry.filename || '未记录文件名'}</div>
                          {entry.sourceUrl && (
                            <button
                              className="mt-3 text-xs text-cyan-300 hover:text-cyan-200 transition-colors inline-flex items-center gap-1"
                              onClick={() => window.open(entry.sourceUrl, '_blank', 'noopener,noreferrer')}
                            >
                              查看源地址 <ChevronRight size={14} />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="py-20 text-center text-white/45">
                      <Download size={52} className="mx-auto mb-4 opacity-30" />
                      <p>完成下载后，记录会显示在这里。</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {activePage === 'system' && (
            <div className="max-w-3xl">
              <h2 className="section-title">系统状态</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[
                  { label: '后端核心', status: backendStatus === 'online', val: backendStatus },
                  { label: '应用版本', status: true, val: systemCheck?.appVersion || '1.2.0' },
                  { label: '运行模式', status: true, val: systemCheck?.runtimeMode === 'packaged' ? '桌面安装版' : '源码模式' },
                  { label: 'ffmpeg', status: !!systemCheck?.ffmpegAvailable, val: systemCheck?.ffmpegAvailable ? '已启用' : '未检测到' },
                  { label: '本地数据库', status: !!systemCheck?.libraryDbAvailable, val: systemCheck?.libraryDbAvailable ? 'SQLite 已连接' : '未初始化' },
                  { label: '前端构建', status: !!systemCheck?.frontendBuilt, val: systemCheck?.frontendBuilt ? '生产模式' : '开发模式' },
                  { label: 'Python', status: true, val: systemCheck?.pythonVersion },
                  { label: 'yt-dlp', status: true, val: systemCheck?.ytDlpVersion },
                  { label: '收藏 / 历史', status: true, val: `${systemCheck?.libraryStats?.favorites ?? favorites.length} / ${systemCheck?.libraryStats?.history ?? historyItems.length}` },
                  { label: '下载记录', status: true, val: `${systemCheck?.libraryStats?.downloads ?? downloadHistory.length} 条` },
                  { label: '歌词偏移', status: true, val: `${systemCheck?.libraryStats?.lyricsOffsets ?? 0} 条` },
                ].map((stat, i) => (
                  <div key={i} className="bg-white/5 border border-white/10 p-4 rounded-xl flex justify-between items-center">
                    <span className="text-sm font-medium text-slate-400">{stat.label}</span>
                    <span className={`text-xs font-bold px-3 py-1 rounded-full ${stat.status ? 'bg-cyan-500/10 text-cyan-400' : 'bg-slate-500/10 text-slate-400'}`}>
                      {stat.val}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-8 p-6 bg-white/5 border border-white/10 rounded-2xl">
                <h4 className="flex items-center gap-2 mb-2 text-slate-200"><Info size={18} /> 关于项目</h4>
                <p className="text-sm text-slate-400 leading-relaxed">
                  NAS Local 是一个面向个人桌面的本地音乐终端，整合了 yt-dlp、FastAPI 与沉浸式歌词视图。
                  现在的界面与品牌元素已经统一为 NAS，更适合继续向个人音乐工作台方向扩展。
                </p>
              </div>
            </div>
          )}

          {activePage === 'browse' && (
            <div className="animate-slide-up">
              <h1 className="text-3xl font-bold text-white mb-6 tracking-tight">按类别浏览</h1>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {BROWSE_CATEGORIES.map(cat => (
                  <div key={cat.id} className={`h-32 rounded-xl bg-gradient-to-br border border-white/5 ${cat.color} p-4 flex items-end cursor-pointer hover:scale-[1.02] transition-transform`} onClick={() => runSearch(cat.title)}>
                    <h3 className="text-xl font-bold text-white drop-shadow-md">{cat.title}</h3>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activePage === 'radio' && (
            <div className="animate-slide-up">
              <h1 className="text-3xl font-bold text-white mb-6 tracking-tight">广播</h1>
              <div className="flex flex-col gap-8">
                {RADIO_STATIONS.map((station, i) => (
                  <div key={station.id} className="relative rounded-2xl overflow-hidden h-64 md:h-80 cursor-pointer group hover:opacity-90 transition-opacity" onClick={() => resolveAndPlay({ title: station.title, artist: 'NAS Radio', cover: station.img, query: station.title + ' live mix' })}>
                    <img src={station.img} alt={station.title} className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105" />
                    <div className="absolute inset-0 bg-gradient-to-r from-black/80 via-black/40 to-transparent" />
                    <div className="absolute top-0 left-0 p-8 h-full flex flex-col justify-center">
                      <p className="text-xs font-bold text-white/70 uppercase tracking-widest mb-3 border border-white/20 inline-block px-3 py-1 rounded-full backdrop-blur-md">LIVE 广播</p>
                      <h3 className="text-4xl md:text-5xl font-bold text-white mb-3 leading-tight drop-shadow-lg">{station.title}</h3>
                      <p className="text-lg text-white/60 font-medium">{station.subtitle}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activePage === 'artists' && (
            <div className="animate-slide-up">
              <h1 className="text-3xl font-bold text-white mb-6 tracking-tight">音乐人</h1>
              {(() => {
                const uniqueArtists = Array.from(new Set([...favorites, ...historyItems].map(item => item.artist))).filter(Boolean);
                if (uniqueArtists.length === 0) return <div className="text-white/50 text-center py-20">暂无收藏的音乐人</div>;
                return (
                  <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-8">
                    {uniqueArtists.map((artist, idx) => (
                      <div key={idx} className="flex flex-col items-center cursor-pointer group" onClick={() => runSearch(artist)}>
                        <div className="w-32 h-32 rounded-full bg-white/10 shadow-lg border border-white/5 mb-4 overflow-hidden group-hover:scale-105 transition-transform relative">
                          <img src={`https://ui-avatars.com/api/?name=${encodeURIComponent(artist)}&background=random&size=256&font-size=0.33`} alt={artist} className="w-full h-full object-cover mix-blend-overlay opacity-60" />
                          <div className="absolute inset-0 flex items-center justify-center text-4xl font-black text-white/50 bg-gradient-to-br from-white/10 to-transparent">
                            {artist.charAt(0).toUpperCase()}
                          </div>
                        </div>
                        <span className="text-sm font-semibold text-center w-full truncate">{artist}</span>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>
          )}

          {activePage === 'songs' && (
            <div className="animate-slide-up">
              <h1 className="text-3xl font-bold text-white mb-6 tracking-tight">歌曲</h1>
              {(() => {
                const map = new Map();
                [...favorites, ...historyItems].forEach(item => { if (!map.has(item.key)) map.set(item.key, item); });
                const allSongs = Array.from(map.values());
                if (allSongs.length === 0) return <div className="text-white/50 text-center py-20">资料库暂无歌曲</div>;
                return (
                  <div className="w-full flex flex-col">
                    <div className="grid grid-cols-[auto_1fr_1fr_auto] gap-4 px-4 py-2 text-xs font-semibold text-white/40 uppercase tracking-wider border-b border-white/5 mb-2">
                      <span className="w-8"></span>
                      <span>歌曲</span>
                      <span>音乐人</span>
                      <span className="w-16 text-right">时长</span>
                    </div>
                    {allSongs.map((song, idx) => (
                      <div key={song.key} className="grid grid-cols-[auto_1fr_1fr_auto] gap-4 px-4 py-3 items-center hover:bg-white/5 rounded-lg cursor-pointer group transition-colors" onClick={() => resolveAndPlay(song)}>
                        <div className="w-8 relative flex justify-center items-center">
                          <img src={song.cover} className="w-8 h-8 rounded shrink-0 opacity-100 group-hover:opacity-40 transition-opacity" />
                          <Play size={14} className="absolute text-white opacity-0 group-hover:opacity-100 drop-shadow-md" fill="currentColor" />
                        </div>
                        <span className="text-sm font-semibold truncate group-hover:text-white transition-colors">{song.title}</span>
                        <span className="text-sm text-white/50 truncate group-hover:text-white/80 transition-colors">{song.artist}</span>
                        <span className="w-16 text-right text-xs text-white/40 group-hover:text-white/60">--:--</span>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      </main>

      <footer className="player-bar">
        <div className="current-track-info">
          {track ? (
            <>
              <img src={track.cover} className="track-img" alt="" />
              <div className="track-details">
                <div className="track-name">{track.title}</div>
                <div className="track-artist">{track.artist}</div>
              </div>
              <button
                onClick={() => toggleFavoriteItem(track)}
                className={`ml-2 transition-colors ${currentIsFavorite ? 'text-white drop-shadow-[0_0_8px_rgba(255,255,255,0.5)]' : 'text-slate-500 hover:text-white'}`}
              >
                <Heart size={18} fill={currentIsFavorite ? "currentColor" : "none"} />
              </button>
            </>
          ) : (
            <div className="flex items-center gap-3 opacity-30">
              <div className="w-12 h-12 bg-white/10 rounded-lg" />
              <div className="flex flex-col gap-2">
                <div className="w-24 h-3 bg-white/10 rounded" />
                <div className="w-16 h-2 bg-white/10 rounded" />
              </div>
            </div>
          )}
        </div>

        <div className="main-controls">
          <div className="control-buttons">
            <button className="control-btn" onClick={() => jumpQueue(queueIndex - 1)} disabled={queueIndex <= 0}>
              <SkipBack size={20} fill="currentColor" />
            </button>
            <button className="play-pause-btn" onClick={handleTogglePlay}>
              {isPlaying ? <Pause size={24} fill="currentColor" /> : <Play size={24} className="ml-1" fill="currentColor" />}
            </button>
            <button className="control-btn" onClick={() => jumpQueue(queueIndex + 1)} disabled={queueIndex < 0 || queueIndex >= playQueue.length - 1}>
              <SkipForward size={20} fill="currentColor" />
            </button>

            <button
              className={`ml-4 transition-all duration-300 flex items-center justify-center w-10 h-10 rounded-full border border-white/10 ${vibeModeEnabled ? 'bg-white/10 border-white/30 shadow-[0_0_15px_rgba(255,255,255,0.1)]' : 'bg-transparent hover:bg-white/5'}`}
              title="Toggle Vibe Mode"
              onClick={() => setVibeModeEnabled(!vibeModeEnabled)}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={`transition-all duration-300 ease-in-out ${vibeModeEnabled ? 'spin-record text-[var(--accent)] scale-[1.2] drop-shadow-[0_0_8px_var(--accent)]' : 'text-slate-400 group-hover:text-white group-hover:scale-110'}`}
                style={{ width: 20, height: 20 }}
              >
                <circle cx="12" cy="12" r="10" />
                <circle cx="12" cy="12" r="3" />
                <circle cx="12" cy="12" r="1" fill="currentColor" />
              </svg>
            </button>
          </div>
          <div className="progress-container">
            <span>{formatTime(currentTime)}</span>
            <div
              className="progress-bar"
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const clickedTime = (x / rect.width) * duration;
                seekTo(clickedTime);
              }}
            >
              <div className="progress-fill" style={{ width: `${(currentTime / duration) * 100}%` }} />
            </div>
            <span>{formatTime(duration)}</span>
          </div>
        </div>

        <div className="right-controls">
          <div className="flex items-center gap-3 w-32">
            <Volume2 size={18} className="text-slate-500" />
            <div className="progress-bar flex-1">
              <input
                type="range"
                min="0" max="1" step="0.01"
                value={volume}
                onChange={(e) => setVolume(parseFloat(e.target.value))}
                className="w-full opacity-0 absolute inset-0 cursor-pointer z-10"
              />
              <div className="progress-fill" style={{ width: `${volume * 100}%` }} />
            </div>
          </div>
          <button
            className="text-slate-500 hover:text-white transition-colors p-2"
            title="下载当前播放"
            onClick={() => handleDownload(track)}
            disabled={!track}
          >
            <Download size={20} />
          </button>
          <button className="text-slate-500 hover:text-white transition-colors" title="播放队列">
            <ListMusic size={20} />
          </button>
        </div>
      </footer>

      {/* Invisible Audio Element */}
      <audio
        ref={audioRef}
        src={track?.audioSrc}
        preload="auto"
        onLoadedMetadata={onLoadedMetadata}
        onTimeUpdate={onTimeUpdate}
        onEnded={() => {
          if (queueIndex < playQueue.length - 1) jumpQueue(queueIndex + 1);
          else setIsPlaying(false);
        }}
      />

      {vibeModeEnabled && (
        <VibeOverlay
          track={track}
          audioRef={audioRef}
          audioDuration={duration}
          playQueue={playQueue}
          queueIndex={queueIndex}
          jumpQueue={jumpQueue}
          isPlaying={isPlaying}
          handleTogglePlay={handleTogglePlay}
          currentTime={currentTime}
          formatTime={formatTime}
          isFavoriteItem={isFavoriteItem}
          toggleFavoriteItem={toggleFavoriteItem}
          onClose={() => setVibeModeEnabled(false)}
          apiUrl={apiUrl}
        />
      )}
    </div>
  );
}

export default App;
