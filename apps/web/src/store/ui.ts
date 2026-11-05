import { create } from 'zustand';
import type { LogEntry } from '@/api/client';
import { mergeRows } from '@/lib/log';
import type { RuleDraft } from '@/lib/rules';

export type EndpointTab = 'rules' | 'try' | 'use' | 'chaos';
export type Connection = 'connecting' | 'live' | 'offline';

interface Toast {
  id: number;
  tone: 'ok' | 'bad';
  message: string;
}

interface UiState {
  tab: EndpointTab;
  /** The rule being edited; null means the list is showing. */
  draft: RuleDraft | null;
  /** Bumps when a different draft is opened. Saving a new rule gives it an id, but it's the same draft. */
  draftVersion: number;
  logRows: LogEntry[];
  connection: Connection;
  selectedLogId: string | null;
  toasts: Toast[];
  setTab: (tab: EndpointTab) => void;
  setDraft: (draft: RuleDraft | null) => void;
  patchDraft: (patch: Partial<RuleDraft>) => void;
  addLogRows: (rows: LogEntry[]) => void;
  clearLogRows: () => void;
  setConnection: (connection: Connection) => void;
  selectLog: (id: string | null) => void;
  toast: (message: string, tone?: Toast['tone']) => void;
  dismissToast: (id: number) => void;
}

let nextToast = 1;

export const useUi = create<UiState>((set) => ({
  tab: 'rules',
  draft: null,
  draftVersion: 0,
  logRows: [],
  connection: 'connecting',
  selectedLogId: null,
  toasts: [],
  setTab: (tab) => set({ tab }),
  setDraft: (draft) => set((state) => ({ draft, draftVersion: state.draftVersion + 1 })),
  patchDraft: (patch) => set((state) => ({ draft: state.draft ? { ...state.draft, ...patch } : null })),
  addLogRows: (rows) => set((state) => ({ logRows: mergeRows(state.logRows, rows) })),
  clearLogRows: () => set({ logRows: [], selectedLogId: null }),
  setConnection: (connection) => set({ connection }),
  selectLog: (selectedLogId) => set({ selectedLogId }),
  toast: (message, tone = 'ok') => {
    const id = nextToast++;
    set((state) => ({ toasts: [...state.toasts, { id, tone, message }] }));
    window.setTimeout(() => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })), 4000);
  },
  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));
