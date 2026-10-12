const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const shuffled = (items) => {
  const result = [...items];
  for (let i = result.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
};
export const emptyQueue = () => ({ items: [], currentId: null, shuffle: false, repeat: 'off', history: [], bag: [] });
export const queueIndexOf = (state) => state.items.findIndex((item) => item.entryId === state.currentId);
export const currentQueueItem = (state) => state.items.find((item) => item.entryId === state.currentId) || null;
export const peekNext = (state, natural = false) => {
  if (natural && state.repeat === 'one') return state.currentId;
  if (state.shuffle) return state.bag[0] || null;
  const index = queueIndexOf(state);
  return state.items[index + 1]?.entryId || (state.repeat === 'all' ? state.items[0]?.entryId : null) || null;
};
const fillBag = (state) => shuffled(state.items.map((i) => i.entryId).filter((id) => id !== state.currentId));
const select = (state, id, record = true) => {
  if (!state.items.some((i) => i.entryId === id)) return state;
  if (id === state.currentId) return state;
  const next = { ...state, currentId: id, history: record && state.currentId ? [...state.history, state.currentId].slice(-300) : state.history, bag: state.bag.filter((i) => i !== id) };
  if (next.shuffle && next.repeat === 'all' && !next.bag.length) next.bag = fillBag(next);
  return next;
};
export function queueReducer(state, action) {
  switch (action.type) {
    case 'replace': {
      const items = action.items.slice(0, 300).map((item) => ({ ...item, entryId: item.entryId || uid() }));
      const next = { ...state, items, currentId: items[action.index || 0]?.entryId || null, history: [], bag: [] };
      if (next.shuffle) next.bag = fillBag(next);
      return next;
    }
    case 'select': return select(state, action.id);
    case 'next': {
      let id = peekNext(state, action.natural);
      if (!id && state.shuffle && state.repeat === 'all' && state.items.length === 1) id = state.currentId;
      return id ? select(state, id) : state;
    }
    case 'previous': {
      const history = [...state.history];
      let id;
      while (history.length && !id) {
        const candidate = history.pop();
        if (state.items.some((i) => i.entryId === candidate)) id = candidate;
      }
      if (!id) return state;
      const next = select({ ...state, history }, id, false);
      if (state.shuffle && state.currentId !== id) next.bag = [state.currentId, ...next.bag.filter((i) => i !== state.currentId)];
      return next;
    }
    case 'shuffle': {
      const next = { ...state, shuffle: action.value ?? !state.shuffle };
      next.bag = next.shuffle ? fillBag(next) : [];
      return next;
    }
    case 'repeat': {
      const next = { ...state, repeat: action.value || ({ off: 'all', all: 'one', one: 'off' }[state.repeat]) };
      if (next.shuffle && next.repeat === 'all' && !next.bag.length) next.bag = fillBag(next);
      return next;
    }
    case 'insert': {
      if (state.items.length >= 300) return state;
      const item = { ...action.item, entryId: uid() };
      const items = [...state.items];
      items.splice(action.next ? queueIndexOf(state) + 1 : items.length, 0, item);
      return { ...state, items, currentId: state.currentId || item.entryId, bag: state.shuffle ? (action.next ? [item.entryId, ...state.bag] : [...state.bag, item.entryId]) : state.bag };
    }
    case 'remove': {
      const index = state.items.findIndex((i) => i.entryId === action.id);
      if (index < 0) return state;
      const items = state.items.filter((i) => i.entryId !== action.id);
      const nextId = state.currentId === action.id
        ? (state.shuffle ? state.bag.find((i) => i !== action.id) : state.items[index + 1]?.entryId) || (state.repeat === 'all' ? items[0]?.entryId : null) || null
        : state.currentId;
      const next = { ...state, items, currentId: nextId, bag: state.bag.filter((i) => i !== action.id && i !== nextId), history: state.history.filter((i) => i !== action.id) };
      if (next.shuffle && next.repeat === 'all' && !next.bag.length) next.bag = fillBag(next);
      return next;
    }
    case 'move': {
      const from = state.items.findIndex((i) => i.entryId === action.id);
      const to = state.items.findIndex((i) => i.entryId === action.beforeId);
      if (from < 0 || to < 0 || from === to) return state;
      const items = [...state.items];
      const [item] = items.splice(from, 1);
      items.splice(to, 0, item);
      return { ...state, items };
    }
    case 'update': return { ...state, items: state.items.map((item) => item.entryId === action.id ? { ...item, ...action.item, entryId: item.entryId } : item) };
    case 'restore': {
      const value = action.session || {};
      const items = (Array.isArray(value.queue) ? value.queue : []).filter((i) => i && typeof i.title === 'string').slice(0, 300).map((i) => ({ ...i, entryId: i.entryId || uid() }));
      const ids = new Set(items.map((i) => i.entryId));
      const next = { items, currentId: ids.has(value.currentEntryId) ? value.currentEntryId : items[0]?.entryId || null, shuffle: !!value.shuffle, repeat: ['off', 'one', 'all'].includes(value.repeat) ? value.repeat : 'off', history: (value.history || []).filter((id) => ids.has(id)), bag: (value.shuffleBag || []).filter((id) => ids.has(id) && id !== value.currentEntryId) };
      if (next.shuffle && !next.bag.length && next.repeat === 'all') next.bag = fillBag(next);
      return next;
    }
    case 'clear': return { ...emptyQueue(), shuffle: state.shuffle, repeat: state.repeat };
    default: return state;
  }
}

export const queueSession = (state, position, effect) => ({ version: 1, queue: state.items, currentEntryId: state.currentId, position, shuffle: state.shuffle, repeat: state.repeat, history: state.history, shuffleBag: state.bag, effect });
