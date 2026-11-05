import { lazy, Suspense, type ComponentProps } from 'react';

// Monaco is several megabytes, and the workspace list never needs it.
const Editor = lazy(() => import('./Code'));
const Diff = lazy(() => import('./Code').then((module) => ({ default: module.CodeDiff })));

const fallback = <div className="p-3 text-muted">Loading editor…</div>;

export function CodeEditor(props: ComponentProps<typeof Editor>) {
  return (
    <Suspense fallback={fallback}>
      <Editor {...props} />
    </Suspense>
  );
}

export function CodeDiff(props: ComponentProps<typeof Diff>) {
  return (
    <Suspense fallback={fallback}>
      <Diff {...props} />
    </Suspense>
  );
}
