import { Check, Copy } from 'lucide-react';
import { useState } from 'react';
import { useUi } from '@/store/ui';
import { Button } from './ui/button';

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const toast = useUi((state) => state.toast);
  return (
    <Button
      size="icon"
      variant="ghost"
      aria-label={label}
      title={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          toast('Your browser blocked clipboard access; select the text and copy it instead.', 'bad');
        }
      }}
    >
      {copied ? <Check size={13} className="text-ok" /> : <Copy size={13} />}
    </Button>
  );
}
