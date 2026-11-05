import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useUi } from '@/store/ui';

export function Toasts() {
  const toasts = useUi((state) => state.toasts);
  const dismiss = useUi((state) => state.dismissToast);
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 z-50 flex w-[calc(100vw-32px)] max-w-md -translate-x-1/2 flex-col gap-2" role="status">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={cn(
            'pointer-events-auto flex items-start gap-2 rounded border border-line bg-surface px-3 py-2 shadow-lg',
            toast.tone === 'bad' && 'border-bad',
          )}
        >
          <span className="flex-1">{toast.message}</span>
          <button aria-label="Dismiss" className="text-muted hover:text-ink" onClick={() => dismiss(toast.id)}>
            <X size={13} />
          </button>
        </div>
      ))}
    </div>
  );
}
