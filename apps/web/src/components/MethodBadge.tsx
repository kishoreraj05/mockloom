import { cn } from '@/lib/utils';

const tones: Record<string, string> = {
  GET: 'text-get',
  POST: 'text-post',
  PUT: 'text-put',
  PATCH: 'text-patch',
  DELETE: 'text-del',
};

export function MethodBadge({ method, className }: { method: string; className?: string }) {
  return (
    <span className={cn('inline-block w-11 shrink-0 font-mono text-2xs font-semibold', tones[method] ?? 'text-muted', className)}>
      {method === 'DELETE' ? 'DEL' : method === 'OPTIONS' ? 'OPT' : method}
    </span>
  );
}
