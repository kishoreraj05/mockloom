import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function mockBaseUrl(mockPath: string): string {
  return `${window.location.origin}${mockPath}`;
}

export function prettyJson(text: string | null | undefined): string {
  if (!text) return '';
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

export function statusTone(status: number): string {
  if (status === 0) return 'text-bad';
  if (status < 300) return 'text-ok';
  if (status < 400) return 'text-muted';
  if (status < 500) return 'text-warn';
  return 'text-bad';
}

export function formatClock(iso: string): string {
  const date = new Date(iso);
  const pad = (n: number, size = 2) => String(n).padStart(size, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}
