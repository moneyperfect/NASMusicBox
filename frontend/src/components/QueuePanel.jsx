import { X, GripVertical, Trash2, Shuffle, Repeat, Play, ArrowUp, ArrowDown } from 'lucide-react';
export default function QueuePanel({ state, onAction, onPlay, onClose }) {
  return <div className="fixed inset-0 z-[110] bg-black/40" onClick={onClose}>
    <section role="dialog" aria-modal="true" aria-label="播放队列" className="absolute right-4 bottom-24 top-8 w-[min(440px,calc(100vw-32px))] bg-[#111d2b] border border-white/10 rounded-2xl shadow-2xl flex flex-col" onClick={(e) => e.stopPropagation()}>
      <header className="p-5 flex justify-between items-center border-b border-white/10"><h2 className="font-bold">播放队列 · {state.items.length}</h2><button aria-label="关闭播放队列" onClick={onClose}><X size={20} /></button></header>
      <div className="flex gap-3 p-4 text-xs border-b border-white/10">
        <button aria-pressed={state.shuffle} className={state.shuffle ? 'text-emerald-300' : 'text-white/50'} onClick={() => onAction({ type: 'shuffle' })}><Shuffle size={16} className="inline mr-1" />随机</button>
        <button className={state.repeat !== 'off' ? 'text-emerald-300' : 'text-white/50'} onClick={() => onAction({ type: 'repeat' })}><Repeat size={16} className="inline mr-1" />{{ off: '顺序播放', all: '列表循环', one: '单曲循环' }[state.repeat]}</button>
        <button className="ml-auto text-white/50" onClick={() => onAction({ type: 'clear' })}>清空</button>
      </div>
      <div className="overflow-y-auto flex-1 p-2">
        {!state.items.length && <p className="text-white/40 text-sm p-8 text-center">从歌曲菜单添加到队列</p>}
        {state.items.map((item, index) => <div key={item.entryId} data-entry-id={item.entryId} draggable onDragStart={(e) => e.dataTransfer.setData('text/plain', item.entryId)} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onAction({ type: 'move', id: e.dataTransfer.getData('text/plain'), beforeId: item.entryId }); }} className={`flex gap-2 items-center p-3 rounded-xl ${item.entryId === state.currentId ? 'bg-emerald-300/10 text-emerald-200' : 'hover:bg-white/5'}`}>
          <GripVertical size={15} className="text-white/25 shrink-0" />
          <button onClick={() => onPlay(index)} className="flex-1 min-w-0 text-left"><div className="text-sm truncate">{item.entryId === state.currentId && <Play size={12} className="inline mr-1" />}{item.title}</div><div className="text-xs text-white/40 truncate">{item.artist}</div></button>
          <button aria-label={`上移 ${item.title}`} disabled={index === 0} onClick={() => onAction({ type: 'move', id: item.entryId, beforeId: state.items[index - 1]?.entryId })}><ArrowUp size={13} /></button>
          <button aria-label={`下移 ${item.title}`} disabled={index === state.items.length - 1} onClick={() => onAction({ type: 'move', id: item.entryId, beforeId: state.items[index + 1]?.entryId })}><ArrowDown size={13} /></button>
          <button aria-label={`移除 ${item.title}`} className="text-white/40 hover:text-red-300" onClick={() => onAction({ type: 'remove', id: item.entryId })}><Trash2 size={15} /></button>
        </div>)}
      </div>
    </section>
  </div>;
}
