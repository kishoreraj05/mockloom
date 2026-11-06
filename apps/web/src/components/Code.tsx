import { DiffEditor as MonacoDiff, Editor as MonacoEditor, type EditorProps } from '@monaco-editor/react';
import { useEffect, useState } from 'react';
import { monaco } from './monaco';

const options: EditorProps['options'] = {
  minimap: { enabled: false },
  fontSize: 12,
  lineNumbersMinChars: 3,
  scrollBeyondLastLine: false,
  tabSize: 2,
  automaticLayout: true,
  renderLineHighlight: 'none',
  overviewRulerLanes: 0,
  folding: true,
  wordWrap: 'on',
  padding: { top: 6, bottom: 6 },
};

function useTheme(): string {
  const query = '(prefers-color-scheme: dark)';
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const listener = (event: MediaQueryListEvent) => setDark(event.matches);
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, []);
  return dark ? 'loom-dark' : 'loom-light';
}

export interface Marker {
  line: number;
  message: string;
  severity: 'error' | 'warning';
}

export default function CodeEditor({
  value,
  onChange,
  language,
  readOnly,
  path,
  schema,
  markers,
  ariaLabel,
}: {
  value: string;
  onChange?: (value: string) => void;
  language: 'json' | 'yaml';
  readOnly?: boolean;
  /** Model URI. Giving each editor its own keeps undo stacks and schemas apart. */
  path?: string;
  /** JSON Schema that Monaco checks the content against, as warnings. */
  schema?: unknown;
  markers?: Marker[];
  ariaLabel: string;
}) {
  const theme = useTheme();
  const uri = path ? monaco.Uri.parse(`inmemory://loom/${path}`).toString() : undefined;

  useEffect(() => {
    if (language !== 'json' || !uri) return;
    const defaults = (monaco.languages as unknown as { json: { jsonDefaults: { setDiagnosticsOptions: (o: unknown) => void } } }).json
      .jsonDefaults;
    defaults.setDiagnosticsOptions({
      validate: true,
      schemaValidation: 'warning',
      schemas: schema ? [{ uri: `${uri}.schema`, fileMatch: [uri], schema }] : [],
    });
  }, [language, schema, uri]);

  useEffect(() => {
    if (!uri) return;
    const model = monaco.editor.getModel(monaco.Uri.parse(uri));
    if (!model) return;
    monaco.editor.setModelMarkers(
      model,
      'mockloom',
      (markers ?? []).map((marker) => ({
        startLineNumber: marker.line,
        endLineNumber: marker.line,
        startColumn: 1,
        endColumn: model.getLineMaxColumn(Math.min(marker.line, model.getLineCount())),
        message: marker.message,
        severity: marker.severity === 'error' ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
      })),
    );
  }, [markers, uri, value]);

  return (
    <MonacoEditor
      value={value}
      language={language}
      theme={theme}
      path={uri}
      onChange={(next) => onChange?.(next ?? '')}
      loading={<div className="p-3 text-muted">Loading editor…</div>}
      options={{ ...options, readOnly, ariaLabel }}
    />
  );
}

export function CodeDiff({ original, modified, language }: { original: string; modified: string; language: string }) {
  const theme = useTheme();
  return (
    <MonacoDiff
      original={original}
      modified={modified}
      language={language}
      theme={theme}
      loading={<div className="p-3 text-muted">Loading diff…</div>}
      options={{ ...options, readOnly: true, renderSideBySide: false }}
    />
  );
}
