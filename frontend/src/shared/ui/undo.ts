import { create } from 'zustand'

export const UNDO_MS = 8000
let serial = 0
type Entry = { id: number; expires: number; restore: () => void }
export const useUndo = create<{ entry: Entry | null; offer: (restore: () => void) => void; dismiss: () => void; undo: () => void }>((set, get) => ({
  entry: null,
  offer: (restore) => set({ entry: { id: ++serial, expires: Date.now() + UNDO_MS, restore } }),
  dismiss: () => set({ entry: null }),
  undo: () => {
    const entry = get().entry
    set({ entry: null })
    if (entry && Date.now() < entry.expires) entry.restore()
  },
}))

